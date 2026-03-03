# ── Backend Dockerfile ─────────────────────────────────────────────────
# Python 3.12 + Node.js 20 (needed for Claude CLI subprocess)
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS base

# ── System deps + Node.js ─────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl git ca-certificates gnupg && \
    # Install Node.js 20.x (required for Claude CLI / MCP servers)
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y nodejs && \
    npm install -g @anthropic-ai/claude-code && \
    # Cleanup
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies (layer cache) ─────────────────────────────────
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# ── Application source ────────────────────────────────────────────────
COPY . .

# ── Non-root user ────────────────────────────────────────────────────
# Claude CLI refuses --dangerously-skip-permissions when running as root.
# Create a dedicated 'geny' user (UID 1000) so the CLI works inside Docker.
RUN groupadd -r geny && useradd -r -g geny -m -d /home/geny -s /bin/bash geny

# ── Storage directories ──────────────────────────────────────────────
# Agent session workspaces — bind-mounted to host for visibility
RUN mkdir -p /data/geny_agent_sessions && \
    mkdir -p /app/logs && \
    mkdir -p /app/service/claude_manager/session_data && \
    mkdir -p /home/geny/.claude && \
    chown -R geny:geny /data /app /home/geny

# ── Environment defaults ─────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    GENY_AGENT_STORAGE_ROOT=/data/geny_agent_sessions

EXPOSE 8000

# Switch to non-root user
USER geny

CMD ["python", "main.py"]
