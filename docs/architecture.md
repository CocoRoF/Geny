# Architecture

How Geny is structured end-to-end, and where each subsystem lives in the repo.

## Stack at a glance

```
┌─────────────────────────────────────────────────────────────────┐
│ Frontend  Next.js 16 + React + TypeScript + Tailwind            │
│           ├─ R3F / drei         (3D scene, VRM)                  │
│           ├─ Pixi.js + Live2D   (2D avatar runtime)              │
│           ├─ Zustand / React Query                               │
│           └─ EventSource SSE    (live execution stream)          │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ HTTP / SSE
┌──────────────────────────────────▼──────────────────────────────┐
│ Backend   FastAPI + Uvicorn (Python 3.12)                       │
│           service/                                               │
│           ├─ executor/         AgentSession wrapper              │
│           ├─ execution/        High-level orchestration          │
│           ├─ logging/          SessionLogger (SSE stream)        │
│           ├─ environment/      Manifest editor + templates       │
│           ├─ credentials/      Provider key bundles              │
│           ├─ vtuber/           Avatar / TTS / Thinking trigger   │
│           ├─ sessions/         SessionInfo, lifecycle            │
│           ├─ mcp_loader.py     MCP server registry               │
│           └─ tool_loader.py    Built-in + MCP tool registry      │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ in-process
┌──────────────────────────────────▼──────────────────────────────┐
│ geny-executor 2.1.0   21-stage pipeline                         │
│   ├─ Stage 1–5    Bootstrap, manifest, credentials, model       │
│   ├─ Stage 6      API call (provider client)                    │
│   ├─ Stage 7–9    Stream parse, accumulator, finalize           │
│   ├─ Stage 10     Tool dispatch (MCP / native / built-in)       │
│   ├─ Stage 11–19  Memory, hooks, persistence, telemetry         │
│   └─ Stage 20–21  Response shape, cleanup                       │
└─────────────────────────────────────────────────────────────────┘
```

The `service/executor/` package is the only place that imports `geny_executor` directly. Every other backend module talks to executor through `AgentSession`, so the pipeline can be upgraded without rippling changes through the rest of the codebase.

## Two execution loops

Geny runs two distinct agent loops in parallel and stitches them together via delegation.

### VTuber loop

Personality-facing. Hosts the avatar, the chat surface, the audience-visible state. It owns:

- Persona prompts and affect modulation ([backend/service/persona/](../backend/service/persona/), [affect/](../backend/service/affect/))
- Live2D / VRM model state ([vtuber/avatar_state_manager.py](../backend/service/vtuber/avatar_state_manager.py))
- TTS routing ([vtuber/tts/](../backend/service/vtuber/tts/))
- Thinking trigger — autonomous wake-ups while idle ([vtuber/thinking_trigger.py](../backend/service/vtuber/thinking_trigger.py))

The VTuber is intentionally light on tools. When a task needs file I/O, code execution, or long research, it delegates.

### Sub-Worker loop

Task-facing. Spawned on demand by the VTuber to run a self-contained goal in a fresh executor pipeline. It owns:

- A separate `AgentSession` with its own manifest, model, and tool registry
- A streaming log that the VTuber surfaces back to the audience as progress
- Optional shared folder for artifacts ([backend/service/shared_folder/](../backend/service/shared_folder/))

The handoff is implemented in [vtuber/delegation.py](../backend/service/vtuber/delegation.py). See [sessions.md](sessions.md) for the full pairing protocol.

## Request lifecycle

A single user message flows through these layers:

1. **HTTP/WebSocket ingress** — FastAPI route in [backend/api/](../backend/api/) receives the message, validates auth, attaches it to a session.
2. **Execution dispatch** — [service/execution/agent_executor.py](../backend/service/execution/agent_executor.py) picks the session, resolves the manifest, calls `AgentSession.astream()`.
3. **Executor pipeline** — geny-executor runs the 21 stages. Tool calls hit the MCP bridge or local registry.
4. **Logging tap** — every stage emits events into [service/logging/session_logger.py](../backend/service/logging/session_logger.py). Every tool call is dispatched by Stage 10 whichever provider answers, so one tap covers them all.
5. **SSE fan-out** — the session logger streams structured events to the frontend over SSE.
6. **Frontend render** — [frontend/src/components/execution/LogEntryCard.tsx](../frontend/src/components/execution/LogEntryCard.tsx) maps each event to a card. Errors look up `executor.<code>` translations for human-friendly text.

## Provider abstraction

Five LLM providers are supported through executor's `CredentialBundle` API:

| Provider          | Streaming | Native tools | MCP        | Notes                                |
| ----------------- | --------- | ------------ | ---------- | ------------------------------------ |
| anthropic         | yes       | yes          | via bridge | Claude API direct                    |
| openai            | yes       | yes          | via bridge | OpenAI + Azure-compatible            |
| google            | yes       | yes          | via bridge | Gemini API                           |
| vllm              | yes       | partial      | via bridge | Self-hosted OpenAI-compatible        |
| geny_router       | yes       | yes          | via bridge | The session's account route — picks which of the below answers |
| geny_claude_code  | yes       | yes          | via bridge | `claude -p --tools ""` — the binary as a pure token generator |
| geny_codex        | yes       | yes          | via bridge | A ChatGPT plan over the Responses API |

Credentials flow:
- User enters keys in the Settings UI → [service/settings/](../backend/service/settings/)
- [service/credentials/install.py](../backend/service/credentials/install.py) materializes them into a `CredentialBundle`
- Bundle is attached to the session manifest; executor stages 4–6 consume it

See [providers.md](providers.md) for per-provider setup.

## Manifest-driven environments

Geny does not hardcode pipeline shape. Each session resolves an `EnvironmentManifest` — a JSON-serializable description of stages, tools, MCP servers, hooks, and policies.

- Templates live in [service/environment/templates.py](../backend/service/environment/templates.py)
- Schemas live in [service/environment/schemas.py](../backend/service/environment/schemas.py)
- Frontend editor: [frontend/src/components/environment/JsonSchemaForm.tsx](../frontend/src/components/environment/JsonSchemaForm.tsx)
- Default manifest for VTuber / Sub-Worker: [service/executor/default_manifest.py](../backend/service/executor/default_manifest.py)

See [environments.md](environments.md) for the editor and template authoring.

## Tool plane

Two tool kinds, unified through MCP:

- **Native MCP servers** — registered through [service/mcp_loader.py](../backend/service/mcp_loader.py). Loaded per-session; tools become `mcp__<server>__<tool>` in the LLM's tool list.
- **In-process Python tools** — declared via [service/tool_loader.py](../backend/service/tool_loader.py). Wrapped as a virtual MCP server (`mcp__geny`) so the LLM sees them through the same surface.

There is one tool surface and one dispatcher. A provider is a model: it asks for a tool, Stage 10 runs it. The per-session MCP bridge that used to hand this registry to a CLI running its own loop was removed with that provider (executor 2.68.0).

## Persistence

- **Sessions and logs** — SQLite by default, configurable via env. Schema in [backend/service/database/](../backend/service/database/).
- **Memory** — long-term recall lives in [service/memory/](../backend/service/memory/). Hooked into executor's memory stages.
- **Artifacts** — [service/shared_folder/](../backend/service/shared_folder/) gives Sub-Worker a scratch directory the VTuber can read.

## Error code pipeline

Errors flow from executor → backend → frontend with a stable string code:

1. Executor raises `GenyExecutorError` subclass with `code` field (e.g. `exec.cli.auth_failed`)
2. `service/executor/agent_session.py:_extract_executor_error_meta` extracts code + exception type
3. `SessionLogger.log_stage_error / log_graph_error / log_response` attach `error_code` + `exception_type` to the SSE event
4. `SessionInfo.error_code` persists the code on the session record
5. Frontend `LogEntryCard` looks up `executor.<code_with_underscores>` in i18n

See [error_codes.md](error_codes.md) for the full code list and i18n mapping.

## Where to dig next

- New backend feature → start in `backend/service/` next to the most similar existing module
- New executor stage or provider → upstream to [geny-executor](https://github.com/CocoRoF/geny-executor), then bump the version in `backend/pyproject.toml`
- New UI surface → [frontend/src/components/](../frontend/src/components/) by domain
- Avatar / 2D editor work → standalone submodule, see [geny-avatar](../geny-avatar/)
