"""B.1 (cycle 20260426_1) — session-param enforcement tests.

Verifies that ``AgentSession._apply_session_limits_to_pipeline`` mutates
the bound Pipeline's ``_config.max_iterations`` to the session-supplied
value, so the executor's iteration guards see the user's cap rather than
the manifest default.

Direct method-level tests against a fake Pipeline avoid spinning the
full ``initialize()`` path (which requires manifest, env, MCP, and
memory wiring). The unit tests here lock the contract of the helper:
the call site in ``_build_pipeline`` is a one-liner and is covered by
existing manager-level tests once exercised.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

# AgentSession's transitive imports require pydantic (sessions.models),
# which the bare test venv does not provide. Skip cleanly here so local
# `pytest backend/tests` runs stay green; CI installs the full backend
# requirements and exercises the test for real.
pytest.importorskip("pydantic")

from service.executor.agent_session import AgentSession  # noqa: E402


def _make_session(
    max_iterations: int,
    *,
    context_window_budget=None,
    cost_budget_usd=None,
) -> AgentSession:
    """Construct a minimal AgentSession suitable for helper testing.

    We avoid calling ``initialize`` — only the attrs the helper reads
    are populated (``_pipeline``, ``_max_iterations``, ``_session_id``).
    """
    session = AgentSession.__new__(AgentSession)
    session._session_id = "test-session"
    session._max_iterations = max_iterations
    session._context_window_budget = context_window_budget
    session._cost_budget_usd = cost_budget_usd
    session._pipeline = None
    return session


def _fake_pipeline_with_config(initial_max_iterations: int) -> SimpleNamespace:
    config = SimpleNamespace(max_iterations=initial_max_iterations)
    return SimpleNamespace(_config=config)


def test_max_iterations_overrides_pipeline_default() -> None:
    """Session value 3 must overwrite the pipeline's manifest-default 50."""
    session = _make_session(max_iterations=3)
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=50)

    session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 3


def test_no_pipeline_is_silent_noop() -> None:
    """Pre-initialize sessions must not raise."""
    session = _make_session(max_iterations=10)
    session._pipeline = None
    # Must not raise.
    session._apply_session_limits_to_pipeline()


def test_pipeline_without_config_is_silent_noop() -> None:
    """Older executor builds without ``_config`` attr must be tolerated."""
    session = _make_session(max_iterations=10)
    session._pipeline = SimpleNamespace()  # no _config
    session._apply_session_limits_to_pipeline()  # must not raise


def test_zero_max_iterations_leaves_manifest_default() -> None:
    """A session value of 0 (treat as unset) must not clobber the manifest default."""
    session = _make_session(max_iterations=0)
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=50)

    session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 50


def test_negative_max_iterations_is_rejected() -> None:
    """Negative values are nonsense for an iteration cap; defer to manifest."""
    session = _make_session(max_iterations=-5)
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=50)

    session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 50


def test_invalid_max_iterations_is_logged_and_ignored(caplog) -> None:
    """A non-numeric ``_max_iterations`` (e.g. coming from a buggy
    upstream) must surface a warning but not raise — telemetry over
    crash for an advisory cap."""
    session = _make_session(max_iterations="not-a-number")  # type: ignore[arg-type]
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=50)

    with caplog.at_level(logging.WARNING):
        session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 50
    assert any(
        "invalid max_iterations" in rec.message
        for rec in caplog.records
    )


def test_idempotent_when_value_unchanged(caplog) -> None:
    """Re-applying the same value must not log a redundant ``X → X`` line."""
    session = _make_session(max_iterations=7)
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=7)

    with caplog.at_level(logging.INFO):
        session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 7
    assert not any(
        "session limit applied" in rec.message
        for rec in caplog.records
    )


def test_change_logged_when_value_overridden(caplog) -> None:
    """When the value changes, a single info line records the transition."""
    session = _make_session(max_iterations=12)
    session._pipeline = _fake_pipeline_with_config(initial_max_iterations=50)

    with caplog.at_level(logging.INFO):
        session._apply_session_limits_to_pipeline()

    assert session._pipeline._config.max_iterations == 12
    transition_lines = [
        rec for rec in caplog.records
        if "session limit applied" in rec.message
    ]
    assert len(transition_lines) == 1
    msg = transition_lines[0].getMessage()
    assert "50" in msg and "12" in msg


class TestTheBudgetsThatSizeTheHarness:
    """Two numbers the pipeline reads every turn and Geny never set.

    ``context_window_budget`` sizes proactive compaction and the Stage-4
    headroom guard: left at the library's 200_000 it compacts six times too
    late for a local server launched at 32k, where the request overflows
    before anything notices. ``cost_budget_usd`` is the spend ceiling — a
    route can hold several paid accounts and nothing bounded what a turn
    could spend on them.
    """

    @staticmethod
    def _pipeline(**config):
        defaults = {
            "max_iterations": 50,
            "context_window_budget": 200_000,
            "cost_budget_usd": None,
        }
        defaults.update(config)
        return SimpleNamespace(_config=SimpleNamespace(**defaults))

    def test_the_routes_window_is_applied(self) -> None:
        session = _make_session(50, context_window_budget=32_768)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.context_window_budget == 32_768

    def test_an_unknown_window_leaves_the_library_default(self) -> None:
        """No hop could say. Better the documented default than a guess —
        and the log line says it is an assumption."""
        session = _make_session(50, context_window_budget=None)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.context_window_budget == 200_000

    def test_a_nonsense_window_is_not_applied(self) -> None:
        session = _make_session(50, context_window_budget=0)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.context_window_budget == 200_000

    def test_a_cost_ceiling_is_applied(self) -> None:
        session = _make_session(50, cost_budget_usd=2.5)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.cost_budget_usd == 2.5

    def test_no_ceiling_stays_no_ceiling(self) -> None:
        session = _make_session(50, cost_budget_usd=None)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.cost_budget_usd is None

    def test_zero_means_no_ceiling_not_a_zero_ceiling(self) -> None:
        """A 0 ceiling would stop every turn before it started."""
        session = _make_session(50, cost_budget_usd=0)
        session._pipeline = self._pipeline()
        session._apply_session_limits_to_pipeline()
        assert session._pipeline._config.cost_budget_usd is None
