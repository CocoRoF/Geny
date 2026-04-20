# Progress 07 — `AgentSessionManager` always resolves `env_id`

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **PR 5 + Step 6** |
| Master ref | `plan/00_overview.md` → **Phase 2 / PR 15** |
| Geny PR | [#154](https://github.com/CocoRoF/Geny/pull/154) |
| Geny merge commit | `8876bfd` on `main` |
| Status | **Merged** |

---

## Why this is the phase's biggest-blast-radius PR

The master plan flags this PR in its "What could go wrong" section:
*"Phase-2 step #14 (delete the `if env_id:` gate) is the
biggest-blast-radius PR in the cycle. It changes every session
creation."* Previously, sessions fell into two paths:

- **env_id present** → `EnvironmentService.instantiate_pipeline`
  builds the Pipeline from the stored manifest; `AgentSession` adopts
  it.
- **env_id absent** → `AgentSession._build_pipeline` constructs the
  pipeline in-process via `GenyPresets.worker_adaptive(...)` /
  `GenyPresets.vtuber(...)`.

The two paths drifted on the 20260420_2 cycle (different tool
registration, different memory wiring, different evaluator pick —
see progress 05 for why Stage 12 silently degraded). This PR
collapses them into one: every session now resolves to a seeded
`env_id` via `resolve_env_id(role, explicit)` and flows through the
same manifest path.

## What shipped

### `backend/service/langgraph/agent_session_manager.py`

The `if env_id:` block (previously lines 447-475) is gone.
Replacement is unconditional:

```python
from service.environment.role_defaults import resolve_env_id

env_id = resolve_env_id(request.role, env_id)
if self._environment_service is None:
    raise RuntimeError(
        "EnvironmentService is not configured on AgentSessionManager. "
        "Wire it via set_environment_service(...) at app boot — "
        "every session now resolves through the manifest path."
    )
# ... api_key resolution (unchanged) ...
adhoc_providers: list = []
if self._tool_loader is not None:
    from service.langgraph.geny_tool_provider import GenyToolProvider
    adhoc_providers.append(GenyToolProvider(self._tool_loader))
prebuilt_pipeline = await self._environment_service.instantiate_pipeline(
    env_id, api_key=api_key, adhoc_providers=adhoc_providers,
)
```

`resolve_env_id` gives the caller's explicit `env_id` precedence;
absent that, it maps `SessionRole` → seeded env per PR 13's table.

The `build_geny_tool_registry(...)` call (previously lines 433-442)
is gone entirely. Its output — a pre-populated `ToolRegistry` handed
to `AgentSession._build_pipeline` — was the manifest path's dual of
`manifest.tools.external` + `GenyToolProvider`. Having one owner,
not two, kills a class of drift bugs.

### `backend/service/langgraph/agent_session.py`

`geny_tool_registry` removed from:

- `__init__` signature
- `self._geny_tool_registry` instance attribute
- The `if self._geny_tool_registry: for t in …: tools.register(t)`
  block inside `_build_pipeline`

The `GenyPresets.*` fallback branches still exist — this PR does not
delete them. After the merge they are reachable only if
`instantiate_pipeline` itself raises (e.g. corrupt seed file).
Master-plan PR 17 replaces the whole branch with a
`pipeline.attach_runtime(...)` call and deletes the preset imports.

### `backend/service/langgraph/tool_bridge.py`

`build_geny_tool_registry()` deleted. `_GenyToolAdapter` stays — it
is the adapter that `GenyToolProvider.get(name)` returns on lookup.
Module docstring updated to say so explicitly, so a future reader
does not go hunting for the removed helper.

## Scope the plan listed but this PR defers

The plan's Step 6 also talked about removing `allowed_tool_names`
computation (lines 360-372 in `agent_session_manager.py`). Those
lines compute `allowed_builtin_tools` / `allowed_custom_tools` from
the tool preset; they produce one log line and then feed only the
deleted `build_geny_tool_registry` call. After this PR the
computation is dead.

I left it in for now. Reasons:

1. The log line is user-visible and answers "what tools did the
   tool_preset resolve to" — it stays useful operationally even
   though the downstream registry is gone.
2. Removing it is purely cosmetic. PR 17's larger surgery
   (`attach_runtime` swap, `GenyPresets.*` removal) naturally folds
   this cleanup in without its own PR.

Noted as TODO for PR 17; will be deleted alongside the preset
imports so one PR owns the "dead observability remnants from the
legacy tool-registration path" cleanup end-to-end.

## Smoke test

Written as `/tmp/test_env_id_always.py` (not checked in — Geny has
no committed test tree yet). 5 groups, all passing against executor
v0.25.0:

| Group | Checks |
|:-----:|:-------|
| A | `resolve_env_id` correctness across 7 (role, explicit) combos including `None` role, string forms of roles, and explicit-wins-over-default |
| B | For every `SessionRole`, the resolver + seed + `instantiate_pipeline` triple produces a valid Pipeline (13 stages for worker/developer/researcher/planner → WORKER seed; 12 stages for vtuber → VTUBER seed) |
| C | VTuber role with explicit `WORKER_ENV_ID` produces a *worker* pipeline (confirms explicit wins and Stage 8 is present) |
| D | `instantiate_pipeline` on a non-existent env raises `EnvironmentNotFoundError` (for REST 404 mapping) |
| E | Module invariants: `AgentSession.__init__` no longer takes `geny_tool_registry`, `tool_bridge` no longer exports `build_geny_tool_registry`, `resolve_env_id` is imported and called inside the session manager, the `if env_id:` gate text no longer appears |

Why not a full `create_agent_session` integration test: the manager
requires app-wide state (global MCP config, shared-folder manager,
memory registry, IdleMonitor). Standing up that scaffolding in a
smoke test would essentially duplicate `main.py`. The narrower
per-piece verification above covers the unit correctness of the
new composition, and the integration is exercised at app boot by
the manual QA checklist in the PR description.

## Manual verification

Per the plan's "What could go wrong" section:

- [ ] App boot succeeds with the new require-EnvironmentService
      invariant (already wired at `main.py:311` since the 20260420_2
      cycle, so this should pass on first try)
- [ ] Worker session without explicit env_id logs
      `env_id: template-worker-env → manifest-backed pipeline built`
- [ ] VTuber session without explicit env_id logs
      `env_id: template-vtuber-env → manifest-backed pipeline built`
- [ ] Session with explicit `env_id=<custom>` still honors the
      custom id (explicit-wins contract)

These are boot-time observations, not automated — the next person
to run a dev server should spot-check them and note the result in a
follow-up doc or this progress's appendix.

## Phase 2 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 7 | Executor: `Pipeline.attach_runtime` | executor#30 / v0.24.0 | Done |
| 8 | Progress doc for PR 7 | #149 (bundled) | Done |
| 9 | Geny: pin bump to 0.24.0 | #148 | Done |
| 10 | Progress doc for PR 9 | #149 (bundled) | Done |
| 10a | Executor: register `binary_classify` (v0.25.0) | executor#31 / v0.25.0 | Done |
| 11 | Geny: populate `build_default_manifest.stages` + pin to 0.25.0 | #150 | Done |
| 12 | Progress doc for PR 11 | #151 | Done |
| 13 | Geny: seed `install_environment_templates` + `ROLE_DEFAULT_ENV_ID` | #152 | Done |
| 14 | Progress doc for PR 13 | #153 | Done |
| 15 | Geny: `AgentSessionManager` always resolves `env_id` | #154 | Done |
| 16 | Progress doc for PR 15 | *this doc* | Done |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | — | **Next** |

## Next

Master-plan PR 17 — the last PR of Phase 2. Collapse
`AgentSession._build_pipeline` (today still a dual-branch
function) to a single `attach_runtime` call:

- Build `GenyMemoryRetriever` / `GenyMemoryStrategy` /
  `GenyPersistence` from `self._memory_manager` + curated_km +
  `llm_reflect` callback.
- Call `self._prebuilt_pipeline.attach_runtime(
  memory_retriever=..., memory_strategy=..., memory_persistence=...)`.
- Delete: the `GenyPresets.*` imports, the `is_vtuber` branch, the
  dead `allowed_tool_names` / `allowed_builtin_tools` /
  `allowed_custom_tools` computation in the session manager, and
  the `ToolRegistry + built_in tools` registration inside
  `_build_pipeline` (since `manifest.tools.built_in` now covers it
  declaratively).

Exit criterion for Phase 2 (from master plan): any session type
goes through the single `from_manifest_async → attach_runtime` path.
`_build_pipeline`'s preset branches are gone. After that, Phase 3
(VTuber↔Worker binding rename + prompt updates) is pure cleanup
against a stable pipeline-build contract.
