# Progress 06 — WORKER/VTUBER env seeds + `ROLE_DEFAULT_ENV_ID`

| Field | Value |
|-------|-------|
| Plan ref | `plan/02_default_env_per_role.md` → **PR 4** / Steps 2+3 |
| Master ref | `plan/00_overview.md` → **Phase 2 / PR 12** |
| Geny PR | [#152](https://github.com/CocoRoF/Geny/pull/152) |
| Geny merge commit | `21ff17b` on `main` |
| Status | **Merged** |

---

## What shipped

### `backend/service/environment/templates.py` (new)

Factories + installer mirroring `service/tool_preset/templates.py`.

- **`create_worker_env(external_tool_names)`** — builds a manifest
  via `build_default_manifest(preset="worker_adaptive",
  external_tool_names=...)` and stamps metadata
  `id="template-worker-env"`, `name="Worker Environment"`.
- **`create_vtuber_env()`** — same, but
  `preset="vtuber"`, `id="template-vtuber-env"`, external fixed to
  `["web_search", "news_search", "web_fetch"]` (matches
  `template-vtuber-tools` in tool_preset land).
- **`install_environment_templates(service, *, external_tool_names)`**
  — saves each seed only if its file is absent. Returns the install
  count. Idempotent across reboots; user edits to a seed persist.

Two module-level constants exported: `WORKER_ENV_ID` and
`VTUBER_ENV_ID`.

### `backend/service/environment/role_defaults.py` (new)

```python
ROLE_DEFAULT_ENV_ID: dict[str, str] = {
    SessionRole.WORKER.value:     WORKER_ENV_ID,
    SessionRole.DEVELOPER.value:  WORKER_ENV_ID,
    SessionRole.RESEARCHER.value: WORKER_ENV_ID,
    SessionRole.PLANNER.value:    WORKER_ENV_ID,
    SessionRole.VTUBER.value:     VTUBER_ENV_ID,
}

def resolve_env_id(role, explicit) -> str:
    if explicit:
        return explicit
    if role is None:
        return WORKER_ENV_ID
    role_value = role.value if hasattr(role, "value") else str(role)
    return ROLE_DEFAULT_ENV_ID.get(role_value.lower(), WORKER_ENV_ID)
```

Explicit `env_id` from the request always wins. Unknown / `None` /
empty string roles fall back to the WORKER env — mirrors the
`template-all-tools` fallback in the tool_preset layer.

### `backend/main.py` boot wiring

Install invocation lands right after `EnvironmentService()` is
constructed, before any controllers come online:

```python
from service.environment.templates import install_environment_templates
env_templates_installed = install_environment_templates(
    environment_service,
    external_tool_names=tool_loader.get_custom_names(),
)
logger.info(f"   - Environment templates installed: {env_templates_installed}")
logger.info(f"   - Total environments: {len(environment_service.list_all())}")
```

`tool_loader.get_custom_names()` is already populated by the
preceding `ToolLoader` boot step, so the worker env's `external`
list reflects whatever custom tools the user actually has — no
stale wildcard, no duplicate source of truth.

## Design choices

### Seed on boot, not on first-use

Plan/02 Step 2 called this out explicitly. The materialized seed is
**inspectable**: users can open the environment editor and see what
their worker does. Edits to the seed persist and are picked up on
the next session create. If the user wants factory defaults back,
that is an explicit "Reset environment" UI action (not in this PR;
called out in plan/02 as a non-goal).

### Worker env's `external` = live custom-tool registry

`template-all-tools` uses `custom_tools=["*"]` to mean "every custom
tool". `EnvironmentManifest.tools.external`, however, needs concrete
names. The installer bridges this by enumerating
`tool_loader.get_custom_names()` once at install time. A second boot
with new custom tools will **not** expand the saved worker env —
that is fine because this file is a *user-editable template*, not a
live view. The user can delete the env and let it reseed, or edit
`external` via the environment editor.

### Why `_write_manifest` and not a new public save method

`EnvironmentService._write_manifest` is technically private but
lives in the same package. Wrapping it in a new public method
(`save_manifest`?) would be one more seam to keep in sync across
the service + controllers, and the only caller is this installer.
Revisit if a second host wants to bulk-seed manifests.

## Smoke test

Written as `/tmp/test_env_templates.py` (not checked in — Geny has
no committed test tree yet). 18 assertions across 7 groups, all
passing against executor v0.25.0:

| Group | Checks |
|:-----:|:-------|
| A | `install_environment_templates` on empty storage writes **2** files with the expected ids |
| B | A second install returns `0` (idempotent, files untouched) |
| C | Both seeds reload via `load_manifest`: `base_preset` is `worker_adaptive` / `vtuber`, stage orders are `[1,2,3,4,5,6,7,8,9,12,13,15,16]` / `[1,2,3,4,5,6,7,9,12,13,15,16]`, vtuber external is `["web_search","news_search","web_fetch"]`, worker external carries the custom tool names passed in |
| D | `resolve_env_id(role, "my-custom-env")` returns `"my-custom-env"` for any role |
| E | Each of `{WORKER, DEVELOPER, RESEARCHER, PLANNER, VTUBER}` and their string forms resolve to the documented env id |
| F | `None`, `"weirdo"`, `""` all fall back to `template-worker-env` |
| G | `instantiate_pipeline(...)` builds a live Pipeline from each seed (`strict=False` so the "no AdhocToolProvider" warning on external names is non-fatal) |

Run command:

```
$ /home/geny-workspace/geny-executor/.venv/bin/python \
    /tmp/test_env_templates.py
...
ALL CHECKS PASSED
```

## What's *not* in this PR

- **AgentSessionManager consumption** — `resolve_env_id` is
  imported by nothing in the session manager yet. That switch (and
  the removal of the `if env_id:` gate, plus the
  `geny_tool_registry` plumbing cleanup) is master-plan PR 14.
- **Environment controller route to reset a seed** — called out as
  an explicit non-goal in plan/02. If we want it later it is a
  one-endpoint addition: delete the file and re-run
  `install_environment_templates` on the single env.
- **Custom-tool drift handling** — if the user adds a new custom
  tool after first boot, the saved worker env will not automatically
  pick it up. This matches `ToolPresetStore` semantics (saved
  preset doesn't track registry growth either) and is acceptable
  because the env is user-editable.

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
| 14 | Progress doc for PR 13 | *this doc* | Done |
| 15 | Geny: `AgentSessionManager` always resolves `env_id` | — | **Next** |
| 16 | Progress doc for PR 15 | — | pending |
| 17 | Geny: `AgentSession._build_pipeline` → `attach_runtime` only | — | pending |

## Next

Master-plan PR 15: `AgentSessionManager.create_agent_session`
always routes through
`EnvironmentService.instantiate_pipeline(env_id=resolve_env_id(...))`.
Delete the `if env_id:` gate (today around `agent_session_manager.py`
line 447-475) and strip the `geny_tool_registry` plumbing that the
manifest path makes redundant. This is the biggest-blast-radius PR
of Phase 2 — the master plan's "What could go wrong" section flags
it. Follow-on PR 17 then collapses `AgentSession._build_pipeline`
to an `attach_runtime` call, deleting the `GenyPresets.*` branches.
