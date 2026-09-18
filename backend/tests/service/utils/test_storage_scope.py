"""An agent's workspace is usually a symlink, and the reader has to follow it.

Production: `workspace` is a symlink into the user's cloud tree, so every path
under it resolves outside the session directory. The listing followed the link
and showed the files; the JSON reader did not and answered 404 for every one
of them — "File not found: workspace/myproject/docs/note.md" on a file plainly
visible in the explorer beside it.
"""

from pathlib import Path

from service.utils.file_storage import read_storage_file, resolve_in_scope, within_scope


def _session_with_linked_workspace(tmp_path: Path) -> Path:
    """The real shape: <session>/workspace → <cloud>/agents/<id>."""
    session = tmp_path / "sessions" / "s1"
    session.mkdir(parents=True)
    cloud = tmp_path / "_cloud" / "user" / "workspace" / "agents" / "s1"
    (cloud / "myproject" / "docs").mkdir(parents=True)
    (cloud / "myproject" / "docs" / "note.md").write_text("# 메모\n", encoding="utf-8")
    (session / "workspace").symlink_to(cloud)
    return session


def test_a_file_under_the_linked_workspace_reads(tmp_path):
    session = _session_with_linked_workspace(tmp_path)

    got = read_storage_file(str(session), "workspace/myproject/docs/note.md")

    assert got is not None, "the listing shows this file; the reader must open it"
    assert got["content"] == "# 메모\n"
    assert got["binary"] is False


def test_the_same_path_without_the_link_still_reads(tmp_path):
    session = tmp_path / "plain"
    (session / "workspace").mkdir(parents=True)
    (session / "workspace" / "a.txt").write_text("hi", encoding="utf-8")

    assert read_storage_file(str(session), "workspace/a.txt")["content"] == "hi"


def test_traversal_is_still_refused(tmp_path):
    session = _session_with_linked_workspace(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_text("no", encoding="utf-8")

    assert read_storage_file(str(session), "../secret.txt") is None
    assert resolve_in_scope(str(session), "../../secret.txt") is None
    assert not within_scope(session, secret.resolve())


def test_bytes_that_are_not_text_say_so_instead_of_vanishing(tmp_path):
    session = tmp_path / "s"
    (session / "workspace").mkdir(parents=True)
    png = session / "workspace" / "volcano.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff\xfe")

    got = read_storage_file(str(session), "workspace/volcano.png")

    assert got is not None, "a PNG exists; 404 would say it does not"
    assert got["binary"] is True
    assert got["size"] == png.stat().st_size


def test_a_missing_file_is_still_missing(tmp_path):
    session = _session_with_linked_workspace(tmp_path)
    assert read_storage_file(str(session), "workspace/nope.md") is None
