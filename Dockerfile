FROM python:3.11-slim

LABEL org.opencontainers.image.title="IT Support Ticket Management OpenEnv"
LABEL org.opencontainers.image.description="OpenEnv environment for IT support ticket triage and resolution"

ENV HOME=/home/user \
    PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY models.py            .
COPY environment.py       .
COPY server.py            .
COPY static_frontend.html .
COPY openenv.yaml         .
COPY README.md            .

RUN useradd -m -u 1000 user
USER user

EXPOSE 7860

ENV PORT=7860 \
    API_BASE_URL="https://api.groq.com/openai/v1" \
    MODEL_NAME="llama-3.3-70b-versatile" \
    HF_TOKEN=""

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD uvicorn server:app \
        --host 0.0.0.0 \
        --port ${PORT} \
        --workers 1 \
        --log-level info
