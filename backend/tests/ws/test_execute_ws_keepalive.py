"""What a phone needs from the execute socket.

A turn belongs to the session, not to the socket. Two consequences the mobile
app is built on, and both are easy to break without noticing:

* ``reconnect`` must rejoin a turn already in flight, and replay it from the
  START — a client that was away (screen locked, tunnel dropped, app
  backgrounded) otherwise shows "running" over an empty bubble, which is the
  worst of both readings.
* ``ping`` must answer. Heartbeats only flow while a turn runs, so an idle
  socket is silent — and silence is indistinguishable from a socket a carrier
  NAT dropped an hour ago. The answer also says whether a turn is running,
  which is the first thing a waking phone needs.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

import ws.execute_stream as module


class _Socket:
    """A WebSocket that plays a script and records what it was sent."""

    def __init__(self, inbound: List[Dict[str, Any]]) -> None:
        self._inbound = list(inbound)
        self.sent: List[Dict[str, Any]] = []
        self.app = type("App", (), {"state": type("S", (), {})()})()

    async def receive_text(self) -> str:
        if not self._inbound:
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect(code=1000)
        return json.dumps(self._inbound.pop(0))

    async def send_json(self, payload: Dict[str, Any]) -> None:
        self.sent.append(payload)

    async def accept(self, subprotocol: Optional[str] = None) -> None:
        self.accepted = True

    def of_type(self, kind: str) -> List[Dict[str, Any]]:
        return [m for m in self.sent if m.get("type") == kind]


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch):
    """The endpoint with its collaborators replaced by ones a test can steer."""

    async def auth(websocket: Any):
        return type("Auth", (), {"subprotocol": None, "payload": {"sub": "admin"}})()

    monkeypatch.setattr(module, "ws_auth_or_close", auth)

    state: Dict[str, Any] = {"holder": None, "streamed": []}

    def get_holder(session_id: str):
        return state["holder"]

    async def stream(ws: Any, holder: Dict[str, Any], session_id: str, app_state: Any = None) -> None:
        state["streamed"].append(holder.get("exec_id"))
        await ws.send_json({"type": "status", "data": {"status": "running", "message": "replaying"}})

    monkeypatch.setattr(module, "get_execution_holder", get_holder)
    monkeypatch.setattr(module, "_stream_execution_ws", stream)
    return state


async def _run(socket: _Socket) -> None:
    await module.ws_execute_stream(socket, "session-1234abcd")


class TestPing:
    @pytest.mark.asyncio
    async def test_an_idle_socket_can_prove_it_is_alive(self, wired) -> None:
        socket = _Socket([{"type": "ping"}])
        await _run(socket)
        pongs = socket.of_type("pong")
        assert len(pongs) == 1
        assert pongs[0]["data"]["running"] is False
        assert pongs[0]["data"]["ts"] > 0

    @pytest.mark.asyncio
    async def test_the_answer_says_a_turn_is_running(self, wired) -> None:
        """The first thing a waking phone needs — before it decides whether to
        draw a spinner or an idle composer."""
        wired["holder"] = {"exec_id": "e1", "done": False}
        socket = _Socket([{"type": "ping"}])
        await _run(socket)
        assert socket.of_type("pong")[0]["data"]["running"] is True

    @pytest.mark.asyncio
    async def test_a_finished_turn_is_not_running(self, wired) -> None:
        wired["holder"] = {"exec_id": "e1", "done": True}
        socket = _Socket([{"type": "ping"}])
        await _run(socket)
        assert socket.of_type("pong")[0]["data"]["running"] is False

    @pytest.mark.asyncio
    async def test_a_keepalive_is_not_an_unknown_message(self, wired) -> None:
        """Answering a keepalive with an error would put a warning in the log
        every fifteen seconds, for every phone."""
        socket = _Socket([{"type": "ping"}])
        await _run(socket)
        assert socket.of_type("error") == []


class TestReconnect:
    @pytest.mark.asyncio
    async def test_it_rejoins_a_turn_in_flight(self, wired) -> None:
        wired["holder"] = {"exec_id": "e1", "done": False}
        socket = _Socket([{"type": "reconnect"}])
        await _run(socket)
        assert wired["streamed"] == ["e1"]

    @pytest.mark.asyncio
    async def test_nothing_running_is_said_plainly(self, wired) -> None:
        """Not an error: a phone that reconnects to a finished conversation is
        in a perfectly normal state and should show a composer, not a failure."""
        socket = _Socket([{"type": "reconnect"}])
        await _run(socket)
        assert wired["streamed"] == []
        idle = [m for m in socket.of_type("status") if m["data"]["status"] == "idle"]
        assert idle and socket.of_type("error") == []

    @pytest.mark.asyncio
    async def test_a_finished_turn_is_not_rejoined(self, wired) -> None:
        wired["holder"] = {"exec_id": "e1", "done": True}
        socket = _Socket([{"type": "reconnect"}])
        await _run(socket)
        assert wired["streamed"] == []


class TestReplayCursor:
    def test_the_cursor_is_fixed_at_execution_start(self) -> None:
        """The reason a phone misses nothing: the holder's cursor is where the
        execution began, and the streamer reads it without advancing it. If it
        ever wrote back, a reconnecting client would resume where the DEAD
        connection stopped and lose everything in between."""
        source = (module.__file__ or "").replace(".pyc", ".py")
        with open(source, encoding="utf-8") as fh:
            body = fh.read()
        assert 'cache_cursor = holder.get("cache_cursor", 0)' in body
        assert 'holder["cache_cursor"]' not in body
