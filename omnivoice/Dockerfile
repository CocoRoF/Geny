# ── geny-omnivoice Dockerfile ─────────────────────────────────────────
# CUDA 12.8 + PyTorch 2.8 + vendored OmniVoice (omnivoice_core/) +
# Geny FastAPI wrapper (server/).
#
# Hardware target (2026-04-25): RTX 5070 (Blackwell, sm_120) on host
# driver 580. cu128 wheels are required — the previous cu126 baseline
# had no sm_100/sm_120 SASS or PTX, so first ``mem_get_info`` aborted
# with ``CUDA unknown error ... Setting available devices to be zero``
# during ``_lazy_init``. The legacy GTX 1070 (sm_61) dev box has been
# retired; if it ever comes back, run an older tag pinned to cu126.
# ──────────────────────────────────────────────────────────────────────
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu22.04 AS base

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
# torch 2.8.0 + cu128 ships Blackwell kernels (sm_100/sm_120). Drops
# Pascal (sm_60/61) support — see header note for why that's intentional.
RUN pip install --no-cache-dir \
        torch==2.8.0 torchaudio==2.8.0 \
        --extra-index-url https://download.pytorch.org/whl/cu128

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
# Note: ``expandable_segments:True`` is mutually exclusive with
# ``max_split_size_mb`` — combining them raises
# ``RuntimeError: Unrecognized CachingAllocator option`` at first CUDA init.
# OMNIVOICE_GPU_MEM_FRACTION: cap this process at 85% of total VRAM by
# default (~10.2 GB on an RTX 5070 12 GB dedicated host). Operators on
# shared GPUs can lower via the compose file.
ENV OMNIVOICE_HOST=0.0.0.0 \
    OMNIVOICE_PORT=9881 \
    OMNIVOICE_VOICES_DIR=/voices \
    OMNIVOICE_HF_CACHE=/models/hf-cache \
    HF_HOME=/models/hf-cache \
    TRANSFORMERS_CACHE=/models/hf-cache \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    OMNIVOICE_GPU_MEMORY_FRACTION=0.85

RUN mkdir -p /voices /models/hf-cache

EXPOSE 9881

# Generous start_period — first run downloads the OmniVoice checkpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -fsS http://localhost:9881/health || exit 1

CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "9881"]
