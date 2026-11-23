"""Out-of-band pipeline observer and control-frame processor for live UI transcripts and latency metrics."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    Frame,
    InputTransportMessageFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    MetricsFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFAMetricsData, TTFATMetricsData, TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from engine.config import mark_cartesia_status

_USER_HANGUP_RE = re.compile(
    r"\b(hang\s*up|end\s+(the\s+)?call|cut\s+(the\s+)?call|disconnect|stop\s+calling|remove\s+(me|my\s+number)|"
    r"take\s+me\s+off|don'?t\s+call(\s+me)?(\s+again)?|do\s+not\s+call|not\s+interested|goodbye|bye(\s+for\s+now)?|"
    r"talk\s+later|have\s+to\s+go)\b",
    re.IGNORECASE,
)
_ASSISTANT_FAREWELL_RE = re.compile(
    r"(\b(goodbye|bye\s+for\s+now|bye\s+now|have\s+a\s+(great|good|wonderful|lovely)\s+(day|evening|one)|take\s+care|talk\s+to\s+you\s+later|thank\s+you\s+for\s+your\s+time[\s,.!]*bye)\b[\s.!]*$|\bbye[\s.!]*$)",
    re.IGNORECASE,
)
_ASSISTANT_SOFT_FAREWELL_RE = re.compile(
    r"\b(goodbye|bye|have\s+a\s+(great|good|wonderful|lovely)\s+(day|evening|one)|take\s+care|appreciate\s+your\s+time|thank\s+you\s+for\s+your\s+time)\b",
    re.IGNORECASE,
)


class ControlMessageProcessor(FrameProcessor):
    """Handles typed browser messages (manual text replies, end_call) cleanly before STT."""

    def __init__(
        self,
        *,
        on_end_call: Callable[[], Awaitable[None]],
        on_user_text: Callable[[str], Awaitable[None]],
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._on_end_call = on_end_call
        self._on_user_text = on_user_text

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame) and isinstance(frame.message, dict):
            action = frame.message.get("action")
            if action == "user_text":
                text = str(frame.message.get("text", "")).strip()
                if text:
                    await self._on_user_text(text)
                    await self.push_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
                    await self.push_frame(
                        LLMMessagesAppendFrame(
                            messages=[{"role": "user", "content": text}],
                            run_llm=True,
                        ),
                        FrameDirection.DOWNSTREAM,
                    )
                return
            if action == "end_call":
                await self._on_end_call()
                return
        await self.push_frame(frame, direction)


class EndCallGuardProcessor(FrameProcessor):
    """Strips [END_CALL] markers before TTS/UI and disconnects cleanly after farewell playback."""

    _MARKER = "[END_CALL]"

    def __init__(self, *, on_end_call: Callable[[], Awaitable[None]], **kwargs):
        super().__init__(**kwargs)
        self._on_end_call = on_end_call
        self._buf = ""
        self._turn_text = ""
        self._user_requested_end = False
        self._hangup_pending = False
        self._ending_call = False
        self._hangup_task: asyncio.Task | None = None

    def _extract_safe_text(self, chunk: str) -> str:
        combined = self._buf + chunk
        self._buf = ""
        if self._MARKER in combined:
            self._hangup_pending = True
            combined = combined.replace(self._MARKER, "")
        # Hold back only a trailing prefix that could complete [END_CALL] across streamed tokens
        max_len = min(len(combined), len(self._MARKER) - 1)
        for k in range(max_len, 0, -1):
            if self._MARKER.startswith(combined[-k:]):
                self._buf = combined[-k:]
                return combined[:-k]
        return combined

    def _schedule_hangup(self, delay_secs: float) -> None:
        if self._ending_call or (self._hangup_task and not self._hangup_task.done()):
            return

        async def _finish() -> None:
            await asyncio.sleep(delay_secs)
            self._ending_call = True
            await self._on_end_call()

        self._hangup_task = asyncio.create_task(_finish())

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                self._user_requested_end = bool(_USER_HANGUP_RE.search(text))

        elif isinstance(frame, LLMMessagesAppendFrame):
            user_texts = [
                str(m.get("content", "")).strip()
                for m in (frame.messages or [])
                if isinstance(m, dict) and m.get("role") == "user"
            ]
            joined = " ".join(t for t in user_texts if t)
            if joined:
                self._user_requested_end = bool(_USER_HANGUP_RE.search(joined))

        elif isinstance(frame, LLMFullResponseStartFrame) and direction == FrameDirection.DOWNSTREAM:
            self._turn_text = ""

        if isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            safe = self._extract_safe_text(frame.text or "")
            if safe:
                self._turn_text += safe
                await self.push_frame(LLMTextFrame(text=safe), direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame) and direction == FrameDirection.DOWNSTREAM:
            if self._buf:
                leftover = self._buf.replace(self._MARKER, "")
                self._buf = ""
                if leftover:
                    self._turn_text += leftover
                    await self.push_frame(LLMTextFrame(text=leftover), direction)
            if not self._hangup_pending:
                completed = self._turn_text.strip()
                if completed and (
                    _ASSISTANT_FAREWELL_RE.search(completed)
                    or (self._user_requested_end and _ASSISTANT_SOFT_FAREWELL_RE.search(completed))
                ):
                    self._hangup_pending = True
            self._turn_text = ""
            await self.push_frame(frame, direction)
            if self._hangup_pending:
                # Safety fallback in case BotStoppedSpeakingFrame is delayed
                self._schedule_hangup(8.0)
            return

        if isinstance(frame, BotStoppedSpeakingFrame) and self._hangup_pending:
            if self._ending_call:
                await self.push_frame(frame, direction)
                return
            if self._hangup_task and not self._hangup_task.done():
                self._hangup_task.cancel()
                self._hangup_task = None
            self._hangup_pending = False
            self._schedule_hangup(0.35)

        elif isinstance(frame, InterruptionFrame):
            self._buf = ""
            self._turn_text = ""
            if self._hangup_pending and not self._ending_call:
                if self._hangup_task and not self._hangup_task.done():
                    self._hangup_task.cancel()
                    self._hangup_task = None
                self._hangup_pending = False
                self._schedule_hangup(0.35)

        await self.push_frame(frame, direction)


_TURN_COMPLETION_PREFIX_RE = re.compile(r"^[●◐○]\s*")


class ContextSanitizerProcessor(FrameProcessor):
    """Prevents Groq Qwen3.8 empty completions and 400 errors from developer/consecutive-user turns."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            msgs = frame.context.get_messages()
            cleaned: list[dict[str, Any]] = []
            for m in msgs:
                if not isinstance(m, dict):
                    cleaned.append(m)
                    continue
                role = m.get("role")
                content = m.get("content")
                if isinstance(content, str):
                    content = _TURN_COMPLETION_PREFIX_RE.sub("", content)
                    m = {**m, "content": content}
                if role == "developer":
                    dev_text = content.strip() if isinstance(content, str) else str(content or "").strip()
                    if not dev_text:
                        continue
                    role = "user"
                    content = f"[Call event: {dev_text}]"
                    m = {"role": "user", "content": content}
                if (
                    cleaned
                    and isinstance(cleaned[-1], dict)
                    and cleaned[-1].get("role") == role
                    and isinstance(cleaned[-1].get("content"), str)
                    and isinstance(content, str)
                    and role in ("user", "assistant")
                ):
                    prev = cleaned[-1]["content"].strip()
                    curr = content.strip()
                    cleaned[-1] = {**cleaned[-1], "content": f"{prev} {curr}".strip()}
                else:
                    cleaned.append(m)
            # Only push LLM inference if there is at least one non-system message
            if any(isinstance(m, dict) and m.get("role") in ("user", "assistant") for m in cleaned):
                frame.context.set_messages(cleaned)
        await self.push_frame(frame, direction)


class PontisUIAndMetricsObserver(BaseObserver):
    """Non-blocking observer forwarding transcripts, LLM stream text, and TTFB/TTFA timings to the browser."""

    def __init__(
        self,
        *,
        emit_event: Callable[[dict[str, Any]], Awaitable[None]],
        transcript_log: list[dict[str, str]],
        active_cartesia_key: str = "",
    ):
        super().__init__(observe_every_push=False)
        self._emit = emit_event
        self._transcript_log = transcript_log
        self._active_cartesia_key = (active_cartesia_key or "").strip()
        self._last_interim = ""
        self._llm_chunks: list[str] = []
        self._in_llm = False
        self._stt_ms = 0
        self._llm_ms = 0
        self._tts_ms = 0
        self._turn_id = 1

    async def _emit_safe(self, payload: dict[str, Any]) -> None:
        try:
            await self._emit(payload)
        except Exception:
            pass

    async def on_push_frame(self, data: FramePushed):
        frame = data.frame

        if isinstance(frame, UserStartedSpeakingFrame):
            await self._emit_safe({"type": "user_speaking", "speaking": True})

        elif isinstance(frame, UserStoppedSpeakingFrame):
            await self._emit_safe({"type": "user_speaking", "speaking": False})

        elif isinstance(frame, InterimTranscriptionFrame):
            text = (frame.text or "").strip()
            if text and text != self._last_interim:
                self._last_interim = text
                await self._emit_safe({"type": "user_interim", "text": text})

        elif isinstance(frame, TranscriptionFrame):
            self._last_interim = ""
            text = (frame.text or "").strip()
            if text:
                self._transcript_log.append({"role": "user", "content": text})
                await self._emit_safe({
                    "type": "user_transcript",
                    "text": text,
                    "stt_ms": self._stt_ms,
                })

        elif isinstance(frame, LLMFullResponseStartFrame):
            self._llm_chunks.clear()
            self._in_llm = True
            self._llm_ms = 0
            self._tts_ms = 0
            self._turn_id += 1

        elif isinstance(frame, LLMTextFrame) and self._in_llm:
            # When EndCallGuardProcessor is in the pipeline, read only its sanitized output
            # so [END_CALL] markers never leak and frames are never double-counted.
            if not isinstance(data.source, EndCallGuardProcessor):
                return
            chunk = (frame.text or "").replace("[END_CALL]", "")
            if chunk:
                self._llm_chunks.append(chunk)
                await self._emit_safe({
                    "type": "agent_text_delta",
                    "turn_id": self._turn_id,
                    "text": chunk,
                })

        elif isinstance(frame, LLMFullResponseEndFrame) and self._in_llm:
            self._in_llm = False
            full_text = "".join(self._llm_chunks).strip()
            self._llm_chunks.clear()
            if full_text:
                self._transcript_log.append({"role": "assistant", "content": full_text})
                await self._emit_safe({
                    "type": "agent_text",
                    "turn_id": self._turn_id,
                    "text": full_text,
                    "stt_ms": self._stt_ms,
                    "llm_ms": self._llm_ms,
                    "tts_ms": self._tts_ms,
                })

        elif isinstance(frame, BotStartedSpeakingFrame):
            await self._emit_safe({"type": "bot_speaking", "speaking": True})

        elif isinstance(frame, BotStoppedSpeakingFrame):
            await self._emit_safe({"type": "bot_speaking", "speaking": False})

        elif isinstance(frame, InterruptionFrame):
            if self._in_llm and self._llm_chunks:
                partial = "".join(self._llm_chunks).strip()
                if partial:
                    self._transcript_log.append({"role": "assistant", "content": f"{partial} [interrupted]"})
            self._in_llm = False
            self._llm_chunks.clear()
            await self._emit_safe({"type": "interruption"})

        elif isinstance(frame, MetricsFrame):
            changed = False
            for m in frame.data:
                proc = (m.processor or "").lower()
                if isinstance(m, TTFAMetricsData):
                    self._tts_ms = int(round(m.ttfa * 1000))
                    changed = True
                elif isinstance(m, TTFATMetricsData):
                    self._llm_ms = int(round(m.ttfat * 1000))
                    changed = True
                elif isinstance(m, TTFBMetricsData):
                    ms = int(round(m.value * 1000))
                    if "stt" in proc or "deepgramstt" in proc:
                        self._stt_ms = ms
                    elif "llm" in proc or "groq" in proc or "google" in proc:
                        self._llm_ms = ms
                    elif "tts" in proc or "cartesia" in proc:
                        self._tts_ms = ms
                    changed = True
            if changed:
                await self._emit_safe({
                    "type": "metrics",
                    "stt_ms": self._stt_ms,
                    "llm_ms": self._llm_ms,
                    "tts_ms": self._tts_ms,
                })

        elif isinstance(frame, ErrorFrame):
            err_text = str(getattr(frame, "error", "") or "")
            err_cat = str(getattr(frame, "category", "") or "").lower()
            if self._active_cartesia_key and (
                "402" in err_text
                or "credits" in err_text.lower()
                or "payment" in err_text.lower()
                or "quota" in err_text.lower()
                or "quota" in err_cat
            ):
                mark_cartesia_status(self._active_cartesia_key, False, "runtime_ws_402")
