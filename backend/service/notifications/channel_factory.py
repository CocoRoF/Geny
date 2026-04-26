"""L.1 (cycle 20260426_3) — SendMessageChannel factory registry.

The executor's ``SendMessageChannelRegistry`` accepts pre-built
channel instances. To drive the registry from settings.json, we need
a way to map a `kind` string in the config to a constructor. This
module owns that mapping.

Hosts shipping custom channels (Discord, Slack, etc.) call
``register_channel_factory("discord", lambda cfg: DiscordChannel(**cfg))``
once at import time. Settings.json then declares which entries to
activate without needing to know about the implementation:

    {
      "channels": {
        "send_message": [
          {"name": "ops-alerts", "kind": "discord",
           "config": {"webhook_url": "https://…"}}
        ]
      }
    }

The shipped factory only handles ``stdout`` (the executor's reference
implementation). Adding more is host policy — the install layer logs
a warning + skips entries with unknown ``kind``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# kind -> factory(config dict) -> SendMessageChannel
_FACTORIES: Dict[str, Callable[[Dict[str, Any]], Any]] = {}


def register_channel_factory(
    kind: str,
    factory: Callable[[Dict[str, Any]], Any],
) -> None:
    """Register a factory for a given ``kind``.

    Re-registering the same ``kind`` overwrites — useful for host
    customizations of the shipped ``stdout`` impl.
    """
    _FACTORIES[kind] = factory


def channel_from_entry(entry: Dict[str, Any]) -> Optional[Any]:
    """Build a SendMessageChannel from a settings entry, or ``None``
    when the kind is unknown (the install layer logs + skips)."""
    kind = entry.get("kind")
    if not kind or not isinstance(kind, str):
        return None
    factory = _FACTORIES.get(kind)
    if factory is None:
        return None
    config = entry.get("config") or {}
    if not isinstance(config, dict):
        config = {}
    try:
        return factory(config)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "send_message_channel_factory_failed kind=%s err=%s", kind, exc,
        )
        return None


def known_kinds() -> list[str]:
    return sorted(_FACTORIES.keys())


# ── Default factories ─────────────────────────────────────────────


def _stdout_factory(_config: Dict[str, Any]) -> Any:
    from geny_executor.channels import StdoutSendMessageChannel

    return StdoutSendMessageChannel()


register_channel_factory("stdout", _stdout_factory)


__all__ = [
    "register_channel_factory",
    "channel_from_entry",
    "known_kinds",
]
