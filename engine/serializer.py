"""WebSocket frame serializers for full-duplex browser PCM and Indian SIP trunks (Vobiz/Exotel/Twilio/Plivo)."""

from __future__ import annotations

import base64
import json

from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import alaw_to_pcm, pcm_to_alaw, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer


class PontisBrowserSerializer(FrameSerializer):
    """Binary 16kHz Int16 PCM + JSON control serializer for browser full-duplex WebSockets."""

    class InputParams(FrameSerializer.InputParams):
        audio_in_sample_rate: int = 16000
        audio_out_sample_rate: int = 16000

    def __init__(self, params: InputParams | None = None):
        super().__init__(params or PontisBrowserSerializer.InputParams())

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            await self._reset_audio_out()
            return json.dumps({"type": "interruption"})
        if isinstance(frame, AudioRawFrame):
            data = await self._resample_audio_out(frame)
            return data if data else None
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
            if not raw:
                return None
            audio = await self._resample_audio_in(raw)
            if not audio:
                return None
            return InputAudioRawFrame(audio=audio, num_channels=1, sample_rate=self._sample_rate)

        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            return None
        return InputTransportMessageFrame(message=message)


class VobizFrameSerializer(FrameSerializer):
    """Serializer for Vobiz / generic 8kHz Indian SIP-WebSocket bridges (PCM16, mu-law, or a-law)."""

    class InputParams(FrameSerializer.InputParams):
        audio_in_sample_rate: int = 8000
        audio_out_sample_rate: int = 8000
        codec: str = "ulaw"  # "ulaw", "alaw", or "pcm16"

    def __init__(self, stream_id: str = "", params: InputParams | None = None):
        params = params or VobizFrameSerializer.InputParams()
        super().__init__(params)
        self._vobiz_params = params
        self._stream_id = stream_id

    async def _encode_wire(self, pcm: bytes, in_rate: int) -> bytes:
        out_rate = self._vobiz_params.audio_out_sample_rate
        codec = self._vobiz_params.codec.lower()
        if codec == "ulaw":
            return await pcm_to_ulaw(pcm, in_rate, out_rate, self._output_resampler)
        if codec == "alaw":
            return await pcm_to_alaw(pcm, in_rate, out_rate, self._output_resampler)
        if in_rate != out_rate:
            return await self._output_resampler.resample(pcm, in_rate, out_rate)
        return pcm

    async def _decode_wire(self, raw: bytes) -> bytes:
        in_rate = self._vobiz_params.audio_in_sample_rate
        codec = self._vobiz_params.codec.lower()
        if codec == "ulaw":
            return await ulaw_to_pcm(raw, in_rate, self._sample_rate, self._input_resampler)
        if codec == "alaw":
            return await alaw_to_pcm(raw, in_rate, self._sample_rate, self._input_resampler)
        if in_rate != self._sample_rate:
            return await self._input_resampler.resample(raw, in_rate, self._sample_rate)
        return raw

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            await self._reset_audio_out()
            return json.dumps({"event": "clear", "stream_id": self._stream_id})
        if isinstance(frame, AudioRawFrame):
            encoded = await self._encode_wire(frame.audio, frame.sample_rate)
            if not encoded:
                return None
            payload = base64.b64encode(encoded).decode("ascii")
            return json.dumps({
                "event": "media",
                "stream_id": self._stream_id,
                "media": {"payload": payload},
            })
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if not self.should_ignore_frame(frame):
                return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            audio = await self._decode_wire(bytes(data))
            return InputAudioRawFrame(audio=audio, num_channels=1, sample_rate=self._sample_rate) if audio else None

        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return None

        event = msg.get("event")
        if event == "media":
            b64 = msg.get("media", {}).get("payload", "")
            if not b64:
                return None
            audio = await self._decode_wire(base64.b64decode(b64))
            return InputAudioRawFrame(audio=audio, num_channels=1, sample_rate=self._sample_rate) if audio else None
        if event == "dtmf":
            digit = str(msg.get("dtmf", {}).get("digit", ""))
            try:
                return InputDTMFFrame(KeypadEntry(digit))
            except ValueError:
                return None
        return None
