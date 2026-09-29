"""Conversation-level ``state.shared`` keys survive the fresh state each turn.

Each Geny turn starts from a new PipelineState. The executor's
read-before-overwrite ledger lives in ``state.shared``; without carrying it
the agent "had never read" a file it read one message ago, and Write refused
to replace it.
"""

from geny_executor.core.state import PipelineState

from service.executor.agent_session import AgentSession


def _session():
    return object.__new__(AgentSession)


def test_the_file_ledger_carries_into_the_next_turn():
    agent = _session()
    previous = PipelineState(session_id="s")
    previous.shared["executor.file_witnessed"] = ["/workspace/a.md"]
    previous.shared["tool.denied_calls"] = {"Bash:x": "no"}  # per turn: not carried
    agent._running_turn_state = previous

    fresh = PipelineState(session_id="s")
    agent._carry_session_shared(fresh)
    assert fresh.shared["executor.file_witnessed"] == ["/workspace/a.md"]
    assert fresh.shared["executor.file_witnessed"] is not previous.shared["executor.file_witnessed"]
    assert "tool.denied_calls" not in fresh.shared


def test_first_turn_has_nothing_to_carry():
    agent = _session()
    fresh = PipelineState(session_id="s")
    agent._carry_session_shared(fresh)
    assert "executor.file_witnessed" not in fresh.shared
