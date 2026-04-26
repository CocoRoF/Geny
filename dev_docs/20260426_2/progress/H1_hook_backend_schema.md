# H.1 — Hook backend schema rewrite

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/controller/hook_controller.py` — full rewrite to executor-compatible schema.
- `backend/service/hooks/install.py` — `_build_config_from_settings_section` now routes through `parse_hook_config` (proper typing).
- `backend/tests/controller/test_hook_controller_schema.py` (new) — 11 cases.

## What it changes

Geny was writing a settings.json shape the executor's `parse_hook_config` rejected and the install layer's defensive fallback bypassed type-correctness. Net effect: hooks never fired regardless of `GENY_ALLOW_HOOKS`.

H.1 fixes three layers:

1. **Schema parity**:
   - `command: str` (was `List[str]`).
   - `args: List[str]` (new).
   - `match: Dict[str, Any]` (was `tool_filter: List[str]`).
   - `env: Dict[str, str]` (new).
   - `working_dir: Optional[str]` (new).
   - `audit_log_path` PATCH endpoint (new).

2. **Event coverage**:
   - `_KNOWN_EVENTS` synced to executor's 16-value `HookEvent` enum (lowercase).
   - Legacy STOP / SUBAGENT_STOP / PRE_COMPACT removed (never existed in executor — silent no-op risk eliminated).

3. **Install path**:
   - `service/hooks/install.py:_build_config_from_settings_section` previously short-circuited on `isinstance(section, dict)` because `get_section("hooks")` returns the registered Pydantic model. Now coerces via `model_dump`.
   - Defensive direct construct path stored raw dicts as `entries` values; `HookRunner.fire` reads them as `HookConfigEntry` objects → silent no-op. Now routes through `parse_hook_config` so the result is type-correct.
   - Translates Geny's `{enabled, entries: {EVENT: [...]}}` → executor's `{enabled, hooks: {event: [...]}}` wrapper while persisting the `entries` key (more discoverable to operators reading the file).

## Backwards compatibility

Reads tolerate the pre-H.1 shape:
- Capitalized event keys (`PRE_TOOL_USE`) → lowercased.
- `command: List[str]` → split into `command: str` (head) + `args: List[str]` (tail).
- `tool_filter: ["X"]` → `match: {"tool": "X"}`. Multi-tool surfaces a warning + first wins.
- Malformed entries returned as `None` from `_normalize_legacy_entry` and skipped (whole list keeps moving).

Writes always emit the new shape, so a single round-trip migrates the file. `_validate_event` accepts both vintages on the input side so older clients still work until they refresh.

## Tests

11 unit cases in `test_hook_controller_schema.py`:
- payload rejects legacy `command: List[str]`
- payload accepts modern shape; `_entry_to_dict` round-trips
- `_entry_to_dict` omits empty optionals (clean settings.json)
- `_validate_event` normalizes uppercase, accepts whitespace
- `_validate_event` rejects unknown / legacy-only events
- `_normalize_legacy_entry`: command list → command + args
- `_normalize_legacy_entry`: tool_filter → match
- `_normalize_legacy_entry`: multi-tool tool_filter logs warning, first wins
- `_normalize_legacy_entry`: skips malformed entries
- `_normalize_legacy_entry`: modern entry passes through unchanged

Local: skipped (pydantic + fastapi). CI runs them.

## Out of scope (rolled into H.2 / H.3)

- Frontend rewrite — H.2.
- End-to-end parse round-trip test — H.3.
