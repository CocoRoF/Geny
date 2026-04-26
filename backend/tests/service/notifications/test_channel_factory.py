"""L.1 (cycle 20260426_3) — channel factory tests.

Verifies the registry-pattern that lets settings.json declare which
SendMessageChannel kinds activate without forcing the install layer
to know about every host's channel implementation.
"""

from __future__ import annotations

import pytest

# Skip cleanly when geny_executor isn't available — the stdout factory
# imports ``geny_executor.channels`` lazily.
pytest.importorskip("geny_executor")

from service.notifications import channel_factory  # noqa: E402


def test_unknown_kind_returns_none() -> None:
    """Settings entry with a kind no factory knows → caller sees None
    and logs a warning rather than crashing the install layer."""
    assert channel_factory.channel_from_entry({"kind": "definitely-not-a-kind"}) is None


def test_missing_kind_returns_none() -> None:
    """Entry without a kind key is skipped, not registered to factory[None]."""
    assert channel_factory.channel_from_entry({"name": "foo"}) is None
    assert channel_factory.channel_from_entry({"kind": ""}) is None
    assert channel_factory.channel_from_entry({"kind": None}) is None  # type: ignore[arg-type]


def test_stdout_factory_registered_by_default() -> None:
    """The shipped factory map includes ``stdout`` so out-of-the-box
    deployments (no settings.json:channels entries) keep working."""
    assert "stdout" in channel_factory.known_kinds()
    channel = channel_factory.channel_from_entry({"kind": "stdout"})
    assert channel is not None
    # geny_executor.channels.StdoutSendMessageChannel implements
    # SendMessageChannel; we just check it has a send_message attr.
    assert callable(getattr(channel, "send_message", None))


def test_register_custom_factory_then_retrieve() -> None:
    """Hosts wire Discord / Slack / etc by calling
    ``register_channel_factory("discord", DiscordChannel)`` once."""

    sentinel = object()

    def fake_factory(_config):
        return sentinel

    channel_factory.register_channel_factory("test-kind", fake_factory)
    try:
        result = channel_factory.channel_from_entry(
            {"kind": "test-kind", "config": {"foo": "bar"}},
        )
        assert result is sentinel
    finally:
        # Clean up so the parametric test doesn't see the test kind.
        channel_factory._FACTORIES.pop("test-kind", None)


def test_factory_exception_is_swallowed(caplog) -> None:
    """A factory that raises must not bring down install_send_message_channels."""
    import logging

    def boom(_config):
        raise RuntimeError("intentional")

    channel_factory.register_channel_factory("boom-kind", boom)
    try:
        with caplog.at_level(logging.WARNING):
            assert channel_factory.channel_from_entry({"kind": "boom-kind"}) is None
        # Warning must mention the kind so operators can pin the entry.
        assert any(
            "boom-kind" in rec.message for rec in caplog.records
        ), caplog.records
    finally:
        channel_factory._FACTORIES.pop("boom-kind", None)


def test_invalid_config_type_falls_through_to_empty() -> None:
    """A non-dict config gets coerced to {} so the factory still runs."""

    seen = {}

    def capture(config):
        seen["config"] = config
        return object()

    channel_factory.register_channel_factory("capture-kind", capture)
    try:
        channel_factory.channel_from_entry({"kind": "capture-kind", "config": "not-a-dict"})
        assert seen["config"] == {}
    finally:
        channel_factory._FACTORIES.pop("capture-kind", None)
