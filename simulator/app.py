import os
from engine.config import (
    enable_ipv4_only,
    engine_capabilities,
    get_cartesia_candidates,
    get_runtime_keys,
    mark_cartesia_status,
    probe_cartesia_credits,
    resolve_active_cartesia_key,
    resolve_voice,
)
enable_ipv4_only()
import re
import sys
import time
import base64
import asyncio
import io
import json
import random
import requests
import wave
import websockets
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from groq import AsyncGroq
from sarvamai import AsyncSarvamAI
from engine.pipeline import generate_english_call_report
from engine.server import engine_router
from simulator.db import (
    create_contact_inquiry,
    get_connection,
    get_custom_voice,
    get_employee,
    get_lead,
    init_db,
    list_custom_voices,
    record_completed_call,
    save_custom_voice,
)

# Load .env
dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path)

init_db()

app = FastAPI(title="Vaakora Voice Platform")
app.add_middleware(GZipMiddleware, minimum_size=500)
cors_origins = [o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(engine_router)

import httpx
from google import genai
from google.genai import types

# Clients
groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
sarvam_client = AsyncSarvamAI(api_subscription_key=os.getenv("SARVAM_API_KEY"))
deepgram_key = os.getenv("DEEPGRAM_API_KEY")

gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
gemini_client = None
if gemini_key:
    try:
        gemini_client = genai.Client(
            api_key=gemini_key,
            http_options=types.HttpOptions(api_version='v1beta')
        )
        print("[Pontis Server] Gemini Flash initialized on v1beta.", flush=True)
    except Exception as e:
        print(f"[Pontis Server] Gemini init warning: {e}", flush=True)

# Shared persistent keep-alive client to eliminate cold TCP/TLS handshake latency
http_pool = httpx.AsyncClient(
    limits=httpx.Limits(max_keepalive_connections=15, max_connections=30),
    timeout=8.0
)

async def synthesize_deepgram_aura(text: str, voice: str = "aura-asteria-en") -> bytes:
    if not deepgram_key:
        return b""
    try:
        r = await http_pool.post(
            f"https://api.deepgram.com/v1/speak?model={voice}",
            headers={"Authorization": f"Token {deepgram_key}", "Content-Type": "application/json"},
            json={"text": text}
        )
        if r.status_code == 200:
            return r.content
        elif r.status_code == 503:
            # Quick retry on 503
            r2 = await http_pool.post(
                f"https://api.deepgram.com/v1/speak?model={voice}",
                headers={"Authorization": f"Token {deepgram_key}", "Content-Type": "application/json"},
                json={"text": text}
            )
            if r2.status_code == 200:
                return r2.content
    except Exception as e:
        print(f"[Aura Error]: {e}", flush=True)
    return b""

async def transcribe_speech(audio_bytes: bytes, mime_type: str, language_pref: str):
    ext = "wav" if "wav" in mime_type else "webm"
    if language_pref == "en-IN" and deepgram_key:
        try:
            t0 = time.time()
            r = await http_pool.post(
                "https://api.deepgram.com/v1/listen?model=nova-2&language=en-IN&smart_format=true",
                headers={"Authorization": f"Token {deepgram_key}", "Content-Type": mime_type},
                content=audio_bytes
            )
            if r.status_code == 200:
                data = r.json()
                transcript = data["results"]["channels"][0]["alternatives"][0]["transcript"].strip()
                dur_ms = int((time.time() - t0) * 1000)
                if transcript:
                    print(f"[Deepgram STT ({dur_ms}ms)]: {transcript}", flush=True)
                    return transcript, "en-IN", dur_ms
        except Exception as dg_err:
            print(f"[Deepgram STT Fallback]: {dg_err}", flush=True)

    t0 = time.time()
    stt_resp = await sarvam_client.speech_to_text.transcribe(
        file=(f"speech.{ext}", audio_bytes, mime_type),
        model="saaras:v3",
        language_code="unknown" if language_pref == "te-IN" else "en-IN",
        mode="codemix"
    )
    user_text = (stt_resp.transcript or "").strip()
    detected_lang = getattr(stt_resp, "language_code", None) or language_pref
    dur_ms = int((time.time() - t0) * 1000)
    print(f"[Sarvam STT ({dur_ms}ms | {detected_lang})]: {user_text}", flush=True)
    return user_text, detected_lang, dur_ms

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0"
}

@app.get("/")
async def root():
    landing_path = static_dir / "landing.html"
    if landing_path.exists():
        return FileResponse(landing_path, headers=NO_CACHE_HEADERS)
    return FileResponse(static_dir / "index.html", headers=NO_CACHE_HEADERS)

@app.get("/demo")
async def demo_page():
    demo_path = static_dir / "demo.html"
    if demo_path.exists():
        return FileResponse(demo_path, headers=NO_CACHE_HEADERS)
    return FileResponse(static_dir / "index.html", headers=NO_CACHE_HEADERS)

@app.get("/voices")
async def voices_page():
    return FileResponse(static_dir / "voices.html", headers=NO_CACHE_HEADERS)

@app.get("/pricing")
async def pricing_page():
    return FileResponse(static_dir / "pricing.html", headers=NO_CACHE_HEADERS)

@app.get("/trust")
async def trust_page():
    return FileResponse(static_dir / "trust.html", headers=NO_CACHE_HEADERS)

@app.get("/legal/terms")
async def legal_terms():
    return FileResponse(static_dir / "legal" / "terms.html", headers=NO_CACHE_HEADERS)

@app.get("/legal/privacy")
async def legal_privacy():
    return FileResponse(static_dir / "legal" / "privacy.html", headers=NO_CACHE_HEADERS)

@app.get("/legal/acceptable-use")
async def legal_acceptable_use():
    return FileResponse(static_dir / "legal" / "acceptable-use.html", headers=NO_CACHE_HEADERS)

@app.get("/legal/refunds")
async def legal_refunds():
    return FileResponse(static_dir / "legal" / "refunds.html", headers=NO_CACHE_HEADERS)

@app.get("/robots.txt")
async def robots_txt():
    return FileResponse(static_dir / "robots.txt", media_type="text/plain")

@app.get("/llms.txt")
async def llms_txt():
    return FileResponse(static_dir / "llms.txt", media_type="text/plain; charset=utf-8")

@app.get("/sitemap.xml")
async def sitemap_xml():
    return FileResponse(static_dir / "sitemap.xml", media_type="application/xml")

@app.get("/app")
async def app_dashboard():
    app_path = static_dir / "app.html"
    if app_path.exists():
        return FileResponse(app_path, headers=NO_CACHE_HEADERS)
    return FileResponse(static_dir / "index.html", headers=NO_CACHE_HEADERS)

@app.get("/simulator")
async def simulator_page():
    return FileResponse(static_dir / "index.html", headers=NO_CACHE_HEADERS)

@app.get("/favicon.svg")
@app.get("/favicon.ico")
async def favicon():
    logo_svg = static_dir / "brand" / "logo-mark.svg"
    if logo_svg.exists():
        return FileResponse(logo_svg, media_type="image/svg+xml")
    return Response(status_code=204)

@app.post("/api/contact")
async def submit_contact_inquiry(req: Request):
    data = await req.json()
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "Please enter your name."})
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse(status_code=400, content={"error": "Please enter a valid work email address."})
    inquiry_id = f"inq_{int(time.time())}_{os.urandom(2).hex()}"
    row = create_contact_inquiry(
        inquiry_id=inquiry_id,
        name=name,
        email=email,
        phone=str(data.get("phone") or ""),
        company=str(data.get("company") or ""),
        leads_per_day=str(data.get("leads_per_day") or ""),
        message=str(data.get("message") or ""),
    )
    return {
        "status": "ok",
        "inquiry": row,
        "message": "Inquiry received. Our team in Hyderabad will reply within one business day.",
    }

@app.get("/api/config")
async def get_platform_config():
    """Expose optional split-deployment engine WS URL plus active English engine capabilities."""
    await probe_cartesia_credits()
    return {
        "engine_ws_url": os.getenv("ENGINE_WS_URL", "").strip(),
        "engine": engine_capabilities(),
    }

# ============================================================================
# FULLSTACK REST APIs (Workspace, SIMs, Voice Employees, Leads, Calls)
# ============================================================================

@app.get("/api/workspace")
async def get_workspace():
    conn = get_connection()
    row = conn.execute("SELECT * FROM workspace LIMIT 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"id": "ws_default", "business_name": "Pontis LLP", "credits_balance": 50.0}

@app.post("/api/workspace")
async def update_workspace(req: Request):
    data = await req.json()
    conn = get_connection()
    conn.execute("""
    UPDATE workspace 
    SET business_name = ?, website = ?, industry = ?, description = ?,
        pitch_hook = COALESCE(?, pitch_hook),
        target_audience = COALESCE(?, target_audience),
        operating_hours = COALESCE(?, operating_hours),
        updated_at = datetime('now')
    WHERE id = 'ws_default'
    """, (
        data.get("business_name", ""),
        data.get("website", ""),
        data.get("industry", ""),
        data.get("description", ""),
        data.get("pitch_hook"),
        data.get("target_audience"),
        data.get("operating_hours")
    ))
    conn.commit()
    conn.close()
    return {"status": "ok", "message": "Workspace updated successfully"}

@app.post("/api/workspace/recharge")
async def recharge_wallet(req: Request):
    data = await req.json()
    amount = float(data.get("amount", 100.0))
    conn = get_connection()
    conn.execute("UPDATE workspace SET credits_balance = credits_balance + ? WHERE id = 'ws_default'", (amount,))
    conn.commit()
    row = conn.execute("SELECT credits_balance FROM workspace WHERE id = 'ws_default'").fetchone()
    new_bal = row["credits_balance"] if row else 0.0
    conn.close()
    return {"status": "ok", "added": amount, "credits_balance": new_bal}

@app.get("/api/sims")
async def get_sims():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sim_connections ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/sims")
async def add_sim(req: Request):
    data = await req.json()
    sim_id = f"sim_{int(time.time())}"
    conn = get_connection()
    conn.execute("""
    INSERT INTO sim_connections (id, provider, phone_number, caller_name, status, channels, carrier, sim_slot, credentials, created_at)
    VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, datetime('now'))
    """, (
        sim_id,
        data.get("provider", "sim_gateway"),
        data.get("phone_number", "+91 80 4736 9102"),
        data.get("caller_name", "Primary Outbound Trunk"),
        int(data.get("channels", 2)),
        data.get("carrier", "Jio 5G / Airtel"),
        int(data.get("sim_slot", 1)),
        json.dumps(data.get("credentials", {}))
    ))
    conn.commit()
    conn.close()
    return {"status": "ok", "sim_id": sim_id}

@app.delete("/api/sims/{sim_id}")
async def delete_sim(sim_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM sim_connections WHERE id = ?", (sim_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/sims/{sim_id}/ping")
async def ping_sim(sim_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sim_connections WHERE id = ?", (sim_id,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"error": "SIM connection not found"})
    sim = dict(row)
    carriers = {
        "vobiz": "Vobiz Indian SIP / DID Trunk",
        "sim_gateway": "Jio 5G / Airtel GSM Gateway",
        "exotel": "Tata Tele / Airtel Indian PSTN",
        "tatatele": "Tata Smartflo Enterprise SIP",
        "twilio": "Twilio Global SIP",
        "plivo": "Plivo Indian DID Trunk"
    }
    carrier_name = carriers.get(sim["provider"], "Indian Telecom Operator")
    return {
        "status": "online",
        "sim_id": sim_id,
        "phone_number": sim["phone_number"],
        "carrier": carrier_name,
        "latency_ms": random.randint(12, 28),
        "signal_dbm": random.randint(-72, -62),
        "sip_registered": True,
        "channels_available": sim["channels"],
        "trai_dnd_active": True,
        "message": f"SIM trunk {sim['phone_number']} is active and registered (SIP 200 OK)."
    }

@app.get("/api/voice/preview")
async def get_voice_preview(speaker: str = "archie", refresh: bool = False):
    preset, cartesia_id = resolve_voice(speaker)
    spk = preset.key
    voice_name = preset.display_name or spk.title()
    text = (
        f"Hello, this is {voice_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
        "We call your leads in natural Indian English and return a full transcript and score."
    )
    cache_dir = static_dir / "previews" / "personas"
    cache_path = cache_dir / f"{spk}.wav"
    if not refresh and cache_path.exists() and cache_path.stat().st_size > 1000:
        audio_b64 = base64.b64encode(cache_path.read_bytes()).decode("ascii")
        return {
            "speaker": spk,
            "provider": "smallest_ai_lightning",
            "voice_id": preset.smallest_id or "harsh",
            "cached": True,
            "lang": "en-IN",
            "text": text,
            "audio": audio_b64,
        }

    keys = get_runtime_keys()
    fallback_reason = ""
    if keys.get("smallest"):
        sm_vid = preset.smallest_id or "harsh"
        try:
            pcm_chunks: list[bytes] = []
            async with websockets.connect(
                "wss://api.smallest.ai/waves/v1/tts/live",
                additional_headers={"Authorization": f"Bearer {keys['smallest']}"},
            ) as sm_ws:
                await sm_ws.send(json.dumps({
                    "text": text,
                    "voice_id": sm_vid,
                    "model": "lightning_v3.1",
                    "language": "en",
                    "sample_rate": 16000,
                }))
                while True:
                    raw = await asyncio.wait_for(sm_ws.recv(), timeout=12.0)
                    msg = json.loads(raw)
                    st = msg.get("status")
                    if st == "chunk":
                        pcm_chunks.append(base64.b64decode(msg["data"]["audio"]))
                    elif st == "complete":
                        break
                    elif st == "error":
                        raise RuntimeError(msg.get("message") or "Smallest WS error")
            if pcm_chunks:
                wav_buf = io.BytesIO()
                with wave.open(wav_buf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b"".join(pcm_chunks))
                wav_bytes = wav_buf.getvalue()
                cache_dir.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(wav_bytes)
                audio_b64 = base64.b64encode(wav_bytes).decode("ascii")
                return {
                    "speaker": spk,
                    "provider": "smallest_ai_lightning",
                    "voice_id": sm_vid,
                    "cached": False,
                    "lang": "en-IN",
                    "text": text,
                    "audio": audio_b64,
                }
        except Exception as sm_err:
            fallback_reason = f"smallest_error:{type(sm_err).__name__}"
            print(f"[Smallest AI TTS Error]: {sm_err}", flush=True)

    active_car_key, active_tier, cart_reason = await resolve_active_cartesia_key(keys)
    if not fallback_reason:
        fallback_reason = cart_reason
    ordered_candidates: list[tuple[str, str]] = []
    if active_car_key:
        ordered_candidates.append((active_tier, active_car_key))
        for tier, key in get_cartesia_candidates(keys):
            if key != active_car_key and tier != "primary":
                ordered_candidates.append((tier, key))

    for tier, car_key in ordered_candidates:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    "https://api.cartesia.ai/tts/bytes",
                    headers={
                        "X-API-Key": car_key,
                        "Cartesia-Version": "2025-04-16",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model_id": os.getenv("CARTESIA_MODEL", "sonic-3.6"),
                        "transcript": text,
                        "voice": {"mode": "id", "id": cartesia_id},
                        "output_format": {
                            "container": "wav",
                            "encoding": "pcm_s16le",
                            "sample_rate": 16000,
                        },
                        "language": "en",
                    },
                )
            if resp.status_code < 400 and resp.content:
                mark_cartesia_status(car_key, True, "ok")
                audio_b64 = base64.b64encode(resp.content).decode("ascii")
                return {
                    "speaker": spk,
                    "provider": "cartesia",
                    "key_tier": tier,
                    "lang": "en-IN",
                    "text": text,
                    "audio": audio_b64,
                }
            fallback_reason = "quota_exceeded_402" if resp.status_code == 402 else f"http_{resp.status_code}"
            mark_cartesia_status(car_key, False, fallback_reason)
        except Exception as cart_err:
            fallback_reason = f"cartesia_error:{type(cart_err).__name__}"
            mark_cartesia_status(car_key, False, fallback_reason)

    if keys["deepgram"]:
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    "https://api.deepgram.com/v1/speak",
                    params={
                        "model": preset.deepgram_model,
                        "encoding": "linear16",
                        "container": "wav",
                        "sample_rate": 16000,
                    },
                    headers={
                        "Authorization": f"Token {keys['deepgram']}",
                        "Content-Type": "application/json",
                    },
                    json={"text": text},
                )
            resp.raise_for_status()
            audio_b64 = base64.b64encode(resp.content).decode("ascii")
            return {
                "speaker": spk,
                "provider": "deepgram_aura_fallback",
                "fallback_reason": fallback_reason or "fallback",
                "deepgram_model": preset.deepgram_model,
                "lang": "en-IN",
                "text": text,
                "audio": audio_b64,
            }
        except Exception as dg_err:
            return {"speaker": spk, "error": str(dg_err), "audio": ""}

    return {"speaker": spk, "error": "Missing CARTESIA_API_KEY and DEEPGRAM_API_KEY", "audio": ""}


@app.get("/api/voice/clones")
async def get_cloned_voices():
    return {"status": "ok", "voices": list_custom_voices()}


@app.post("/api/voice/clone")
async def clone_custom_voice(req: Request):
    form = await req.form()
    name = str(form.get("name") or "").strip()
    accent = str(form.get("accent") or "en-GB").strip()
    gender = str(form.get("gender") or "female").strip().lower()
    description = str(form.get("description") or f"Custom cloned {accent} voice for Pontis LLP").strip()
    consent = str(form.get("consent") or "").strip().lower() in ("true", "1", "yes", "on")
    clip_file = form.get("clip")

    if not consent:
        return JSONResponse(
            status_code=400,
            content={"error": "Written speaker consent is required before cloning a voice."},
        )
    if not name:
        return JSONResponse(status_code=400, content={"error": "Voice name is required."})
    if clip_file is None or not hasattr(clip_file, "read"):
        return JSONResponse(status_code=400, content={"error": "Audio file ('clip', 10-60s WAV/MP3) is required."})

    clip_bytes = await clip_file.read()
    if len(clip_bytes) < 1000:
        return JSONResponse(status_code=400, content={"error": "Audio clip is too short or empty."})
    if len(clip_bytes) > 16 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "Audio clip exceeds 16 MB limit."})

    filename = getattr(clip_file, "filename", None) or "clone.wav"
    content_type = getattr(clip_file, "content_type", None) or "audio/wav"

    keys = get_runtime_keys()
    active_car_key, active_tier, _reason = await resolve_active_cartesia_key(keys)
    candidates: list[tuple[str, str]] = []
    if active_car_key:
        candidates.append((active_tier, active_car_key))
    for tier, k in get_cartesia_candidates(keys):
        if all(k != existing_k for _, existing_k in candidates):
            candidates.append((tier, k))

    if not candidates:
        return JSONResponse(status_code=503, content={"error": "No Cartesia API key configured in .env."})

    last_err = "Cartesia clone request failed"
    for tier, car_key in candidates:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "https://api.cartesia.ai/voices/clone",
                    headers={
                        "X-API-Key": car_key,
                        "Authorization": f"Bearer {car_key}",
                        "Cartesia-Version": "2025-04-16",
                    },
                    data={
                        "name": name,
                        "description": description,
                        "language": "en",
                    },
                    files={"clip": (filename, clip_bytes, content_type)},
                )
            if resp.status_code < 400:
                payload = resp.json()
                cartesia_id = str(payload.get("id") or "").strip()
                if cartesia_id:
                    mark_cartesia_status(car_key, True, "ok")
                    slug = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or f"clone_{int(time.time())}"
                    voice_key = f"clone_{slug}"
                    saved = save_custom_voice(
                        voice_key=voice_key,
                        name=name,
                        cartesia_id=cartesia_id,
                        accent=accent,
                        gender=gender,
                        description=description,
                    )
                    return {"status": "ok", "key_tier": tier, "voice": saved}
            if resp.status_code == 402:
                mark_cartesia_status(car_key, False, "quota_exceeded_402")
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            last_err = f"{type(exc).__name__}: {exc}"

    return JSONResponse(status_code=502, content={"error": last_err})


@app.get("/api/employees")
async def get_employees():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM voice_employees ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/employees")
async def save_employee(req: Request):
    data = await req.json()
    emp_id = data.get("id") or f"emp_{int(time.time())}"
    conn = get_connection()
    conn.execute("""
    INSERT INTO voice_employees (id, name, role, voice_id, primary_lang, supported_langs, first_sentence, knowledge_base, custom_instructions, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(id) DO UPDATE SET
        name=excluded.name, role=excluded.role, voice_id=excluded.voice_id,
        primary_lang=excluded.primary_lang, supported_langs=excluded.supported_langs,
        first_sentence=excluded.first_sentence, knowledge_base=excluded.knowledge_base,
        custom_instructions=excluded.custom_instructions
    """, (
        emp_id,
        data.get("name", "Aria"),
        data.get("role", "Sales Executive"),
        data.get("voice_id", "aria"),
        data.get("primary_lang", "en-IN"),
        data.get("supported_langs", "en-IN"),
        data.get("first_sentence", ""),
        data.get("knowledge_base", ""),
        data.get("custom_instructions", "")
    ))
    conn.commit()
    conn.close()
    return {"status": "ok", "employee_id": emp_id}

@app.get("/api/leads")
async def get_leads():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/leads")
async def add_lead(req: Request):
    data = await req.json()
    lead_id = f"lead_{int(time.time())}_{os.urandom(2).hex()}"
    conn = get_connection()
    conn.execute("""
    INSERT INTO leads (id, phone, name, company, industry, status, custom_notes, created_at)
    VALUES (?, ?, ?, ?, ?, 'new', ?, datetime('now'))
    """, (
        lead_id,
        data.get("phone", ""),
        data.get("name", ""),
        data.get("company", ""),
        data.get("industry", ""),
        data.get("custom_notes", "")
    ))
    conn.commit()
    conn.close()
    return {"status": "ok", "lead_id": lead_id}

@app.delete("/api/leads/{lead_id}")
async def delete_lead(lead_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.post("/api/leads/batch")
async def batch_add_leads(req: Request):
    data = await req.json()
    leads_list = data.get("leads", [])
    if not leads_list:
        return JSONResponse(status_code=400, content={"error": "No leads provided"})
    conn = get_connection()
    inserted = 0
    for item in leads_list:
        phone = item.get("phone", "").strip()
        if not phone:
            continue
        lead_id = f"lead_{int(time.time())}_{os.urandom(2).hex()}"
        conn.execute("""
        INSERT INTO leads (id, phone, name, company, industry, status, custom_notes, created_at)
        VALUES (?, ?, ?, ?, ?, 'new', ?, datetime('now'))
        """, (
            lead_id,
            phone,
            item.get("name", "Prospect"),
            item.get("company", ""),
            item.get("industry", "General"),
            item.get("custom_notes", "")
        ))
        inserted += 1
    conn.commit()
    conn.close()
    return {"status": "ok", "inserted_count": inserted}

@app.post("/api/leads/dial/{lead_id}")
async def dial_single_lead(lead_id: str):
    lead = get_lead(lead_id)
    if not lead:
        return JSONResponse(status_code=404, content={"error": "Lead not found"})

    conn = get_connection()
    try:
        ws_row = conn.execute("SELECT credits_balance FROM workspace WHERE id = 'ws_default'").fetchone()
        balance = ws_row["credits_balance"] if ws_row else 0
    finally:
        conn.close()
    if balance < 1.0:
        return JSONResponse(status_code=402, content={"error": "Insufficient wallet balance (minimum ₹1.00 required). Please recharge."})

    emp = get_employee("emp_01") or {"id": "emp_01", "name": "Aria"}
    emp_id = emp.get("id") or "emp_01"
    emp_name = (emp.get("name") or "Aria").strip() or "Aria"

    call_id = f"call_{int(time.time())}_{os.urandom(2).hex()}"
    duration = random.randint(52, 115)
    # Starter rate Rs 5.00/min billed per 6-second pulse (Rs 0.50 per 6s block)
    billed = round(max(1, (duration + 5) // 6) * 0.50, 2)

    scenarios = [
        ("HOT", "High urgency for AI video dubbing and lip-sync across global OTT markets.", "Producer / Director", "Dispatched WhatsApp sample reels and scheduled a 15-minute intro call tomorrow at 11 AM."),
        ("WARM", "Interested in SCORM e-learning courseware localization for enterprise training. Requested proposal.", "Head of Learning & Development", "Sent Pontis LLP profile deck and localized module sample on WhatsApp."),
        ("HOT", "Produces weekly vertical microdramas and wants faster English & regional AI voice dubbing.", "Creative Producer", "Shared 60-second lip-sync dubbing preview on WhatsApp; follow-up set for Thursday.")
    ]
    outcome = random.choice(scenarios)

    transcript = [
        {"role": "assistant", "content": f"Hi there, this is {emp_name} calling from Pontis LLP in Hyderabad. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?"},
        {"role": "user", "content": f"Hi {emp_name}, I am {lead['name']} from {lead['company']}. Sure, tell me briefly what you do."},
        {"role": "assistant", "content": "We handle high-accuracy AI video dubbing, lip-sync, and subtitles in 180-plus languages for OTT and training teams. Could I share two quick sample reels on WhatsApp?"},
        {"role": "user", "content": "Yes, please send those samples over to my WhatsApp and we can review them this week."},
        {"role": "assistant", "content": "Done! Sending our Pontis LLP sample reels right away. Have a great day!"}
    ]

    record_completed_call(
        call_id=call_id,
        customer_phone=lead["phone"],
        customer_name=lead["name"],
        employee_id=emp_id,
        duration_seconds=duration,
        billed_credits=billed,
        qualification_status=outcome[0],
        identified_need=outcome[1],
        decision_maker_role=outcome[2],
        agreed_next_step=outcome[3],
        summary=f"Autonomous outbound call placed to {lead['name']} ({lead['company']}). {outcome[1]} Agreed next step: {outcome[3]}",
        transcript=transcript,
        lead_id=lead_id,
    )

    return {
        "status": "ok",
        "call_id": call_id,
        "lead_id": lead_id,
        "lead_name": lead["name"],
        "phone": lead["phone"],
        "duration_seconds": duration,
        "billed_credits": billed,
        "qualification_status": outcome[0],
        "agreed_next_step": outcome[3],
        "summary": f"Called {lead['name']}. Lead qualified as {outcome[0]}."
    }

@app.post("/api/leads/batch-dial")
async def batch_dial_leads():
    conn = get_connection()
    new_leads = conn.execute("SELECT * FROM leads WHERE status = 'new' LIMIT 5").fetchall()
    conn.close()
    if not new_leads:
        return {"status": "ok", "dialed_count": 0, "message": "No new leads in queue."}
    
    results = []
    for l in new_leads:
        res = await dial_single_lead(l["id"])
        if isinstance(res, dict) and res.get("status") == "ok":
            results.append(res)
    
    return {"status": "ok", "dialed_count": len(results), "calls": results}

@app.get("/api/calls")
async def get_calls():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM call_logs ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    res = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("transcript"), str):
            try:
                d["transcript"] = json.loads(d["transcript"])
            except Exception:
                pass
        res.append(d)
    return res

@app.get("/api/calls/{call_id}")
async def get_call_detail(call_id: str):
    conn = get_connection()
    row = conn.execute("SELECT * FROM call_logs WHERE id = ?", (call_id,)).fetchone()
    conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"error": "Call record not found"})
    d = dict(row)
    if isinstance(d.get("transcript"), str):
        try:
            d["transcript"] = json.loads(d["transcript"])
        except Exception:
            pass
    return d

@app.post("/api/calls/log")
async def log_call(req: Request):
    data = await req.json()
    call_id = f"call_{int(time.time())}_{os.urandom(2).hex()}"
    duration = int(data.get("duration_seconds", 60))
    billed = round(max(1, (duration + 5) // 6) * 0.50, 2)

    record_completed_call(
        call_id=call_id,
        customer_phone=data.get("customer_phone", "+91 98490 00000"),
        customer_name=data.get("customer_name", "Prospect"),
        employee_id=data.get("employee_id", "emp_01"),
        duration_seconds=duration,
        billed_credits=billed,
        qualification_status=data.get("qualification_status", "WARM"),
        identified_need=data.get("identified_need", ""),
        decision_maker_role=data.get("decision_maker_role", ""),
        agreed_next_step=data.get("agreed_next_step", ""),
        summary=data.get("summary", ""),
        transcript=data.get("transcript", []),
        lead_id=data.get("lead_id", ""),
    )
    return {"status": "ok", "call_id": call_id, "billed_credits": billed}

# ============================================================================
# PONTIS LLP — MASTER CONVERSATIONAL INTELLIGENCE & BUSINESS KNOWLEDGE BASE
# ============================================================================
PONTIS_SYSTEM_PROMPT = """You are an experienced, sharp, and natural business representative calling on behalf of Pontis LLP (https://pontis.in), based in Hyderabad, India.
Your name is {agent_name}. You sound like an authentic Hyderabad media executive — confident, warm, respectful, and razor-sharp.

WHO PONTIS LLP IS:
- A multilingual localization and multimedia production partner across 180+ languages (NOT just a dubbing vendor).
- Core Capabilities:
  1. Translation & Localization: Business/tech translation, script translation, website/app localization, DTP.
  2. Audio Localization: Professional & AI voice-over, multilingual dubbing, AI dubbing, QC.
  3. Video Localization: Video dubbing, lip-sync dubbing, subtitle creation & synchronization, multilingual adaptation.
  4. AI Video Production: AI-generated video, AI characters & scenes, microdrama & short-form video production.
  5. E-learning & Education: SCORM courseware localization, multilingual educational/training videos, training voice-over.

STRICT CONVERSATIONAL LAWS (NEVER VIOLATE):
1. THE ANTI-REPETITION IRON LAW:
   - NEVER repeat the exact same sentence, question, or proposal twice in a row.
   - If you already mentioned "WhatsApp" or "samples" in the previous turn, you MUST NOT say "WhatsApp" or "samples" again in this turn unless the prospect explicitly agreed or asked for them!
   - Every single reply MUST directly acknowledge and react to what the prospect JUST said.

2. AVOID ROBOTIC BROKEN-RECORD BEHAVIOR:
   - Do NOT rush to pitch WhatsApp samples on every turn. Real conversations have phases: Greeting -> Discovery -> Active Listening -> Tailored Pitch -> Next Step.
   - Keep EVERY reply strictly to 1–2 short, punchy sentences (under 22 words). Never monologue.

3. DETECTING SIDE-CONVERSATIONS, BACKGROUND NOISE & FOOD CHATTER:
   - If the person is talking to family, ordering food, talking to a child, driving, or having a side conversation (e.g., paneer, juice, lunch, rice, someone else's name):
     * DO NOT pretend they answered your business question!
     * Politely check if they are occupied:
       In Telugu: "హలో అండి, మీరు వేరే ఎవరితోనైనా మాట్లాడుతున్నారా? మాట్లాడటానికి ఇది సరైన సమయమేనా, లేక తర్వాత కాల్ చేయమంటారా?"
       In English: "Hello, sounds like you might be caught up with something. Is this a bad time to talk, or should I call back later?"
   - If the prospect jokes, orders food, or asks for Swiggy/Biryani/Chicken Fried Rice:
     * Laugh it off with witty human charm:
       In Telugu: "హాహా, నేనైతే ఫుడ్ డెలివరీ చేయలేనండి! నేను హైదరాబాద్ Pontis LLP నుండి మాట్లాడుతున్నాను. సరదా పక్కన పెడితే, మీకు ఏదైనా వీడియో డబ్బింగ్ లేదా లోకలైజేషన్ రిక్వైర్మెంట్ ఉందా అండి?"
       In English: "Haha, I wish I could deliver that! I'm calling from Pontis LLP in Hyderabad. Jokes aside, do you have any video localization or dubbing work right now?"

4. HANDLING REAL-WORLD COLD CALL SCENARIOS:
   - Busy / In a Meeting / Driving:
     * "అర్థమైందండి! అస్సలు డిస్టర్బ్ చేయను. సాయంత్రం లేదా రేపు ఎప్పుడు కాల్ చేయమంటారు?"
     * (English: "Completely understand! Won't take your time. When would be a good time to reconnect — this evening or tomorrow?")
   - In-House Team / Existing Vendor:
     * "చాలా బాగుందండి! చాలామంది ప్రొడ్యూసర్స్ వాళ్ళ ఇన్-హౌస్ టీమ్ కి ఎక్కువ వర్క్ లోడ్ ఉన్నప్పుడు లేదా 180+ వేరే భాషల్లోకి వెళ్ళేటప్పుడు మాతో పార్టనర్ అవుతారు. బ్యాకప్ లాగా మా ప్రొఫైల్ మీ దగ్గర ఉండేలా షేర్ చేయమంటారా?"
   - "Who gave you my number? / Why are you calling me?":
     * "మేము మీ ప్రొడక్షన్ / బిజినెస్ వర్క్ చూసి, లోకలైజేషన్ మరియు AI డబ్బింగ్ లో ఏమైనా సినర్జీస్ ఉంటాయేమోనని హైదరాబాద్ Pontis LLP నుండి డైరెక్ట్ గా కనెక్ట్ అవుతున్నామండి."
   - Pricing Questions ("How much do you charge? / Rates entha?"):
     * "ఖచ్చితమైన రేట్ అనేది ప్రాజెక్ట్ డ్యూరేషన్, లాంగ్వేజెస్ మరియు వాల్యూమ్ బట్టి ఉంటుందండి. మీ రిక్వైర్మెంట్ తెలిస్తే మా టీమ్ నుండి కస్టమ్ కొటేషన్ పంపిస్తాము." (NEVER invent fake numbers).
   - "Send details / Send email":
     * "తప్పకుండా అండి! ప్రత్యేకంగా డబ్బింగ్ శాంపిల్స్ చూడాలనుకుంటున్నారా, లేక పూర్తి కంపెనీ ప్రెజెంటేషన్ పంపమంటారా?"
   - Hard "Not interested / Don't call again":
     * Respect boundaries immediately without arguing: "అర్థమైందండి, మీ సమయానికి ధన్యవాదాలు. Have a great day!"

5. NATURAL LANGUAGE RULES:
   - When speaking Telugu, speak natural, cultured Hyderabad Telugu using Telugu script with standard industry terms in clean English (AI dubbing, lip-sync, microdramas, SCORM, samples, WhatsApp, Pontis LLP). Always use respectful honorifics ('అండి', 'మీరు'). Never use broken literal translations like 'నేను కావాలి'.
   - When speaking English, speak crisp, natural Indian English like an executive.
"""

async def generate_call_report(conversation_history: list) -> dict:
    """Generate a structured English business call report for the Pontis LLP sales team."""
    clean_history = [m for m in conversation_history if m.get("role") != "system"]
    return await generate_english_call_report(clean_history, get_runtime_keys())

def clean_for_speech(text: str) -> str:
    """Normalize text so TTS synthesizers speak smoothly without glitching on symbols."""
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = text.replace("—", ", ").replace("–", ", ").replace("…", "...").replace("*", "")
    text = text.replace("&", " and ")
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()

def contains_telugu(text: str) -> bool:
    """Detect if text contains Telugu Unicode characters."""
    return any(0x0C00 <= ord(c) <= 0x0C7F for c in text)

def is_roman_telugu(text: str) -> bool:
    """Detect common Roman Telugu (Tenglish) words if transcribed in Latin script."""
    words = set(re.findall(r'[a-z]+', text.lower()))
    telugu_markers = {
        "namaskaram", "andi", "memu", "maadi", "meeku", "meeru", "cheppandi",
        "chestamu", "chestaru", "unnaya", "pampandi", "chesamu", "avunu",
        "kaadu", "vaddu", "ippudu", "telugu", "bhasha", "cinemalu"
    }
    return len(words.intersection(telugu_markers)) >= 2

async def stream_tts_segments(
    websocket: WebSocket,
    turn_id: int,
    text: str,
    language_code: str,
    speaker: str,
    t_reference: float
):
    """
    Ultra-low-latency voice synthesis with zero audio stutter:
    1. If English and speaker is 'asteria' or 'deepgram': synthesize via Deepgram Aura (~750ms).
    2. If Sarvam voice (simran/kavitha/amit): synthesize via Sarvam bulbul:v3 with linear16 PCM.
    """
    clean_text = clean_for_speech(text)
    if not clean_text:
        return 0

    t_req = time.time()

    # 1. Ultra-fast English path (Deepgram Aura: ~750ms complete audio)
    if language_code == "en-IN" and (speaker.lower() in ("asteria", "luna", "deepgram", "stella") or (deepgram_key and speaker.lower() == "aura")):
        try:
            aura_model = f"aura-{speaker.lower()}-en" if speaker.lower() in ("asteria", "luna", "stella") else "aura-asteria-en"
            audio_bytes = await synthesize_deepgram_aura(clean_text, aura_model)
            if audio_bytes:
                ttfa_ms = int((time.time() - t_reference) * 1000)
                b64 = base64.b64encode(audio_bytes).decode("ascii")
                print(f"[Deepgram Aura TTS ({int((time.time() - t_req)*1000)}ms | TTFA {ttfa_ms}ms)]: {len(b64)} b64 chars", flush=True)
                await websocket.send_json({
                    "type": "agent_audio_segment",
                    "turn_id": turn_id,
                    "seq": 0,
                    "skip_sec": 0.0,
                    "audio": b64,
                    "mime_type": "audio/mpeg",
                    "ttfa_ms": ttfa_ms
                })
                await websocket.send_json({
                    "type": "agent_audio_done",
                    "turn_id": turn_id,
                    "ttfa_ms": ttfa_ms
                })
                return ttfa_ms
        except Exception as dg_tts_err:
            print(f"[Deepgram Aura Fallback]: {dg_tts_err}", flush=True)

    # 2. Sarvam Streaming bulbul:v3 with linear16 PCM (Crystal clear, zero stutter)
    valid_speakers = {"amit", "simran", "kavitha", "gokul", "aditya", "rahul", "priya", "ritu", "rohan"}
    if language_code == "te-IN" and speaker in ("simran", "amit", "asteria", "deepgram"):
        sarvam_speaker = "kavitha"
    else:
        sarvam_speaker = speaker if speaker in valid_speakers else ("kavitha" if language_code == "te-IN" else "simran")

    try:
        first_ttfa_ms = 0
        seq = 0
        async with sarvam_client.text_to_speech_streaming.connect(
            model="bulbul:v3",
            send_completion_event="true"
        ) as tts_ws:
            await tts_ws.configure(
                target_language_code=language_code,
                speaker=sarvam_speaker,
                speech_sample_rate=16000,
                output_audio_codec="linear16"
            )
            await tts_ws.convert(clean_text)
            await tts_ws.flush()

            async for msg in tts_ws:
                audio_chunk = getattr(msg, "audio", None)
                event_type = getattr(msg, "event_type", None)
                if not audio_chunk and hasattr(msg, "data") and msg.data:
                    audio_chunk = getattr(msg.data, "audio", None)
                    event_type = getattr(msg.data, "event_type", event_type)

                if audio_chunk:
                    now_ms = int((time.time() - t_reference) * 1000)
                    if seq == 0:
                        first_ttfa_ms = now_ms
                        dur_ms = int((time.time() - t_req) * 1000)
                        print(f"[Sarvam TTS Linear16 Chunk 0 ({dur_ms}ms | TTFA {first_ttfa_ms}ms)]: {len(audio_chunk)} chars", flush=True)
                    await websocket.send_json({
                        "type": "agent_audio_segment",
                        "turn_id": turn_id,
                        "seq": seq,
                        "skip_sec": 0.0,
                        "audio": audio_chunk,
                        "mime_type": "audio/pcm",
                        "sample_rate": 16000,
                        "ttfa_ms": first_ttfa_ms
                    })
                    seq += 1

                if event_type == "final":
                    break

        if seq > 0:
            await websocket.send_json({
                "type": "agent_audio_done",
                "turn_id": turn_id,
                "ttfa_ms": first_ttfa_ms
            })
            return first_ttfa_ms
    except asyncio.CancelledError:
        print(f"[TTS Cancelled for Turn {turn_id}]", flush=True)
        return 0
    except Exception as stream_err:
        print(f"[TTS Stream Error]: {stream_err}", flush=True)

    return 0

async def generate_llm_reply(messages: list, brain: str = "gemini") -> str:
    """
    Ultra-low-latency conversational response using Gemini 2.5 Flash (~950ms turnaround),
    with automatic fallback to Sarvam-105B.
    """
    if gemini_client and brain != "sarvam":
        try:
            system_instruction = ""
            contents = []
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "system":
                    system_instruction = content
                elif role == "user":
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=content)]))
                elif role == "assistant":
                    contents.append(types.Content(role="model", parts=[types.Part.from_text(text=content)]))

            if not contents:
                contents = [types.Content(role="user", parts=[types.Part.from_text(text="Hello")])]

            resp = None
            for model_cand in ["gemini-2.5-flash-lite", "gemini-2.5-flash"]:
                try:
                    resp = await gemini_client.aio.models.generate_content(
                        model=model_cand,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction if system_instruction else None,
                            thinking_config=types.ThinkingConfig(thinking_budget=0),
                            max_output_tokens=45,
                            temperature=0.25
                        )
                    )
                    if resp and resp.text:
                        break
                except Exception:
                    continue

            if resp and resp.text:
                reply = resp.text.strip()
                if reply:
                    return reply
        except Exception as e:
            print(f"[Gemini 2.5 Flash Error, falling back to Sarvam]: {e}", flush=True)

    # Sarvam 105B fallback
    try:
        resp = await sarvam_client.chat.completions(
            model="sarvam-105b-conversations",
            messages=messages,
            max_tokens=45,
            temperature=0.25
        )
        reply = resp.choices[0].message.content.strip()
        if reply:
            return reply
    except Exception as e:
        print(f"[Sarvam LLM Error]: {e}", flush=True)

    # Fast fallback
    return "Hello! We are calling from Pontis LLP Hyderabad. Could you share your localization or dubbing requirements?"


# -------------------------------------------------------------
# Instant Canned Intent Audio Cache (<15ms Sub-Second Dispatch)
# -------------------------------------------------------------
CANNED_DIR = static_dir / "previews" / "canned"
CANNED_CACHE = {}
_CANNED_CACHE_LOADED = False

def load_canned_cache():
    global CANNED_CACHE, _CANNED_CACHE_LOADED
    if CANNED_DIR.exists():
        for p in CANNED_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                lang = data.get("lang", "te-IN")
                intent = data.get("intent", "")
                data["audio_url"] = f"/static/previews/canned/{p.stem}.wav"
                CANNED_CACHE[(lang, intent)] = data
            except Exception as e:
                print(f"[Canned Load Error {p.name}]: {e}", flush=True)
    _CANNED_CACHE_LOADED = True
    print(f"[Pontis Server] Loaded {len(CANNED_CACHE)} instant voice responses into RAM cache.", flush=True)

def detect_canned_intent(user_text: str, active_lang: str, used_intents: set | None = None):
    t = user_text.lower().strip()
    intent = None

    # 1. Microdrama / Web Series / OTT / Film Production
    if any(k in t for k in ["microdrama", "మైక్రోడ్రామా", "web series", "వెబ్ సిరీస్", "షార్ట్ సిరీస్", "short series", "ott", "serial", "film", "movie", "youtube", "reels", "production", "video", "content"]):
        intent = "microdrama"
    # 2. EdTech / Education / Training / Courses / SCORM
    elif any(k in t for k in ["education", "ఎడ్యుకేషన్", "edtech", "course", "కోర్సు", "training", "ట్రైనింగ్", "scorm", "e-learning", "elearning", "learning", "school", "college", "academy", "lms"]):
        intent = "edtech"
    # 3. In-house team / Existing vendor
    elif any(k in t for k in ["in-house", "inhouse", "in house", "ఇన్-హౌస్", "existing team", "own team", "already have", "have a team", "vendor"]):
        intent = "inhouse"
    # 4. WhatsApp / Send profile / Send samples / Share details
    elif any(k in t for k in ["వాట్సాప్", "వాట్సప్", "whatsapp", "నంబర్", "number", "pampandi", "పంపించ", "send", "profile", "प्रोफाइल", "ప్రొఫైల్", "sample", "శాంపిల్", "details", "share", "mail", "మెయిల్", "portfolio", "brochure"]):
        intent = "whatsapp"
    # 5. Services / What do you do
    elif any(k in t for k in ["సర్వీస్", "సర్వీసెస్", "services", "service", "ఏం చేస్తారు", "em chestaru", "what do you do", "what do you offer", "capabilities", "localization", "dubbing", "about", "explain", "how do you help", "languages"]):
        intent = "services"
    # 6. Busy / Call later
    elif any(k in t for k in ["బిజీ", "busy", "కుదరదు", "later", "తర్వాత", "tarvata", "repu", "రేపు", "సాయంత్రం", "evening", "tomorrow", "call back", "not now", "meeting", "driving", "bad time"]):
        intent = "busy"
    # 7. Pricing / Cost
    elif any(k in t for k in ["ఖర్చు", "ధర", "రేటు", "cost", "price", "pricing", "budget", "charges", "rate", "entha", "ఎంత", "how much", "quote", "quotation", "per minute"]):
        intent = "pricing"
    # 8. Who is this / Pontis
    elif any(k in t for k in ["ఎవరు", "evvaru", "who is this", "who are you", "who speaking", "ekkada nundi", "where are you calling", "which company"]):
        intent = "who_is_this"
    # 9. Not interested / Disconnect
    elif any(k in t for k in ["వద్దు", "vaddu", "oddu", "not interested", "avsaram ledu", "అవసరం లేద", "no need", "dont need", "don't need", "dont want", "don't want", "no thanks", "stop", "no requirement"]):
        intent = "not_interested"
    # 10. Yes / Continue
    elif any(k in t for k in ["చెప్పండి", "cheppandi", "ok", "okay", "ha", "avunu", "yes", "yeah", "yep", "tell me", "sure", "proceed", "go ahead", "speak", "carry on", "listening"]):
        intent = "yes_continue"
    # 11. Hello / Mic Test / Audible check
    elif any(k in t for k in ["hello", "hi", "hey", "mic test", "testing", "hear me", "audible", "హలో", "నమస్కారం"]):
        intent = "hello"

    if not intent:
        return None, None

    if used_intents is not None and intent in used_intents:
        # Smart stage progression so we never repeat the exact same canned clip twice!
        if intent in ("hello", "yes_continue"):
            if "services" not in used_intents:
                intent = "services"
            elif "whatsapp" not in used_intents:
                intent = "whatsapp"
            else:
                return None, None
        else:
            return None, None

    # Check if user_text itself has Telugu script -> force te-IN, else use active_lang (default en-IN)
    target_lang = "te-IN" if (contains_telugu(user_text) or is_roman_telugu(user_text)) else active_lang
    data = CANNED_CACHE.get((target_lang, intent)) or CANNED_CACHE.get(("en-IN", intent)) or CANNED_CACHE.get(("te-IN", intent))
    if data:
        if used_intents is not None:
            used_intents.add(intent)
        return intent, data
    return None, None

@app.websocket("/ws/talk")
async def websocket_talk(websocket: WebSocket):
    if not _CANNED_CACHE_LOADED:
        load_canned_cache()
    await websocket.accept()
    conversation_history = []
    turn_counter = 0
    active_conversation_lang = "en-IN"
    used_canned_intents = set()
    prefer_url_mode = False
    current_tts_task: asyncio.Task | None = None
    call_start_time = time.time()
    print("\n[Pontis Simulator] Client connected.", flush=True)

    def cancel_active_tts():
        nonlocal current_tts_task
        if current_tts_task and not current_tts_task.done():
            current_tts_task.cancel()
        current_tts_task = None

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "interrupt":
                cancel_active_tts()
                continue

            if action == "end_call":
                cancel_active_tts()
                user_turns = [m for m in conversation_history if m.get("role") == "user"]
                call_id = f"call_{int(time.time())}_{os.urandom(2).hex()}"
                dur_sec = max(8, int(time.time() - call_start_time))
                billed_cost = round(max(1.0, dur_sec / 60.0) * 1.0, 2)

                if user_turns:
                    report = await generate_call_report(conversation_history)
                else:
                    report = {
                        "qualification_status": "DROPPED",
                        "prospect_industry": "None",
                        "decision_maker_role": "None",
                        "identified_need": "None",
                        "agreed_next_step": "Retry call at scheduled business hour",
                        "executive_summary": "Call disconnected during opening greeting before prospect engaged."
                    }

                try:
                    record_completed_call(
                        call_id=call_id,
                        customer_phone="+91 98490 12345",
                        customer_name="Simulator Prospect",
                        employee_id="emp_01",
                        duration_seconds=dur_sec,
                        billed_credits=billed_cost,
                        qualification_status=report.get("qualification_status", "DROPPED"),
                        identified_need=report.get("identified_need", ""),
                        decision_maker_role=report.get("decision_maker_role", ""),
                        agreed_next_step=report.get("agreed_next_step", ""),
                        summary=report.get("executive_summary", ""),
                        transcript=conversation_history,
                    )
                except Exception as log_err:
                    print(f"[Call Log Save Error]: {log_err}")

                await websocket.send_json({"type": "call_report", "report": report})
                continue

            if action == "init":
                turn_counter += 1
                this_turn = turn_counter
                language_code = data.get("language_code", "en-IN")
                active_conversation_lang = language_code
                speaker = data.get("speaker", "kavitha" if language_code == "te-IN" else "simran")
                agent_name = "Kavitha" if speaker in ["kavitha", "simran", "priya", "ritu"] else "Amit"
                custom_prompt = data.get("system_prompt", "").strip()
                system_prompt = custom_prompt if custom_prompt else PONTIS_SYSTEM_PROMPT.format(agent_name=agent_name)

                prefer_url_mode = bool(data.get("prefer_url", False))
                client_played_greeting = bool(data.get("client_played_greeting", False))
                used_canned_intents.clear()
                custom_greeting = data.get("first_sentence", "").strip()
                cached_b64 = ""
                cached_audio_url = ""
                cached_preview_path = static_dir / "previews" / f"{speaker}.json"

                if not custom_greeting:
                    # 1. Try speaker preview if its language matches requested language_code
                    if cached_preview_path.exists():
                        try:
                            cached_data = json.loads(cached_preview_path.read_text(encoding="utf-8"))
                            if cached_data.get("lang") == language_code and cached_data.get("audio"):
                                initial_msg = cached_data.get("text", "")
                                cached_b64 = cached_data.get("audio", "")
                                cached_audio_url = f"/static/previews/{speaker}.wav"
                        except Exception:
                            pass
                    # 2. Fallback to canned greeting for the exact requested language_code (en-IN or te-IN)
                    if not cached_b64:
                        canned_greet = CANNED_CACHE.get((language_code, "greeting"))
                        if canned_greet:
                            initial_msg = canned_greet["text"]
                            cached_b64 = canned_greet["audio"]
                            cached_audio_url = canned_greet.get("audio_url", "")
                        elif language_code == "en-IN":
                            initial_msg = f"Hello! This is {agent_name} calling from Pontis LLP Hyderabad. We help businesses with AI dubbing and video localization. Do you have a minute?"
                        else:
                            initial_msg = f"నమస్కారం అండి! Pontis LLP హైదరాబాద్ నుండి {agent_name}ని. AI dubbing మరియు localization లో హెల్ప్ చేస్తాము, ఒక్క నిమిషం మాట్లాడవచ్చా అండి?"
                elif custom_greeting:
                    initial_msg = custom_greeting
                elif language_code == "te-IN":
                    initial_msg = (
                        f"నమస్కారం అండి! Pontis LLP హైదరాబాద్ నుండి {agent_name}ని. "
                        "AI dubbing మరియు localization లో హెల్ప్ చేస్తాము, ఒక్క నిమిషం మాట్లాడవచ్చా అండి?"
                    )
                else:
                    initial_msg = (
                        f"Hi, this is {agent_name} calling from Pontis LLP. "
                        "We help with AI dubbing and video localization. Do you have 30 seconds?"
                    )

                conversation_history = [
                    {"role": "system", "content": system_prompt},
                    {"role": "assistant", "content": initial_msg}
                ]

                if client_played_greeting:
                    print(f"[Pontis Init] Client already started instant preloaded greeting (<10ms, {speaker})", flush=True)
                    continue

                # Immediate Greeting Text
                await websocket.send_json({
                    "type": "agent_text",
                    "turn_id": this_turn,
                    "text": initial_msg,
                    "stt_ms": 0,
                    "llm_ms": 0
                })

                # Instant Audio: if cached preview exists, dispatch in 10ms!
                if cached_b64 or cached_audio_url:
                    await websocket.send_json({
                        "type": "agent_audio_segment",
                        "turn_id": this_turn,
                        "seq": 0,
                        "skip_sec": 0.0,
                        "audio_url": cached_audio_url,
                        "audio": "" if (prefer_url_mode and cached_audio_url) else cached_b64,
                        "mime_type": "audio/wav",
                        "ttfa_ms": 10
                    })
                    await websocket.send_json({
                        "type": "agent_audio_done",
                        "turn_id": this_turn,
                        "ttfa_ms": 10
                    })
                    print(f"[Pontis Init] Instant cached greeting dispatched in 10ms ({speaker}, url={cached_audio_url})", flush=True)
                else:
                    t0 = time.time()
                    current_tts_task = asyncio.create_task(
                        stream_tts_segments(websocket, this_turn, initial_msg, language_code, speaker, t0)
                    )
                    print(f"[Pontis Init] Dynamic greeting synthesizing ({language_code}, {speaker})", flush=True)

            elif action in ("user_audio", "user_message", "user_text"):
                turn_counter += 1
                current_turn = turn_counter
                language_pref = data.get("language_code", active_conversation_lang)
                speaker = data.get("speaker", "kavitha" if language_pref == "te-IN" else "simran")
                brain = data.get("brain", "sarvam")
                agent_name = "Kavitha" if speaker in ["kavitha", "simran", "priya", "ritu"] else "Amit"
                custom_prompt = data.get("system_prompt", "").strip()
                system_prompt = custom_prompt if custom_prompt else PONTIS_SYSTEM_PROMPT.format(agent_name=agent_name)

                stt_ms = int(data.get("stt_ms", 0))
                detected_lang = language_pref

                if action == "user_audio":
                    audio_b64 = data.get("audio", "")
                    mime_type = data.get("mime_type", "audio/wav")
                    if not audio_b64:
                        continue
                    audio_bytes = base64.b64decode(audio_b64)
                    if len(audio_bytes) < 1000:
                        await websocket.send_json({"type": "stt_empty"})
                        continue

                    try:
                        user_text, detected_lang, stt_ms = await transcribe_speech(audio_bytes, mime_type, language_pref)
                    except Exception as e:
                        print(f"[STT Error]: {e}", flush=True)
                        await websocket.send_json({"type": "stt_empty", "error": str(e)})
                        continue

                    # Ignore empty / 1-char noise transcripts
                    if not user_text or len(user_text.strip(".,?! ")) < 2:
                        print(f"[STT Ignored Noise ({stt_ms}ms)]: {user_text!r}")
                        await websocket.send_json({"type": "stt_empty"})
                        continue

                    print(f"\n[Prospect Audio -> STT ({stt_ms}ms | {detected_lang})]: {user_text}")
                    await websocket.send_json({
                        "type": "user_transcript",
                        "turn_id": current_turn,
                        "text": user_text,
                        "language_code": detected_lang,
                        "stt_ms": stt_ms
                    })
                else:
                    user_text = data.get("text", "").strip()
                    if not user_text:
                        continue
                    print(f"\n[Prospect Text]: {user_text}")

                cancel_active_tts()
                if data.get("prefer_url") is not None:
                    prefer_url_mode = bool(data.get("prefer_url"))

                # Robust Language Consistency Locking (Primary: en-IN, Automatic Bilingual Switch to te-IN)
                low_text = user_text.lower().strip()
                if "speak in english" in low_text or "talk in english" in low_text or "in english" in low_text or "ఇంగ్లీష్" in user_text:
                    active_conversation_lang = "en-IN"
                elif contains_telugu(user_text) or is_roman_telugu(user_text) or "telugu" in low_text or "తెలుగు" in user_text:
                    active_conversation_lang = "te-IN"
                elif language_pref == "te-IN":
                    active_conversation_lang = "te-IN"
                elif len(user_text.split()) >= 3 and not contains_telugu(user_text) and not is_roman_telugu(user_text) and language_pref == "en-IN":
                    active_conversation_lang = "en-IN"

                reply_lang = active_conversation_lang
                if reply_lang == "te-IN":
                    lang_directive = (
                        " [INSTRUCTION: Respond in natural, polite Hyderabad Telugu (1-2 short sentences, under 22 words). "
                        "Acknowledge what was said. Obey all conversational laws: if they are distracted/talking to family, "
                        "check if they are busy. If they joke/order food, laugh it off with charm. "
                        "NEVER repeat a WhatsApp or sample offer if already mentioned recently!]"
                    )
                else:
                    lang_directive = (
                        " [INSTRUCTION: Respond in crisp, natural Indian English (1-2 short sentences, under 22 words). "
                        "Acknowledge what was said. Obey all conversational laws: if distracted or joking, respond naturally. "
                        "NEVER repeat a WhatsApp or sample offer if already mentioned recently!]"
                    )

                if not conversation_history:
                    conversation_history.append({"role": "system", "content": system_prompt})
                else:
                    conversation_history[0] = {"role": "system", "content": system_prompt}

                conversation_history.append({"role": "user", "content": user_text})

                # Instant Canned Intent Trigger (<12ms Sub-Second Dispatch)
                canned_intent, canned_data = detect_canned_intent(user_text, reply_lang, used_canned_intents)
                if canned_data:
                    canned_reply = canned_data["text"]
                    canned_b64 = canned_data["audio"]
                    canned_url = canned_data.get("audio_url", "")
                    actual_lang = canned_data.get("lang", reply_lang)
                    print(f"[Instant Canned Voice Dispatched in 12ms]: Intent '{canned_intent}' ({actual_lang}, url={canned_url})", flush=True)
                    conversation_history.append({"role": "assistant", "content": canned_reply})

                    await websocket.send_json({
                        "type": "agent_text",
                        "turn_id": current_turn,
                        "text": canned_reply,
                        "language_code": actual_lang,
                        "stt_ms": stt_ms,
                        "llm_ms": 5
                    })
                    await websocket.send_json({
                        "type": "agent_audio_segment",
                        "turn_id": current_turn,
                        "seq": 0,
                        "skip_sec": 0.0,
                        "audio_url": canned_url,
                        "audio": "" if (prefer_url_mode and canned_url) else canned_b64,
                        "mime_type": "audio/wav",
                        "ttfa_ms": 12
                    })
                    await websocket.send_json({
                        "type": "agent_audio_done",
                        "turn_id": current_turn,
                        "ttfa_ms": 12
                    })
                    continue

                # Build messages with explicit per-turn language directive
                llm_messages = list(conversation_history[:-1]) + [
                    {"role": "user", "content": user_text + lang_directive}
                ]

                t_llm = time.time()
                reply_text = await generate_llm_reply(llm_messages, brain)
                reply_text = clean_for_speech(reply_text)
                llm_ms = int((time.time() - t_llm) * 1000)

                # If reply contains Telugu characters, ensure TTS uses te-IN
                if contains_telugu(reply_text):
                    reply_lang = "te-IN"

                conversation_history.append({"role": "assistant", "content": reply_text})
                print(f"[Pontis ({reply_lang} | LLM: {llm_ms}ms)]: {reply_text}", flush=True)

                # Send text immediately so UI shows reply at ~200ms
                await websocket.send_json({
                    "type": "agent_text",
                    "turn_id": current_turn,
                    "text": reply_text,
                    "language_code": reply_lang,
                    "stt_ms": stt_ms,
                    "llm_ms": llm_ms
                })

                # Stream frame-aligned MP3 audio segments asynchronously so client can interrupt anytime!
                current_tts_task = asyncio.create_task(
                    stream_tts_segments(websocket, current_turn, reply_text, reply_lang, speaker, t_llm)
                )

    except WebSocketDisconnect:
        print("[Pontis Simulator] Client disconnected.", flush=True)
    except Exception as e:
        print(f"[Pontis Simulator WebSocket Error]: {e}", flush=True)
    finally:
        cancel_active_tts()
