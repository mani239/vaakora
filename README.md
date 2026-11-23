# Vaakora Voice Calling Platform

Real-time Indian English AI voice calling engine, marketing storefront, live browser demo, and operator console, configured with **Pontis LLP** (Hyderabad) as the active client workspace and calling demo persona.

## Architecture

- **`engine/`**: FastAPI WebSocket + Pipecat real-time audio pipeline (`16 kHz` binary PCM WebSockets, Silero VAD, SmartTurn end-of-turn detection, Deepgram Nova-3 STT, Groq / Google Gemini LLM, Smallest AI Lightning v3.1 -> Cartesia -> Deepgram Aura-2 TTS, AI disclosure guardrails, and clean hangup handling).
- **`simulator/`**: FastAPI server, SQLite repository (`db.py`), CRM/campaign REST APIs, Paper & Obsidian static frontend (`/, /demo, /voices, /pricing, /trust, /app, /simulator, /legal/*`), and pre-rendered `16 kHz` voice preview WAVs.
- **`deploy/`**: Docker Compose, Dockerfile, Nginx config, setup script, and Python dependency manifest.
- **`DESIGN.md`**: Design tokens and Paper/Obsidian surface specification.

## Local Setup

1. Install Python dependencies (Python 3.11+):

   ```bash
   pip install -r deploy/requirements.txt
   pip install "pipecat-ai[silero,deepgram,cartesia,groq,google]"
   ```

2. Create `.env` from `.env.example` and add your API keys (`SMALLEST_API_KEY`, `DEEPGRAM_API_KEY`, `GROQ_API_KEY`, and optionally `GEMINI_API_KEY` / `CARTESIA_API_KEY`).

3. Start the server:

   ```bash
   python -m uvicorn simulator.app:app --host 127.0.0.1 --port 8000
   ```

4. Open:
   - Marketing site: `http://127.0.0.1:8000/`
   - Live browser voice demo: `http://127.0.0.1:8000/demo`
   - Operator console: `http://127.0.0.1:8000/app`
   - Engine sandbox: `http://127.0.0.1:8000/simulator`
