"""Core Outpero-style real-time English streaming pipeline built on Pipecat."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket
from groq import AsyncGroq
from loguru import logger
from starlette.websockets import WebSocketState

from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.serializers.plivo import PlivoFrameSerializer
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.smallest.tts import SmallestTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.tts_service import TextAggregationMode
from pipecat.transcriptions.language import Language
from pipecat.turns.empty_user_turn import EmptyUserTurnConfig
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.utils.types import assert_given
from pipecat.workers.runner import WorkerRunner

from engine.config import (
    DEFAULT_OPENING_GREETING,
    PONTIS_ENGLISH_PROMPT,
    enable_ipv4_only,
    get_runtime_keys,
    resolve_active_cartesia_key,
    resolve_genre,
    resolve_voice,
)
from engine.observer import (
    ContextSanitizerProcessor,
    ControlMessageProcessor,
    EndCallGuardProcessor,
    PontisUIAndMetricsObserver,
)
from engine.serializer import PontisBrowserSerializer, VobizFrameSerializer
from simulator.db import get_employee, get_lead, record_completed_call


@dataclass
class SessionConfig:
    """Per-call configuration resolved from WS params, employee profile, and lead record."""

    mode: str = "browser"  # "browser" or telephony provider name
    speaker: str = "archie"
    llm_provider: str = "auto"  # "auto", "groq", or "gemini"
    employee_id: str = ""
    lead_id: str = ""
    genre: str = ""
    first_sentence: str = ""
    system_prompt: str = ""
    customer_phone: str = "+91 98490 12345"
    customer_name: str = "Simulator Prospect"
    stream_sid: str = ""
    call_sid: str = ""
    codec: str = "ulaw"
    demo: bool = False


def _load_db_context(cfg: SessionConfig) -> tuple[str, str, str, str]:
    """Hydrate agent name, prompt, greeting, and customer identity from genre preset & SQLite."""
    preset, _ = resolve_voice(cfg.speaker)
    speaker = cfg.speaker.strip() or preset.key
    genre_preset = resolve_genre(cfg.genre)

    agent_name = preset.display_name or "Aria"
    prompt = cfg.system_prompt.strip()
    greeting = cfg.first_sentence.strip()
    cust_name = cfg.customer_name
    cust_phone = cfg.customer_phone

    if genre_preset:
        if not prompt:
            prompt = genre_preset.system_prompt.format(agent_name=agent_name)
        if not greeting:
            greeting = genre_preset.opening_greeting.format(agent_name=agent_name)
    else:
        emp_id = cfg.employee_id or "emp_01"
        emp = get_employee(emp_id, fallback_first=not bool(cfg.employee_id))
        if emp:
            db_voice = (emp.get("voice_id") or "").strip().lower()
            if not cfg.speaker:
                speaker = db_voice or speaker
                preset, _ = resolve_voice(speaker)
            db_name = (emp.get("name") or "").strip()
            if db_name and (not cfg.speaker or cfg.speaker.lower() == db_voice):
                agent_name = db_name
            else:
                agent_name = preset.display_name or db_name or agent_name
            if not prompt:
                kb = (emp.get("knowledge_base") or "").strip()
                rules = (emp.get("custom_instructions") or "").strip()
                base = PONTIS_ENGLISH_PROMPT.format(agent_name=agent_name)
                extras = "\n".join(x for x in (f"Business Knowledge:\n{kb}" if kb else "", f"Rules:\n{rules}" if rules else "") if x)
                prompt = f"{base}\n\n{extras}" if extras else base
            if not greeting and emp.get("first_sentence"):
                cand = emp["first_sentence"].strip()
                if cand.isascii():
                    if db_name and agent_name != db_name and f"this is {db_name}" in cand:
                        cand = cand.replace(f"this is {db_name}", f"this is {agent_name}")
                    greeting = cand

    if cfg.lead_id:
        lead = get_lead(cfg.lead_id)
        if lead:
            cust_name = lead.get("name") or cust_name
            cust_phone = lead.get("phone") or cust_phone
            lead_ctx = (
                f"\n\nProspect Profile: Calling {cust_name} from {lead.get('company', 'Unknown')} "
                f"(Industry: {lead.get('industry', 'General')}). Notes: {lead.get('custom_notes', '')}"
            )
            prompt = (prompt or PONTIS_ENGLISH_PROMPT.format(agent_name=agent_name)) + lead_ctx

    if not prompt:
        prompt = PONTIS_ENGLISH_PROMPT.format(agent_name=agent_name)
    if not greeting:
        greeting = DEFAULT_OPENING_GREETING.format(agent_name=agent_name)

    cfg.customer_name = cust_name
    cfg.customer_phone = cust_phone
    cfg.speaker = speaker
    return agent_name, prompt, greeting, speaker


def compute_call_rubric(transcript_log: list[dict[str, str]]) -> tuple[int, list[str], str]:
    """Deterministically score a call (0-100) and extract buying signals per the Pontis B2B rubric."""
    user_turns = [str(m.get("content", "")).strip() for m in transcript_log if m.get("role") == "user" and str(m.get("content", "")).strip()]
    if not user_turns:
        return 0, [], "DROPPED"

    user_blob = " ".join(user_turns).lower()
    if re.search(r"\b(don'?t call|do not call|stop calling|wrong number|remove me|take me off)\b", user_blob):
        return 0, ["explicit_opt_out"], "UNQUALIFIED"

    score = 0
    signals: list[str] = []

    if re.search(r"\b(whatsapp|send (it|sample|samples|reel|reels|clip|details|quote)|share (on|over|via)?\s*whatsapp|yes.*send)\b", user_blob):
        score += 35
        signals.append("whatsapp_sample_consent (+35)")
    if re.search(r"\b(tomorrow|monday|tuesday|wednesday|thursday|friday|morning|evening|afternoon|15[\s-]*min|demo|schedule|call back at|11\s*am|3\s*pm|this week)\b", user_blob):
        score += 25
        signals.append("demo_or_callback_slot (+25)")
    if re.search(r"\b(producer|director|founder|ceo|head of|vp|manager|lead|i decide|my team|our studio)\b", user_blob):
        score += 15
        signals.append("decision_maker_identified (+15)")
    if re.search(r"\b(episode|episodes|microdrama|series|dubbing|lip[\s-]*sync|scorm|course|courses|localization|translate|ott|campaign|video)\b", user_blob):
        score += 15
        signals.append("confirmed_active_need (+15)")
    if re.search(r"\b(price|pricing|cost|rate|per minute|quote|budget|how much|turnaround|how fast|hours|days)\b", user_blob):
        score += 10
        signals.append("pricing_or_turnaround_inquiry (+10)")

    score = min(100, score)
    if score >= 70:
        tier = "HOT"
    elif score >= 40:
        tier = "WARM"
    elif score >= 15:
        tier = "NURTURE"
    else:
        tier = "UNQUALIFIED"
    return score, signals, tier


async def generate_english_call_report(transcript_log: list[dict[str, str]], keys: dict[str, str]) -> dict[str, Any]:
    """Summarize the English sales call into structured qualification JSON with 0-100 rubric score."""
    rubric_score, rubric_signals, rubric_tier = compute_call_rubric(transcript_log)
    user_turns = [m for m in transcript_log if m.get("role") == "user"]
    if not user_turns:
        return {
            "qualification_status": "DROPPED",
            "score": 0,
            "signals": [],
            "prospect_industry": "None",
            "decision_maker_role": "None",
            "identified_need": "None",
            "agreed_next_step": "Retry call during business hours",
            "executive_summary": "Call ended during the opening greeting before the prospect spoke.",
        }

    transcript_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in transcript_log)
    prompt = (
        "Analyze this Pontis LLP English B2B cold-call transcript and return ONLY a valid JSON object "
        "with keys: prospect_industry, decision_maker_role, identified_need, "
        "qualification_status (one of HOT, WARM, NURTURE, UNQUALIFIED), score (integer 0-100), "
        "signals (array of short strings), agreed_next_step, "
        f"executive_summary (max 2 short sentences).\n\nTranscript:\n{transcript_text}"
    )

    if keys.get("groq"):
        client = AsyncGroq(api_key=keys["groq"], max_retries=0)
        try:
            report_models = [
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
                os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b"),
            ]
            for rmodel in dict.fromkeys(report_models):
                try:
                    effort = "none" if "qwen" in rmodel else "low"
                    resp = await client.chat.completions.create(
                        model=rmodel,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=240,
                        temperature=0.1,
                        extra_body={"reasoning_effort": effort},
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    start = raw.find("{")
                    end = raw.rfind("}")
                    if start != -1 and end > start:
                        parsed = json.loads(raw[start : end + 1])
                        parsed.setdefault("score", rubric_score)
                        parsed.setdefault("signals", rubric_signals)
                        if not parsed.get("qualification_status"):
                            parsed["qualification_status"] = rubric_tier
                        return parsed
                except Exception as merr:
                    logger.warning(f"Groq report model {rmodel} fallback: {merr}")
                    continue
        except Exception as err:
            logger.warning(f"Groq report generation fallback: {err}")
        finally:
            await client.close()

    return {
        "prospect_industry": "Media / Entertainment",
        "decision_maker_role": "Prospect",
        "identified_need": "AI Dubbing / Video Localization",
        "qualification_status": rubric_tier if rubric_score > 0 else "WARM",
        "score": rubric_score,
        "signals": rubric_signals,
        "agreed_next_step": "Share Pontis LLP sample reels on WhatsApp",
        "executive_summary": "Prospect engaged in an English discovery call with Pontis LLP. Follow up with sample links on WhatsApp.",
    }


def _persist_call_record(
    cfg: SessionConfig,
    dur_sec: int,
    report: dict[str, Any],
    transcript_log: list[dict[str, str]],
) -> str:
    call_id = f"call_{int(time.time())}_{os.urandom(2).hex()}"
    # Starter rate Rs 5.00/min billed per 6-second pulse (Rs 0.50 per 6s block)
    billed_cost = round(max(1, (dur_sec + 5) // 6) * 0.50, 2)
    try:
        record_completed_call(
            call_id=call_id,
            customer_phone=cfg.customer_phone,
            customer_name=cfg.customer_name,
            employee_id=cfg.employee_id or "emp_01",
            duration_seconds=dur_sec,
            billed_credits=billed_cost,
            qualification_status=report.get("qualification_status", "WARM"),
            identified_need=report.get("identified_need", ""),
            decision_maker_role=report.get("decision_maker_role", ""),
            agreed_next_step=report.get("agreed_next_step", ""),
            summary=report.get("executive_summary", ""),
            transcript=transcript_log,
            lead_id=cfg.lead_id,
        )
    except Exception as err:
        logger.error(f"DB call_logs save failed: {err}")
    return call_id


class ResilientGroqLLMService(GroqLLMService):
    """Groq LLM service with proactive rolling-bucket load balancing, 3.5s stall timeout, and instant failover."""

    _MODEL_POOL = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")
    _MODEL_USAGE: dict[str, list[tuple[float, int]]] = {}
    _BUCKET_SOFT_LIMIT = 4800

    def create_client(self, *args, **kwargs):
        client = super().create_client(*args, **kwargs)
        return client.with_options(max_retries=0)

    @classmethod
    def _select_candidate_order(cls, primary_model: str, est_tokens: int) -> list[str]:
        now = time.monotonic()
        pool = [primary_model] + [m for m in cls._MODEL_POOL if m != primary_model]
        usage_by_model: dict[str, int] = {}
        for m in pool:
            recent = [(ts, tok) for ts, tok in cls._MODEL_USAGE.get(m, []) if now - ts < 60.0]
            cls._MODEL_USAGE[m] = recent
            usage_by_model[m] = sum(tok for _, tok in recent)

        under_limit = [m for m in pool if usage_by_model[m] + est_tokens <= cls._BUCKET_SOFT_LIMIT]
        over_limit = sorted(
            [m for m in pool if m not in under_limit],
            key=lambda m: usage_by_model[m],
        )
        return under_limit + over_limit

    @classmethod
    def _record_usage(cls, model: str, est_tokens: int) -> None:
        now = time.monotonic()
        recent = [(ts, tok) for ts, tok in cls._MODEL_USAGE.get(model, []) if now - ts < 60.0]
        recent.append((now, est_tokens))
        cls._MODEL_USAGE[model] = recent

    @staticmethod
    def _prepare_model_params(base_params: dict[str, Any], target_model: str) -> dict[str, Any]:
        cand = dict(base_params)
        cand["model"] = target_model
        if target_model.startswith("openai/gpt-oss"):
            cand["reasoning_effort"] = "low"
            fb_extra = dict(cand.get("extra_body") or {})
            fb_extra.pop("reasoning_effort", None)
            if fb_extra:
                cand["extra_body"] = fb_extra
            else:
                cand.pop("extra_body", None)
            cand["max_tokens"] = max(int(cand.get("max_tokens") or 220), 260)
        return cand

    async def get_chat_completions(self, context: LLMContext):
        adapter = self.get_llm_adapter()
        self._log_llm_response(context)
        params_from_context = await adapter.get_llm_invocation_params(
            context,
            system_instruction=assert_given(self._settings.system_instruction),
            convert_developer_to_user=not self.supports_developer_role,
        )
        params = self.build_chat_completion_params(params_from_context)
        primary_model = str(params.get("model") or "qwen/qwen3.8-27b")
        msg_chars = sum(len(str(m.get("content", ""))) for m in (params.get("messages") or []))
        est_tokens = max(850, msg_chars // 3 + 300)

        candidates = self._select_candidate_order(primary_model, est_tokens)
        last_err: Exception | None = None
        for idx, cand_model in enumerate(candidates):
            cand_params = self._prepare_model_params(params, cand_model)
            if idx > 0 or cand_model != primary_model:
                logger.info(
                    f"[Outpero Engine] Groq bucket routing -> {cand_model} (est_tokens={est_tokens})"
                )
            try:
                self._record_usage(cand_model, est_tokens)
                return await asyncio.wait_for(
                    self._client.chat.completions.create(**cand_params),
                    timeout=3.5,
                )
            except Exception as err:
                last_err = err
                logger.warning(
                    f"[Outpero Engine] Groq {cand_model} failed/timed out ({type(err).__name__}: {err}); rotating bucket"
                )
                continue
        if last_err is not None:
            raise last_err
        return await self._client.chat.completions.create(**params)


def _build_llm(cfg: SessionConfig, keys: dict[str, str], system_prompt: str):
    choice = cfg.llm_provider.lower()
    if (choice in ("auto", "groq")) and keys.get("groq"):
        model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        return ResilientGroqLLMService(
            api_key=keys["groq"],
            settings=GroqLLMService.Settings(
                model=model,
                reasoning_effort="none",
                system_instruction=system_prompt,
                max_tokens=220,
                temperature=0.40,
            ),
        ), f"groq:{model}"

    if keys.get("gemini"):
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
        return GoogleLLMService(
            api_key=keys["gemini"],
            http_options={"api_version": "v1beta"},
            settings=GoogleLLMService.Settings(
                model=model,
                system_instruction=system_prompt,
                max_tokens=220,
                temperature=0.40,
                thinking=GoogleLLMService.ThinkingConfig(thinking_budget=0),
            ),
        ), f"gemini:{model}"

    raise RuntimeError("No valid LLM API key configured (GROQ_API_KEY or GEMINI_API_KEY required).")


def _build_tts(speaker: str, sample_rate: int, keys: dict[str, str], cartesia_api_key: str = ""):
    preset, cartesia_uuid = resolve_voice(speaker)

    # Priority 1: Smallest AI Lightning v3.1 (Native Indian cadence, ultra-fast 180ms TTFB)
    smallest_key = (keys.get("smallest") or os.getenv("SMALLEST_API_KEY") or "").strip()
    if smallest_key:
        smallest_voice = preset.smallest_id or "harsh"
        return (
            SmallestTTSService(
                api_key=smallest_key,
                sample_rate=sample_rate,
                settings=SmallestTTSService.Settings(
                    model="lightning_v3.1",
                    voice=smallest_voice,
                    language=Language.EN,
                ),
            ),
            f"smallest:{smallest_voice}",
            False,
        )

    # Priority 2: Cartesia Sonic-3.6 (Secondary high-expressiveness backup)
    active_car_key = (cartesia_api_key or "").strip()
    if active_car_key:
        model_override = os.getenv("CARTESIA_MODEL", "").strip()
        settings = (
            CartesiaTTSService.Settings(model=model_override, voice=cartesia_uuid, language=Language.EN)
            if model_override
            else CartesiaTTSService.Settings(voice=cartesia_uuid, language=Language.EN)
        )
        return (
            CartesiaTTSService(
                api_key=active_car_key,
                sample_rate=sample_rate,
                encoding="pcm_s16le",
                container="raw",
                text_aggregation_mode=TextAggregationMode.SENTENCE,
                settings=settings,
            ),
            f"cartesia:{preset.key}",
            False,
        )

    # Priority 3: Deepgram Aura-2 (Zero-fail baseline)
    return (
        DeepgramTTSService(
            api_key=keys["deepgram"],
            sample_rate=sample_rate,
            encoding="linear16",
            settings=DeepgramTTSService.Settings(voice=preset.deepgram_model),
        ),
        f"deepgram-aura:{preset.deepgram_model}",
        True,
    )


def _make_serializer(cfg: SessionConfig, keys: dict[str, str]) -> tuple[FrameSerializer, int, int]:
    mode = cfg.mode.lower()
    if mode == "browser":
        return PontisBrowserSerializer(), 16000, 16000
    if mode == "exotel":
        return ExotelFrameSerializer(stream_sid=cfg.stream_sid or "exotel_stream", call_sid=cfg.call_sid), 8000, 8000
    if mode == "twilio":
        return (
            TwilioFrameSerializer(
                stream_sid=cfg.stream_sid or "twilio_stream",
                call_sid=cfg.call_sid,
                account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
                auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            ),
            8000,
            8000,
        )
    if mode == "plivo":
        return (
            PlivoFrameSerializer(
                stream_id=cfg.stream_sid or "plivo_stream",
                call_id=cfg.call_sid,
                auth_id=os.getenv("PLIVO_AUTH_ID", ""),
                auth_token=os.getenv("PLIVO_AUTH_TOKEN", ""),
            ),
            8000,
            8000,
        )
    return VobizFrameSerializer(
        stream_id=cfg.stream_sid or "vobiz_stream",
        params=VobizFrameSerializer.InputParams(codec=cfg.codec),
    ), 8000, 8000


async def run_voice_session(websocket: WebSocket, cfg: SessionConfig) -> None:
    """Run one complete real-time Pipecat streaming voice call on an accepted WebSocket."""
    enable_ipv4_only()
    keys = get_runtime_keys()
    if not keys.get("deepgram"):
        await websocket.send_text(json.dumps({"type": "error", "message": "DEEPGRAM_API_KEY missing in .env"}))
        await websocket.close(code=1011)
        return

    agent_name, system_prompt, greeting, resolved_speaker = _load_db_context(cfg)
    voice_preset, cartesia_uuid = resolve_voice(resolved_speaker)
    genre_preset = resolve_genre(cfg.genre)
    serializer, in_rate, out_rate = _make_serializer(cfg, keys)
    transcript_log: list[dict[str, str]] = []
    call_start = time.time()
    finalized = False

    async def send_ui_json(payload: dict[str, Any]) -> None:
        if cfg.mode != "browser":
            return
        if websocket.client_state == WebSocketState.CONNECTED and websocket.application_state != WebSocketState.DISCONNECTED:
            await websocket.send_text(json.dumps(payload))

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=in_rate,
            audio_out_sample_rate=out_rate,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    stt = DeepgramSTTService(
        api_key=keys["deepgram"],
        sample_rate=in_rate,
        ttfs_p99_latency=0.80,
        settings=DeepgramSTTService.Settings(
            model=os.getenv("DEEPGRAM_STT_MODEL", "nova-3-general"),
            language=Language.EN_IN,
            interim_results=True,
            punctuate=True,
            smart_format=True,
            endpointing=500,
            keyterm=[
                "Pontis",
                "Pontis LLP",
                "microdrama",
                "microdramas",
                "dubbing",
                "lip-sync",
                "SCORM",
                "localization",
                "WhatsApp",
            ],
        ),
    )

    llm, llm_label = _build_llm(cfg, keys, system_prompt)
    active_car_key, cartesia_tier, tts_reason = await resolve_active_cartesia_key(keys)
    tts, tts_label, is_fallback_tts = _build_tts(
        resolved_speaker,
        out_rate,
        keys,
        cartesia_api_key=active_car_key,
    )

    context = LLMContext()
    vad = SileroVADAnalyzer(
        sample_rate=in_rate,
        params=VADParams(confidence=0.82, start_secs=0.30, stop_secs=0.20, min_volume=0.65),
    )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad,
            audio_idle_timeout=1.5,
            user_turn_strategies=UserTurnStrategies(
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3(
                            params=SmartTurnParams(stop_secs=2.2, pre_speech_ms=500, max_duration_secs=8)
                        )
                    ),
                    SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.55),
                ],
            ),
            empty_user_turn=EmptyUserTurnConfig(
                interrupted_prompt=None,
                idle_prompt=None,
            ),
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
        ),
    )

    runner = WorkerRunner(handle_sigint=False)
    finalize_lock = asyncio.Lock()
    cached_report: dict[str, Any] | None = None
    report_sent = False

    async def finalize_call(send_report: bool) -> None:
        nonlocal finalized, cached_report, report_sent
        async with finalize_lock:
            if not finalized:
                dur_sec = max(5, int(time.time() - call_start))
                report = await generate_english_call_report(transcript_log, keys)
                call_id = _persist_call_record(cfg, dur_sec, report, transcript_log)
                report["call_id"] = call_id
                report["duration_seconds"] = dur_sec
                cached_report = report
                finalized = True
            if send_report and not report_sent and cached_report is not None:
                report_sent = True
                await send_ui_json({"type": "call_report", "report": cached_report})

    async def on_end_call() -> None:
        await finalize_call(send_report=True)
        await runner.cancel()

    async def on_manual_user_text(text: str) -> None:
        transcript_log.append({"role": "user", "content": text})
        await send_ui_json({"type": "user_transcript", "text": text, "stt_ms": 0})

    control = ControlMessageProcessor(on_end_call=on_end_call, on_user_text=on_manual_user_text)
    context_sanitizer = ContextSanitizerProcessor()
    end_call_guard = EndCallGuardProcessor(on_end_call=on_end_call)

    ui_observer = PontisUIAndMetricsObserver(
        emit_event=send_ui_json,
        transcript_log=transcript_log,
        active_cartesia_key=active_car_key,
    )
    latency_observer = UserBotLatencyObserver()

    @latency_observer.event_handler("on_latency_measured")
    async def on_latency_measured(_obs, latency_seconds: float):
        await send_ui_json({"type": "turn_latency", "total_ms": int(round(latency_seconds * 1000))})

    pipeline = Pipeline(
        [
            transport.input(),
            control,
            stt,
            user_aggregator,
            context_sanitizer,
            llm,
            end_call_guard,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            audio_in_sample_rate=in_rate,
            audio_out_sample_rate=out_rate,
        ),
        observers=[ui_observer, latency_observer],
        idle_timeout_secs=300,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    await runner.add_workers(worker)

    demo_watchdog: asyncio.Task | None = None

    async def _demo_timeout_watchdog() -> None:
        await asyncio.sleep(180)
        await send_ui_json({"type": "error", "message": "Public demo calls are capped at 3 minutes. Ending call now."})
        await on_end_call()

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client):
        nonlocal demo_watchdog
        logger.info(
            f"[Outpero Engine] Session started mode={cfg.mode} llm={llm_label} tts={tts_label} "
            f"voice={voice_preset.key}({cartesia_uuid}) genre={cfg.genre or 'custom'} agent={agent_name}"
        )
        await send_ui_json({
            "type": "engine_ready",
            "agent_name": agent_name,
            "speaker": voice_preset.key,
            "voice_label": voice_preset.label,
            "cartesia_id": cartesia_uuid,
            "genre": cfg.genre or "custom_employee",
            "genre_label": genre_preset.label if genre_preset else "Saved CRM Employee",
            "llm": llm_label,
            "tts": tts_label,
            "tts_reason": tts_reason,
            "cartesia_tier": cartesia_tier,
            "cartesia_fallback": is_fallback_tts,
            "sample_rate": out_rate,
            "demo": cfg.demo,
            "max_duration_secs": 180 if cfg.demo else 0,
        })
        if cfg.demo and demo_watchdog is None:
            demo_watchdog = asyncio.create_task(_demo_timeout_watchdog())
        transcript_log.append({"role": "assistant", "content": greeting})
        await send_ui_json({"type": "agent_text", "turn_id": 1, "text": greeting, "llm_ms": 0})
        await worker.queue_frames([TTSSpeakFrame(text=greeting, append_to_context=True)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info(f"[Outpero Engine] Client disconnected mode={cfg.mode}")
        if demo_watchdog and not demo_watchdog.done():
            demo_watchdog.cancel()
        await finalize_call(send_report=False)
        await runner.cancel()

    try:
        await runner.run()
    finally:
        if demo_watchdog and not demo_watchdog.done():
            demo_watchdog.cancel()
        await finalize_call(send_report=False)
