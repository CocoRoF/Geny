"""Regression guard: no runtime code writes to ``agent._system_prompt``.

Cycle 20260421_7 X1 tore out 5 side-doors that mutated
``AgentSession._system_prompt`` directly. After PR-X1-3, the only writes
that remain are:

* ``agent_session.__init__`` — self-assignment from the constructor kwarg
  (``self._system_prompt = system_prompt``), which is an immutable initial
  seed, not a mutation side-door. Preserved so ``SessionInfo.system_prompt``
  continues to report what the session was constructed with.

* Tests under ``backend/tests/`` — may exercise the legacy attribute
  for regression cases.

Anything else is a re-introduced side-door and must be rejected.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[4]
_BACKEND = _REPO_ROOT / "backend"

# Pattern: ``<something>._system_prompt = <rhs>``. Permit the init kwarg
# self-assignment (`self._system_prompt = system_prompt`) via an allowlist.
_WRITE_RE = re.compile(r"\._system_prompt\s*=\s*")

_ALLOWED_WRITES = {
    # AgentSession.__init__: immutable initial seed.
    ("backend/service/langgraph/agent_session.py", "self._system_prompt = system_prompt"),
}


def _iter_python_sources():
    for py in _BACKEND.rglob("*.py"):
        rel = py.relative_to(_REPO_ROOT).as_posix()
        if rel.startswith("backend/tests/"):
            continue
        yield py, rel


def test_no_runtime_writes_to_agent_system_prompt() -> None:
    offenders: list[str] = []
    for py, rel in _iter_python_sources():
        text = py.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if not _WRITE_RE.search(line):
                continue
            stripped = line.strip()
            if (rel, stripped) in _ALLOWED_WRITES:
                continue
            offenders.append(f"{rel}:{line_no}: {stripped}")
    assert not offenders, (
        "New ``agent._system_prompt = …`` side-door detected. Route the "
        "mutation through ``AgentSessionManager.persona_provider`` "
        "(set_static_override / set_character / append_context). "
        "Offenders:\n  " + "\n  ".join(offenders)
    )


def test_allowlisted_init_assignment_still_present() -> None:
    """Sanity check — the one permitted assignment must still exist in
    ``AgentSession.__init__``. If it moves or is renamed, the allowlist
    above needs to be updated."""
    target = _BACKEND / "service" / "langgraph" / "agent_session.py"
    text = target.read_text(encoding="utf-8")
    assert "self._system_prompt = system_prompt" in text
