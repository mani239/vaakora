"""Standalone Outpero-style real-time WebSocket voice engine server + mountable router."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import sys
from fastapi import APIRouter, FastAPI, Query, WebSocket

from engine.config import enable_ipv4_only, engine_capabilities, probe_cartesia_credits
from engine.pipeline import SessionConfig, run_voice_session

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

enable_ipv4_only()

engine_router = APIRouter()

_DEMO_DAILY_LIMIT = 3
_DEMO_IP_USAGE: dict[tuple[str, str], int] = {}


def _check_and_record_demo_quota(client_host: str) -> bool:
    """Allow unlimited calls on loopback; cap external IPs at 3 public demo calls per UTC day."""
    host = (client_host or "").strip()
    if host in ("", "127.0.0.1", "::1", "localhost"):
        return True
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = (host, today)
    count = _DEMO_IP_USAGE.get(key, 0)
    if count >= _DEMO_DAILY_LIMIT:
        return False
    _DEMO_IP_USAGE[key] = count + 1
    return True


@engine_router.get("/health")
@engine_router.get("/api/engine/health")
async def engine_health():
    """Return active English engine providers (Silero VAD, Deepgram STT, Groq/Gemini LLM, Smallest/Cartesia/Aura TTS)."""
    await probe_cartesia_credits()
    return engine_capabilities()


@engine_router.websocket("/ws/engine")
async def ws_browser_engine(
    websocket: WebSocket,
    speaker: str = Query("archie"),
    llm: str = Query("auto"),
    employee_id: str = Query(""),
    lead_id: str = Query(""),
    genre: str = Query(""),
    demo: bool = Query(False),
):
    """Real-time full-duplex 16kHz Int16 PCM + JSON WebSocket endpoint for browser testing."""
    await websocket.accept()
    if demo:
        client_host = websocket.client.host if websocket.client else ""
        if not _check_and_record_demo_quota(client_host):
            await websocket.send_json({
                "type": "error",
                "message": "Daily demo limit reached (3 calls per day). Open the console or try again tomorrow.",
            })
            await websocket.close(code=1008)
            return
    cfg = SessionConfig(
        mode="browser",
        speaker=speaker,
        llm_provider=llm,
        employee_id=employee_id,
        lead_id=lead_id,
        genre=genre,
        demo=demo,
    )

    # Wait briefly for optional JSON `init` handshake before spinning up Pipecat pipeline
    try:
        first_msg = await asyncio.wait_for(websocket.receive(), timeout=1.5)
        if first_msg.get("type") == "websocket.disconnect":
            return
        if first_msg.get("text"):
            data = json.loads(first_msg["text"])
            if data.get("action") == "init":
                cfg.speaker = data.get("speaker") or cfg.speaker
                cfg.llm_provider = data.get("llm") or cfg.llm_provider
                cfg.employee_id = data.get("employee_id") or cfg.employee_id
                cfg.lead_id = data.get("lead_id") or cfg.lead_id
                cfg.genre = data.get("genre") if data.get("genre") is not None else cfg.genre
                cfg.first_sentence = data.get("first_sentence") or ""
                cfg.system_prompt = data.get("system_prompt") or ""
                if data.get("demo") is True and not cfg.demo:
                    client_host = websocket.client.host if websocket.client else ""
                    if not _check_and_record_demo_quota(client_host):
                        await websocket.send_json({
                            "type": "error",
                            "message": "Daily demo limit reached (3 calls per day). Open the console or try again tomorrow.",
                        })
                        await websocket.close(code=1008)
                        return
                    cfg.demo = True
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    await run_voice_session(websocket, cfg)


@engine_router.websocket("/ws/telephony/{provider}")
async def ws_telephony_engine(
    websocket: WebSocket,
    provider: str,
    speaker: str = Query("aria"),
    employee_id: str = Query(""),
    lead_id: str = Query(""),
    genre: str = Query(""),
    codec: str = Query("ulaw"),
    call_sid: str = Query(""),
    stream_sid: str = Query(""),
):
    """Bidirectional telephony Media Streams endpoint for Vobiz, Exotel, Twilio, and Plivo trunks."""
    await websocket.accept()
    cfg = SessionConfig(
        mode=provider.lower(),
        speaker=speaker,
        employee_id=employee_id,
        lead_id=lead_id,
        genre=genre,
        codec=codec,
        call_sid=call_sid,
        stream_sid=stream_sid,
    )

    # Handshake detection for Exotel/Twilio/Vobiz `start` event carrying stream_sid / call_sid
    if not cfg.stream_sid:
        try:
            peek = await websocket.receive_text()
            msg = json.loads(peek)
            start_meta = msg.get("start") or msg
            cfg.stream_sid = start_meta.get("streamSid") or start_meta.get("stream_sid") or start_meta.get("stream_id") or ""
            cfg.call_sid = start_meta.get("callSid") or start_meta.get("call_sid") or cfg.call_sid
        except Exception:
            pass

    await run_voice_session(websocket, cfg)


app = FastAPI(title="Outpero-Style Real-Time Voice Engine (English)")
app.include_router(engine_router)
