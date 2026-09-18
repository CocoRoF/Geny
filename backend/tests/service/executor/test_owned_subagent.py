"""Owning a companion sub-agent is a property of the SESSION.

It has been three things. First a hardcode (``role == VTUBER``), then a
declaration on the ENVIRONMENT (``host_selections.extras.owned_subagent``) —
which meant "give this one a companion" required building it a whole
environment. There is one environment now, so it is back where it belongs:
on the session, with the role deciding what a new one starts with.
"""

from __future__ import annotations

import types

from service.executor.agent_session_manager import AgentSessionManager


def _mgr(record=None):
    mgr = object.__new__(AgentSessionManager)
    mgr._store = types.SimpleNamespace(get=lambda _sid: record)
    return mgr


def test_a_vtuber_starts_with_one():
    assert _mgr({"role": "vtuber"})._owned_subagent("s1") == {"enabled": True}


def test_a_worker_does_not():
    assert _mgr({"role": "worker"})._owned_subagent("s1") is None


def test_the_sessions_own_record_wins_over_its_role():
    # A worker given a companion keeps it …
    given = _mgr({"role": "worker", "owned_subagent": {"enabled": True}})
    assert given._owned_subagent("s1") == {"enabled": True}
    # … and a VTuber denied one stays denied.
    denied = _mgr({"role": "vtuber", "owned_subagent": {"enabled": False}})
    assert denied._owned_subagent("s1") is None


def test_the_role_can_be_passed_when_the_record_is_not_written_yet():
    """At creation the record may not exist; the caller knows the role."""
    assert _mgr(None)._owned_subagent(None, "vtuber") == {"enabled": True}
    assert _mgr(None)._owned_subagent(None, "worker") is None


def test_a_broken_store_falls_back_to_the_role():
    mgr = object.__new__(AgentSessionManager)

    def _boom(_sid):
        raise RuntimeError("store down")

    mgr._store = types.SimpleNamespace(get=_boom)
    assert mgr._owned_subagent("s1", "vtuber") == {"enabled": True}


def test_a_vtuber_can_delegate_gapt_work_and_a_worker_has_no_need_to():
    """The persona stays lean and sends project/sandbox work to a sub-worker
    carrying those nine tools; a worker holds them itself."""
    vtuber = _mgr({"role": "vtuber"})._subworker_types("s1")
    assert [t["agent_type"] for t in vtuber] == ["gapt"]
    assert "gapt_deploy" in vtuber[0]["allowed_tools"]
    assert _mgr({"role": "worker"})._subworker_types("s1") == []
