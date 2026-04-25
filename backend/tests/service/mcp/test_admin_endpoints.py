"""Endpoint tests for /api/agents/{id}/mcp/* (G8.1).

Same shape as test_endpoints.py for HITL — call the route handler
functions directly with stub agents, skipping FastAPI's TestClient.

Skipped when fastapi isn't importable (geny-executor venv).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

import controller.agent_controller as agent_controller  # noqa: E402
from controller.agent_controller import (  # noqa: E402
    MCPServerAddRequest,
    add_mcp_server,
    control_mcp_server,
    disconnect_mcp_server,
    list_mcp_servers,
)


class _StubManager:
    def __init__(
        self,
        servers: dict[str, str] | None = None,
        connect_raises: Exception | None = None,
    ):
        self._states = dict(servers or {})
        self._configs = {n: {} for n in self._states}
        self._connect_raises = connect_raises

    def server_names(self) -> list[str]:
        return list(self._configs)

    def get_state(self, name: str) -> str:
        return self._states.get(name, "unknown")

    def connect(self, name: str, config: dict) -> None:
        if self._connect_raises is not None:
            raise self._connect_raises
        self._configs[name] = config
        self._states[name] = "connected"

    def disconnect(self, name: str) -> None:
        self._configs.pop(name, None)
        self._states.pop(name, None)

    def disable_server(self, name: str) -> None:
        self._states[name] = "disabled"

    def enable_server(self, name: str) -> None:
        self._states[name] = "connected"

    def test_connection(self, name: str) -> str:
        return f"ok:{name}"


class _StubPipeline:
    def __init__(self, manager: Any | None) -> None:
        self._mcp_manager = manager


class _StubAgent:
    def __init__(self, pipeline: Any | None) -> None:
        self._pipeline = pipeline


@pytest.fixture(autouse=True)
def _patch_agent_manager(monkeypatch):
    mgr = MagicMock()
    monkeypatch.setattr(agent_controller, "agent_manager", mgr)
    yield mgr


def _bind_agent(mgr, agent: _StubAgent | None) -> None:
    mgr.get_agent = MagicMock(return_value=agent)


# ── /mcp/servers (GET) ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_known_servers(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"fs": "connected", "git": "needs_auth"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await list_mcp_servers(session_id="s1", auth={})
    assert resp.session_id == "s1"
    by_name = {s.name: s.state for s in resp.servers}
    assert by_name == {"fs": "connected", "git": "needs_auth"}


@pytest.mark.asyncio
async def test_list_empty_when_no_servers(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(_StubManager())))
    resp = await list_mcp_servers(session_id="s1", auth={})
    assert resp.servers == []


@pytest.mark.asyncio
async def test_list_unknown_session_404(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, None)
    with pytest.raises(HTTPException) as exc:
        await list_mcp_servers(session_id="ghost", auth={})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_no_manager_409(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(None)))
    with pytest.raises(HTTPException) as exc:
        await list_mcp_servers(session_id="s1", auth={})
    assert exc.value.status_code == 409


# ── /mcp/servers (POST) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_happy_path(_patch_agent_manager) -> None:
    manager = _StubManager()
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await add_mcp_server(
        body=MCPServerAddRequest(name="newsrv", config={"command": "echo"}),
        session_id="s1",
        auth={},
    )
    assert resp["session_id"] == "s1"
    assert resp["server"]["name"] == "newsrv"
    assert resp["server"]["state"] == "connected"


@pytest.mark.asyncio
async def test_add_connect_raises_400(_patch_agent_manager) -> None:
    manager = _StubManager(connect_raises=RuntimeError("boom"))
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    with pytest.raises(HTTPException) as exc:
        await add_mcp_server(
            body=MCPServerAddRequest(name="x", config={}),
            session_id="s1",
            auth={},
        )
    assert exc.value.status_code == 400


# ── DELETE /mcp/servers/{name} ──────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnect_happy_path(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"x": "connected"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await disconnect_mcp_server(session_id="s1", name="x", auth={})
    assert resp["disconnected"] is True
    assert "x" not in manager._configs


# ── POST /mcp/servers/{name}/{action} ────────────────────────────────


@pytest.mark.asyncio
async def test_disable_action(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"x": "connected"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await control_mcp_server(
        session_id="s1", name="x", action="disable", auth={}
    )
    assert resp["server"]["state"] == "disabled"


@pytest.mark.asyncio
async def test_enable_action(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"x": "disabled"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await control_mcp_server(
        session_id="s1", name="x", action="enable", auth={}
    )
    assert resp["server"]["state"] == "connected"


@pytest.mark.asyncio
async def test_test_action(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"x": "connected"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    resp = await control_mcp_server(
        session_id="s1", name="x", action="test", auth={}
    )
    assert resp["result"] == "ok:x"


@pytest.mark.asyncio
async def test_unknown_action_400(_patch_agent_manager) -> None:
    manager = _StubManager(servers={"x": "connected"})
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(manager)))
    with pytest.raises(HTTPException) as exc:
        await control_mcp_server(
            session_id="s1", name="x", action="explode", auth={}
        )
    assert exc.value.status_code == 400
