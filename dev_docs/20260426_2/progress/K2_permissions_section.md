# K.2 — Permissions section in FrameworkSettings

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — new `PermissionsConfigSection` Pydantic model.
- `backend/service/settings/install.py` — `register_section("permissions", PermissionsConfigSection)` call.

## What it changes

The `permissions` section now has a typed schema registered with the executor's `SettingsLoader`. Knock-on effects:

1. **FrameworkSettingsPanel** lists `permissions` alongside the other sections; operators can edit `mode`, `executor_mode`, and the `rules` array as JSON in one place.
2. **D.2 (cycle 20260426_1) reader map** already had `"permissions": ["service.permission.install"]`; this PR makes that entry consistent — previously the section was unregistered, so the panel never showed it.
3. **R.1's read path** — `_resolve_mode` / `_resolve_executor_mode` now get a `PermissionsConfigSection` from `get_section`, but the `model_dump` coercion in `_settings_section` already handles both raw dict and Pydantic model returns, so no further change is required.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 7) — every other settings section was registered + editable via FrameworkSettingsPanel; `permissions` was the lone outlier. Operators had to use the dedicated PermissionsTab for rule edits, which is fine, but the section's existence was invisible to the broader settings workflow.

## Schema

```python
class PermissionsConfigSection(BaseModel):
    mode: Optional[str] = None             # "advisory" | "enforce"
    executor_mode: Optional[str] = None    # default | plan | auto | bypass | acceptEdits | dontAsk
    rules: List[Dict[str, Any]] = []       # raw rule dicts; PermissionsTab is the typed editor
```

Schema is intentionally permissive — older deployments with hand-written values keep loading. Strict validation lives in `permission_controller` (`_BEHAVIORS` / `_GENY_MODES` / `_EXECUTOR_MODES`) and `service.permission.install`.

## Tests

The known_sections registry test (cycle 20260426_1, D.2) already asserts every install-registered section has a reader map entry; that test continues to pass after this PR. CI lint is the gate.

## Out of scope

- Rule-level typed schema (would require migrating PermissionsTab + permission_controller to use it; deferred to keep this PR small).
- FrameworkSettingsPanel routing to PermissionsTab when the operator clicks the `permissions` row — current panel renders all sections as JSON; `permissions` follows that convention. Deep-linking is a separate UX cycle.
