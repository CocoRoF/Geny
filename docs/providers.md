# Providers

Geny reaches its models through **accounts**. An account is one login or one key; a session's **route** is an ordered list of them, and `geny_router` is the provider every environment names. Which account answers a turn is the route's business, not the environment's — so changing model never costs a session its tools, persona or permission policy.

This page covers what each backend needs and the trade-offs.

| Provider          | Best for                                | Streaming | Native tools | MCP            | Key requirement                            |
| ----------------- | --------------------------------------- | --------- | ------------ | -------------- | ------------------------------------------ |
| anthropic         | Default for Claude users                | yes       | yes          | via bridge     | `ANTHROPIC_API_KEY`                        |
| openai            | OpenAI / Azure / OpenAI-compatible APIs | yes       | yes          | via bridge     | `OPENAI_API_KEY` (+ optional base URL)     |
| google            | Gemini family                           | yes       | yes          | via bridge     | `GOOGLE_API_KEY`                           |
| vllm              | Self-hosted OSS models                  | yes       | partial      | via bridge     | OpenAI-compatible endpoint URL             |
| geny_claude_code  | A Claude Code login (Pro/Max, setup-token, key) | yes | yes | host-attached | `claude` installed; sign in per account |
| geny_codex        | A ChatGPT plan (Plus/Pro/Business)      | yes       | yes          | host-attached  | sign in per account (no `codex` binary)    |

Every one of them is a **model** and nothing more. Claude Code and Codex ship their own agent loops; Geny does not use them. It drives both as pure token generators and runs the tools itself — same 21 stages, same permission ladder, same memory, same workspace, whichever account answers. That is what lets one conversation move between a Claude subscription, a second Claude login and a ChatGPT plan without losing anything.

## Where to configure

All provider credentials and defaults live in the Settings UI:

- Sidebar → Settings → **Providers** tab
- Each row has: name, model, credential fields, default-on flag
- Saved values are stored encrypted via [backend/service/auth/](../backend/service/auth/) and resolved at session start by [backend/service/credentials/install.py](../backend/service/credentials/install.py)

You can also set provider keys as environment variables when starting the backend. See [environments.md](environments.md) for the env precedence rules.

## anthropic

Direct Claude API integration.

**Required**
- `ANTHROPIC_API_KEY`

**Optional**
- Model override per session (defaults to `claude-sonnet-4-6` for VTuber, `claude-opus-4-7` for Sub-Worker)
- Custom base URL for proxy / regional endpoints

**Notes**
- Best end-to-end streaming and tool use latency
- 1M context window on Opus 4.7 (use `claude-opus-4-7[1m]` model id)

## openai

OpenAI direct, Azure OpenAI, and any OpenAI-compatible endpoint.

**Required**
- `OPENAI_API_KEY`

**Optional**
- `OPENAI_BASE_URL` — defaults to `https://api.openai.com/v1`. Set to your Azure endpoint or local proxy.
- `OPENAI_ORG_ID` for org-scoped accounts

**Notes**
- Tool use uses the JSON-mode function calling path
- Reasoning models (`o1`, `o3`) supported; executor handles their non-streaming reasoning blocks

## google

Gemini API direct.

**Required**
- `GOOGLE_API_KEY` (from Google AI Studio)

**Notes**
- Multi-turn tool use supported
- Use `gemini-2.5-pro` for long-context tasks, `gemini-2.5-flash` for cheap/fast Sub-Worker spawns

## vllm

Self-hosted OpenAI-compatible inference server.

**Required**
- Endpoint URL pointing to a running vLLM (or compatible) server
- Model name as served by the endpoint

**Optional**
- API key if your endpoint enforces one
- Custom timeout for slow self-hosted models

**Caveats**
- Tool calling depends on the served model's training. Some OSS models emit malformed JSON for tool calls — executor's parser tolerates common variants but not all.
- Streaming JSON parsing assumes OpenAI-format SSE chunks.

## geny_claude_code

Drives the locally installed [Claude Code](https://claude.com/claude-code) binary as a **token generator**, not as an agent.

**Required**
- `claude` installed and on PATH (the image installs it; Settings → LLM keeps it updated)
- Each account signs in separately — Settings → Models → add a Claude Code account

**How it works**
- `claude -p --tools "" --strict-mcp-config --mcp-config {} --max-turns 1 --system-prompt-file …`: no built-in tools, no MCP of its own, one generation, never an agent loop
- Geny's tool catalogue rides in the system prompt; the model asks for a tool as a `<tool_call>` block, which becomes a canonical `tool_use` and is dispatched by Stage 10
- Each account owns a private `CLAUDE_CONFIG_DIR`, so any number of logins coexist without touching the host's own `~/.claude`

**Caveats**
- Subprocess overhead — slower first-token latency than a direct API
- `temperature`, `top_p`, `top_k`, `stop_sequences`, `max_tokens` and `tool_choice` are declared drops: `claude -p` takes none of them, and you get an `llm_client.field_dropped` event rather than a setting that silently does nothing

## geny_codex

A ChatGPT plan over the Responses API — there is no `codex` binary to install.

**Required**
- Sign in per account (Settings → Models → add a Codex account, then the device flow)

**Caveats**
- The refresh token is single-use. Geny persists each rotation; an out-of-band copy of the tokens will lock the account out
- Usage limits are the plan's, and a 429 is what the route fails over from

## Picking a model per session

A session's route is its own. In the UI:

1. Open the agent
2. Model → pick an account (or reorder the route)
3. The next turn uses it — mid-conversation, with no restart

For programmatic control, see the request body in [backend/api/agent_session.py](../backend/api/agent_session.py).

## Error codes by provider

Each provider raises distinct executor error codes. Common ones:

| Code                       | Provider(s)  | Meaning                                  |
| -------------------------- | ------------ | ---------------------------------------- |
| `exec.api.auth_failed`     | all          | Invalid or missing key                   |
| `exec.api.rate_limited`    | all          | 429 from upstream                        |
| `exec.api.timeout`         | all          | Upstream request timed out               |
| `exec.api.retry_exhausted` | all          | All retries failed                       |
| `exec.cli.binary_not_found`| geny_claude_code | `claude` not on PATH                    |
| `exec.cli.auth_failed`     | geny_claude_code | That account is not signed in           |
| `exec.cli.timeout`         | geny_claude_code | The binary did not answer in time       |

See [error_codes.md](error_codes.md) for the full list.
