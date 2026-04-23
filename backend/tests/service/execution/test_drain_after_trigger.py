"""Drain-after-trigger guarantee for ``execute_command`` (Plan / Phase06).

Background
----------

``execute_command``'s post-execution ``finally`` block previously only
scheduled ``_drain_inbox`` when ``is_trigger`` was False. That gap meant
a Sub-Worker result queued into the inbox while the VTuber was running a
``[THINKING_TRIGGER:*]`` cycle would sit unread until the next genuine
user message — leaving the VTuber narrating "still waiting" while the
result was already in the queue.

The fix is intentionally tiny: the condition was relaxed to depend only
on the existing ``_draining_sessions`` re-entry guard. These tests pin
the new contract by inspecting the source so a future refactor cannot
silently re-introduce the regression.

We deliberately do *not* spin up a full ``execute_command`` here — that
would require mocking the entire agent / session / logger surface.
Instead the tests are structural and document *why* the line looks the
way it does so the next reader doesn't tighten the gate again.
"""

from __future__ import annotations

import inspect
import re

from service.execution import agent_executor


def test_post_execution_drain_runs_for_triggers_too() -> None:
    """The post-execution drain branch in ``execute_command`` must
    schedule ``_drain_inbox`` regardless of ``is_trigger``.

    We grep the source of ``execute_command`` for the drain branch and
    assert it does NOT condition on ``not is_trigger``. The
    ``_draining_sessions`` guard alone is enough to prevent recursion
    because ``_drain_inbox`` re-enters ``execute_command`` *without*
    ``is_trigger=True``.
    """
    source = inspect.getsource(agent_executor.execute_command)

    # Find the line that schedules the drain.
    drain_lines = [
        line for line in source.splitlines()
        if "_drain_inbox" in line and "create_task" in line
    ]
    assert drain_lines, (
        "expected execute_command to schedule _drain_inbox in its "
        "post-execution finally block"
    )

    # Locate the surrounding `if` for that scheduling.
    drain_idx = source.index("create_task(_drain_inbox")
    preceding = source[:drain_idx].splitlines()[-3:]
    guard = " ".join(line.strip() for line in preceding)

    assert "_draining_sessions" in guard, (
        "drain scheduling must still be guarded by _draining_sessions "
        f"to prevent recursion; got: {guard!r}"
    )
    assert not re.search(r"not\s+is_trigger", guard), (
        "drain scheduling must NOT condition on `not is_trigger` — "
        "thinking-trigger executions must also drain queued inbox "
        "messages so [SUB_WORKER_RESULT] doesn't sit unread; "
        f"got: {guard!r}"
    )


def test_async_path_also_drains_unconditionally() -> None:
    """The async-execution path in ``execute_command_async`` already
    drained unconditionally; verify the contract is still in place so
    both entry points behave the same.
    """
    source = inspect.getsource(agent_executor)

    # Two scheduling sites are expected (sync + async). Both must be
    # guarded only by ``_draining_sessions``, never by ``is_trigger``.
    sites = [
        m.start() for m in re.finditer(
            r"asyncio\.create_task\(_drain_inbox\(", source
        )
    ]
    assert len(sites) >= 2, (
        "expected at least two _drain_inbox scheduling sites "
        f"(sync + async); found {len(sites)}"
    )

    for site in sites:
        # Look at a small window before the scheduling line for the
        # surrounding `if` clause.
        window = source[max(0, site - 200):site]
        guard_line = window.splitlines()[-2] if len(window.splitlines()) >= 2 else ""
        assert "_draining_sessions" in guard_line, (
            f"drain site at offset {site} missing _draining_sessions guard; "
            f"saw: {guard_line!r}"
        )
        assert "is_trigger" not in guard_line, (
            f"drain site at offset {site} re-introduced is_trigger gating; "
            f"saw: {guard_line!r}"
        )
