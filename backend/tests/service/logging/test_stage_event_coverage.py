"""Pin the stage-event coverage added in cycle 20260421_3 / plan 02.

Before this cycle, ``agent_session._invoke_pipeline`` translated
``stage.enter`` / ``stage.exit`` but silently dropped ``stage.bypass``
and ``stage.error`` — so the log panel couldn't show a skipped-slot
or a failed stage at all. These tests script a fake pipeline that
yields the neglected events and assert that matching session_logger
entries are written with the right level + metadata.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from service.executor.agent_session import AgentSession
from service.logging.session_logger import LogLevel, SessionLogger


class _FakeEvent:
    """PipelineEvent stand-in — matches the attributes agent_session inspects."""

    def __init__(
        self,
        event_type: str,
        data: Dict[str, Any] | None = None,
        *,
        stage: str | None = None,
        iteration: int | None = None,
    ) -> None:
        self.type = event_type
        self.data = data or {}
        if stage is not None:
            self.stage = stage
        if iteration is not None:
            self.iteration = iteration


class _FakePipeline:
    def __init__(self, events: List[_FakeEvent]) -> None:
        self._events = events

    async def run_stream(self, input_text: str, state: Any):
        for evt in self._events:
            yield evt


def _make_session(
    events: List[_FakeEvent], tmp_path
) -> Tuple[AgentSession, SessionLogger]:
    session = AgentSession(session_id="s-test", session_name="T")
    session._pipeline = _FakePipeline(events)  # type: ignore[assignment]
    session._execution_count = 0
    sl = SessionLogger(session_id="s-test", logs_dir=str(tmp_path))
    return session, sl


def _success_tail() -> List[_FakeEvent]:
    return [
        _FakeEvent(
            "pipeline.complete",
            {"result": "", "total_cost_usd": 0.0, "iterations": 0},
        ),
    ]


# ─────────────────────────────────────────────────────────────────
# stage.bypass / stage.error translation
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage_bypass_produces_session_log_entry(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("stage.bypass", {"reason": "slot empty"}, stage="cache", iteration=0),
            *_success_tail(),
        ],
        tmp_path,
    )
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=sl)

    entries, _ = sl.get_cache_entries_since(0)
    bypass = [e for e in entries if e.metadata.get("event_type") == "stage_bypass"]
    assert len(bypass) == 1
    meta = bypass[0].metadata
    assert bypass[0].level == LogLevel.STAGE
    assert meta["stage_name"] == "cache"
    assert meta["stage_order"] == 5
    assert meta["stage_display_name"] == "s05_cache"
    assert meta["data"]["reason"] == "slot empty"


@pytest.mark.asyncio
async def test_stage_error_produces_session_log_entry(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("stage.error", {"error": "boom"}, stage="tool", iteration=2),
            *_success_tail(),
        ],
        tmp_path,
    )
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=sl)

    entries, _ = sl.get_cache_entries_since(0)
    err = [e for e in entries if e.metadata.get("event_type") == "stage_error"]
    assert len(err) == 1
    meta = err[0].metadata
    assert err[0].level == LogLevel.STAGE
    assert meta["stage_name"] == "tool"
    assert meta["stage_order"] == 10
    assert meta["stage_display_name"] == "s10_tool"
    assert meta["iteration"] == 2
    assert meta["data"]["error"] == "boom"


# ─────────────────────────────────────────────────────────────────
# stage.enter — metadata upgrade (order + display name + iteration)
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage_enter_carries_order_and_iteration(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("stage.enter", stage="yield", iteration=4),
            *_success_tail(),
        ],
        tmp_path,
    )
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=sl)

    entries, _ = sl.get_cache_entries_since(0)
    enters = [e for e in entries if e.metadata.get("event_type") == "stage_enter"]
    assert len(enters) == 1
    meta = enters[0].metadata
    # yield moved 16 → 21 in the geny-executor 1.0 21-stage layout.
    assert meta["stage_order"] == 21
    assert meta["stage_display_name"] == "s21_yield"
    assert meta["iteration"] == 4


# ─────────────────────────────────────────────────────────────────
# pipeline lifecycle events
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_start_logs_execution_start_entry(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("pipeline.start", {}),
            *_success_tail(),
        ],
        tmp_path,
    )
    await session._invoke_pipeline("hi there", start_time=0.0, session_logger=sl)

    entries, _ = sl.get_cache_entries_since(0)
    starts = [e for e in entries if e.metadata.get("event_type") == "execution_start"]
    assert len(starts) == 1
    assert starts[0].metadata["data"]["execution_mode"] == "invoke"


@pytest.mark.asyncio
async def test_pipeline_error_writes_error_level_entry(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("pipeline.error", {"error": "kaboom"}),
        ],
        tmp_path,
    )
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=sl)

    entries, _ = sl.get_cache_entries_since(0)
    errors = [
        e for e in entries
        if e.level == LogLevel.ERROR and "Pipeline error" in (e.message or "")
    ]
    assert len(errors) == 1
    assert errors[0].metadata.get("source") == "pipeline"


# ─────────────────────────────────────────────────────────────────
# astream path — parity check
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_astream_path_also_translates_bypass(tmp_path) -> None:
    session, sl = _make_session(
        [
            _FakeEvent("stage.bypass", stage="think", iteration=1),
            _FakeEvent("text.delta", {"text": "hi"}),
            *_success_tail(),
        ],
        tmp_path,
    )
    async for _ in session._astream_pipeline("hi", start_time=0.0, session_logger=sl):
        pass

    entries, _ = sl.get_cache_entries_since(0)
    bypass = [e for e in entries if e.metadata.get("event_type") == "stage_bypass"]
    assert len(bypass) == 1
    assert bypass[0].metadata["stage_name"] == "think"
    assert bypass[0].metadata["stage_order"] == 8
