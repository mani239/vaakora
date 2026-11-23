FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries needed for soundfile / Silero ONNX / healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install bundled Pipecat engine cleanly first so version stays locked to local tested API
COPY voice-research/pipecat /app/voice-research/pipecat
RUN pip install --upgrade pip && \
    pip install -e /app/voice-research/pipecat

# Install API + LLM + STT + ASGI server dependencies
COPY deploy/requirements.txt /app/deploy/requirements.txt
RUN pip install -r /app/deploy/requirements.txt

# Copy application code
COPY engine /app/engine
COPY simulator /app/simulator

RUN mkdir -p /app/data

EXPOSE 8000 8001

CMD ["uvicorn", "simulator.app:app", "--host", "0.0.0.0", "--port", "8000"]
