# Progress 05 — `build_default_manifest.stages` populated

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **PR 3** / Step 1 |
| Master ref | `plan/00_overview.md` → **Phase 2 / PR 11** |
| Geny PR | [#150](https://github.com/CocoRoF/Geny/pull/150) |
| Geny merge commit | `1f080e5` on `main` |
| Executor prereq | [CocoRoF/geny-executor#31](https://github.com/CocoRoF/geny-executor/pull/31) / [v0.25.0](https://github.com/CocoRoF/geny-executor/releases/tag/v0.25.0) |
| Status | **Merged** |

---

## What shipped

### `backend/service/langgraph/default_manifest.py`

`build_default_manifest.stages` was a `[]` placeholder with a
"filled in by a later PR" comment. It is now filled.

Two module-level helpers emit the typed `StageManifestEntry` lists:

- **`_worker_adaptive_stage_entries(...)`** — 13 entries.
  Orders: `1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 15, 16`.
  Matches `GenyPresets.worker_adaptive` one-to-one.
- **`_vtuber_stage_entries(...)`** — 12 entries.
  Orders: `1, 2, 3, 4, 5, 6, 7, 9, 12, 13, 15, 16`.
  Same as worker_adaptive minus Stage 8 (Think). Matches
  `GenyPresets.vtuber`.

The `_build_stage_entries(preset)` dispatcher is called from
`build_default_manifest(...)`. `"default"` and `"worker_easy"` both
resolve to the `worker_adaptive` layout — `worker_easy`'s
single-turn behaviour is expressed by the session layer setting
`max_turns=1` on the loop at attach time, not by a separate
manifest variant.

### Declarative slot picks per stage

| Stage | Slot | worker_adaptive | vtuber |
|:---:|---|---|---|
| 1 Input | validator / normalizer | default / default | default / default |
| 2 Context | strategy / compactor / retriever | simple_load / truncate / **null**¹ | simple_load / truncate / **null**¹ |
| 3 System | builder | composable² | composable² |
| 4 Guard | — | — | — |
| 5 Cache | strategy | aggressive_cache | system_cache |
| 6 API | provider / retry | anthropic / exponential_backoff | anthropic / exponential_backoff |
| 7 Token | tracker / calculator | default / anthropic_pricing | default / anthropic_pricing |
| 8 Think | processor | extract_and_store | *(stage absent)* |
| 9 Parse | parser / signal_detector | default / regex | default / regex |
| 12 Evaluate | strategy / scorer | binary_classify³ / no_scorer | signal_based / no_scorer |
| 13 Loop | controller | standard (cfg `max_turns=30`) | standard (cfg `max_turns=10`) |
| 15 Memory | strategy / persistence | **append_only¹ / null¹** | **append_only¹ / null¹** |
| 16 Yield | formatter | default | default |

¹ Runtime-swapped. Replaced by `GenyMemoryRetriever` /
`GenyMemoryStrategy` / `GenyPersistence` via
`Pipeline.attach_runtime(...)` at session start.
² `builder="composable"` name matches preset, but the block list
(PersonaBlock + DateTimeBlock + MemoryContextBlock) is runtime
state and is not encoded in the manifest. A future PR expands
`attach_runtime` to accept a system builder.
³ `strategies_configs.strategy = {easy_max_turns: 1,
not_easy_max_turns: 30}` — encoded declaratively thanks to the new
`BinaryClassifyEvaluation.configure(...)` from executor v0.25.0.

### Stage 10 (Tool) is intentionally absent

`GenyPresets.*` builders call `.with_tools(registry=...)`
conditionally on a `tools` kwarg. The manifest does not carry
Stage 10 declaratively — instead,
`Pipeline.from_manifest_async(manifest, adhoc_providers=[...])`
builds a registry from `manifest.tools.external` +
`manifest.tools.mcp_servers` + `adhoc_providers`, and registers
Stage 10 when that registry is non-empty. This keeps env-level
tool composition in one place (the manifest's `tools` block) and
avoids the "do I need a tool stage?" question leaking into two
places.

### Executor pin

- `backend/pyproject.toml`: `>=0.24.0,<0.25.0` → `>=0.25.0,<0.26.0`
- `backend/requirements.txt`: same

v0.25.0 is required because `binary_classify` was not registered
in the default `EvaluateStage` strategy slot before that release —
serializing `worker_adaptive` through an `EnvironmentManifest`
previously silently degraded it to `signal_based` evaluation.

## Parity smoke test

Written as `/tmp/test_manifest_parity.py` (not checked in — Geny
has no committed test tree yet). Executed against the v0.25.0
executor venv. 17 assertions, all passing:

| # | Preset | Assertion |
|---|--------|-----------|
| 1 | worker_adaptive | stage orders `[1,2,3,4,5,6,7,8,9,12,13,15,16]` |
| 2 | worker_adaptive | all artifact names match preset |
| 3 | worker_adaptive | all strategy slot names match (excluding the 3 runtime-swapped slots) |
| 4 | worker_adaptive | `loop.max_turns == 30` |
| 5 | worker_adaptive | live Stage-12 strategy is `BinaryClassifyEvaluation` with `easy_max_turns=1`, `not_easy_max_turns=30` |
| 6 | vtuber | stage orders `[1,2,3,4,5,6,7,9,12,13,15,16]` (no Stage 8) |
| 7 | vtuber | all artifact names match preset |
| 8 | vtuber | all strategy slot names match |
| 9 | vtuber | `loop.max_turns == 10` |
| 10 | — | `known_presets()` returns `['default', 'vtuber', 'worker_adaptive', 'worker_easy']` |
| 11 | — | `"default"` alias collapses to `worker_adaptive` stage chain |
| 12 | — | `"default"`.base_preset == `"worker_adaptive"` |
| 13 | — | unknown preset raises `ValueError` with helpful message |
| 14 | — | `tools.built_in == ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep']` |
| 15 | — | `tools.external` plumbs through from kwarg |
| 16 | worker_adaptive | `Pipeline.from_manifest(...)` succeeds (strict=False) |
| 17 | vtuber | `Pipeline.from_manifest(...)` succeeds (strict=False) |

Run command:

```
$ /home/geny-workspace/geny-executor/.venv/bin/python \
    /tmp/test_manifest_parity.py
...
ALL PARITY CHECKS PASSED
```

## Known deferred gaps (not blockers for PR10)

These cannot be expressed in the declarative manifest and are
handled by runtime attach code in a later PR:

1. **Stage 3 composable builder blocks** — `ComposablePromptBuilder(
   blocks=[PersonaBlock(prompt), DateTimeBlock(), MemoryContextBlock()])`
   cannot be serialised. Manifest-restore produces a default empty
   `ComposablePromptBuilder()`. A later PR will expand
   `attach_runtime` with a `system_builder=` kwarg. Until that PR
   lands, `AgentSession._build_pipeline` continues to go through
   `GenyPresets.*` (PR 16 in master plan does the swap).
2. **Runtime callbacks not yet in attach_runtime** — `llm_reflect`
   and `llm_gate` are today Geny-constructed at session start and
   passed into `GenyMemoryStrategy` / `GenyMemoryRetriever`. Since
   `attach_runtime` takes the *already-constructed* strategy
   objects, this is a non-issue: Geny builds the objects with the
   callbacks, then hands them in.

## Phase 2 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 7 | Executor: `Pipeline.attach_runtime` | executor#30 / v0.24.0 | Done |
| 8 | Progress doc for PR 7 | #149 (bundled) | Done |
| 9 | Geny: pin bump to 0.24.0 | #148 | Done |
| 10 | Progress doc for PR 9 | #149 (bundled) | Done |
| 10a | **Executor: register `binary_classify`** (added to plan during PR10) | executor#31 / v0.25.0 | Done |
| 11 | Geny: populate `build_default_manifest.stages` + pin to 0.25.0 | #150 | Done |
| 12 | Progress doc for PR 11 | *this doc* | Done |
| 13 | Geny: seed `install_environment_templates` + `ROLE_DEFAULT_ENV_ID` | — | **Next** |
| 14 | Progress doc for PR 13 | — | pending |
| 15 | Geny: `AgentSessionManager` always resolves `env_id` | — | pending |
| 16 | Progress doc for PR 15 | — | pending |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | — | pending |

Note on scope drift: PR10a (executor v0.25.0 register
`binary_classify`) was added during this PR when we discovered
that manifest-restore for `worker_adaptive` silently degraded to
`signal_based` without a registry entry. The plan did not
originally enumerate this release — it was implied by
"v0.24.0 populates manifest stage support for worker_adaptive /
vtuber" but that line referred to the attach_runtime helper, not
the evaluator registry. The gap was real and v0.25.0 closes it.

## Next

Master-plan PR 13: seed `install_environment_templates` with
`create_worker_env()` / `create_vtuber_env()` and add
`ROLE_DEFAULT_ENV_ID` mapping. This is what gives every role a
concrete env_id to resolve to so the non-env_id branch in
`AgentSessionManager` can be deleted (PR 15).
