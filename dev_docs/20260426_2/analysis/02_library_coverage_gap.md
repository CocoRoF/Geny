# 02 — Library coverage gap (geny-executor surface)

**Date:** 2026-04-26
**Method:** 3 parallel Explore agents — (a) executor full surface, (b) Geny extension surface, (c) Library tab actual exposure. Direct-verified the high-impact claims.

## Tier 0 — 🔴 BUG: Hook UI non-functional

See `01_hook_schema_bug.md`. Schema mismatch means hooks never fire even with the env gate open. **Fix before anything else.**

## Tier 1 — Pipeline / model config not editable

`Builder` tab edits `manifest.stages[]` but `manifest.pipeline` and `manifest.model` are read-only. To change `max_iterations` or `temperature` the operator must use `ImportManifestModal` and replace the entire JSON.

| Manifest path | Field | Default | Currently editable |
|---|---|---|---|
| `pipeline.max_iterations` | int | 50 | ❌ |
| `pipeline.cost_budget_usd` | Optional[float] | None | ❌ |
| `pipeline.context_window_budget` | int | 200000 | ❌ |
| `pipeline.single_turn` | bool | False | ❌ |
| `pipeline.metadata` | Dict | {} | ❌ |
| `model.model` | str | "claude-sonnet-4-…" | ❌ (CreateSessionModal only) |
| `model.max_tokens` | int | 8192 | ❌ |
| `model.temperature` | float | 0.0 | ❌ |
| `model.top_p` / `top_k` / `stop_sequences` | various | None | ❌ |
| `model.thinking_enabled` | bool | False | ❌ |
| `model.thinking_budget_tokens` | int | 10000 | ❌ |
| `model.thinking_type` | enum | "enabled" | ❌ |
| `model.thinking_display` | Optional[enum] | None | ❌ |

## Tier 2 — Per-stage advanced fields

| Manifest path | Builder UI |
|---|---|
| `stages[].active` | ✅ checkbox |
| `stages[].artifact` | ✅ dropdown |
| `stages[].config` | ✅ JSON / schema form |
| `stages[].strategies` | ✅ JSON |
| `stages[].strategy_configs` | ✅ JSON |
| `stages[].chain_order` | ✅ JSON |
| `stages[].model_override` | ❌ not surfaced (executor 1.3.0+) |
| `stages[].tool_binding` | ❌ not surfaced (s10) |

## Tier 3 — Permissions mode picker

`PermissionMode` (DEFAULT / PLAN / AUTO / BYPASS / ACCEPT_EDITS / DONT_ASK) and the Geny advisory↔enforce toggle are env-only:
- `GENY_PERMISSION_MODE` = `advisory | enforce`
- `GENY_PERMISSION_EXEC_MODE` = one of the 6 enum values

PermissionsTab shows only the rule list — no mode control.

## Tier 4 — `manifest.tools` partial

| `manifest.tools` field | Library UI |
|---|---|
| `built_in: List[str]` | ✅ ToolCatalog toggle grid |
| `adhoc: List[Dict]` | ✅ JSON textarea (Builder) |
| `mcp_servers: List[Dict]` | ✅ JSON textarea (Builder) |
| `external: List[str]` | ❌ — but Geny's `GenyToolProvider` actually consumes this list. Without UI, env-driven sessions can't pick which external tools attach. |
| `scope: Dict` | ❌ |
| `global_allowlist / global_blocklist` | ✅ pattern lists (Builder) |

## Tier 5 — Skills / MCP missing fields

**Skills** (`SkillsTab`):
- ❌ `version` (str)
- ❌ `execution_mode` ("inline" | "fork", default "inline")
- ❌ `extras` (Dict — host-specific metadata)

**MCP servers** (`McpServersTab`):
- Raw JSON only — no transport-aware structured form.
- For `transport: "stdio"`: fields `command`, `args`, `env` should be separate inputs.
- For `transport: "http"` / `"sse"`: fields `url`, `headers` should be separate inputs.

## Tier 6 — Geny extensions code-only

| Extension | Configured today via | UI surface |
|---|---|---|
| Memory provider (provider/root/dsn/dialect/scope/timezone) | env vars at boot | ❌ (CreateSessionModal has per-session override only) |
| Memory retriever knobs (`max_inject_chars=80000`, `recent_turns=6`, `enable_vector_search=True`) | hardcoded in `agent_session.py:1376-1381` | ❌ |
| Memory strategy (`enable_reflection=True`) | hardcoded `agent_session.py:1383-1389` | ❌ |
| Curated knowledge manager | code only | ❌ |
| AffectTagEmitter `max_tags_per_turn` | constant | ❌ |
| Notification endpoints | `~/.geny/notifications.json` | ❌ — Admin shows read-only list |
| Send-message channels | code-registered | (only stdout default) |
| Persona block ordering / templates | hardcoded in `service/persona/` | ❌ (character text editable, not block config) |
| Sub-Worker auto-spawn config | hardcoded VTuber-only | ❌ |
| Subagent type registry | code-registered descriptors | (Admin shows read-only list) |

## Tier 7 — Settings sections registry coverage

`install_geny_settings` registers 7 sections accessible via FrameworkSettingsPanel:

> preset, vtuber, hooks, skills, model, telemetry, notifications

**Gaps:**
- `permissions` section NOT registered (controller writes settings.json directly, bypassing the loader's typed access).
- `memory` section NOT registered (env vars only).
- `affect` section NOT registered.

## Coverage scorecard

| Area | Coverage % |
|---|---|
| Stages structure (active / artifact / config / strategies) | ~80% |
| Pipeline-level config | ~10% (read-only display only) |
| Model config | ~5% |
| Permissions | ~70% (rules yes, mode no) |
| Hooks | 🔴 0% (BROKEN — see Tier 0) |
| Skills | ~70% (3 fields missing) |
| MCP servers | ~50% (works via raw JSON; structured form missing) |
| Tools (built_in + adhoc + mcp + lists) | ~70% (external + scope missing) |
| Memory layer | ~10% (env-only, code-only) |
| Notifications | ~30% (file-only) |
| Geny-side extensions (persona / affect / sub-worker) | 0% |

## Sprint plan summary (see `plan/cycle_plan.md` for detail)

**Phase H** (3 PR) — Hook schema rescue.
**Phase P** (2 PR) — Pipeline + Model config in Builder.
**Phase S** (2 PR) — Per-stage model_override + tool_binding.
**Phase R** (1 PR) — Permission mode picker.
**Phase T** (3 PR) — `tools.external` picker, `tools.scope`, MCP structured editor.
**Phase K** (2 PR) — Skills missing fields, permissions section in FrameworkSettings.
**Phase G** (4 PR) — Memory provider UI, memory tuning, affect emitter, notification endpoints CRUD.

Total: ~17 PRs, ordered front-to-back. User directive: "앞에서부터 제대로 하나씩 구현해."
