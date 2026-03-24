![](img/Geny_full_logo.png)
# 🧞 Geny — *Geny Execute, Not You*

> 지니가 할게, 넌 가만히 있어.

Autonomous multi-agent system — manage multiple agent sessions, orchestrate autonomous tasks, and visualize it all in a 3D city playground.

---

## Overview

Geny lets you spin up multiple Claude Code sessions, each working autonomously on its own task. A **Next.js** frontend with a 3D city visualization shows your agents as characters walking around a miniature city, while a **FastAPI + LangGraph** backend manages session lifecycles, pathfinding AI, memory, and tool orchestration.

### Key Features

- **🤖 Multi-Agent Orchestration**: Run multiple Claude Code sessions in parallel, each with independent storage
- **🏙️ 3D City Playground**: Three.js / React Three Fiber visualization — agents are characters wandering a city
- **🧠 LangGraph Autonomous Agent**: Resilient graph-based agent with memory, context guard, and model fallback
- **🗂️ Role-based Prompts**: Pre-built prompts for developer, researcher, planner, and worker roles
- **📡 Multi-pod Support**: Redis-backed session sharing across Kubernetes pods
- **🔌 MCP Auto-loading**: Drop JSON configs into `backend/mcp/` — automatically available in all sessions
- **🔧 Custom Tools**: Drop Python tool files into `backend/tools/` — auto-registered

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Geny                                       │
├──────────────────────────┬──────────────────────────────────────────┤
│   Frontend (Next.js)     │   Backend (FastAPI + LangGraph)          │
│                          │                                          │
│   App Shell              │   [API Layer]                            │
│   ├── Header             │   ├── /api/sessions      CRUD           │
│   ├── Sidebar            │   ├── /api/sessions/execute              │
│   └── Tabs               │   ├── /api/agent/sessions  LangGraph    │
│       ├── Dashboard      │   ├── /api/commands        CLI dispatch │
│       ├── Playground 🏙️  │   └── /api/config          runtime cfg  │
│       ├── Command        │                                          │
│       ├── Graph          │   [LangGraph Agent]                      │
│       ├── Logs           │   ├── autonomous_graph.py                │
│       ├── Info           │   ├── context_guard.py                   │
│       ├── Settings       │   ├── model_fallback.py                  │
│       └── Storage        │   ├── resilience_nodes.py                │
│                          │   └── memory (short/long-term)           │
│   3D Engine              │                                          │
│   ├── City layout 21×21  │   [Session Manager]                      │
│   ├── Asset loader       │   ├── Claude CLI process mgmt            │
│   ├── Avatar system      │   ├── Redis-based metadata               │
│   │   ├── Bone animation │   └── Multi-pod routing                  │
│   │   ├── A* pathfinding │                                          │
│   │   └── Wandering AI   │   [Tool & MCP]                           │
│   └── R3F + Drei         │   ├── mcp/ auto-loader                   │
│                          │   └── tools/ auto-register               │
└──────────────────────────┴──────────────────────────────────────────┘
```

## Project Structure

```
geny/
├── README.md
├── backend/                            # FastAPI + LangGraph backend
│   ├── main.py                         # App entrypoint
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── .env.example
│   ├── controller/
│   │   ├── agent_controller.py         # LangGraph agent endpoints
│   │   ├── claude_controller.py        # Session CRUD + execute
│   │   ├── command_controller.py       # CLI command dispatch
│   │   └── config_controller.py        # Runtime config API
│   ├── service/
│   │   ├── claude_manager/             # Core session management
│   │   │   ├── models.py              # Data models
│   │   │   ├── process_manager.py     # Claude CLI process control
│   │   │   ├── session_manager.py     # Session lifecycle
│   │   │   ├── session_store.py       # Persistence
│   │   │   ├── stream_parser.py       # Output stream parsing
│   │   │   └── mcp_tools_server.py    # LangChain → MCP wrapper
│   │   ├── langgraph/                  # Autonomous agent engine
│   │   │   ├── autonomous_graph.py    # Main LangGraph graph
│   │   │   ├── agent_session.py       # Agent session state
│   │   │   ├── context_guard.py       # Context window guard
│   │   │   ├── model_fallback.py      # Model fallback strategy
│   │   │   ├── resilience_nodes.py    # Error recovery nodes
│   │   │   ├── checkpointer.py        # Graph checkpointing
│   │   │   └── state.py              # Graph state definition
│   │   ├── memory/                     # Agent memory system
│   │   │   ├── short_term.py          # Working memory
│   │   │   ├── long_term.py           # Persistent memory
│   │   │   └── manager.py            # Memory coordinator
│   │   ├── config/                     # Configuration management
│   │   ├── prompt/                     # Prompt building & templates
│   │   ├── redis/                      # Redis client
│   │   ├── pod/                        # Pod info (multi-pod)
│   │   ├── middleware/                 # Session routing middleware
│   │   ├── proxy/                      # Inter-pod proxy
│   │   ├── tool_policy/                # Tool access policies
│   │   ├── logging/                    # Session logger
│   │   └── mcp_loader.py              # MCP/tools auto-loader
│   ├── prompts/                        # Role-based prompt templates
│   │   ├── developer.md
│   │   ├── researcher.md
│   │   ├── planner.md
│   │   ├── worker.md
│   │   └── self-manager.md
│   ├── mcp/                            # MCP server configs (auto-load)
│   └── tools/                          # Custom tools (auto-load)
│       ├── base.py                     # BaseTool, @tool decorator
│       └── example_tool.py
│
├── frontend/                           # Next.js 16 + React 19 frontend
│   ├── package.json
│   ├── next.config.ts                  # API proxy → backend:8000
│   ├── tsconfig.json
│   ├── public/
│   │   └── assets/                     # 3D models & textures
│   │       ├── kenney_mini-characters/ # Character GLB models
│   │       ├── kenney_city-kit-*/      # City building/road models
│   │       └── sky.jpg
│   └── src/
│       ├── app/
│       │   ├── layout.tsx              # Root layout + metadata
│       │   ├── page.tsx                # Main page
│       │   └── globals.css             # Tailwind v4 + CSS vars
│       ├── components/
│       │   ├── Header.tsx              # "Geny" branding header
│       │   ├── Sidebar.tsx             # Session list + stats
│       │   ├── TabNavigation.tsx       # Tab switcher
│       │   ├── TabContent.tsx          # Active tab renderer
│       │   ├── tabs/
│       │   │   ├── PlaygroundTab.tsx   # 3D city + R3F canvas
│       │   │   ├── CommandTab.tsx
│       │   │   ├── GraphTab.tsx
│       │   │   ├── LogsTab.tsx
│       │   │   ├── InfoTab.tsx
│       │   │   ├── SettingsTab.tsx
│       │   │   └── StorageTab.tsx
│       │   ├── modals/
│       │   │   ├── CreateSessionModal.tsx
│       │   │   └── DeleteSessionModal.tsx
│       │   └── ui/
│       │       └── NumberStepper.tsx
│       ├── lib/
│       │   ├── api.ts                  # Typed API layer
│       │   ├── cityLayout.ts           # 21×21 city grid generator
│       │   ├── assetLoader.ts          # GLB model cache & manifest
│       │   └── avatarSystem.ts         # Bone animation + pathfinding
│       ├── store/
│       │   └── useAppStore.ts          # Zustand global state
│       └── types/
│           └── index.ts                # Shared TypeScript types
│
└── frontend-legacy/                    # Legacy vanilla JS frontend (reference)
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| **3D Engine** | Three.js 0.183, React Three Fiber 9, Drei 10 |
| **State** | Zustand 5 |
| **Backend** | Python 3.11+, FastAPI, Uvicorn |
| **Agent** | LangGraph, LangChain, langchain-anthropic |
| **Cache** | Redis (optional, for multi-pod) |
| **Models** | Kenney Mini Characters, Kenney City Kit |

---

## Installation

### 🐳 Docker (Recommended)

**Prerequisites**: Docker Desktop (or Docker Engine + Docker Compose v2)

```bash
# 1. Clone
git clone https://github.com/<your-org>/geny.git && cd geny

# 2. Configure API keys
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY at minimum

# 3. Run
docker compose up --build
```

Open **http://localhost:3000** — done!

**Custom ports:**

```bash
BACKEND_PORT=8080 FRONTEND_PORT=3001 docker compose up --build
```

**Data directories** (bind-mounted to host for visibility):

| Host Path | Container Path | Description |
|-----------|---------------|-------------|
| `./data/geny_agent_sessions/` | `/data/geny_agent_sessions` | Agent workspace directories (one per session) |
| `./data/sessions.json` | `/app/service/claude_manager/sessions.json` | Session metadata — persists across restarts |
| `./data/logs/` | `/app/logs` | Backend execution logs |

You can browse, edit, or `tail -f` these files directly from the host.

**Other commands:**

```bash
docker compose up -d            # Background
docker compose logs -f          # Tail logs
docker compose logs backend     # Backend logs only
docker compose down             # Stop
docker compose down -v          # Stop + remove volumes
docker compose build --no-cache # Full rebuild
```

### Manual Setup (without Docker)

<details>
<summary>Click to expand manual setup instructions</summary>

#### Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | 3.11+ | Backend runtime |
| Node.js | 18+ | Frontend + Claude CLI + MCP servers |
| npm | 9+ | Frontend package manager |
| Git | 2.30+ | Version control |
| Claude CLI | latest | `npm i -g @anthropic-ai/claude-code` |
| GitHub CLI | 2.0+ | PR/Issue automation (optional) |
| Redis | 6+ | Multi-pod session sharing (optional) |

#### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
# or
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY at minimum
```

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Development server (proxies API to backend:8000)
npm run dev

# Production build
npm run build
npm start
```

#### Quick Start

```bash
# Terminal 1 — Backend
cd backend
python main.py                  # Starts on :8000

# Terminal 2 — Frontend
cd frontend
npm run dev                     # Starts on :3000, proxies /api → :8000
```

Open http://localhost:3000 — the Geny dashboard with 3D City Playground.

</details>

---

## Environment Variables

Configure in `backend/.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_HOST` | Server bind address | `0.0.0.0` |
| `APP_PORT` | Server port | `8000` |
| `DEBUG_MODE` | Debug mode | `false` |
| `USE_REDIS` | Enable Redis for multi-pod | `false` |
| `REDIS_HOST` | Redis host | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password | — |
| `GENY_AGENT_STORAGE_ROOT` | Session storage path | OS-dependent* |
| `ANTHROPIC_API_KEY` | Anthropic API key (**required**) | — |
| `GITHUB_TOKEN` | GitHub PAT for PR automation | — |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Autonomous mode | `true` |

\*Default storage: Windows `%LOCALAPPDATA%\geny_agent_sessions` / macOS & Linux `/tmp/geny_agent_sessions`

For frontend, set `API_URL` in the shell environment to override the backend target (default `http://localhost:8000`).

---

## API Usage

### Session Management

```bash
# Create session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"session_name": "my-session", "model": "claude-sonnet-4-20250514"}'

# List sessions
curl http://localhost:8000/api/sessions

# Execute prompt
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello, Claude!"}'

# Delete session
curl -X DELETE http://localhost:8000/api/sessions/{session_id}
```

### 🤖 Autonomous Mode

```bash
# Create autonomous session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "auto-refactor",
    "max_turns": 100,
    "autonomous": true
  }'

# Autonomous execution — Claude works independently
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze all files, refactor for quality, add types and tests, commit with descriptive messages.",
    "system_prompt": "Work autonomously without asking questions.",
    "max_turns": 50,
    "timeout": 21600
  }'
```

---

## 🔌 MCP & Custom Tools

### MCP Auto-Loading

Drop `.json` configs into `backend/mcp/` — they are automatically available in every session.

```jsonc
// backend/mcp/github.json
{
  "type": "http",
  "url": "https://api.githubcopilot.com/mcp/",
  "description": "GitHub MCP server"
}
```

See [backend/mcp/README.md](backend/mcp/README.md) for details.

### Custom Tool Auto-Loading

Drop `*_tool.py` files into `backend/tools/` — they are auto-registered in every session.

```python
# backend/tools/my_tool.py
from tools.base import tool

@tool
def search_database(query: str) -> str:
    """Search the database for records"""
    return f"Results for: {query}"

TOOLS = [search_database]
```

See [backend/tools/README.md](backend/tools/README.md) for details.

### MCP via API

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "full-stack",
    "mcp_config": {
      "servers": {
        "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
        "filesystem": {"type": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]},
        "database": {"type": "stdio", "command": "npx", "args": ["-y", "@bytebase/dbhub", "--dsn", "postgresql://user:pass@localhost:5432/mydb"]}
      }
    }
  }'
```

| Transport | Description | Use Case |
|-----------|-------------|----------|
| `stdio` | Local process | npx, python scripts |
| `http` | Remote HTTP | GitHub, Notion, Sentry, Slack |

---

## 🔄 GitHub Automation

Geny can clone repos, create branches, make changes, and submit PRs autonomously.

**Setup**: Set `GITHUB_TOKEN` in `backend/.env` (scopes: `repo`, `workflow`). Geny auto-configures `gh` CLI.

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Clone https://github.com/user/repo.git, create branch feature/docs, add JSDoc to all functions, commit, push, and create a PR.",
    "timeout": 21600,
    "system_prompt": "You are an autonomous coding agent. Complete all tasks without asking questions."
  }'
```

---

## Cross-Platform Support

Geny works on Windows, macOS, and Linux:

- **Windows**: Uses `%LOCALAPPDATA%\geny_agent_sessions`, auto-detects `.cmd`/`.exe` executables
- **macOS/Linux**: Uses `/tmp/geny_agent_sessions`, standard executable paths

---

## Community

| Author|  Name | Description | URL |
|-------|-------|-------------|----------|
|<a href="https://github.com/SonAIengine"><img src="https://avatars.githubusercontent.com/u/166786347?v=4&s=48" width="48" height="48" alt="Son Seong Jun" title="Son Seong Jun"/></a>|`graph-tool-call` | Tool-Search-Logic is inspired by SonSJ| https://github.com/SonAIengine/graph-tool-call |

---

## License

MIT License
