"""Companion runtime contract — the owner's workspace, the host's auth.

The companion's tools run in the OWNER's sandbox (one unified workspace)
while its LLM is called from the host with the credentials Geny
configured. Nothing is ever spawned into the container: executor 2.68.0
removed the last path that could (``containerize_cli``), which is what
caused the 2026-07-15 regression — the companion's CLI ran inside the
gapt-ws container with its own baked binary and no Geny auth, failing
every delegated turn with authentication_failed while the owner kept
working.
"""

from __future__ import annotations

from types import SimpleNamespace

from service.vtuber.sub_agent_bridge import _companion_attach_kwargs


class TestCompanionAttachContract:
    def _ctx(self, **over):
        base = {
            "sub_agent_id": "owner-1-subagent",
            "working_dir": "/data/geny_agent_sessions/owner-1",
            "storage_path": "/data/geny_agent_sessions/owner-1",
            "sandbox": SimpleNamespace(container_name="gapt-ws-x"),
        }
        base.update(over)
        return base

    def test_sandbox_is_a_tool_surface_only(self):
        """THE invariant: the owner's sandbox reaches the companion as a
        TOOL surface, and nothing else is handed to the executor that
        could put a provider inside it (``containerize_cli`` is gone as
        of executor 2.68.0 — passing it now raises TypeError)."""
        kwargs = _companion_attach_kwargs(self._ctx())
        assert kwargs["sandbox"].container_name == "gapt-ws-x"
        assert "containerize_cli" not in kwargs

    def test_no_sandbox_attaches_none(self):
        kwargs = _companion_attach_kwargs(self._ctx(sandbox=None))
        assert "sandbox" not in kwargs
        assert "containerize_cli" not in kwargs

    def test_tool_context_carries_owner_workspace(self):
        kwargs = _companion_attach_kwargs(self._ctx())
        tc = kwargs["tool_context"]
        assert tc.session_id == "owner-1-subagent"
        assert tc.working_dir == "/data/geny_agent_sessions/owner-1"
        assert tc.storage_path == "/data/geny_agent_sessions/owner-1"
