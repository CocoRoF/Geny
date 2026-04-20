# Analysis 02 — "Default ENV per role" design gap

The user's hypothesis, verbatim:

> 기본적으로 VTuber와 기본적인 WORKER를 위한 기본 ENV 가 존재해야하고,
> 그것이 개별적으로 할당되어야 하는데 아마 제대로 안 되면서 이런 현상이
> 발생할 수도 있어.

In other words: *there should be a default environment manifest for
VTuber and for the baseline Worker; each role should be
individually assigned to its own default; the missing assignment
may be why the current failure happens.*

This is a real gap in the architecture — but it is **not** the
cause of today's `news_search` failure (Bug A from analysis/01 is).
This document is about the gap itself, because closing it also
closes the non-env_id `_build_pipeline` cutover that 20260420_2/PR8
deliberately deferred, and it improves the user story for
role-based sessions.

---

## What is configured per role today

Two configuration axes, handled by two different subsystems:

### Axis 1: Tool whitelist — already role-driven

File: `backend/service/tool_preset/templates.py`, lines 13-74.

```python
def create_vtuber_tools_preset() -> ToolPresetDefinition:
    return ToolPresetDefinition(
        id="template-vtuber-tools",
        name="VTuber Tools",
        ...
        custom_tools=["web_search", "news_search", "web_fetch"],
        mcp_servers=[],
        is_template=True,
        template_name="vtuber-tools",
    )

ROLE_DEFAULT_PRESET: dict[str, str] = {
    "worker": "template-all-tools",
    "developer": "template-all-tools",
    "researcher": "template-all-tools",
    "planner": "template-all-tools",
    "vtuber": "template-vtuber-tools",
}
```

`agent_session_manager.py:343-351` looks this up per request:

```python
preset_id = request.tool_preset_id
if not preset_id:
    role_key = (request.role.value if request.role else "worker").lower()
    preset_id = ROLE_DEFAULT_PRESET.get(role_key, "template-all-tools")
```

So today **tool preset** is correctly assigned per role. A VTuber
session without an explicit `tool_preset_id` *does* land on
`template-vtuber-tools` (three tools whitelisted). This part works.

### Axis 2: Stage chain / preset — hardcoded per role, not discoverable

File: `backend/service/langgraph/agent_session.py`, lines 685-752.

```python
# ── Determine preset: vtuber or default ──
is_vtuber = self._role == SessionRole.VTUBER
self._preset_name = "vtuber" if is_vtuber else "default"
...
if is_vtuber:
    self._pipeline = GenyPresets.vtuber(
        api_key=api_key,
        memory_manager=self._memory_manager,
        model=model,
        persona_prompt=system_prompt,
        curated_knowledge_manager=curated_km,
        llm_reflect=llm_reflect,
        tools=tools,
        tool_context=tool_context,
    )
else:
    max_turns = self._max_iterations or 30
    self._pipeline = GenyPresets.worker_adaptive(
        api_key=api_key,
        memory_manager=self._memory_manager,
        ...
    )
```

The **stage chain** (what stages run, in what order, with what
strategies) is selected by `role == VTUBER ? GenyPresets.vtuber :
GenyPresets.worker_adaptive`. That mapping:

- is **hardcoded** inside `_build_pipeline`, not expressed as data;
- does **not** go through `EnvironmentManifest` / env_id at all;
- is **invisible** to any env_id consumer (the UI environment
  editor, the manifest store, the diff tool).

When the user says "there should be a default ENV per role", this
is the axis they're pointing at. The *tool whitelist* has a
role-default mapping; the *stage chain* does not.

---

## What env_id solves — and what it does not

The 20260420_2 cycle (PRs #137–#141) made `env_id` a real first-class
concept:

- `EnvironmentManifest` stores `stages: list[StageManifestEntry]`,
  `tools: ToolsSnapshot` (with `external: list[str]` whitelist), and
  a `preset` string.
- `Pipeline.from_manifest_async` assembles the stages, attaches MCP
  servers, registers provider-backed tools, and returns a pipeline.
- `ROLE_DEFAULT_PRESET` (tool-preset side) already exists.

What **does not** exist yet:

- A `ROLE_DEFAULT_MANIFEST` (or equivalent) mapping role → manifest.
- A bootstrapper that seeds default manifests for each role on
  first boot.
- A `GenyPresets` → `EnvironmentManifest` converter that can turn
  the hardcoded `vtuber` / `worker_adaptive` presets into the
  manifest shape, so env_id and no-env_id paths collapse into one.

That last point was explicitly deferred in
`dev_docs/20260420_2/progress/08_cutover_env_pipeline.md`:
`_build_pipeline` was kept for the no-env_id path because
`GenyPresets.vtuber` bakes runtime objects (memory_manager,
llm_reflect, curated_knowledge_manager) into stage constructors,
while `from_manifest_async` needs declarative stages plus a
post-construction attach helper the executor does not yet expose.

---

## Does the "missing default env" cause today's failure?

**No.** Today's failure is deterministic whether env_id is set or
not:

| Session shape            | Path taken              | Adapter used        | Bug A fires? |
|--------------------------|-------------------------|---------------------|--------------|
| VTuber, no env_id        | `_build_pipeline`       | `_GenyToolAdapter`  | Yes          |
| VTuber, with env_id      | `instantiate_pipeline`  | `_GenyToolAdapter`  | Yes          |
| Worker, no env_id        | `_build_pipeline`       | `_GenyToolAdapter`  | Yes (if the tool lacks `session_id`) |
| Worker, with env_id      | `instantiate_pipeline`  | `_GenyToolAdapter`  | Yes (same)   |

All four paths go through the same `_GenyToolAdapter.execute`. So
closing the env gap does not make the failure go away — Bug A has
to be fixed on the adapter layer regardless.

That said, closing the env gap is still *valuable*, because:

1. It removes the two-path divergence (env_id vs `_build_pipeline`).
   Today if a bug exists in one path it may or may not exist in
   the other; a single path makes the surface smaller.
2. It lets the user customize the stage chain per role without
   editing `agent_session.py`. Right now "VTuber with a longer
   memory window" requires a code change, not a config change.
3. It makes role defaults *inspectable* — a manifest on disk
   beats a conditional in Python for diffing, review, and audit.

---

## Relationship to the tool-preset template system

Tool presets are templates installed at boot
(`install_templates` in `templates.py:49-63`) into the
`ToolPresetStore`. They are persisted, editable, and referenceable
by ID.

Default environments should follow the **same pattern**:

- `install_environment_templates(store)` — seeds
  `template-vtuber-env` and `template-worker-env` on first boot.
- `ROLE_DEFAULT_ENV_ID: dict[str, str]` — role → env_id mapping.
- When `agent_session_manager.create_session` runs and `env_id` is
  absent, resolve it from role just like tool_preset is resolved.

This is the shape plan/02 proposes. Two design sub-choices there:

- **Seed-on-boot**: literally write
  `~/.geny/environments/template-vtuber-env.json` (or DB row) at
  startup, exactly the way the tool-preset templates are seeded.
  Pro: mirrors existing pattern; cons: materialized config that can
  drift from code.
- **On-the-fly**: materialize a manifest at session-creation time by
  calling `GenyPresets.vtuber_manifest()` / `worker_adaptive_manifest()`
  (new helpers that return `EnvironmentManifest` instead of a
  pipeline). Pro: single source of truth (the preset functions);
  cons: no inspection / diff story unless we also add a `freeze`
  command.

Plan/02 recommends **on-the-fly + optional freeze**: the role
default is always computed from the preset function (so there is
no drift), but any user can run "freeze default to manifest" to
materialize an editable copy. This also solves the deferred PR8
problem because the same helper is what `_build_pipeline` would
now delegate to.

---

## Summary

- "Default env per role" is a real missing feature, but it is
  **orthogonal** to the current `news_search` failure.
- The tool-preset system already does the equivalent thing one
  layer down (tool whitelist per role) and provides a clean
  pattern to copy.
- Closing this gap also closes the deferred 20260420_2/PR8
  non-env_id cutover, because both want the same primitive:
  `GenyPresets` → `EnvironmentManifest`.
- Priority order: ship plan/01 (fix the adapter + the logger bug)
  first; plan/02 (default env per role) is a follow-on that the
  user can reasonably defer without losing today's VTuber session.
