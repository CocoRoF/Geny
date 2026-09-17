"""Switching model without ending the conversation.

A live session holds everything that makes it that session: its history,
tools, memory, hooks and permission policy. Rebuilding its pipeline to
change which model answers would throw all of that away — so the route is
swapped in place and only the next turn's destination changes.

The refusal case matters just as much: a route that resolves to nothing must
leave the session on the route it had. A switch the user can retry is a much
smaller loss than a session that can no longer reach any model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


class _Pipeline:
    def __init__(self) -> None:
        self.swapped: List[Any] = []

    def set_provider_credentials(self, provider: str, creds: Any) -> None:
        self.swapped.append((provider, creds))


class _Agent:
    def __init__(self, pipeline: Optional[_Pipeline] = None) -> None:
        self._pipeline = pipeline
        self.route: Optional[Dict[str, Any]] = None
        self.last_route: Optional[Dict[str, Any]] = None


class _Store:
    def __init__(self, record: Optional[Dict[str, Any]] = None) -> None:
        self.record = record
        self.updates: List[Dict[str, Any]] = []

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self.record

    def update(self, session_id: str, updates: Dict[str, Any]) -> None:
        self.updates.append(updates)
        if self.record is not None:
            self.record.update(updates)


def _manager(store: _Store, agents: Dict[str, _Agent], targets: List[Dict[str, Any]]):
    """A manager with only the collaborators route switching touches."""
    from service.executor.agent_session_manager import AgentSessionManager

    manager = AgentSessionManager.__new__(AgentSessionManager)
    manager._store = store
    manager._local_agents = agents

    async def route_targets(route: Dict[str, Any]) -> List[Dict[str, Any]]:
        return list(targets)

    manager._route_targets = route_targets
    return manager


_ROUTE = {"primary": {"accountId": "a2", "model": "opus"}, "fallbacks": []}
_TARGETS = [{
    "accountId": "a2", "label": "Claude 2", "kind": "claude_code",
    "engineProvider": "geny_claude_code", "model": "opus", "options": {},
}]


class TestLiveSwitch:
    @pytest.mark.asyncio
    async def test_a_live_session_switches_without_a_rebuild(self) -> None:
        pipeline = _Pipeline()
        agent = _Agent(pipeline)
        manager = _manager(_Store({"route": {"primary": {"accountId": "a1"}}}),
                           {"s1": agent}, _TARGETS)

        result = await manager.change_session_route("s1", _ROUTE)

        assert result["applies"] == "immediately"
        assert [p for p, _ in pipeline.swapped] == ["geny_router"]
        assert pipeline.swapped[0][1].extras["targets"] == _TARGETS
        assert agent.route == _ROUTE

    @pytest.mark.asyncio
    async def test_the_new_route_is_persisted_so_a_restart_keeps_it(self) -> None:
        store = _Store({"route": {"primary": {"accountId": "a1"}}})
        manager = _manager(store, {"s1": _Agent(_Pipeline())}, _TARGETS)
        await manager.change_session_route("s1", _ROUTE)
        assert store.updates == [{"route": _ROUTE}]

    @pytest.mark.asyncio
    async def test_a_dormant_session_picks_it_up_on_its_next_wake(self) -> None:
        manager = _manager(_Store({"route": None}), {}, _TARGETS)
        result = await manager.change_session_route("s1", _ROUTE)
        assert result["live"] is False
        assert result["applies"] == "next_turn"

    @pytest.mark.asyncio
    async def test_the_answer_names_the_accounts_it_will_use(self) -> None:
        manager = _manager(_Store({"route": None}), {}, _TARGETS)
        result = await manager.change_session_route("s1", _ROUTE)
        assert result["targets"] == [
            {"accountId": "a2", "label": "Claude 2", "kind": "claude_code", "model": "opus"}
        ]


class TestRefusals:
    @pytest.mark.asyncio
    async def test_an_unknown_session_is_not_found(self) -> None:
        manager = _manager(_Store(None), {}, _TARGETS)
        with pytest.raises(ValueError, match="session not found"):
            await manager.change_session_route("nope", _ROUTE)

    @pytest.mark.asyncio
    async def test_a_route_with_no_usable_account_keeps_the_old_one(self) -> None:
        pipeline = _Pipeline()
        store = _Store({"route": {"primary": {"accountId": "a1"}}})
        manager = _manager(store, {"s1": _Agent(pipeline)}, [])

        with pytest.raises(ValueError):
            await manager.change_session_route("s1", _ROUTE)

        assert store.updates == []
        assert pipeline.swapped == []
        assert store.record["route"] == {"primary": {"accountId": "a1"}}


class TestReading:
    def test_a_live_session_reports_its_route_and_who_answered(self) -> None:
        agent = _Agent()
        agent.route = _ROUTE
        agent.last_route = {"accountId": "a2", "label": "Claude 2", "failedOver": False}
        manager = _manager(_Store({"route": None}), {"s1": agent}, _TARGETS)
        state = manager.get_session_route("s1")
        assert state["route"] == _ROUTE
        assert state["last_route"]["accountId"] == "a2"
        assert state["live"] is True

    def test_a_dormant_session_reports_from_the_store(self) -> None:
        manager = _manager(_Store({"route": _ROUTE, "last_route": {"accountId": "a2"}}), {}, _TARGETS)
        state = manager.get_session_route("s1")
        assert state["route"] == _ROUTE
        assert state["live"] is False
