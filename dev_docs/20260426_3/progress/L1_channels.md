# L.1 — send_message_channels settings.json read

**PR:** TBD
**Status:** Merged TBD
**Files changed:**
- `backend/service/settings/sections.py` — `ChannelsConfigSection` + `SendMessageChannelEntry` schemas.
- `backend/service/settings/install.py` — `register_section("channels", ChannelsConfigSection)`.
- `backend/service/settings/known_sections.py` — reader map entry; parametrized lock test updated.
- `backend/service/notifications/channel_factory.py` (new) — factory registry mapping `kind` strings to constructors. Ships `stdout` factory; hosts add Discord / Slack / etc by calling `register_channel_factory`.
- `backend/service/notifications/install.py` — `install_send_message_channels` reads `settings.json:channels.send_message`, looks up each entry's `kind` in the factory registry, and registers the constructed instance under the entry's `name`. Legacy `"geny" → StdoutSendMessageChannel()` default kept.
- `backend/tests/service/notifications/test_channel_factory.py` (new) — 6 unit cases covering unknown kind, missing kind, stdout default, custom-factory round-trip, exception swallowing, invalid-config coercion.

## What it changes

Operators can declare SendMessage channels in `settings.json:channels.send_message`:

```json
{
  "channels": {
    "send_message": [
      {"name": "ops-alerts", "kind": "discord",
       "config": {"webhook_url": "https://…"}}
    ]
  }
}
```

The install layer looks up `discord` in the factory registry and constructs the channel. Hosts that ship Discord / Slack / etc register their factory once at module import time:

```python
from service.notifications.channel_factory import register_channel_factory
from my_host.discord import DiscordChannel

register_channel_factory("discord", lambda cfg: DiscordChannel(**cfg))
```

The shipped factory only handles `stdout` (the executor's reference impl). Unknown kinds are skipped with a warning.

## Why

Audit (cycle 20260426_3, analysis/01) — `install_send_message_channels` was code-only, with no settings-driven path. Mirrors the G.4 pattern for notification endpoints.

## Backwards compatibility

- Legacy `"geny" → StdoutSendMessageChannel()` registration kept. Operators with no settings.json entries see no behavior change.
- Settings entries can collide with the legacy "geny" name; later registration wins per the executor's registry semantics.

## Tests

6 unit cases in `test_channel_factory.py` (skip on geny_executor missing). Parametrized `test_known_sections.py` adds `channels` to lock the install ↔ reader-map sync.

## Out of scope

- Frontend sub-tab dedicated to channel CRUD — the JSON editor in FrameworkSettingsPanel handles it.
- `kind` autocomplete in the UI based on `known_kinds()` — defer; operators with custom factories know what they registered.
