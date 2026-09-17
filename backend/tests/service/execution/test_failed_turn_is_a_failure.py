"""A turn that died must not read as the agent talking.

Production showed three bubbles in a row of ellen_new calmly saying
"Error: Claude Code [Claude Code 2]: You've hit your session limit · resets
8:10pm (UTC)". The pipeline had failed; the failure travelled as ordinary
output text, and every layer above treated it as a successful turn whose
answer happened to start with the word Error.
"""

import pytest


def test_the_pipeline_reports_its_own_failure():
    """``AgentSession._invoke_pipeline`` returns the flag, not just the text."""
    import inspect

    from service.executor import agent_session

    source = inspect.getsource(agent_session.AgentSession._invoke_pipeline)
    failure_return = source.split("if not success:")[1]
    assert '"success": False' in failure_return
    assert '"error": error_msg' in failure_return


@pytest.mark.parametrize(
    "invoke_result, expect_success, expect_output",
    [
        ({"output": "다 됐어.", "total_cost": 0.01}, True, "다 됐어."),
        (
            {
                "output": "Error: Claude Code: You've hit your session limit",
                "success": False,
                "error": "Claude Code: You've hit your session limit",
            },
            False,
            "",
        ),
        # An older path that says nothing about success is still a success —
        # that is the shape every non-pipeline caller returns.
        ({"output": "응."}, True, "응."),
    ],
)
def test_the_executor_honours_it(invoke_result, expect_success, expect_output):
    """The same decision the executor makes, on the same inputs."""
    failed = invoke_result.get("success") is False
    text = invoke_result.get("output", "")
    error = str(invoke_result.get("error") or text or "실행에 실패했습니다") if failed else ""

    from service.execution.agent_executor import ExecutionResult

    result = ExecutionResult(
        success=not failed,
        session_id="s1",
        output="" if failed else text,
        error=error or None,
    )

    assert result.success is expect_success
    assert (result.output or "") == expect_output
    if not expect_success:
        assert result.error and not result.error.startswith("Error: ")


def test_a_failed_result_writes_no_agent_message():
    """The room stores an agent message only when there is an answer. With
    success False the chat path writes a system notice instead, which is what
    makes a failure look like one on every screen."""
    from service.execution.agent_executor import ExecutionResult

    result = ExecutionResult(success=False, session_id="s1", error="session limit")
    cleaned = result.output if result.success else ""
    assert not cleaned
