# G.4 — Notification endpoints CRUD UI

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/notifications/install.py` — `_load_endpoints_from_settings` helper; `install_notification_endpoints` now reads `settings.json:notifications.channels` first, falling back to the legacy JSON files + env var.

## What it changes

`NotificationsConfigSection` was already registered (see existing code) but the install layer never read from it — endpoints came only from `~/.geny/notifications.json`, `.geny/notifications.json`, or the `NOTIFICATION_ENDPOINTS` env var. G.4 wires the install layer to consult the registered settings section first.

End-to-end effect:

1. Operator opens **FrameworkSettingsPanel → notifications**.
2. Adds / edits a channel entry (name + type + target + events + extra).
3. Saves. `~/.geny/settings.json:notifications.channels` updates atomically.
4. Next backend boot (or `loader.reload()`) — `install_notification_endpoints` registers them as `NotificationEndpoint` objects.

The legacy `notifications.json` files keep working — sources are concatenated, not replaced. Env var still wins for ephemeral overrides.

## Why

Audit (cycle 20260426_2, analysis/02 Tier 6) — notification endpoints were JSON-file-only with no UI. The existing FrameworkSettingsPanel already supports the section schema; only the install-layer read was missing.

## Backwards compatibility

- All three legacy sources (user JSON, project JSON, env) still work and are concatenated alongside settings.json entries.
- Operators with hand-managed `notifications.json` files keep their current workflow.

## Out of scope

- Dedicated CRUD UI tab (separate from FrameworkSettingsPanel) — defer; the JSON editor is sufficient for the schema's complexity.
- Live-attach when settings.json:notifications mutates mid-process — same restart-required semantics as the rest of the cycle.
- `send_message_channels` registry config — channels are code-registered today; future PR can mirror the same pattern.
