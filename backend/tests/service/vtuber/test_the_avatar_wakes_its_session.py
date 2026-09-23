"""An avatar appearing wakes its dormant session — before anyone speaks.

Production after a restart: the first voice turn to the VTuber paid for the
whole wake (pipeline, memory provider, and a cold vector index whose warm-up
held retrieval for its 10 s timeout) — 45-60 s for a one-line reply, against
~7 s warm. The avatar connects first, so the wake starts there.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

import ws.avatar_stream as avatar_stream


class _Manager:
    def __init__(self, live: bool, fail: bool = False) -> None:
        self.live = live
        self.fail = fail
        self.woken: List[str] = []

    def get_agent(self, session_id: str) -> Optional[object]:
        return object() if self.live else None

    async def ensure_session_live(self, session_id: str) -> Optional[object]:
        if self.fail:
            raise RuntimeError("store unavailable")
        self.woken.append(session_id)
        return object()


def _run(manager: _Manager, monkeypatch) -> None:
    monkeypatch.setattr(
        "service.executor.agent_session_manager.get_agent_session_manager",
        lambda: manager,
    )

    async def go() -> None:
        avatar_stream._schedule_prewake("S")
        await asyncio.gather(*list(avatar_stream._PREWAKE_TASKS))

    asyncio.run(go())


def test_a_dormant_session_is_woken(monkeypatch) -> None:
    manager = _Manager(live=False)
    _run(manager, monkeypatch)
    assert manager.woken == ["S"]


def test_a_live_session_is_left_alone(monkeypatch) -> None:
    manager = _Manager(live=True)
    _run(manager, monkeypatch)
    assert manager.woken == []


def test_a_failed_wake_never_reaches_the_avatar(monkeypatch) -> None:
    _run(_Manager(live=False, fail=True), monkeypatch)  # must not raise


def test_the_socket_schedules_it_on_subscribe() -> None:
    import inspect

    source = inspect.getsource(avatar_stream.ws_avatar_state_stream)
    subscribed = source.index('subscribed to avatar state')
    assert "_schedule_prewake(session_id)" in source[subscribed:subscribed + 200]
