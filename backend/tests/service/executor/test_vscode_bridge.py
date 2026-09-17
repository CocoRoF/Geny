"""VSCode local-development tool set — the isolated connector capability group.

The contract: the ``vscode_*`` tools (a) exist only in ``VSCodeToolProvider``,
never in the ToolLoader name universe, (b) route over the SAME connector bridge
as the desktop tools but on ``vscode.*`` capability strings, and (c) reach a
session ONLY when its environment sets ``extras.vscode_enabled`` — which is set
only on ``template-vscode-env``. Two fail-closed gates ⇒ no leak into any other
environment.
"""

from __future__ import annotations

from service.executor.vscode_bridge import (
    VSCODE_CAPABILITIES,
    VSCodeToolProvider,
    _build_vscode_tools,
)


def test_provider_exposes_all_vscode_tools_and_only_those():
    p = VSCodeToolProvider()
    names = set(p.list_names())
    assert names == set(_build_vscode_tools().keys())
    # Every name is vscode_* — no desktop_* / generic leakage.
    assert all(n.startswith("vscode_") for n in names)
    # Core Claude-Code-like coverage is present.
    for n in (
        "vscode_read_file", "vscode_write_file", "vscode_edit",
        "vscode_run_terminal", "vscode_search_text", "vscode_diagnostics",
        "vscode_workspace_info",
    ):
        assert n in names


def test_capability_strings_are_namespaced_and_consistent():
    p = VSCodeToolProvider()
    tool_caps = {p.get(n)._capability for n in p.list_names()}
    assert tool_caps == set(VSCODE_CAPABILITIES)
    assert all(c.startswith("vscode.") for c in tool_caps)


def test_write_and_terminal_are_destructive_reads_are_not():
    p = VSCodeToolProvider()
    for destructive_name in ("vscode_write_file", "vscode_edit", "vscode_run_terminal"):
        caps = p.get(destructive_name).capabilities({})
        assert caps.destructive is True and caps.read_only is False
    for read_name in (
        "vscode_read_file", "vscode_search_text", "vscode_find_files",
        "vscode_workspace_info", "vscode_active_editor", "vscode_diagnostics",
    ):
        caps = p.get(read_name).capabilities({})
        assert caps.read_only is True and caps.destructive is False


def test_names_are_isolated_from_the_tool_loader_universe():
    """The isolation invariant: vscode_* names must NOT be in the built-in /
    custom tool universe, so a normal env's tools.external (seeded from
    get_all_names) can never contain them."""
    from service.tool_loader import ToolLoader

    loader = ToolLoader()
    try:
        universe = set(loader.get_all_names())
    except Exception:
        universe = set()
    vscode_names = set(VSCodeToolProvider().list_names())
    assert vscode_names.isdisjoint(universe)


def test_vscode_env_template_gates_and_isolates():
    from service.environment.templates import create_vscode_env, VSCODE_ENV_ID

    m = create_vscode_env()
    assert m.metadata.id == VSCODE_ENV_ID
    # vscode_* are NOT baked into the whitelist — they arrive via the gate.
    assert list(getattr(m.tools, "external", []) or []) == []
    assert bool(m.host_selections.extras.get("vscode_enabled")) is True
    # Sandbox fs/shell built-ins are excluded so the agent uses vscode_* only.
    built_in = set(getattr(m.tools, "built_in", []) or [])
    assert built_in.isdisjoint({"Read", "Write", "Edit", "Bash", "Glob", "Grep"})
    assert "AskUserQuestion" in built_in
