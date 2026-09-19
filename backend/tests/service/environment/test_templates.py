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


def test_install_writes_exactly_one_environment(tmp_path) -> None:
    """There is one environment: the pipeline every agent runs.

    It used to install three, and before that eleven. Each round of shrinking
    removed something that was never really an environment — the model became
    the session's route, the pipeline became the one harness, and the persona,
    tool roster and sub-agents became things a session carries.
    """
    from service.environment.service import EnvironmentService
    from service.environment.templates import (
        WORKER_ENV_ID,
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
    loader = _loader_for({"send_direct_message_internal", "read_inbox", "memory_read"})

    written = install_environment_templates(
        service, external_tool_names=all_names, tool_loader=loader,
    )

    assert written == 1
    assert [e["id"] for e in service.list_all()] == [WORKER_ENV_ID]

    only = service.load_manifest(WORKER_ENV_ID)
    assert only is not None
    # Every tool the boot path knew about reaches it — narrowing is a tool
    # preset on the session, not a second environment.
    for name in all_names:
        assert name in only.tools.external, name
    assert list(only.tools.built_in) == ["*"]
    # And nothing in it declares a persona: that is the session's to attach.
    assert not (only.host_selections.extras or {}).get("persona_preset_id")


def test_every_role_resolves_to_the_one_environment() -> None:
    """A role used to pick an environment. Now it picks nothing — the VTuber
    persona is attached to the session, so a VTuber and a worker run the same
    pipeline with different things hanging off them."""
    from service.environment.role_defaults import resolve_env_id
    from service.environment.templates import WORKER_ENV_ID

    for role in ("worker", "developer", "researcher", "planner", "vtuber", None):
        assert resolve_env_id(role, None) == WORKER_ENV_ID, role
    # Even an id from before the change — the environment it names is gone,
    # and the session keeps working.
    assert resolve_env_id("vtuber", "52a7eb77f2bb") == WORKER_ENV_ID


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


def test_install_templates_persists_built_in_choices(tmp_path) -> None:
    """``.built_in`` survives the write/read roundtrip, so a boot-time edit of
    the environment and a read-back don't silently drop the selection."""
    from service.environment.service import EnvironmentService
    from service.environment.templates import (
        WORKER_ENV_ID,
        install_environment_templates,
    )

    service = EnvironmentService(storage_path=str(tmp_path))
    install_environment_templates(
        service,
        external_tool_names=["memory_read", "web_search"],
    )

    only = service.load_manifest(WORKER_ENV_ID)
    assert only is not None
    assert list(only.tools.built_in) == ["*"]


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
