"""Regression tests for the seed env template rosters.

PR #1 of the 20260420_5 cycle (`fix/manifest-tool-roster`) changed
the seed env factories to declare every provider-backed tool
(Geny platform builtins + Geny custom tools) in
``manifest.tools.external`` — the sole registration path the
executor honours via ``_register_external_tools``.

Before PR #1 the worker env only received ``tool_loader.get_custom_names()``
at boot, so platform tools (``geny_send_direct_message`` etc.) never
reached ``pipeline.tool_registry``. These tests lock that in: if a
future refactor drops platform tools from the worker roster, the
unit test is the first thing to fail.
"""

from __future__ import annotations


def test_worker_env_includes_platform_tools_when_given_all_names() -> None:
    """Passing the union of builtin + custom names into
    :func:`create_worker_env` must put the Geny platform tools on
    the manifest. The worker's tool registry is built from this
    list alone."""
    from service.environment.templates import create_worker_env

    all_names = [
        # Platform builtins
        "geny_send_direct_message",
        "geny_read_inbox",
        "geny_session_list",
        "memory_read",
        "memory_write",
        "knowledge_search",
        # Custom
        "web_search",
        "news_search",
        "web_fetch",
        "browser_navigate",
    ]
    manifest = create_worker_env(external_tool_names=all_names)
    external = list(manifest.tools.external)

    # Platform tools reach the registry
    assert "geny_send_direct_message" in external
    assert "geny_read_inbox" in external
    assert "memory_read" in external
    assert "knowledge_search" in external
    # Custom tools remain
    assert "web_search" in external
    assert "browser_navigate" in external


def test_worker_env_external_mirrors_caller_input() -> None:
    """The worker factory is a pass-through for *external_tool_names*.
    It must not re-order, de-duplicate silently, or drop names."""
    from service.environment.templates import create_worker_env

    names = ["zeta", "alpha", "mike"]
    manifest = create_worker_env(external_tool_names=names)
    assert list(manifest.tools.external) == names


def test_vtuber_env_includes_platform_tools() -> None:
    """PR #2 of the 20260420_5 cycle: VTuber must receive every
    platform-layer builtin so it can DM its Sub-Worker, read its
    inbox, and consult memory/knowledge. Prior to this PR the
    VTuber was hardcoded to three web tools."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "geny_send_direct_message",
        "geny_read_inbox",
        "memory_read",
        "memory_write",
        "knowledge_search",
        "opsidian_browse",
        "web_search",
        "news_search",
        "web_fetch",
        "browser_navigate",
    ]
    manifest = create_vtuber_env(all_tool_names=all_names)
    external = list(manifest.tools.external)

    # Platform tools present
    assert "geny_send_direct_message" in external
    assert "geny_read_inbox" in external
    assert "memory_read" in external
    assert "knowledge_search" in external
    assert "opsidian_browse" in external


def test_vtuber_env_excludes_browser_tools() -> None:
    """Browser automation is heavy and inappropriate for the VTuber
    conversational persona. The filter must drop every ``browser_*``
    name even when the loader reports them."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "web_search",
        "browser_navigate",
        "browser_click",
        "browser_screenshot",
    ]
    manifest = create_vtuber_env(all_tool_names=all_names)
    for name in manifest.tools.external:
        assert not name.startswith("browser_"), (
            f"VTuber roster should not contain browser tool: {name}"
        )


def test_vtuber_env_keeps_conversational_web_tools() -> None:
    """The three conversational web tools (``web_search``,
    ``news_search``, ``web_fetch``) stay in the VTuber roster —
    they're the persona's primary information access."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "web_search",
        "news_search",
        "web_fetch",
        "browser_navigate",
    ]
    manifest = create_vtuber_env(all_tool_names=all_names)
    external = list(manifest.tools.external)
    assert "web_search" in external
    assert "news_search" in external
    assert "web_fetch" in external


def test_vtuber_env_legacy_call_site_still_works() -> None:
    """Calling :func:`create_vtuber_env` without *all_tool_names*
    falls back to the three-web-tool roster. This keeps any caller
    that hasn't yet adopted the new signature from breaking."""
    from service.environment.templates import create_vtuber_env

    manifest = create_vtuber_env()
    external = list(manifest.tools.external)
    assert external == ["web_search", "news_search", "web_fetch"]


def test_install_templates_propagates_to_vtuber(tmp_path) -> None:
    """``install_environment_templates`` must pipe *external_tool_names*
    into the VTuber factory as well. Before PR #2 the VTuber got
    its hardcoded 3-tuple regardless of what the boot path knew."""
    from service.environment.service import EnvironmentService
    from service.environment.templates import (
        VTUBER_ENV_ID,
        install_environment_templates,
    )

    service = EnvironmentService(storage_path=str(tmp_path))
    all_names = [
        "geny_send_direct_message",
        "memory_read",
        "web_search",
        "browser_navigate",
    ]
    install_environment_templates(service, external_tool_names=all_names)

    vtuber = service.load_manifest(VTUBER_ENV_ID)
    assert vtuber is not None
    assert "geny_send_direct_message" in vtuber.tools.external
    assert "memory_read" in vtuber.tools.external
    assert "web_search" in vtuber.tools.external
    # browser_navigate filtered out even though passed in
    assert "browser_navigate" not in vtuber.tools.external


def test_vtuber_env_denies_session_create() -> None:
    """Cycle 20260420_7 / PR-1: the VTuber must not receive
    ``geny_session_create``. The tool is platform-prefixed so the prior
    filter let it through; the deny list now gates it. The LLM used to
    treat "## Sub-Worker Agent" as a literal name and call
    ``geny_session_create(session_name="Sub-Worker Agent")``, spawning
    a spurious session and routing subsequent DMs to the wrong target
    (see dev_docs/20260420_7/analysis/01)."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "geny_session_create",
        "geny_session_list",
        "geny_send_direct_message",
        "geny_message_counterpart",
        "memory_read",
        "web_search",
    ]
    manifest = create_vtuber_env(all_tool_names=all_names)
    external = list(manifest.tools.external)
    assert "geny_session_create" not in external, (
        "VTuber must not see geny_session_create; deny list regressed"
    )
    # But every other platform tool stays — the deny set is narrow.
    assert "geny_session_list" in external
    assert "geny_send_direct_message" in external
    assert "geny_message_counterpart" in external
    assert "memory_read" in external


def test_worker_env_still_receives_session_create() -> None:
    """The deny list is VTuber-only. Workers (solo or Sub-Worker)
    retain session-creation capability."""
    from service.environment.templates import create_worker_env

    manifest = create_worker_env(
        external_tool_names=["geny_session_create", "memory_read"]
    )
    assert "geny_session_create" in manifest.tools.external


def test_worker_env_declares_all_executor_built_ins() -> None:
    """Cycle 20260420_7 / PR-3: worker seeds opt into every
    framework-shipped built-in by setting
    ``manifest.tools.built_in = ["*"]``. The executor
    (``Pipeline.from_manifest_async`` in geny-executor >= 0.27.0)
    resolves ``"*"`` against ``BUILT_IN_TOOL_CLASSES`` so the session
    registry ends up with ``Write`` / ``Read`` / ``Edit`` / ``Bash`` /
    ``Glob`` / ``Grep``. Before this PR the field was hardcoded to
    ``[]`` and Sub-Workers had no filesystem tool, forcing
    ``memory_write`` fallback for "create test.txt"-style requests
    (see dev_docs/20260420_7/analysis/02)."""
    from service.environment.templates import create_worker_env

    manifest = create_worker_env(external_tool_names=["memory_read"])
    assert list(manifest.tools.built_in) == ["*"], (
        "worker env must opt into every executor built-in via '*'"
    )


def test_vtuber_env_declares_no_executor_built_ins() -> None:
    """Cycle 20260420_7 / PR-3: VTuber seeds keep
    ``manifest.tools.built_in = []``. The conversational persona has
    no business touching files — every file action is delegated to
    its bound Sub-Worker via ``geny_message_counterpart``."""
    from service.environment.templates import create_vtuber_env

    manifest = create_vtuber_env(all_tool_names=["web_search"])
    assert list(manifest.tools.built_in) == [], (
        "VTuber env must not declare any built-in; file ops go via Sub-Worker"
    )


def test_install_templates_persists_role_built_in_choices(tmp_path) -> None:
    """Cycle 20260420_7 / PR-3: the ``.built_in`` field is serialized
    to disk by ``install_environment_templates``. Worker seed keeps
    ``["*"]``, VTuber seed keeps ``[]`` — verifies the roundtrip, so
    a boot-time edit of the seed env and a read-back don't silently
    drop the selection."""
    from service.environment.service import EnvironmentService
    from service.environment.templates import (
        VTUBER_ENV_ID,
        WORKER_ENV_ID,
        install_environment_templates,
    )

    service = EnvironmentService(storage_path=str(tmp_path))
    install_environment_templates(
        service,
        external_tool_names=["memory_read", "web_search"],
    )

    worker = service.load_manifest(WORKER_ENV_ID)
    vtuber = service.load_manifest(VTUBER_ENV_ID)
    assert worker is not None and vtuber is not None
    assert list(worker.tools.built_in) == ["*"]
    assert list(vtuber.tools.built_in) == []


def test_install_environment_templates_passes_all_names(tmp_path) -> None:
    """The boot path calls ``install_environment_templates`` with
    ``tool_loader.get_all_names()`` (see ``backend/main.py``). A
    caller supplying the full union must see the worker env's
    external list contain every passed name — no filtering,
    no hidden "builtin-only" split."""
    from service.environment.service import EnvironmentService
    from service.environment.templates import (
        WORKER_ENV_ID,
        install_environment_templates,
    )

    service = EnvironmentService(storage_path=str(tmp_path))
    all_names = [
        "geny_send_direct_message",
        "memory_read",
        "knowledge_search",
        "web_search",
        "browser_navigate",
    ]
    install_environment_templates(service, external_tool_names=all_names)

    worker = service.load_manifest(WORKER_ENV_ID)
    assert worker is not None
    for name in all_names:
        assert name in worker.tools.external, (
            f"{name} passed via install_environment_templates but "
            f"missing from worker env manifest. External: {worker.tools.external}"
        )
