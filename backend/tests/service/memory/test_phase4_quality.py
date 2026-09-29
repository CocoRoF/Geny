"""Phase 4 quality fixes on the Geny side.

* ``memory_read`` on a missing note offers the nearest real filenames.
* An execution record says "partial" when the turn finished but its tools
  did not — a ✅ on it later read, from memory, as "that was done".
* The memory prompt tells the model the earlier turns are history.
"""

import json

from service.executor.agent_session import _turn_tool_stats
from service.memory.host_memory_tools_block import HostMemoryToolsBlock
from service.memory.manager import SessionMemoryManager, classify_outcome
from tools.built_in.memory_tools import _read_miss_payload


def test_a_missing_note_suggests_the_real_names():
    names = ["topics/project-geny.md", "daily/2026-09-29.md", "people/hrjang.md"]
    payload = json.loads(_read_miss_payload("project_geny.md", names))
    assert payload["error"].startswith("Note not found")
    assert payload["did_you_mean"][0] == "topics/project-geny.md"
    assert "do not guess" in payload["hint"]
    empty = json.loads(_read_miss_payload("x.md", []))
    assert "no notes yet" in empty["hint"]


def test_outcome_has_three_states():
    assert classify_outcome(False) == "failed"
    assert classify_outcome(True, tool_calls=5, tool_failures=0) == "ok"
    # Worked around a failure: still ok.
    assert classify_outcome(True, tool_calls=6, tool_failures=1, last_failed=False) == "ok"
    # Ended on a failure, or most calls failed: partial.
    assert classify_outcome(True, tool_calls=6, tool_failures=1, last_failed=True) == "partial"
    assert classify_outcome(True, tool_calls=4, tool_failures=2) == "partial"


def test_the_record_marks_a_partial_turn():
    entry = SessionMemoryManager._build_execution_entry(
        input_text="build it",
        result_state={"final_answer": "done", "tool_calls": 3, "tool_failures": 2, "tool_last_failed": 1},
        duration_ms=1200,
        execution_number=7,
        success=True,
    )
    assert entry.startswith("### [⚠️] Execution #7")
    assert "**Tools:** 3 call(s) · 2 failed" in entry
    assert "do not treat the task as done" in entry


def test_turn_tool_stats_skip_the_replayed_turns():
    class _S:
        metadata = {"memory.short_term_window": {"messages": 2}}
        messages = [
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "old", "is_error": True, "content": "x"}]},
            {"role": "assistant", "content": "earlier"},
            {"role": "user", "content": "now"},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a", "content": "ok"}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "b", "is_error": True, "content": "no"}]},
        ]

    assert _turn_tool_stats(_S()) == {"tool_calls": 2, "tool_failures": 1, "tool_last_failed": 1}


def test_the_memory_prompt_says_earlier_turns_are_history():
    assert "treat them as\nhistory, not as facts to re-verify" in HostMemoryToolsBlock().render(None)
