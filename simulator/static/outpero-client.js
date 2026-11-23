/**
 * Outpero-Style Full-Duplex 16kHz Int16 Binary PCM Browser Client
 * Handles continuous mic streaming (for Silero VAD barge-in), scheduled ring-buffer audio playback,
 * instant WebAudio queue flushing on `interruption`, and live transcript / latency events.
 */
(function (global) {
  'use strict';

  const TARGET_RATE = 16000;
  const CHUNK_SAMPLES = 512; // 32ms @ 16kHz for Silero VAD & low-latency Deepgram streaming

  function downsampleFloat32ToInt16(float32Buf, inputRate) {
    if (inputRate === TARGET_RATE) {
      const out = new Int16Array(float32Buf.length);
      for (let i = 0; i < float32Buf.length; i++) {
        const s = Math.max(-1, Math.min(1, float32Buf[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      return out;
    }
    const ratio = inputRate / TARGET_RATE;
    const outLen = Math.floor(float32Buf.length / ratio);
    const out = new Int16Array(outLen);
    let outIdx = 0;
    let srcIdx = 0;
    while (outIdx < outLen) {
      const nextSrc = Math.floor((outIdx + 1) * ratio);
      let acc = 0;
      let count = 0;
      for (let i = srcIdx; i < nextSrc && i < float32Buf.length; i++) {
        acc += float32Buf[i];
        count++;
      }
      const val = count > 0 ? acc / count : float32Buf[Math.min(srcIdx, float32Buf.length - 1)];
      const clamped = Math.max(-1, Math.min(1, val));
      out[outIdx++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7FFF;
      srcIdx = nextSrc;
    }
    return out;
  }

  class OutperoVoiceClient {
    constructor(callbacks = {}) {
      this.cb = callbacks;
      this.ws = null;
      this.isCalling = false;
      this.audioCtx = null;
      this.micStream = null;
      this.micSource = null;
      this.processorNode = null;
      this.silentGain = null;
      this.pcmQueue = [];
      this.activeNodes = new Set();
      this.nextPlayTime = 0;
      this.isMuted = false;
      this._endTimer = null;
      this._closedNotified = false;
    }

    setMuted(muted) {
      this.isMuted = Boolean(muted);
      if (this.micStream) {
        this.micStream.getAudioTracks().forEach((tr) => {
          tr.enabled = !this.isMuted;
        });
      }
      if (this.isMuted && this.cb.onMicLevel) {
        this.cb.onMicLevel(0);
      }
    }

    _notifyClosedOnce() {
      if (this._closedNotified) return;
      this._closedNotified = true;
      if (this.cb.onClosed) this.cb.onClosed();
    }

    _resolveWsUrl(customWsUrl, isDemo = false) {
      let base = customWsUrl;
      if (!base) {
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        base = `${proto}//${window.location.host}/ws/engine`;
      }
      if (isDemo && !base.includes('demo=')) {
        base += (base.includes('?') ? '&' : '?') + 'demo=1';
      }
      return base;
    }

    async start(initConfig = {}, customWsUrl = '') {
      if (this.isCalling) return;
      if (this._endTimer) {
        clearTimeout(this._endTimer);
        this._endTimer = null;
      }
      this._closedNotified = false;
      this.isCalling = true;
      this.isMuted = false;
      this.pcmQueue = [];
      this.nextPlayTime = 0;

      // Unlock WebAudio inside user click gesture
      if (!this.audioCtx) {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        try {
          this.audioCtx = new Ctx({ sampleRate: TARGET_RATE });
        } catch (e) {
          this.audioCtx = new Ctx();
        }
      }
      if (this.audioCtx.state === 'suspended') {
        await this.audioCtx.resume();
      }

      const wsUrl = this._resolveWsUrl(customWsUrl, Boolean(initConfig.demo));
      this.ws = new WebSocket(wsUrl);
      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = async () => {
        // Send initial session parameters before starting mic capture
        this.ws.send(JSON.stringify({
          action: 'init',
          speaker: initConfig.speaker || 'archie',
          llm: initConfig.llm || 'auto',
          employee_id: initConfig.employee_id || '',
          lead_id: initConfig.lead_id || '',
          genre: initConfig.genre || '',
          first_sentence: initConfig.first_sentence || '',
          system_prompt: initConfig.system_prompt || '',
          demo: Boolean(initConfig.demo),
        }));

        if (this.cb.onConnected) this.cb.onConnected();
        await this._startMicCapture();
      };

      this.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          this._playPcm16Buffer(event.data);
          return;
        }
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then((buf) => this._playPcm16Buffer(buf));
          return;
        }
        try {
          const msg = JSON.parse(event.data);
          this._handleControlMessage(msg);
        } catch (err) {
          console.warn('[OutperoClient] Bad JSON message:', err);
        }
      };

      this.ws.onclose = () => {
        if (this._endTimer) {
          clearTimeout(this._endTimer);
          this._endTimer = null;
        }
        this._cleanupMedia();
        this.isCalling = false;
        this.ws = null;
        this._notifyClosedOnce();
      };

      this.ws.onerror = (err) => {
        console.error('[OutperoClient] WebSocket error:', err);
        if (this.cb.onError) this.cb.onError('WebSocket connection error');
      };
    }

    async _startMicCapture() {
      try {
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        });
      } catch (err) {
        if (this.cb.onMicError) this.cb.onMicError(err);
        return;
      }

      this.micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      this.processorNode = this.audioCtx.createScriptProcessor(1024, 1, 1);
      this.silentGain = this.audioCtx.createGain();
      this.silentGain.gain.value = 0;

      this.processorNode.onaudioprocess = (ev) => {
        if (!this.isCalling || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        if (this.isMuted) {
          if (this.cb.onMicLevel) this.cb.onMicLevel(0);
          return;
        }
        const input = ev.inputBuffer.getChannelData(0);

        let sumSq = 0;
        for (let i = 0; i < input.length; i++) sumSq += input[i] * input[i];
        const rms = Math.sqrt(sumSq / input.length);
        if (this.cb.onMicLevel) this.cb.onMicLevel(rms);

        const int16 = downsampleFloat32ToInt16(input, this.audioCtx.sampleRate);
        for (let i = 0; i < int16.length; i++) {
          this.pcmQueue.push(int16[i]);
        }

        while (this.pcmQueue.length >= CHUNK_SAMPLES) {
          const slice = this.pcmQueue.splice(0, CHUNK_SAMPLES);
          const packet = new Int16Array(slice);
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(packet.buffer);
          }
        }
      };

      this.micSource.connect(this.processorNode);
      this.processorNode.connect(this.silentGain);
      this.silentGain.connect(this.audioCtx.destination);
    }

    _playPcm16Buffer(arrayBuffer) {
      if (!this.isCalling || !this.audioCtx || !arrayBuffer || arrayBuffer.byteLength < 2) return;
      if (this.audioCtx.state === 'suspended') this.audioCtx.resume();

      const int16 = new Int16Array(arrayBuffer);
      const float32 = new Float32Array(int16.length);
      for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
      }

      const audioBuffer = this.audioCtx.createBuffer(1, float32.length, TARGET_RATE);
      audioBuffer.getChannelData(0).set(float32);

      const src = this.audioCtx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(this.audioCtx.destination);

      const now = this.audioCtx.currentTime;
      if (this.nextPlayTime < now + 0.01) {
        this.nextPlayTime = now + 0.02;
      }
      src.start(this.nextPlayTime);
      this.nextPlayTime += audioBuffer.duration;
      this.activeNodes.add(src);
      src.onended = () => {
        this.activeNodes.delete(src);
      };
    }

    clearPlaybackQueue() {
      this.activeNodes.forEach((node) => {
        try { node.stop(); } catch (e) {}
      });
      this.activeNodes.clear();
      this.nextPlayTime = 0;
    }

    _handleControlMessage(msg) {
      const t = msg.type;
      if (t === 'interruption') {
        this.clearPlaybackQueue();
        if (this.cb.onInterruption) this.cb.onInterruption();
      } else if (t === 'engine_ready') {
        if (this.cb.onEngineReady) this.cb.onEngineReady(msg);
      } else if (t === 'user_interim') {
        if (this.cb.onUserInterim) this.cb.onUserInterim(msg.text || '');
      } else if (t === 'user_transcript') {
        if (this.cb.onUserTranscript) this.cb.onUserTranscript(msg);
      } else if (t === 'agent_text_delta') {
        if (this.cb.onAgentTextDelta) this.cb.onAgentTextDelta(msg);
      } else if (t === 'agent_text') {
        if (this.cb.onAgentText) this.cb.onAgentText(msg);
      } else if (t === 'metrics') {
        if (this.cb.onMetrics) this.cb.onMetrics(msg);
      } else if (t === 'turn_latency') {
        if (this.cb.onTurnLatency) this.cb.onTurnLatency(msg);
      } else if (t === 'bot_speaking') {
        if (this.cb.onBotSpeaking) this.cb.onBotSpeaking(Boolean(msg.speaking));
      } else if (t === 'user_speaking') {
        if (this.cb.onUserSpeaking) this.cb.onUserSpeaking(Boolean(msg.speaking));
      } else if (t === 'call_report') {
        if (this.cb.onCallReport) this.cb.onCallReport(msg.report);
        this.forceClose();
      } else if (t === 'error') {
        if (this.cb.onError) this.cb.onError(msg.message || 'Engine error');
      }
    }

    sendText(text) {
      const clean = (text || '').trim();
      if (!clean || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      this.clearPlaybackQueue();
      this.ws.send(JSON.stringify({ action: 'user_text', text: clean }));
    }

    endCall() {
      if (!this.isCalling) return;
      this.isCalling = false;
      this._cleanupMedia();
      if (this._endTimer) {
        clearTimeout(this._endTimer);
        this._endTimer = null;
      }
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'end_call' }));
        // Wait up to 6.5s for server call_report generation before forcing socket close
        this._endTimer = setTimeout(() => this.forceClose(), 6500);
      } else {
        this.forceClose();
      }
      this._notifyClosedOnce();
    }

    _cleanupMedia() {
      this.clearPlaybackQueue();
      if (this.processorNode) {
        try { this.processorNode.disconnect(); } catch (e) {}
        this.processorNode = null;
      }
      if (this.micSource) {
        try { this.micSource.disconnect(); } catch (e) {}
        this.micSource = null;
      }
      if (this.silentGain) {
        try { this.silentGain.disconnect(); } catch (e) {}
        this.silentGain = null;
      }
      if (this.micStream) {
        this.micStream.getTracks().forEach((tr) => tr.stop());
        this.micStream = null;
      }
    }

    forceClose() {
      if (this._endTimer) {
        clearTimeout(this._endTimer);
        this._endTimer = null;
      }
      this._cleanupMedia();
      this.isCalling = false;
      if (this.ws) {
        const ws = this.ws;
        this.ws = null;
        try { ws.close(); } catch (e) {}
      }
      this._notifyClosedOnce();
    }
  }

  global.OutperoVoiceClient = OutperoVoiceClient;
})(window);
