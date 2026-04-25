"""Pin the LogLevel.STAGE rename and the new log_stage_* helpers.

Cycle 20260421_3 / plan 01: the Geny log panel migrated from the
legacy LangGraph "Graph" terminology to the geny-executor Environment
"Stage" model. These tests lock down the contract: the new level
exists, the new helpers fire at that level and carry stage_order /
stage_display_name / iteration metadata, the legacy ``log_graph_*``
wrappers still work (routing to STAGE level), and the locally-mirrored
stage-order table stays in sync with the executor's private name map.
"""

from __future__ import annotations

import pytest

from service.logging.session_logger import (
    LogLevel,
    SessionLogger,
    STAGE_ORDER,
    stage_display_name,
)


# ─────────────────────────────────────────────────────────────────
# Enum + constants
# ─────────────────────────────────────────────────────────────────


def test_loglevel_stage_and_graph_both_present() -> None:
    """STAGE is the new preferred level; GRAPH stays for legacy DB rows."""
    assert LogLevel.STAGE.value == "STAGE"
    assert LogLevel.GRAPH.value == "GRAPH"
    # Deserializing persisted strings must not raise
    assert LogLevel("STAGE") is LogLevel.STAGE
    assert LogLevel("GRAPH") is LogLevel.GRAPH


def test_stage_order_table_covers_21_stages_in_order() -> None:
    """geny-executor 1.0+ Sub-phase 9a widened the layout to 21 slots."""
    assert len(STAGE_ORDER) == 21
    assert STAGE_ORDER["input"] == 1
    assert STAGE_ORDER["loop"] == 16
    assert STAGE_ORDER["yield"] == 21
    # New scaffold orders.
    assert STAGE_ORDER["tool_review"] == 11
    assert STAGE_ORDER["task_registry"] == 13
    assert STAGE_ORDER["hitl"] == 15
    assert STAGE_ORDER["summarize"] == 19
    assert STAGE_ORDER["persist"] == 20
    # Monotonic 1..21
    orders = sorted(STAGE_ORDER.values())
    assert orders == list(range(1, 22))


def test_stage_order_table_matches_executor_names() -> None:
    """Guardrail: if geny-executor renames a stage this test must fail
    loudly so the local table can be updated in lockstep instead of
    silently drifting."""
    from geny_executor.core.pipeline import Pipeline

    expected = dict(Pipeline._DEFAULT_STAGE_NAMES)  # {order: name}
    assert set(STAGE_ORDER.keys()) == set(expected.values())
    for order, name in expected.items():
        assert STAGE_ORDER[name] == order, (
            f"Stage {name!r} order drift: executor={order}, "
            f"local={STAGE_ORDER[name]}"
        )


def test_stage_display_name_formats_with_order_padding() -> None:
    assert stage_display_name("yield", 21) == "s21_yield"
    assert stage_display_name("input", 1) == "s01_input"
    # Unknown stage falls back to raw name
    assert stage_display_name("custom", None) == "custom"


# ─────────────────────────────────────────────────────────────────
# log_stage_* helpers
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sl(tmp_path) -> SessionLogger:
    return SessionLogger(session_id="test-sid", logs_dir=str(tmp_path))


def _last(sl: SessionLogger):
    entries, _ = sl.get_cache_entries_since(0)
    return entries[-1]


def test_log_stage_enter_writes_stage_level_with_metadata(sl) -> None:
    sl.log_stage_enter(stage_name="yield", stage_order=16, iteration=3)
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    meta = entry.metadata
    assert meta["event_type"] == "stage_enter"
    assert meta["stage_name"] == "yield"
    assert meta["stage_order"] == 16
    assert meta["stage_display_name"] == "s16_yield"
    assert meta["iteration"] == 3
    # Legacy mirror kept for old frontend code
    assert meta["node_name"] == "yield"


def test_log_stage_exit_includes_duration_when_present(sl) -> None:
    sl.log_stage_exit(
        stage_name="tool", stage_order=10, iteration=2,
        output_preview="42", duration_ms=123,
    )
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    assert entry.metadata["event_type"] == "stage_exit"
    assert entry.metadata["stage_display_name"] == "s10_tool"
    assert entry.metadata["data"]["duration_ms"] == 123
    assert entry.metadata["data"]["output_preview"] == "42"


def test_log_stage_bypass_records_skip(sl) -> None:
    sl.log_stage_bypass(stage_name="cache", stage_order=5, iteration=0, reason="slot empty")
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    assert entry.metadata["event_type"] == "stage_bypass"
    assert entry.metadata["stage_display_name"] == "s05_cache"
    assert entry.metadata["data"]["reason"] == "slot empty"


def test_log_stage_error_records_failure(sl) -> None:
    sl.log_stage_error(stage_name="tool", stage_order=10, iteration=1, error="boom")
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    assert entry.metadata["event_type"] == "stage_error"
    assert entry.metadata["data"]["error"] == "boom"


def test_log_stage_enter_handles_unknown_stage_gracefully(sl) -> None:
    """If a future stage name isn't in STAGE_ORDER, the call must still
    record (just without a number prefix) — never raise."""
    sl.log_stage_enter(stage_name="newstage", stage_order=None, iteration=0)
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    assert entry.metadata["stage_name"] == "newstage"
    # stage_order is omitted when None (dropped during metadata cleanup)
    assert "stage_order" not in entry.metadata
    assert entry.metadata["stage_display_name"] == "newstage"


# ─────────────────────────────────────────────────────────────────
# Legacy log_graph_* wrappers
# ─────────────────────────────────────────────────────────────────


def test_legacy_log_graph_event_still_works_and_writes_stage(sl) -> None:
    sl.log_graph_event(
        event_type="node_enter",
        message="→ yield",
        node_name="yield",
    )
    entry = _last(sl)
    # New writes route to STAGE regardless of which helper was called.
    assert entry.level == LogLevel.STAGE
    # stage_order populated from the local lookup so existing callers
    # automatically get the metadata upgrade. yield moved 16 → 21 in
    # the geny-executor 1.0 21-stage layout.
    assert entry.metadata["stage_order"] == 21


def test_legacy_log_graph_node_enter_populates_stage_metadata(sl) -> None:
    sl.log_graph_node_enter(node_name="tool", iteration=4)
    entry = _last(sl)
    assert entry.level == LogLevel.STAGE
    assert entry.metadata["stage_order"] == 10
    assert entry.metadata["stage_display_name"] == "s10_tool"
    assert entry.metadata["iteration"] == 4
