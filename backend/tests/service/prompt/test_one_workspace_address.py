"""An agent has one address for its workspace, and the tools answer to it.

Production, same instruction, two providers: OpenAI wrote
``/workspace/harness-openai.txt`` and Claude Code wrote
``<host>/workspace/harness-claude.txt``, which the container mapper re-rooted
into ``workspace/workspace/harness-claude.txt``. Both were following the
prompt — it named the host path for the files workspace while the sandbox
tools only understood ``/workspace``, so it held two equally absolute answers
to "where am I".
"""

from service.prompt.sections import SectionLibrary


def _text(section) -> str:
    return section.content


def test_a_sandboxed_session_is_told_the_container_address():
    section = SectionLibrary.files_workspace("/workspace")
    assert "/workspace — uploads/" in _text(section)
    assert "/data/" not in _text(section)


def test_a_host_session_is_told_the_host_address():
    section = SectionLibrary.files_workspace("/data/geny_agent_sessions/s1/workspace")
    assert "/data/geny_agent_sessions/s1/workspace — uploads/" in _text(section)


def test_the_address_is_never_doubled():
    """The old template appended `/workspace` to whatever it was given, so a
    caller passing the workspace itself produced `.../workspace/workspace`."""
    for addr in ("/workspace", "/data/x/workspace"):
        body = _text(SectionLibrary.files_workspace(addr))
        assert "workspace/workspace" not in body, addr
        assert body.count(addr) >= 1


def test_the_cloud_note_adds_layout_not_a_second_address():
    body = _text(SectionLibrary.files_workspace("/workspace", "agents/s1"))
    assert "GenyCloud at `agents/s1`" in body
    # A relative prefix, never an absolute second answer to "where am I".
    assert "/data/" not in body
