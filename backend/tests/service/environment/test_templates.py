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
