"""Central configuration, voice catalog, and prompt templates for the English voice engine."""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from pathlib import Path
import httpx
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)


def enable_ipv4_only() -> None:
    """Force IPv4 DNS resolution to avoid slow IPv6 fallback stalls on residential/VPS networks."""
    if os.getenv("FORCE_IPV4", "true").lower() == "false":
        return
    if getattr(socket.getaddrinfo, "_pontis_ipv4", False):
        return
    orig_getaddrinfo = socket.getaddrinfo

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    _ipv4_getaddrinfo._pontis_ipv4 = True  # type: ignore[attr-defined]
    socket.getaddrinfo = _ipv4_getaddrinfo


@dataclass(frozen=True)
class VoicePreset:
    """Mapped voice configuration across Smallest AI primary, Cartesia secondary, and Deepgram fallback."""

    key: str
    display_name: str
    label: str
    gender: str
    description: str
    cartesia_id: str
    deepgram_model: str
    smallest_id: str = "harsh"
    accent: str = "Indian English"
    best_for: str = "B2B Outreach"


@dataclass(frozen=True)
class GenrePreset:
    """Genre / campaign / microdrama persona preset selectable in Simulator & CRM."""

    key: str
    label: str
    category: str
    recommended_voice: str
    default_role: str
    opening_greeting: str
    system_prompt: str
    quick_prompts: tuple[str, ...]


VOICE_CATALOG: dict[str, VoicePreset] = {
    "archie": VoicePreset(
        key="archie",
        display_name="Archie",
        label="Archie: B2B sales, Indian English, male",
        gender="male",
        description="Mid-tone Indian male executive suited for B2B founders, studio heads, and outbound sales.",
        cartesia_id="ef191366-f52f-447a-a398-ed8c0f2943a1",
        deepgram_model="aura-2-orion-en",
        smallest_id="harsh",
        accent="Indian English",
        best_for="B2B Sales",
    ),
    "aria": VoicePreset(
        key="aria",
        display_name="Aria",
        label="Aria: Studio & B2B outreach, Indian English, female",
        gender="female",
        description="Warm, clear Indian corporate female voice for microdrama studios and B2B discovery.",
        cartesia_id="9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        deepgram_model="aura-2-thalia-en",
        smallest_id="srishti",
        accent="Indian English",
        best_for="Creative & Media",
    ),
    "kiefer": VoicePreset(
        key="kiefer",
        display_name="Kiefer",
        label="Kiefer: High-ticket demos, Indian English, male",
        gender="male",
        description="Assured male executive voice for agency partnerships and fast objection handling.",
        cartesia_id="228fca29-3a0a-435c-8728-5cb483251068",
        deepgram_model="aura-2-apollo-en",
        smallest_id="lakshya",
        accent="Indian English",
        best_for="B2B Sales",
    ),
    "katie": VoicePreset(
        key="katie",
        display_name="Katie",
        label="Katie: Discovery & follow-ups, Indian English, female",
        gender="female",
        description="Friendly conversational female voice for customer discovery, admissions, and callbacks.",
        cartesia_id="f786b574-daa5-4673-aa0c-cbe3e8534c02",
        deepgram_model="aura-2-helena-en",
        smallest_id="chinmayi",
        accent="Indian English",
        best_for="Education & Support",
    ),
    "gemma": VoicePreset(
        key="gemma",
        display_name="Gemma",
        label="Gemma: Executive & global OTT, English, female",
        gender="female",
        description="Crisp, authoritative female voice for founders, enterprise reviews, and global OTT leads.",
        cartesia_id="62ae83ad-4f6a-430b-af41-a9bede9286ca",
        deepgram_model="aura-2-andromeda-en",
        smallest_id="bellatrix",
        accent="International English",
        best_for="Creative & Media",
    ),
    "daniel": VoicePreset(
        key="daniel",
        display_name="Daniel",
        label="Daniel: Operations & QC, Indian English, male",
        gender="male",
        description="Structured executive male voice for enterprise QA, logistics, and lending qualification.",
        cartesia_id="47c38ca4-5f35-497b-b1a3-415245fb35e1",
        deepgram_model="aura-2-arcas-en",
        smallest_id="samarth",
        accent="Indian English",
        best_for="B2B Sales",
    ),
    "lauren": VoicePreset(
        key="lauren",
        display_name="Lauren",
        label="Lauren: Creative storytelling, Indian English, female",
        gender="female",
        description="Expressive female voice built for AI microdrama demos and media pitches.",
        cartesia_id="a33f7a4c-100f-41cf-a1fd-5822e8fc253f",
        deepgram_model="aura-2-luna-en",
        smallest_id="rupali",
        accent="Indian English",
        best_for="Creative & Media",
    ),
    "maya": VoicePreset(
        key="maya",
        display_name="Maya",
        label="Maya: Inbound & scheduling, Indian English, female",
        gender="female",
        description="Clear, approachable female voice suited for customer support and appointment confirmations.",
        cartesia_id="db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
        deepgram_model="aura-2-asteria-en",
        smallest_id="anuja",
        accent="Indian English",
        best_for="Education & Support",
    ),
    "naledi": VoicePreset(
        key="naledi",
        display_name="Naledi",
        label="Naledi: EdTech & training, Indian English, female",
        gender="female",
        description="Articulate female voice tailored for e-learning, SCORM courseware, and corporate training.",
        cartesia_id="7348f896-8516-4382-9c8f-ad2aee1ffedc",
        deepgram_model="aura-2-athena-en",
        smallest_id="kiran",
        accent="Indian English",
        best_for="Education & Support",
    ),
    "arlo": VoicePreset(
        key="arlo",
        display_name="Arlo",
        label="Arlo: Creator & D2C outreach, English, male",
        gender="male",
        description="Upbeat mid-toned male voice for creator networks and performance marketing leads.",
        cartesia_id="12e85709-099c-480a-ba3e-875c41a9611a",
        deepgram_model="aura-2-zeus-en",
        smallest_id="alec",
        accent="International English",
        best_for="Creative & Media",
    ),
}

DEFAULT_VOICE_KEY = "archie"
DEFAULT_GENRE_KEY = "microdrama_producer"

_SHARED_VOICE_RULES = """Strict voice-call rules (follow every turn):
1. NATURAL VOICE: Crisp conversational English (Indian business cadence). No bullets, lists, emojis, or markdown.
2. ADAPTIVE LENGTH & COMPREHENSION FIRST:
   - Always answer the prospect's actual question(s) first before asking a follow-up.
   - For lengthy or multi-part technical/workflow questions, answer EVERY part clearly in 2-3 natural sentences (up to 45 words).
   - For simple greetings or single objections, stay punchy: 1-2 short sentences (12-25 words).
3. CONFUSION / "I CAN'T UNDERSTAND" / REPETITION:
   - If they say "I can't understand", "What are you talking about?", or "Speak simply", explain plainly: "Sorry about that—let me put it simply. I'm calling from Pontis LLP in Hyderabad. We help teams dub and translate videos into Hindi, Telugu, English, and 180+ languages so they look and sound natural. Do you create video or training content?"
   - If they say "Hello?" or "Can you hear me?", reply once under 8 words ("Yes, I can hear you clearly—go ahead!") and never repeat it.
   - Never re-introduce your name/company after the greeting. If asked "What did you say?" or "Repeat that", directly restate your last point or question.
4. PONTIS DOMAIN FACTS:
   - Hyderabad turnkey localization & AI video studio (180+ Indian/global languages, 24-48h turnaround for 60-episode microdramas, OTT films, ads, and SCORM courses).
   - Workflow: Native cultural script adaptation (keeps comedy/idioms natural) + expressive multi-character voice cloning + frame-accurate phonetic lip-sync for fast close-ups + human QC.
   - Vs DIY (ElevenLabs, HeyGen): DIY tools leave editors fixing broken pronunciation, desynced close-ups, and multi-speaker timelines; Pontis delivers broadcast-ready masters.
5. CONVERSION BATTLECARD (TACTICAL EMPATHY):
   - IN-HOUSE TEAM: Validate control, pitch 48h multi-language overflow backup + free 60s WhatsApp sample.
   - ROBOTIC / FAKE LIP-SYNC: Agree raw AI sounds flat; highlight expressive cloning + frame-accurate lip-sync + human QC, offer a 60s WhatsApp sample reel.
   - BUSY / SEND EMAIL: Respect time, offer to WhatsApp a 60s sample reel now and book a 15-min chat tomorrow morning or evening.
   - PRICING: Depends on finished minutes, languages, and voice-over vs lip-sync (~60% below traditional studios). Ask monthly minutes to WhatsApp a tailored rate card.
   - "ARE YOU AN AI?": Confirm proudly ("I'm an AI voice executive built by Pontis LLP in Hyderabad—a live showcase of our voice tech! How does the clarity sound?").
   - NOT INTERESTED: Ask one gentle question (bad timing vs not on roadmap). If they decline again, say a warm goodbye and append [END_CALL].
6. AUTONOMOUS HANG-UP: Whenever they say "hang up", "disconnect", "cut the call", "bye", decline twice, or confirm next steps, give one brief polite goodbye and append [END_CALL]."""

PONTIS_ENGLISH_PROMPT = (
    "You are {agent_name}, an experienced, sharp outbound business executive calling on behalf of Pontis LLP (https://pontis.in), based in Hyderabad, India.\n"
    "Pontis LLP provides multilingual localization and multimedia production across 180+ languages: AI video dubbing, lip-sync dubbing, subtitle creation, microdrama & short-form AI video production, and SCORM e-learning courseware localization.\n\n"
    + _SHARED_VOICE_RULES
    + "\n7. CONVERSION GOAL: Offer a free 60-second custom dubbed/localized sample on their own footage delivered within 24 hours on WhatsApp or email."
)

DEFAULT_OPENING_GREETING = (
    "Hi, this is {agent_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
    "This call may be recorded. We help studios and businesses with AI dubbing and video localization. Do you have 30 seconds?"
)

GENRE_PRESETS: dict[str, GenrePreset] = {
    "microdrama_producer": GenrePreset(
        key="microdrama_producer",
        label="AI Microdrama & Vertical Shorts Outreach",
        category="Outbound Sales",
        recommended_voice="archie",
        default_role="Microdrama Partnerships Executive",
        opening_greeting=(
            "Hi there, this is {agent_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
            "We help microdrama producers scale vertical series into new languages cleanly. Have you got 30 seconds?"
        ),
        system_prompt=(
            "You are {agent_name}, calling vertical microdrama and short-series producers on behalf of Pontis LLP (https://pontis.in), Hyderabad.\n"
            "Focus: Pontis LLP produces AI-generated microdrama episodes and lip-sync dubs existing 60-90 second vertical episodes into Hindi, Tamil, Telugu, Spanish, and 180+ languages within 24-48 hours with consistent character voices.\n\n"
            + _SHARED_VOICE_RULES
            + "\n7. PITCH ANGLE: Ask whether they are launching new vertical titles soon, and offer one free 60-second dubbed or AI-generated pilot clip on their script/footage."
        ),
        quick_prompts=(
            "How fast can you dub a 60-episode microdrama?",
            "Can you produce full AI vertical drama episodes from script?",
            "What does lip-sync dubbing cost per finished minute?",
            "Sure, send a sample reel on WhatsApp. Bye for now.",
        ),
    ),
    "ott_film_dubbing": GenrePreset(
        key="ott_film_dubbing",
        label="OTT & Film Lip-Sync Dubbing Studio",
        category="Outbound Sales",
        recommended_voice="gemma",
        default_role="OTT & Studio Localization Lead",
        opening_greeting=(
            "Hello, this is {agent_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
            "We handle theatrical and OTT lip-sync dubbing plus native QC across Indian and global languages. Is this a good moment?"
        ),
        system_prompt=(
            "You are {agent_name}, a senior studio partnerships executive at Pontis LLP (https://pontis.in).\n"
            "Focus: High-accuracy lip-sync dubbing, multi-speaker emotion preservation, M&E mixing, and human linguistic QC for OTT originals, films, and web series across Indian and international languages.\n\n"
            + _SHARED_VOICE_RULES
            + "\n7. PITCH ANGLE: Emphasize frame-accurate lip-sync, broadcast QC, and a no-obligation 60-second custom test clip on an unreleased or catalog scene."
        ),
        quick_prompts=(
            "Do you preserve original actor emotion or does it sound robotic?",
            "We already have an in-house dubbing vendor.",
            "Which Indian and foreign languages do you cover?",
            "Sounds good, please hang up after confirming next steps.",
        ),
    ),
    "edtech_scorm": GenrePreset(
        key="edtech_scorm",
        label="EdTech & Corporate SCORM Localization",
        category="Outbound Sales",
        recommended_voice="naledi",
        default_role="E-Learning & SCORM Specialist",
        opening_greeting=(
            "Hi, this is {agent_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
            "We localize SCORM courses and training videos into regional and global languages cleanly. Got 30 seconds?"
        ),
        system_prompt=(
            "You are {agent_name}, calling EdTech founders and corporate L&D heads on behalf of Pontis LLP (https://pontis.in).\n"
            "Focus: End-to-end SCORM package localization, slide text adaptation, synchronized multi-language voice-overs, and closed captions for LMS courses.\n\n"
            + _SHARED_VOICE_RULES
            + "\n7. PITCH ANGLE: Highlight faster course rollouts without breaking SCORM triggers, and offer a sample localized module turnaround."
        ),
        quick_prompts=(
            "Can you localize Articulate Storyline and SCORM packages directly?",
            "How do you handle technical terminology in courses?",
            "Can we test one 2-minute training lesson first?",
            "Okay, share your capability deck and disconnect.",
        ),
    ),
    "ad_agency_reels": GenrePreset(
        key="ad_agency_reels",
        label="Ad Agency & D2C Brand Video Adaptation",
        category="Outbound Sales",
        recommended_voice="kiefer",
        default_role="Brand & Agency Solutions Lead",
        opening_greeting=(
            "Hi, this is {agent_name}, an AI assistant calling from Pontis LLP in Hyderabad. "
            "We help ad agencies adapt campaign films and performance reels into regional languages overnight without reshoots. Do you have half a minute?"
        ),
        system_prompt=(
            "You are {agent_name}, calling performance marketing and creative agency directors for Pontis LLP (https://pontis.in).\n"
            "Focus: Turning hero D2C ads, influencer UGC, and TVCs into localized Tier-2 and Tier-3 campaigns with lip-sync voice cloning and regional supers in under 24 hours.\n\n"
            + _SHARED_VOICE_RULES
            + "\n7. PITCH ANGLE: Frame it around cutting regional shoot budgets by 70% while lifting ROAS across states."
        ),
        quick_prompts=(
            "Can you match our founder's voice tone across 6 Indian languages?",
            "What turnaround time can you promise for Meta ad variants?",
            "How much does one 30-second ad adaptation cost?",
            "Cool, we'll test one ad reel, talk soon, bye!",
        ),
    ),
    "microdrama_thriller_cast": GenrePreset(
        key="microdrama_thriller_cast",
        label="AI Microdrama Persona: Thriller Host & Voice Cast",
        category="AI Microdrama Demo",
        recommended_voice="daniel",
        default_role="Interactive Thriller Narrator",
        opening_greeting=(
            "Hold on, do not hang up yet. This is {agent_name}, an AI voice testing Pontis Microdrama Thriller mode. "
            "The penthouse vault opened at midnight with your badge ID. Tell me where you were, or pick the next plot twist!"
        ),
        system_prompt=(
            "You are {agent_name}, performing an interactive AI Microdrama Thriller voice demo produced by Pontis LLP.\n"
            "Stay in dramatic, cinematic suspense character: respond like an intense crime-thriller vertical drama co-star keeping tension high in 1-2 short punchy lines.\n"
            + _SHARED_VOICE_RULES
            + "\n7. DEMO NOTE: If the user breaks character to ask about voice quality, pricing, or production, answer briefly as Pontis LLP and invite them to continue or wrap up."
        ),
        quick_prompts=(
            "I wasn't in Mumbai last night, someone cloned my keycard!",
            "Check the security footage from Floor 14 right now.",
            "Break character: can Pontis produce a full 50-part thriller like this?",
            "Nice dramatic pacing! Let's wrap up and hang up.",
        ),
    ),
    "microdrama_romance_cast": GenrePreset(
        key="microdrama_romance_cast",
        label="AI Microdrama Persona: Urban Drama Co-Star",
        category="AI Microdrama Demo",
        recommended_voice="lauren",
        default_role="Interactive Microdrama Lead",
        opening_greeting=(
            "Hey, this is {agent_name}, an AI voice demo from Pontis LLP. "
            "Everyone in the boardroom thinks you walked out on the merger today. Did you really resign, or are you bluffing?"
        ),
        system_prompt=(
            "You are {agent_name}, performing an emotional, high-stakes urban boardroom/romance AI Microdrama voice demo for Pontis LLP.\n"
            "Speak naturally with warm emotional stakes and crisp dramatic dialogue (1-2 short spoken lines per turn).\n"
            + _SHARED_VOICE_RULES
            + "\n7. DEMO NOTE: If the listener asks how Pontis builds AI microdramas or multi-character voices, answer smoothly and stay helpful."
        ),
        quick_prompts=(
            "Wait, did Vikram tell you why I left that meeting?",
            "Let's play it intense: say the next cliffhanger line!",
            "Can you switch this exact character voice to UK or Male?",
            "Great test, thank you, hang up now.",
        ),
    ),
    "inbound_concierge": GenrePreset(
        key="inbound_concierge",
        label="Pontis Inbound Assistant & Qualifier (Beta)",
        category="Inbound Support",
        recommended_voice="archie",
        default_role="Inbound Client Specialist",
        opening_greeting=(
            "Hello, thanks for reaching Pontis LLP in Hyderabad. This is {agent_name}, an AI assistant. "
            "Are you looking into AI dubbing, microdrama production, or e-learning localization today?"
        ),
        system_prompt=(
            "You are {agent_name}, answering inbound client inquiries for Pontis LLP (https://pontis.in).\n"
            "Greet warmly, identify their project genre (OTT, microdramas, SCORM e-learning, or brand ads), language count, and rough timeline, and offer a callback or WhatsApp sample.\n\n"
            + _SHARED_VOICE_RULES
        ),
        quick_prompts=(
            "We need 10 hours of corporate training translated quickly.",
            "Do you support custom voice cloning for ongoing series?",
            "My email is producer@studio.in, please share your rates.",
            "Thanks, that covers everything. Bye!",
        ),
    ),
    "custom_employee": GenrePreset(
        key="custom_employee",
        label="Saved Voice Agent Config (CRM DB)",
        category="Custom CRM",
        recommended_voice="archie",
        default_role="Custom Saved Agent",
        opening_greeting="",
        system_prompt="",
        quick_prompts=(
            "Tell me more about your AI dubbing services.",
            "How much does localization cost per minute?",
            "We already handle editing and dubbing in-house.",
            "Please end the call now, thank you.",
        ),
    ),
}


def resolve_genre(genre_key: str | None) -> GenrePreset | None:
    """Resolve a genre/scenario key to its preset definition, or None for DB custom."""
    raw = (genre_key or "").strip().lower()
    if not raw or raw == "custom_employee":
        return None
    return GENRE_PRESETS.get(raw)


def _custom_row_to_preset(row: dict) -> VoicePreset:
    accent = (row.get("accent") or "en-GB").strip()
    gender = (row.get("gender") or "female").strip().lower()
    is_uk = "gb" in accent.lower() or "uk" in accent.lower() or "brit" in accent.lower()
    dg_fallback = (
        ("aura-2-andromeda-en" if gender == "female" else "aura-2-draco-en")
        if is_uk
        else ("aura-2-thalia-en" if gender == "female" else "aura-2-apollo-en")
    )
    name = (row.get("name") or row.get("id") or "Custom").strip()
    return VoicePreset(
        key=str(row["id"]).strip().lower(),
        display_name=name,
        label=f"{name}: Cloned ({accent})",
        gender=gender,
        description=str(row.get("description") or f"Custom cloned {accent} voice profile."),
        cartesia_id=str(row["cartesia_id"]).strip(),
        deepgram_model=dg_fallback,
        smallest_id="harsh" if gender == "male" else "srishti",
        accent=accent,
        best_for="Custom Cloned",
    )


def resolve_voice(speaker_or_voice_id: str | None) -> tuple[VoicePreset, str]:
    """Resolve a preset key, custom cloned voice, or raw Cartesia UUID into a VoicePreset + Cartesia UUID."""
    raw = (speaker_or_voice_id or DEFAULT_VOICE_KEY).strip()
    low = raw.lower()
    if low in VOICE_CATALOG:
        preset = VOICE_CATALOG[low]
        return preset, preset.cartesia_id
    # Map legacy workspace presets cleanly to distinct English voices
    legacy_map = {"amit": "kiefer", "gokul": "daniel", "simran": "aria", "kavitha": "katie"}
    if low in legacy_map:
        preset = VOICE_CATALOG[legacy_map[low]]
        return preset, preset.cartesia_id
    # Check custom cloned voices in SQLite
    try:
        from simulator.db import get_custom_voice

        custom_row = get_custom_voice(raw)
        if custom_row and custom_row.get("cartesia_id"):
            custom_preset = _custom_row_to_preset(custom_row)
            return custom_preset, custom_preset.cartesia_id
    except Exception:
        pass
    # Treat UUID-like input directly as a custom Cartesia voice ID
    if "-" in raw and len(raw) >= 20:
        fallback = VOICE_CATALOG[DEFAULT_VOICE_KEY]
        return fallback, raw
    preset = VOICE_CATALOG[DEFAULT_VOICE_KEY]
    return preset, preset.cartesia_id


def get_runtime_keys() -> dict[str, str]:
    """Read fresh API keys from environment so updated .env values take effect."""
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    return {
        "cartesia": os.getenv("CARTESIA_API_KEY", "").strip(),
        "cartesia_fallback": (
            os.getenv("CARTESIA_FALLBACK_API_KEY", "").strip()
            or os.getenv("CARTESIA_API_KEY_BACKUP", "").strip()
        ),
        "deepgram": os.getenv("DEEPGRAM_API_KEY", "").strip(),
        "groq": os.getenv("GROQ_API_KEY", "").strip(),
        "gemini": (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip(),
        "openai": os.getenv("OPENAI_API_KEY", "").strip(),
        "smallest": os.getenv("SMALLEST_API_KEY", "").strip(),
    }


def get_cartesia_candidates(keys: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Return ordered unique Cartesia (tier, api_key) candidates: primary then fallback."""
    runtime = keys or get_runtime_keys()
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tier, env_key in (("primary", runtime.get("cartesia", "")), ("fallback", runtime.get("cartesia_fallback", ""))):
        k = (env_key or "").strip()
        if k and k not in seen:
            seen.add(k)
            candidates.append((tier, k))
    return candidates


_CARTESIA_KEY_HEALTH: dict[str, dict[str, object]] = {}


def mark_cartesia_status(key: str, ok: bool, reason: str = "") -> None:
    """Cache recent Cartesia API health/quota status per API key."""
    clean = (key or "").strip()
    if not clean:
        return
    _CARTESIA_KEY_HEALTH[clean] = {
        "ok": bool(ok),
        "reason": reason,
        "checked_at": time.time(),
    }


async def _probe_single_cartesia_key(car_key: str, force: bool = False) -> tuple[bool, str]:
    """Probe one Cartesia API key with TTL caching (90s healthy / 120s blocked)."""
    now = time.time()
    cached = _CARTESIA_KEY_HEALTH.get(car_key)
    if cached and not force:
        ttl = 90.0 if cached.get("ok") else 120.0
        if (now - float(cached.get("checked_at") or 0.0)) < ttl:
            return bool(cached.get("ok")), str(cached.get("reason") or "")

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                "https://api.cartesia.ai/tts/bytes",
                headers={
                    "X-API-Key": car_key,
                    "Cartesia-Version": "2025-04-16",
                    "Content-Type": "application/json",
                },
                json={
                    "model_id": os.getenv("CARTESIA_MODEL", "sonic-3.6"),
                    "transcript": "Hi.",
                    "voice": {"mode": "id", "id": VOICE_CATALOG[DEFAULT_VOICE_KEY].cartesia_id},
                    "output_format": {
                        "container": "wav",
                        "encoding": "pcm_s16le",
                        "sample_rate": 16000,
                    },
                    "language": "en",
                },
            )
        if resp.status_code < 400:
            mark_cartesia_status(car_key, True, "ok")
            return True, "ok"
        reason = "quota_exceeded_402" if resp.status_code == 402 else f"http_{resp.status_code}"
        mark_cartesia_status(car_key, False, reason)
        return False, reason
    except Exception as exc:
        reason = f"probe_error:{type(exc).__name__}"
        mark_cartesia_status(car_key, False, reason)
        return False, reason


async def resolve_active_cartesia_key(
    keys: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[str, str, str]:
    """Return (active_api_key, tier, reason) across primary and fallback Cartesia keys."""
    runtime = keys or get_runtime_keys()
    candidates = get_cartesia_candidates(runtime)
    if not candidates:
        return "", "none", "not_configured"

    reasons: list[str] = []
    for tier, key in candidates:
        ok, reason = await _probe_single_cartesia_key(key, force=force)
        if ok:
            if tier == "primary":
                return key, "primary", "ok"
            prev = reasons[0] if reasons else "unavailable"
            return key, "fallback", f"primary_{prev}_using_fallback_key"
        reasons.append(reason or "unavailable")
    return "", "none", reasons[-1]


async def probe_cartesia_credits(keys: dict[str, str] | None = None, force: bool = False) -> tuple[bool, str]:
    """Check whether any configured Cartesia key (primary or fallback) has active credits."""
    api_key, _tier, reason = await resolve_active_cartesia_key(keys, force=force)
    return bool(api_key), reason


def engine_capabilities() -> dict:
    """Report active stack providers, voices, and genre presets without exposing secret keys."""
    keys = get_runtime_keys()
    candidates = get_cartesia_candidates(keys)
    active_tier = "none"
    cached_reasons: list[str] = []
    for tier, key in candidates:
        cached = _CARTESIA_KEY_HEALTH.get(key)
        is_ok = True if cached is None else bool(cached.get("ok"))
        reason = str(cached.get("reason") or "") if cached else ""
        if is_ok:
            active_tier = tier
            break
        cached_reasons.append(reason or "unavailable")

    if active_tier == "primary":
        tts_reason = "ok"
    elif active_tier == "fallback":
        prev = cached_reasons[0] if cached_reasons else "unavailable"
        tts_reason = f"primary_{prev}_using_fallback_key"
    else:
        tts_reason = cached_reasons[-1] if cached_reasons else "not_configured"

    cartesia_active = active_tier in ("primary", "fallback")
    if keys.get("smallest"):
        tts_active = "smallest_ai_lightning"
        tts_reason = "ok"
    elif cartesia_active:
        tts_active = "cartesia"
    else:
        tts_active = "deepgram_aura_fallback"
    llm_active = "groq" if keys["groq"] else ("gemini" if keys["gemini"] else "none")
    all_voices: list[VoicePreset] = list(VOICE_CATALOG.values())
    try:
        from simulator.db import list_custom_voices

        for row in list_custom_voices():
            if row.get("id") and row.get("cartesia_id") and str(row["id"]).lower() not in VOICE_CATALOG:
                all_voices.append(_custom_row_to_preset(row))
    except Exception:
        pass

    return {
        "status": "ok",
        "language": "en-IN",
        "vad": "silero",
        "stt": "deepgram-nova-3" if keys["deepgram"] else "missing_key",
        "llm": llm_active,
        "tts": tts_active,
        "tts_reason": tts_reason,
        "cartesia_configured": bool(candidates),
        "cartesia_key_tier": active_tier,
        "cartesia_quota_exceeded": bool(candidates) and not cartesia_active and "402" in tts_reason,
        "voices": [
            {
                "key": v.key,
                "name": v.display_name,
                "label": v.label,
                "gender": v.gender,
                "description": v.description,
                "accent": v.accent,
                "best_for": v.best_for,
                "smallest_id": v.smallest_id,
                "cartesia_id": v.cartesia_id,
                "deepgram_model": v.deepgram_model,
            }
            for v in all_voices
        ],
        "genres": [
            {
                "key": g.key,
                "label": g.label,
                "category": g.category,
                "recommended_voice": g.recommended_voice,
                "default_role": g.default_role,
                "opening_greeting": g.opening_greeting,
                "quick_prompts": list(g.quick_prompts),
            }
            for g in GENRE_PRESETS.values()
        ],
    }
