# H.2 — HooksTab frontend rewrite

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `frontend/src/lib/api.ts` — `HOOK_EVENTS` swapped to lowercase 16-event list; `HookEntryPayload` / `HookEntryRow` swapped to executor schema (command:str, args, match dict, env, working_dir); `HookListResponse.entries` typed loosely to tolerate the legacy admin endpoint output; new `hookApi.setAuditLog`.
- `frontend/src/components/tabs/HooksTab.tsx` — full rewrite to drive the new schema. Form has command + args + match dict editor + env table + working_dir + timeout. Top-level audit_log_path editor. Reusable `KvEditor` for dict inputs.

## What it changes

The hook editor now produces payloads the executor's `parse_hook_config` accepts cleanly. Concretely:

- **Event picker** — 16 lowercase HookEvent values (was 8 stale capitalized).
- **Command** — single string input (was free-text "argv" that got space-split).
- **Args** — separate textarea, one per line (no shell interpolation, matches executor docs).
- **Match dict editor** — generic key/value rows; only the `tool` key is honored today but the dict shape is forward-compatible.
- **Env table** — key/value rows for extra subprocess env.
- **Working dir** — optional override.
- **Timeout** — unchanged numeric input.
- **Audit log path** — top-level editor with Save button, surfaces in a separate section above the entries list.

## i18n

Strings are inline english for now — matches the existing tab style. I18n migration is a separate cleanup PR (out of cycle scope).

## Tests

UI-only changes; CI lint + tsc + Next build is the gate.

## Out of scope

- Per-event affordance differences (e.g. PERMISSION_DENIED could pre-fill a stricter timeout). The match dict is universal enough that operators can compose any constraint without per-event UI.
- Recent fires re-rendering. The fire records still use the same JSONL shape; only the form changed.
