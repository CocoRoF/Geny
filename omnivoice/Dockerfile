# ── geny-omnivoice Dockerfile ─────────────────────────────────────────
# CUDA 12.8 + PyTorch 2.8 + vendored OmniVoice (omnivoice_core/) +
# Geny FastAPI wrapper (server/).
# ──────────────────────────────────────────────────────────────────────
FROM nvidia/cuda:12.8.0-cudnn-runtime-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ── System deps ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common curl ca-certificates ffmpeg \
        libsndfile1 libsox-dev git \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── PyTorch first (heavy layer, cached separately) ────────────────────
RUN pip install --no-cache-dir \
        torch==2.8.0 torchaudio==2.8.0 \
        --extra-index-url https://download.pytorch.org/whl/cu128

# ── Project install ──────────────────────────────────────────────────
COPY pyproject.toml README.md ./
COPY omnivoice_core/ ./omnivoice_core/
COPY server/ ./server/
RUN pip install --no-cache-dir .

# ── Runtime defaults ─────────────────────────────────────────────────
ENV OMNIVOICE_HOST=0.0.0.0 \
    OMNIVOICE_PORT=9881 \
    OMNIVOICE_VOICES_DIR=/voices \
    OMNIVOICE_HF_CACHE=/models/hf-cache \
    HF_HOME=/models/hf-cache \
    TRANSFORMERS_CACHE=/models/hf-cache

RUN mkdir -p /voices /models/hf-cache

EXPOSE 9881

# Generous start_period — first run downloads the OmniVoice checkpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -fsS http://localhost:9881/health || exit 1

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "9881"]
