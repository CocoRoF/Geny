#!/bin/bash
set -euo pipefail

log() { echo "[$(date +"%Y-%m-%d %H:%M:%S")] [entrypoint] $*" >&2; }

# ?? Model auto-download ?????????????????????????????????????????
CHECKPOINT_DIR="/app/checkpoints"
MODEL_REPO="${FISH_SPEECH_MODEL_REPO:-fishaudio/s2-pro}"
MODEL_DIR="${CHECKPOINT_DIR}/$(basename "${MODEL_REPO}")"
AUTO_DOWNLOAD="${FISH_SPEECH_AUTO_DOWNLOAD:-false}"

check_model() {
    # Check if the model directory exists and contains at least one .safetensors or .pth file
    if [ -d "${MODEL_DIR}" ] && \
       find "${MODEL_DIR}" -maxdepth 1 \( -name '*.safetensors' -o -name '*.pth' \) -print -quit | grep -q .; then
        return 0
    fi
    return 1
}

if check_model; then
    log "Model found at ${MODEL_DIR}"
else
    log "Model not found at ${MODEL_DIR}"
    if [ "${AUTO_DOWNLOAD}" = "true" ] || [ "${AUTO_DOWNLOAD}" = "1" ]; then
        log "AUTO_DOWNLOAD enabled ??downloading ${MODEL_REPO} ..."
        mkdir -p "${MODEL_DIR}"
        pip install -q huggingface_hub 2>/dev/null || true
        python -c "
from huggingface_hub import snapshot_download
snapshot_download('${MODEL_REPO}', local_dir='${MODEL_DIR}')
print('Download complete!')
"
        if check_model; then
            log "Model downloaded successfully."
        else
            log "ERROR: Download finished but model files not found. Check logs."
            exit 1
        fi
    else
        log "ERROR: Set FISH_SPEECH_AUTO_DOWNLOAD=true in .env to enable auto-download,"
        log "       or manually place model files in the mounted checkpoints volume."
        exit 1
    fi
fi

# ?? Hand off to original entrypoint ?????????????????????????????
log "Starting Fish Speech ..."
exec /app/start_webui.sh "$@"
