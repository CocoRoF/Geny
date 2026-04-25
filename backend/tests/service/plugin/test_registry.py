""":class:`PluginRegistry` — register / collect / apply.

PR-X5-2 tests. Covers:

- registration (dup name, empty name, non-plugin raise)
- collection ordering — plugin-registration order drives per-hook order
- attach_runtime key collision raises
- session-listener unknown event raises
- ``apply_tickers`` wires into a real :class:`TickEngine`
- ``apply_session_listeners`` wires into a real
  :class:`SessionLifecycleBus` and dispatched events actually fire
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

import pytest

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.interface import PromptBlock
from geny_executor.stages.s17_emit.interface import Emitter
from geny_executor.stages.s17_emit.types import EmitResult

from service.lifecycle.bus import SessionLifecycleBus
from service.lifecycle.events import LifecycleEvent, LifecyclePayload
from service.tick.engine import TickEngine, TickSpec

from service.plugin import (
    AttachRuntimeKeyConflict,
    DuplicatePluginError,
    GenyPlugin,
    PluginBase,
    PluginRegistry,
    SessionContext,
    SessionListener,
    UnknownLifecycleEventError,
)


# ── Test doubles ────────────────────────────────────────────────────────


class _NamedBlock(PromptBlock):
    def __init__(self, label: str) -> None:
        self._label = label

    @property
    def name(self) -> str:
        return self._label

    def render(self, state: PipelineState) -> str:
        return self._label


class _NamedEmitter(Emitter):
    def __init__(self, label: str) -> None:
        self._label = label

    @property
    def name(self) -> str:
        return self._label

    async def emit(self, state):  # type: ignore[override]
        return EmitResult(emitter_name=self._label, emitted=False)


async def _noop_tick() -> None:
    return None


async def _noop_listener(payload: LifecyclePayload) -> None:
    return None


class _Plugin(PluginBase):
    """Parametrizable plugin for building scenarios quickly."""

    def __init__(
        self,
        name: str,
        *,
        blocks: Sequence[PromptBlock] = (),
        emitters: Sequence[Emitter] = (),
        attach: Mapping[str, Any] | None = None,
        tickers: Sequence[TickSpec] = (),
        tools: Sequence[Any] = (),
        listeners: Mapping[str, SessionListener] | None = None,
    ) -> None:
        self.name = name
        self.version = "0.0.1"
        self._blocks = tuple(blocks)
        self._emitters = tuple(emitters)
        self._attach = dict(attach or {})
        self._tickers = tuple(tickers)
        self._tools = tuple(tools)
        self._listeners = dict(listeners or {})

    def contribute_prompt_blocks(self, session_ctx):
        return self._blocks

    def contribute_emitters(self, session_ctx):
        return self._emitters

    def contribute_attach_runtime(self, session_ctx):
        return dict(self._attach)

    def contribute_tickers(self):
        return self._tickers

    def contribute_tools(self):
        return self._tools

    def contribute_session_listeners(self):
        return dict(self._listeners)


# ── Registration ────────────────────────────────────────────────────────


def test_register_accepts_plugin_and_tracks_order() -> None:
    reg = PluginRegistry()
    a = _Plugin("a")
    b = _Plugin("b")
    reg.register(a)
    reg.register(b)

    assert len(reg) == 2
    assert "a" in reg and "b" in reg
    assert reg.get("a") is a
    assert list(reg.plugins) == [a, b]


def test_register_duplicate_name_raises() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("dup"))
    with pytest.raises(DuplicatePluginError) as exc:
        reg.register(_Plugin("dup"))
    assert "dup" in str(exc.value)


def test_register_empty_name_raises() -> None:
    reg = PluginRegistry()
    with pytest.raises(ValueError, match="empty name"):
        reg.register(_Plugin(""))


def test_register_non_plugin_raises() -> None:
    reg = PluginRegistry()

    class _NotAPlugin:
        name = "x"
        version = "1"

    with pytest.raises(TypeError, match="does not implement the GenyPlugin Protocol"):
        reg.register(_NotAPlugin())  # type: ignore[arg-type]


def test_plugins_property_is_read_only_snapshot() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a"))
    snap = reg.plugins
    reg.register(_Plugin("b"))
    assert len(snap) == 1 and len(reg.plugins) == 2


# ── Per-session collection ──────────────────────────────────────────────


def test_collect_prompt_blocks_preserves_registration_order() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", blocks=(_NamedBlock("a1"), _NamedBlock("a2"))))
    reg.register(_Plugin("b", blocks=(_NamedBlock("b1"),)))

    names = [b.name for b in reg.collect_prompt_blocks({})]
    assert names == ["a1", "a2", "b1"]


def test_collect_emitters_flat_list() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", emitters=(_NamedEmitter("ea"),)))
    reg.register(_Plugin("b", emitters=(_NamedEmitter("eb1"), _NamedEmitter("eb2"))))

    names = [e.name for e in reg.collect_emitters({})]
    assert names == ["ea", "eb1", "eb2"]


def test_collect_attach_runtime_merges_non_conflicting_keys() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", attach={"a_service": 1}))
    reg.register(_Plugin("b", attach={"b_service": 2}))

    merged = reg.collect_attach_runtime({})
    assert merged == {"a_service": 1, "b_service": 2}


def test_collect_attach_runtime_conflict_raises_with_owners() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", attach={"state_provider": "a-impl"}))
    reg.register(_Plugin("b", attach={"state_provider": "b-impl"}))

    with pytest.raises(AttachRuntimeKeyConflict) as exc:
        reg.collect_attach_runtime({})
    msg = str(exc.value)
    assert "state_provider" in msg
    assert "'a'" in msg and "'b'" in msg


def test_collect_attach_runtime_empty_for_empty_registry() -> None:
    reg = PluginRegistry()
    assert dict(reg.collect_attach_runtime({})) == {}


# ── Registry-global collection ──────────────────────────────────────────


def test_collect_tickers_flat_list() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", tickers=(
        TickSpec(name="a.beat", interval=60.0, handler=_noop_tick),
    )))
    reg.register(_Plugin("b", tickers=(
        TickSpec(name="b.beat", interval=30.0, handler=_noop_tick),
    )))
    specs = list(reg.collect_tickers())
    assert [s.name for s in specs] == ["a.beat", "b.beat"]


def test_collect_tools_flat_list() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", tools=("tool_a1", "tool_a2")))
    reg.register(_Plugin("b", tools=("tool_b1",)))
    assert list(reg.collect_tools()) == ["tool_a1", "tool_a2", "tool_b1"]


def test_collect_session_listeners_groups_by_event() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", listeners={"session_created": _noop_listener}))
    reg.register(_Plugin("b", listeners={
        "session_created": _noop_listener,
        "session_deleted": _noop_listener,
    }))
    grouped = reg.collect_session_listeners()

    assert len(grouped[LifecycleEvent.SESSION_CREATED]) == 2
    assert len(grouped[LifecycleEvent.SESSION_DELETED]) == 1
    assert grouped[LifecycleEvent.SESSION_IDLE] == ()


def test_collect_session_listeners_unknown_event_raises() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", listeners={"not_a_real_event": _noop_listener}))
    with pytest.raises(UnknownLifecycleEventError) as exc:
        reg.collect_session_listeners()
    assert "not_a_real_event" in str(exc.value)
    assert "'a'" in str(exc.value)


# ── Apply helpers ───────────────────────────────────────────────────────


def test_apply_tickers_registers_on_engine() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("alpha", tickers=(
        TickSpec(name="alpha.beat", interval=60.0, handler=_noop_tick),
    )))
    reg.register(_Plugin("beta", tickers=(
        TickSpec(name="beta.beat", interval=60.0, handler=_noop_tick),
    )))
    engine = TickEngine()
    reg.apply_tickers(engine)

    # Engine stored both specs — registering the same name again raises.
    with pytest.raises(ValueError, match="alpha.beat"):
        engine.register(
            TickSpec(name="alpha.beat", interval=60.0, handler=_noop_tick)
        )


def test_apply_tickers_duplicate_names_across_plugins_raise_via_engine() -> None:
    reg = PluginRegistry()
    reg.register(_Plugin("a", tickers=(
        TickSpec(name="same", interval=60.0, handler=_noop_tick),
    )))
    reg.register(_Plugin("b", tickers=(
        TickSpec(name="same", interval=60.0, handler=_noop_tick),
    )))
    engine = TickEngine()
    with pytest.raises(ValueError, match="same"):
        reg.apply_tickers(engine)


def test_apply_session_listeners_subscribes_and_dispatches() -> None:
    calls: list[str] = []

    async def h_created(payload: LifecyclePayload) -> None:
        calls.append(f"created:{payload.session_id}")

    async def h_deleted(payload: LifecyclePayload) -> None:
        calls.append(f"deleted:{payload.session_id}")

    reg = PluginRegistry()
    reg.register(_Plugin("plug", listeners={
        "session_created": h_created,
        "session_deleted": h_deleted,
    }))

    bus = SessionLifecycleBus()
    reg.apply_session_listeners(bus)

    async def scenario() -> None:
        await bus.emit(LifecycleEvent.SESSION_CREATED, session_id="s1")
        await bus.emit(LifecycleEvent.SESSION_DELETED, session_id="s1")

    asyncio.run(scenario())
    assert calls == ["created:s1", "deleted:s1"]


def test_apply_session_listeners_multiple_plugins_same_event_all_fire() -> None:
    fired: list[str] = []

    def _mk(label: str):
        async def _h(payload: LifecyclePayload) -> None:
            fired.append(label)
        return _h

    reg = PluginRegistry()
    reg.register(_Plugin("p1", listeners={"session_created": _mk("p1")}))
    reg.register(_Plugin("p2", listeners={"session_created": _mk("p2")}))

    bus = SessionLifecycleBus()
    reg.apply_session_listeners(bus)

    async def scenario() -> None:
        await bus.emit(LifecycleEvent.SESSION_CREATED, session_id="s")

    asyncio.run(scenario())
    assert fired == ["p1", "p2"]


# ── Structural-plugin compatibility ─────────────────────────────────────


class _StructuralPlugin:
    """Registry must accept duck-typed plugins too, not just PluginBase
    subclasses."""

    name = "structural"
    version = "1.0.0"

    def contribute_prompt_blocks(self, session_ctx):
        return (_NamedBlock("struct-block"),)

    def contribute_emitters(self, session_ctx):
        return ()

    def contribute_attach_runtime(self, session_ctx):
        return {}

    def contribute_tickers(self):
        return ()

    def contribute_tools(self):
        return ()

    def contribute_session_listeners(self):
        return {}


def test_registry_accepts_structural_plugin() -> None:
    reg = PluginRegistry()
    reg.register(_StructuralPlugin())

    blocks = reg.collect_prompt_blocks({})
    assert len(blocks) == 1 and blocks[0].name == "struct-block"
