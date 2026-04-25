"""Endpoint test for G15 — pipeline introspection.

Skipped when fastapi isn't importable (test venv). The handler is
called directly with a stub agent to avoid spinning the FastAPI
TestClient.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

import controller.agent_controller as agent_controller  # noqa: E402
from controller.agent_controller import introspect_pipeline  # noqa: E402


class _StubStage:
    def __init__(self, name: str, order: int) -> None:
        self.name = name
        self.order = order
        self.artifact = "default"


class _StubPipeline:
    def __init__(self, stages: list[_StubStage]) -> None:
        self._stages_list = stages

    @property
    def stages(self) -> list[_StubStage]:
        return self._stages_list


class _StubAgent:
    def __init__(self, pipeline: Any) -> None:
        self._pipeline = pipeline


@pytest.fixture(autouse=True)
def _patch_agent_manager(monkeypatch):
    mgr = MagicMock()
    monkeypatch.setattr(agent_controller, "agent_manager", mgr)
    yield mgr


def _bind(mgr, agent: _StubAgent | None) -> None:
    mgr.get_agent = MagicMock(return_value=agent)


@pytest.mark.asyncio
async def test_unknown_session_404(_patch_agent_manager) -> None:
    _bind(_patch_agent_manager, None)
    with pytest.raises(HTTPException) as exc:
        await introspect_pipeline(session_id="ghost", auth={})
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_introspect_returns_stages(_patch_agent_manager) -> None:
    """Real introspect_all walks the executor's stage catalog. The
    response should carry every stage in the v3 layout (1..21 minus
    any stages this build dropped). We assert presence of a few
    canonical stage names rather than exact count, so a future
    executor pin that adds optional stages still passes."""
    pipeline = _StubPipeline([_StubStage("input", 1), _StubStage("yield", 21)])
    _bind(_patch_agent_manager, _StubAgent(pipeline))

    resp = await introspect_pipeline(session_id="s1", auth={})
    assert resp.session_id == "s1"
    names = {s.name for s in resp.stages}
    # Core stages every preset has — locks the response shape.
    assert {"input", "tool", "yield"}.issubset(names)
