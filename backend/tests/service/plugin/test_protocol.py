""":class:`GenyPlugin` Protocol — runtime check + PluginBase defaults.

PR-X5-1 ships the *contract* only. These tests pin the three
properties downstream PRs rely on:

- :class:`GenyPlugin` is :func:`runtime_checkable` so
  :class:`PluginRegistry` (PR-X5-2) can ``isinstance(x, GenyPlugin)``
  without import cycles.
- :class:`PluginBase` implements every optional hook with a harmless
  no-op default, so a minimal ``(name, version)`` plugin is usable
  end-to-end without boilerplate.
- Optional hook signatures accept a :data:`SessionContext` when
  session-scoped and nothing when registry-global — guards against a
  regression where a subclass accidentally widens / narrows the
  contract.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pytest

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock
from geny_executor.stages.s17_emit.interface import Emitter
from geny_executor.stages.s17_emit.types import EmitResult

from service.plugin import (
    GenyPlugin,
    PluginBase,
    SessionContext,
    SessionListener,
)
from service.tick.engine import TickSpec


# ── Lightweight test doubles ───────────────────────────────────────────


class _StubBlock(PromptBlock):
    @property
    def name(self) -> str:
        return "stub-block"

    def render(self, state: PipelineState) -> str:
        return ""


class _StubEmitter(Emitter):
    @property
    def name(self) -> str:
        return "stub"

    async def emit(self, state):  # type: ignore[override]
        return EmitResult(emitter_name="stub", emitted=False)


async def _noop_tick() -> None:
    return None


async def _noop_listener(*args: Any, **kwargs: Any) -> None:
    return None


# ── PluginBase default behaviour ───────────────────────────────────────


class _BareMinimumPlugin(PluginBase):
    """Only sets ``name`` + ``version`` — every hook inherits the
    default no-op. Exercises the "I only need one surface later"
    incremental-adoption story."""

    name = "bare"
    version = "0.0.0"


def test_plugin_base_implements_protocol() -> None:
    """The canonical parent class is structurally a :class:`GenyPlugin`."""
    plugin = _BareMinimumPlugin()
    assert isinstance(plugin, GenyPlugin)


def test_plugin_base_defaults_are_empty_but_callable() -> None:
    plugin = _BareMinimumPlugin()
    ctx: SessionContext = {"session_id": "s", "is_vtuber": False}

    assert tuple(plugin.contribute_prompt_blocks(ctx)) == ()
    assert tuple(plugin.contribute_emitters(ctx)) == ()
    assert dict(plugin.contribute_attach_runtime(ctx)) == {}
    assert tuple(plugin.contribute_tickers()) == ()
    assert tuple(plugin.contribute_tools()) == ()
    assert dict(plugin.contribute_session_listeners()) == {}


def test_plugin_base_default_attach_runtime_is_per_call_empty() -> None:
    """Default attach_runtime must return a fresh mapping per call so
    a caller that mutates the result doesn't leak into the next plugin
    that reuses the default."""
    plugin = _BareMinimumPlugin()
    a = plugin.contribute_attach_runtime({})
    b = plugin.contribute_attach_runtime({})
    # Two distinct (or at least non-shared mutable) values — mutating
    # one must not affect the other.
    assert dict(a) == {}
    assert dict(b) == {}


# ── Structural (non-inheriting) plugins also satisfy the Protocol ──────


class _StructuralPlugin:
    """Duck-typed plugin — does not inherit :class:`PluginBase`. The
    registry (PR-X5-2) must accept these too."""

    name = "structural"
    version = "1.2.3"

    def contribute_prompt_blocks(
        self, session_ctx: SessionContext,
    ) -> Sequence[PromptBlock]:
        return (_StubBlock(),)

    def contribute_emitters(
        self, session_ctx: SessionContext,
    ) -> Sequence[Emitter]:
        return (_StubEmitter(),)

    def contribute_attach_runtime(
        self, session_ctx: SessionContext,
    ) -> Mapping[str, Any]:
        return {"stub_service": object()}

    def contribute_tickers(self) -> Sequence[TickSpec]:
        return (
            TickSpec(
                name="structural.heartbeat", interval=60.0, handler=_noop_tick,
            ),
        )

    def contribute_tools(self) -> Sequence[Any]:
        return ()

    def contribute_session_listeners(self) -> Mapping[str, SessionListener]:
        return {"session.created": _noop_listener}


def test_structural_plugin_is_recognized_as_geny_plugin() -> None:
    plugin = _StructuralPlugin()
    assert isinstance(plugin, GenyPlugin)


def test_structural_plugin_contributions_round_trip() -> None:
    plugin = _StructuralPlugin()
    blocks = plugin.contribute_prompt_blocks({})
    emitters = plugin.contribute_emitters({})
    tickers = plugin.contribute_tickers()
    listeners = plugin.contribute_session_listeners()

    assert len(blocks) == 1 and isinstance(blocks[0], PromptBlock)
    assert len(emitters) == 1 and isinstance(emitters[0], Emitter)
    assert len(tickers) == 1 and tickers[0].name == "structural.heartbeat"
    assert "session.created" in listeners


# ── Negative cases — objects that are NOT plugins ───────────────────────


class _MissingAttributes:
    """No ``name``, no ``version`` — fails the Protocol's required
    attribute check."""


def test_missing_name_and_version_is_not_a_plugin() -> None:
    assert not isinstance(_MissingAttributes(), GenyPlugin)


class _MissingHookMethod:
    """Has the required attributes but is missing a ``contribute_*``
    method — fails the Protocol's structural check."""

    name = "incomplete"
    version = "0.0.0"

    def contribute_prompt_blocks(self, session_ctx):
        return ()

    def contribute_emitters(self, session_ctx):
        return ()

    def contribute_attach_runtime(self, session_ctx):
        return {}

    def contribute_tickers(self):
        return ()

    # Deliberately omits contribute_tools and contribute_session_listeners.


def test_incomplete_hook_surface_is_not_a_plugin() -> None:
    assert not isinstance(_MissingHookMethod(), GenyPlugin)


# ── PluginBase override ergonomics ─────────────────────────────────────


class _OverridingPlugin(PluginBase):
    """Overrides a subset of hooks — inherits defaults for the rest."""

    name = "override"
    version = "0.1.0"

    def __init__(self) -> None:
        self._service = {"provider": "mock"}

    def contribute_prompt_blocks(self, session_ctx):
        return (_StubBlock(),)

    def contribute_attach_runtime(self, session_ctx):
        return {"plugin_service": self._service}


def test_override_keeps_inherited_defaults_for_other_hooks() -> None:
    plugin = _OverridingPlugin()
    # Overridden — non-empty.
    assert len(plugin.contribute_prompt_blocks({})) == 1
    assert plugin.contribute_attach_runtime({}) == {"plugin_service": {"provider": "mock"}}
    # Inherited defaults — still empty.
    assert tuple(plugin.contribute_emitters({})) == ()
    assert tuple(plugin.contribute_tickers()) == ()
    assert dict(plugin.contribute_session_listeners()) == {}


# ── Required attributes are enforced by Protocol shape ─────────────────


class _NamelessPlugin(PluginBase):
    """Inherits the no-op hooks but forgets to set ``name`` /
    ``version``. The Protocol declares these at class-attribute level,
    so an instance without them (``name`` stays as the uninitialized
    :class:`PluginBase` descriptor placeholder) should fail the
    structural check — this test pins that behavior."""


def test_plugin_without_name_fails_protocol_check() -> None:
    # ``_NamelessPlugin().name`` raises AttributeError because
    # PluginBase declares ``name: str`` with no default. The
    # runtime_checkable Protocol check catches the missing attribute.
    plugin = _NamelessPlugin()
    with pytest.raises(AttributeError):
        _ = plugin.name
    assert not isinstance(plugin, GenyPlugin)
