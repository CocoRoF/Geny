"""AgentSessionManager.set_state_provider (cycle 20260421_9 PR-X3-5).

Tests the thin plumbing that forwards a process-wide
``CreatureStateProvider`` into newly constructed ``AgentSession``
instances. Full session creation is covered by integration tests;
here we only exercise:

1. ``state_provider`` defaults to ``None`` at construction.
2. ``set_state_provider`` stores the provider + decay service.
3. The provider + decay service are exposed as properties.
"""

from __future__ import annotations

from service.executor.agent_session_manager import AgentSessionManager
from service.state import InMemoryCreatureStateProvider


def _manager_skeleton() -> AgentSessionManager:
    mgr = object.__new__(AgentSessionManager)
    mgr._state_provider = None
    mgr._state_decay_service = None
    mgr._state_provider_vtuber_only = True
    return mgr


def test_state_provider_defaults_to_none() -> None:
    mgr = _manager_skeleton()
    assert mgr.state_provider is None
    assert mgr.state_decay_service is None


def test_set_state_provider_stores_provider_and_decay_service() -> None:
    mgr = _manager_skeleton()
    prov = InMemoryCreatureStateProvider()

    class _FakeService:
        pass

    svc = _FakeService()
    mgr.set_state_provider(prov, decay_service=svc)

    assert mgr.state_provider is prov
    assert mgr.state_decay_service is svc


def test_set_state_provider_without_decay_service_is_allowed() -> None:
    """decay_service is optional — useful for tests / reduced setups."""
    mgr = _manager_skeleton()
    prov = InMemoryCreatureStateProvider()
    mgr.set_state_provider(prov)
    assert mgr.state_provider is prov
    assert mgr.state_decay_service is None


def test_set_state_provider_overrides_previous() -> None:
    mgr = _manager_skeleton()
    first = InMemoryCreatureStateProvider()
    second = InMemoryCreatureStateProvider()
    mgr.set_state_provider(first)
    mgr.set_state_provider(second)
    assert mgr.state_provider is second


def test_set_state_provider_stores_vtuber_only_flag() -> None:
    """Cycle 20260422_5 follow-up — role gating flag survives across
    set_state_provider calls so create_agent_session can read it."""
    mgr = _manager_skeleton()
    prov = InMemoryCreatureStateProvider()
    mgr.set_state_provider(prov, vtuber_only=False)
    assert mgr._state_provider_vtuber_only is False
    mgr.set_state_provider(prov, vtuber_only=True)
    assert mgr._state_provider_vtuber_only is True


def test_set_state_provider_defaults_vtuber_only_true() -> None:
    """Default for vtuber_only must be True — the safer behavior,
    matching the intent that plain Worker sessions don't spawn
    orphan creature rows."""
    mgr = _manager_skeleton()
    prov = InMemoryCreatureStateProvider()
    mgr.set_state_provider(prov)
    assert mgr._state_provider_vtuber_only is True
