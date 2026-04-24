# Geny Agent — Backend

> Multi-session agent management system based on Claude CLI

## Project Overview

Geny Agent is a FastAPI backend that wraps Claude CLI to manage **multi-agent sessions**. It supports LangGraph-based autonomous execution workflows, MCP tool integration, vector memory, and real-time chat.

### Key Features

- **Multi-Session** — Run and manage independent Claude CLI processes in parallel
- **Autonomous Workflows** — LangGraph StateGraph automates difficulty-based branching, review, and TODO decomposition
- **MCP Proxy** — Unifies external MCP servers + built-in Python tools into a single interface
- **Vector Memory** — FAISS + Embedding API for semantic search over long-term memory
- **Real-time Chat** — Inter-session broadcast, DM, and SSE streaming
- **Config Management** — Dataclass-based UI auto-generation with DB+JSON dual storage

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI (main.py)                    │
│                                                         │
│  10 Routers ─────────────────────────────────────────── │
│  ├── /api/agent/*          Session/agent CRUD + execution│
│  ├── /api/sessions/*       Legacy session management    │
│  ├── /api/commands/*       Log query + monitor          │
│  ├── /api/config/*         Config CRUD + export/import  │
│  ├── /api/workflows/*      Workflow editor              │
│  ├── /api/shared-folder/*  Shared folder file CRUD      │
│  ├── /api/chat/*           Chat broadcast + DM          │
│  ├── /api/internal-tool/*  Proxy MCP tool execution     │
│  ├── /api/tool-presets/*   Tool preset management       │
│  └── /api/tools/*          Tool catalog                 │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                     Service Layer                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ AgentSession  │  │  Workflow    │  │   Memory     │  │
│  │ Manager       │  │  Executor   │  │   Manager    │  │
│  │ (LangGraph)   │  │  (Compiler) │  │ (LTM+STM+V) │  │
│  └──────┬───────┘  └──────┬──────┘  └──────────────┘  │
│         │                  │                            │
│  ┌──────┴───────┐  ┌──────┴──────┐  ┌──────────────┐  │
│  │ ClaudeProcess │  │ 20 Node    │  │   Prompt     │  │
│  │ (CLI Wrapper) │  │ Types      │  │   Builder    │  │
│  └──────┬───────┘  └─────────────┘  └──────────────┘  │
│         │                                               │
│  ┌──────┴───────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ StreamParser  │  │  ToolLoader │  │  ConfigMgr   │  │
│  │ (JSON Stream) │  │  MCPLoader  │  │  (DB+JSON)   │  │
│  └──────────────┘  └─────────────┘  └──────────────┘  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                   Infrastructure                         │
│                                                         │
│  PostgreSQL ──── psycopg3 ConnectionPool                │
│  File System ─── JSON/JSONL/Markdown/FAISS              │
│  Claude CLI ──── node.exe + cli.js (stream-json)        │
└─────────────────────────────────────────────────────────┘
```

---

## Startup Sequence

Initialized in order by the `lifespan()` handler in `main.py`:

| Step | System | Description |
|------|--------|-------------|
| 1 | **Database** | PostgreSQL connection, model registration, table creation, data migration |
| 2 | **Config** | ConfigManager init, DB backend connect, JSON→DB migration |
| 3 | **Sessions** | Connect DB to SessionStore and ChatStore |
| 4 | **Logging** | Connect DB to SessionLogger and AgentSession |
| 5 | **Tools** | Load built-in + custom Python tools via ToolLoader |
| 6 | **MCP** | Load external MCP server configs via MCPLoader |
| 7 | **Presets** | Install ToolPreset templates |
| 8 | **Workflow** | Register workflow nodes + install templates |
| 9 | **Shared** | Initialize SharedFolderManager + apply config |
| 10 | **Monitor** | Start session idle monitor (10-minute threshold) |

Falls back to **file-only mode** (JSON-based) on DB connection failure.

---

## Directory Structure

```
backend/
├── main.py                    # FastAPI app + lifespan handler
├── requirements.txt           # Python dependencies
├── Dockerfile                 # Container image
│
├── controller/                # API routers (10)
│   ├── agent_controller.py    #   /api/agent/*
│   ├── claude_controller.py   #   /api/sessions/* (legacy)
│   ├── command_controller.py  #   /api/commands/*
│   ├── config_controller.py   #   /api/config/*
│   ├── workflow_controller.py #   /api/workflows/*
│   ├── shared_folder_controller.py
│   ├── chat_controller.py
│   ├── internal_tool_controller.py
│   ├── tool_preset_controller.py
│   └── tool_controller.py
│
├── service/                   # Business logic
│   ├── claude_manager/        #   Claude CLI process management
│   ├── executor/              #   geny-executor agent sessions
│   ├── workflow/              #   Workflow definition, execution, compiler
│   │   ├── nodes/             #     20 workflow node types
│   │   └── compiler/          #     Workflow test compiler
│   ├── memory/                #   LTM + STM + FAISS vector
│   ├── chat/                  #   Chat rooms, messages, inbox
│   ├── config/                #   Config management + auto-discovery
│   │   └── sub_config/        #     12 config classes
│   ├── database/              #   PostgreSQL manager + helpers
│   ├── logging/               #   Per-session structured logging
│   ├── prompt/                #   Prompt builder + section library
│   ├── shared_folder/         #   Inter-session shared folder
│   ├── tool_policy/           #   Tool access policy engine
│   ├── tool_preset/           #   Tool preset management
│   ├── proxy/                 #   Redis proxy (unused)
│   ├── middleware/            #   Middleware (unused)
│   ├── pod/                   #   Pod management (unused)
│   ├── utils/                 #   Utilities (KST time, etc.)
│   ├── mcp_loader.py          #   External MCP server config loader
│   └── tool_loader.py         #   Python tool discovery/loader
│
├── tools/                     # Python tool definitions
│   ├── base.py                #   BaseTool ABC + @tool decorator
│   ├── _mcp_server.py         #   FastMCP server (built-in tool exposure)
│   ├── _proxy_mcp_server.py   #   Proxy MCP server (Claude ↔ backend)
│   ├── built_in/              #   11 built-in tools
│   └── custom/                #   11 custom tools
│
├── prompts/                   # Role-specific Markdown prompt templates
│   ├── worker.md
│   ├── developer.md
│   ├── researcher.md
│   ├── planner.md
│   └── templates/             #   6 specialized templates
│
├── workflows/                 # Workflow JSON templates
│   ├── template-simple.json
│   └── template-autonomous.json
│
├── tool_presets/              # Tool preset JSON templates
├── mcp/                       # MCP server config examples
├── logs/                      # Session log files
└── docs/                      # Detailed documentation (see below)
```

---

## Documentation

Detailed documentation for each system:

| Document | Description |
|----------|-------------|
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | Workflow System — 20 node types, StateGraph compilation, execution flow, templates |
| [docs/DATABASE.md](docs/DATABASE.md) | Database — ConnectionPool, 6 tables, query operators, migrations |
| [docs/TOOLS.md](docs/TOOLS.md) | Tools & MCP — BaseTool, proxy pattern, policy engine, presets |
| [docs/SESSIONS.md](docs/SESSIONS.md) | Session Management — ClaudeProcess, StreamParser, AgentSession lifecycle |
| [docs/CHAT.md](docs/CHAT.md) | Chat — Broadcast, DM, SSE streaming, conversation store |
| [docs/MEMORY.md](docs/MEMORY.md) | Memory — LTM, STM, FAISS vector, embedding, context build |
| [docs/PROMPTS.md](docs/PROMPTS.md) | Prompts — PromptBuilder, sections, role templates, context loader |
| [docs/CONFIG.md](docs/CONFIG.md) | Config — BaseConfig, 12 config classes, auto-discovery, env_sync |
| [docs/LOGGING.md](docs/LOGGING.md) | Logging — 11 LogLevels, triple recording, structured extraction |
| [docs/SHARED_FOLDER.md](docs/SHARED_FOLDER.md) | Shared Folder — Symlinks, security validation, REST API |

---

## Environment Variables

### Required

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DB` | Database name | `geny_agent` |
| `POSTGRES_USER` | DB user | `geny` |
| `POSTGRES_PASSWORD` | DB password | — |

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_MODEL` | Claude model | `claude-sonnet-4-6` |
| `APP_PORT` | Server port | `8000` |
| `GITHUB_TOKEN` | GitHub PAT | — |
| `GENY_LANGUAGE` | UI language (`en`/`ko`) | `en` |
| `CLAUDE_MAX_BUDGET_USD` | Max cost per session | `10.0` |
| `CLAUDE_MAX_TURNS` | Max turns per task | `50` |

### Memory Provider (v0.20.0 integration)

`MemorySessionRegistry` stays **dormant** unless `MEMORY_PROVIDER` is set — the legacy `SessionMemoryManager` owns the path until an operator opts in.

| Variable | Description | Default |
|----------|-------------|---------|
| `MEMORY_PROVIDER` | Factory key: `ephemeral`, `file`, `sql`, or unset/`disabled` (dormant) | unset |
| `MEMORY_ROOT` | Filesystem root for `file` provider (required when `MEMORY_PROVIDER=file`) | — |
| `MEMORY_DSN` | SQLAlchemy DSN for `sql` provider (required when `MEMORY_PROVIDER=sql`) | — |
| `MEMORY_DIALECT` | Override DSN scheme auto-detect: `sqlite` or `postgres` | auto |
| `MEMORY_SCOPE` | Provider scope | `session` |
| `MEMORY_TIMEZONE` | IANA tz name used for provider timestamps | host tz |
| `MEMORY_PROVIDER_ATTACH` | Attach providers to pipeline Stage 2 (truthy: `1`/`true`/`yes`/`on`) | `false` |
| `MEMORY_API_PROVIDER` | Route `/api/agents/{id}/memory/*` through provider instead of legacy manager | `false` |
| `MEMORY_LEGACY_STM` | Keep legacy STM reads/writes active (per-layer rollout flag) | `true` |
| `MEMORY_LEGACY_LTM` | Keep legacy LTM active | `true` |
| `MEMORY_LEGACY_NOTES` | Keep legacy notes active | `true` |
| `MEMORY_LEGACY_VECTOR` | Keep legacy FAISS vector path active | `true` |
| `MEMORY_LEGACY_CURATED` | Keep legacy curated/global memory active | `true` |

### Environment Service

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVIRONMENT_STORAGE_PATH` | Root directory for environment manifests | `./data/environments` |
