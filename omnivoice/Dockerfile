# ── geny-omnivoice Dockerfile ─────────────────────────────────────────
# CUDA 12.6 + PyTorch 2.6 + vendored OmniVoice (omnivoice_core/) +
# Geny FastAPI wrapper (server/).
#
# Note: We deliberately stay on CUDA 12.6 / torch 2.6 rather than the
# newer cu128 / torch 2.8 wheels because the latter dropped Pascal
# (sm_60/61) support — Geny's reference dev box ships a GTX 1070
# (sm_61) and would otherwise crash at first kernel launch with
# ``CUDA error: no kernel image is available for execution on the
# device``. cu126 wheels still bundle sm_60/61/70/75/80/86/90 kernels.
# ──────────────────────────────────────────────────────────────────────
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04 AS base

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
# torch 2.6.0 + cu126 still ships Pascal (sm_60/61) kernels.
RUN pip install --no-cache-dir \
        torch==2.6.0 torchaudio==2.6.0 \
        --extra-index-url https://download.pytorch.org/whl/cu126

# ── Project install ──────────────────────────────────────────────────
COPY pyproject.toml README.md ./
COPY omnivoice_core/ ./omnivoice_core/
COPY server/ ./server/
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir . \
    && chmod +x scripts/*.sh 2>/dev/null || true

# ── Runtime defaults ─────────────────────────────────────────────────
# PYTORCH_CUDA_ALLOC_CONF: ``expandable_segments`` keeps a single growing
# arena instead of fragmenting into many fixed-size blocks — essential
# for the persistent-residency policy (see dev_docs/20260422_OmniVoice_Perf/).
# ``max_split_size_mb=128`` discourages the allocator from carving large
# arenas into small slivers that fragment over many requests.
# OMNIVOICE_GPU_MEM_FRACTION: cap this process at 70% of total VRAM by
# default (~5.5 GB on a GTX 1070 8 GB). Operators on dedicated hosts
# can raise to 0.9 via the compose file.
ENV OMNIVOICE_HOST=0.0.0.0 \
    OMNIVOICE_PORT=9881 \
    OMNIVOICE_VOICES_DIR=/voices \
    OMNIVOICE_HF_CACHE=/models/hf-cache \
    HF_HOME=/models/hf-cache \
    TRANSFORMERS_CACHE=/models/hf-cache \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,max_split_size_mb=128 \
    OMNIVOICE_GPU_MEMORY_FRACTION=0.7

RUN mkdir -p /voices /models/hf-cache

EXPOSE 9881

# Generous start_period — first run downloads the OmniVoice checkpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -fsS http://localhost:9881/health || exit 1

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "9881"]
