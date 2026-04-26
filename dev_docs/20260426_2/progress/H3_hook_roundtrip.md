# H.3 — Hook end-to-end parse roundtrip

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/tests/integration/test_hook_executor_roundtrip.py` (new) — 4 cases.

## What it changes

Adds the regression guard that would have caught the H.1 bug at PR-merge time. Each case writes via Geny's REST handler (called directly to skip the FastAPI TestClient), reads the resulting settings.json off disk, then passes the file through the executor's `parse_hook_config`. The result must parse cleanly and contain the entries we wrote.

If anyone re-introduces a shape mismatch the test will fail loudly instead of hooks silently never firing.

## Cases

1. `test_modern_payload_parses_in_executor` — happy path with all fields populated; round-trip preserves them.
2. `test_minimal_entry_parses` — only `command` set; optional fields elided cleanly.
3. `test_audit_log_path_roundtrips` — top-level PATCH lands and the executor's wrapper parser reads it.
4. `test_legacy_entry_migrates_on_next_write` — pre-H.1 settings.json (uppercase keys, `command: list`, `tool_filter`) reads through `_normalize_legacy_entry`, then a follow-up write rewrites the file in the new shape and the executor parses it.

## Test infrastructure

- `monkeypatch` redirects `_user_settings_path` to a tmp_path so the real `~/.geny/settings.json` is never touched.
- `_reload_loader` is patched out (the test reads the file directly).
- `_wrap_for_executor` mirrors the production install layer's translation from Geny's on-disk shape to the wrapper executor expects.

## Local

Skipped (importorskip on pydantic + fastapi + geny_executor — none in the bare test venv). CI runs all 4.
