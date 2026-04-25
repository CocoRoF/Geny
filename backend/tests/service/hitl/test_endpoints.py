"""Endpoint tests for /api/agents/{id}/hitl/* (G2.5).

We don't spin up FastAPI's TestClient — the agent_controller pulls
the AgentSessionManager singleton which requires a configured app
state. Instead we call the route handler functions directly with
stub agents, which is the same contract the production wsgi layer
exercises.

Skipped when fastapi isn't importable (the geny-executor venv used
by some local sweeps doesn't ship the full backend deps; CI runs
with the production dev requirements installed).
"""

from __future__ import annotations

from typing import Any, List
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

import controller.agent_controller as agent_controller
from controller.agent_controller import (
    HITLPendingResponse,
    HITLResumeRequest,
    cancel_hitl,
    list_pending_hitl,
    resume_hitl,
)


# ── stubs ────────────────────────────────────────────────────────────


class _StubPipeline:
    def __init__(
        self,
        *,
        pending: List[str] | None = None,
        has_resume: bool = True,
        has_cancel: bool = True,
        resume_raises: Exception | None = None,
        cancel_returns: bool = True,
    ) -> None:
        self._pending = list(pending or [])
        self._cancel_returns = cancel_returns
        if has_resume:

            def _resume(token: str, decision: Any):
                if resume_raises is not None:
                    raise resume_raises
                self._pending = [t for t in self._pending if t != token]

            self.resume = _resume
        if has_cancel:
            self.cancel_pending_hitl = lambda token: bool(self._cancel_returns)

    def list_pending_hitl(self):
        return list(self._pending)


class _StubAgent:
    def __init__(self, pipeline: Any | None) -> None:
        self._pipeline = pipeline


@pytest.fixture(autouse=True)
def _patch_agent_manager(monkeypatch):
    """Replace the controller's agent_manager singleton with a stub."""
    mgr = MagicMock()
    monkeypatch.setattr(agent_controller, "agent_manager", mgr)
    yield mgr


def _bind_agent(mgr, agent: _StubAgent | None) -> None:
    mgr.get_agent = MagicMock(return_value=agent)


# ── /hitl/pending ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_pending_returns_token_list(_patch_agent_manager) -> None:
    pipe = _StubPipeline(pending=["tok-a", "tok-b"])
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    resp = await list_pending_hitl(session_id="s1", auth={})
    assert isinstance(resp, HITLPendingResponse)
    assert resp.session_id == "s1"
    assert [p.token for p in resp.pending] == ["tok-a", "tok-b"]


@pytest.mark.asyncio
async def test_list_pending_empty(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(pending=[])))
    resp = await list_pending_hitl(session_id="s1", auth={})
    assert resp.pending == []


@pytest.mark.asyncio
async def test_list_pending_unknown_session_404(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, None)
    with pytest.raises(HTTPException) as exc:
        await list_pending_hitl(session_id="ghost", auth={})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_list_pending_no_pipeline_409(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(pipeline=None))
    with pytest.raises(HTTPException) as exc:
        await list_pending_hitl(session_id="s1", auth={})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_list_pending_pipeline_without_resume_api_returns_empty(
    _patch_agent_manager,
) -> None:
    """Mixed-version deployments: a pipeline built before geny-executor
    1.0 has no ``list_pending_hitl`` — degrade to empty list instead
    of 500."""
    pipe = _StubPipeline()
    delattr(pipe, "list_pending_hitl")
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    resp = await list_pending_hitl(session_id="s1", auth={})
    assert resp.pending == []


# ── /hitl/resume ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_happy_path(_patch_agent_manager) -> None:
    pipe = _StubPipeline(pending=["tok-1"])
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    resp = await resume_hitl(
        body=HITLResumeRequest(token="tok-1", decision="approve"),
        session_id="s1",
        auth={},
    )
    assert resp == {
        "session_id": "s1",
        "token": "tok-1",
        "decision": "approve",
        "resumed": True,
    }


@pytest.mark.asyncio
async def test_resume_unknown_token_409(_patch_agent_manager) -> None:
    pipe = _StubPipeline(resume_raises=KeyError("tok-x"))
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    with pytest.raises(HTTPException) as exc:
        await resume_hitl(
            body=HITLResumeRequest(token="tok-x", decision="approve"),
            session_id="s1",
            auth={},
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_already_resolved_409(_patch_agent_manager) -> None:
    pipe = _StubPipeline(resume_raises=RuntimeError("already resolved"))
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    with pytest.raises(HTTPException) as exc:
        await resume_hitl(
            body=HITLResumeRequest(token="tok-1", decision="approve"),
            session_id="s1",
            auth={},
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_resume_unknown_decision_400(_patch_agent_manager) -> None:
    pipe = _StubPipeline(resume_raises=ValueError("unknown decision"))
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    with pytest.raises(HTTPException) as exc:
        await resume_hitl(
            body=HITLResumeRequest(token="tok-1", decision="huh"),
            session_id="s1",
            auth={},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_resume_pipeline_without_resume_api_409(_patch_agent_manager) -> None:
    pipe = _StubPipeline(has_resume=False)
    _bind_agent(_patch_agent_manager, _StubAgent(pipe))
    with pytest.raises(HTTPException) as exc:
        await resume_hitl(
            body=HITLResumeRequest(token="tok-1", decision="approve"),
            session_id="s1",
            auth={},
        )
    assert exc.value.status_code == 409


# ── DELETE /hitl/{token} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_happy_path(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(cancel_returns=True)))
    resp = await cancel_hitl(session_id="s1", token="tok-1", auth={})
    assert resp == {"session_id": "s1", "token": "tok-1", "cancelled": True}


@pytest.mark.asyncio
async def test_cancel_unknown_token_returns_false(_patch_agent_manager) -> None:
    _bind_agent(
        _patch_agent_manager, _StubAgent(_StubPipeline(cancel_returns=False))
    )
    resp = await cancel_hitl(session_id="s1", token="ghost", auth={})
    assert resp["cancelled"] is False


@pytest.mark.asyncio
async def test_cancel_pipeline_without_api_409(_patch_agent_manager) -> None:
    _bind_agent(_patch_agent_manager, _StubAgent(_StubPipeline(has_cancel=False)))
    with pytest.raises(HTTPException) as exc:
        await cancel_hitl(session_id="s1", token="tok-1", auth={})
    assert exc.value.status_code == 409
