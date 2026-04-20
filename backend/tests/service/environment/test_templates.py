"""Regression tests for the seed env template rosters.

PR #1 of the 20260420_5 cycle (`fix/manifest-tool-roster`) changed
the seed env factories to declare every provider-backed tool
(Geny platform builtins + Geny custom tools) in
``manifest.tools.external`` — the sole registration path the
executor honours via ``_register_external_tools``.

Before PR #1 the worker env only received ``tool_loader.get_custom_names()``
at boot, so platform tools (``send_direct_message_external`` etc.)
never reached ``pipeline.tool_registry``. These tests lock that in:
if a future refactor drops platform tools from the worker roster,
the unit test is the first thing to fail.

Cycle 20260420_8 / plan/01 renamed built-ins (dropped the ``geny_``
prefix, split DM into ``_internal`` / ``_external``) and replaced
the prefix-based platform filter with a source-stem allowlist
(:data:`_PLATFORM_TOOL_SOURCES`). The VTuber deny list grew to
include every address-discovery / external-DM primitive so the
persona defaults to ``send_direct_message_internal`` as its only
inter-agent outbound channel.
"""

from __future__ import annotations

from typing import Iterable, Optional


class _FakeToolLoader:
    """Minimal :class:`ToolLoader` stand-in for tests.

    Supplies :meth:`get_tool_source` over a caller-provided mapping so
    the VTuber roster filter can identify platform-layer stems without
    touching the filesystem.
    """

    def __init__(self, source_map: dict[str, str]):
        self._source = source_map

    def get_tool_source(self, name: str) -> Optional[str]:
        return self._source.get(name)


def _loader_for(platform_names: Iterable[str]) -> _FakeToolLoader:
    """Build a fake loader that tags every *platform_names* entry as
    part of ``geny_tools``. Names not listed are treated as custom.
    """
    return _FakeToolLoader({name: "geny_tools" for name in platform_names})


def test_worker_env_includes_platform_tools_when_given_all_names() -> None:
    """Passing the union of builtin + custom names into
    :func:`create_worker_env` must put the Geny platform tools on
    the manifest. The worker's tool registry is built from this
    list alone."""
    from service.environment.templates import create_worker_env

    all_names = [
        # Platform builtins (post-rename)
        "send_direct_message_external",
        "send_direct_message_internal",
        "read_inbox",
        "session_list",
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
    assert "send_direct_message_external" in external
    assert "send_direct_message_internal" in external
    assert "read_inbox" in external
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


def test_vtuber_env_has_internal_dm_and_inbox_only() -> None:
    """Cycle 20260420_8 / plan/01: VTuber must receive the
    ``send_direct_message_internal`` + ``read_inbox`` pair (plus
    ``memory_*`` / ``knowledge_*``) and **must not** see
    ``send_direct_message_external``, ``session_list``,
    ``session_info``, or ``session_create``. Exposing those caused
    the trial-and-error DM sequence observed in the 01:15:28 →
    01:15:37 log (analysis/01)."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "send_direct_message_external",
        "send_direct_message_internal",
        "read_inbox",
        "session_list",
        "session_info",
        "session_create",
        "memory_read",
        "memory_write",
        "knowledge_search",
        "web_search",
        "news_search",
        "web_fetch",
        "browser_navigate",
    ]
    platform_names = {
        "send_direct_message_external",
        "send_direct_message_internal",
        "read_inbox",
        "session_list",
        "session_info",
        "session_create",
    }
    loader = _loader_for(platform_names)
    manifest = create_vtuber_env(all_tool_names=all_names, tool_loader=loader)
    external = list(manifest.tools.external)

    # Must be present
    assert "send_direct_message_internal" in external
    assert "read_inbox" in external
    assert "memory_read" in external
    assert "knowledge_search" in external

    # Must be absent — deny list
    assert "send_direct_message_external" not in external, (
        "VTuber must not see send_direct_message_external; "
        "it should rely on internal DM for its counterpart"
    )
    assert "session_list" not in external, sorted(external)
    assert "session_info" not in external, sorted(external)
    assert "session_create" not in external, sorted(external)


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
        "send_direct_message_internal",
        "read_inbox",
        "memory_read",
        "web_search",
        "browser_navigate",
    ]
    loader = _loader_for({"send_direct_message_internal", "read_inbox"})
    install_environment_templates(
        service,
        external_tool_names=all_names,
        tool_loader=loader,
    )

    vtuber = service.load_manifest(VTUBER_ENV_ID)
    assert vtuber is not None
    assert "send_direct_message_internal" in vtuber.tools.external
    assert "read_inbox" in vtuber.tools.external
    assert "memory_read" in vtuber.tools.external
    assert "web_search" in vtuber.tools.external
    # browser_navigate filtered out even though passed in
    assert "browser_navigate" not in vtuber.tools.external


def test_vtuber_env_denies_full_address_primitives_set() -> None:
    """Cycle 20260420_8 / plan/01: the VTuber deny set now covers
    every address-discovery / external-DM primitive, not just
    ``session_create``. Regression guard against a future change
    that re-narrows the deny list."""
    from service.environment.templates import create_vtuber_env

    all_names = [
        "session_create",
        "session_list",
        "session_info",
        "send_direct_message_external",
        "send_direct_message_internal",
        "memory_read",
        "web_search",
    ]
    loader = _loader_for({
        "session_create",
        "session_list",
        "session_info",
        "send_direct_message_external",
        "send_direct_message_internal",
    })
    manifest = create_vtuber_env(all_tool_names=all_names, tool_loader=loader)
    external = list(manifest.tools.external)

    for denied in (
        "session_create",
        "session_list",
        "session_info",
        "send_direct_message_external",
    ):
        assert denied not in external, (
            f"VTuber must not see {denied}; deny list regressed "
            f"(external={sorted(external)})"
        )
    # Counterpart DM remains
    assert "send_direct_message_internal" in external
    assert "memory_read" in external


def test_worker_env_retains_full_messaging_set() -> None:
    """The deny list is VTuber-only. Workers (solo or Sub-Worker)
    retain every session / messaging primitive."""
    from service.environment.templates import create_worker_env

    manifest = create_worker_env(
        external_tool_names=[
            "session_create",
            "session_list",
            "session_info",
            "send_direct_message_external",
            "send_direct_message_internal",
            "memory_read",
        ]
    )
    external = list(manifest.tools.external)
    for name in (
        "session_create",
        "session_list",
        "session_info",
        "send_direct_message_external",
        "send_direct_message_internal",
    ):
        assert name in external, sorted(external)


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
    its bound Sub-Worker via ``send_direct_message_internal``."""
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
        "send_direct_message_external",
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
