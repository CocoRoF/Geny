"""Preset → :class:`EnvironmentManifest` factory.

Non-``env_id`` sessions have historically been wired through
:class:`~geny_executor.memory.GenyPresets`'s imperative preset builders
(``worker_adaptive`` / ``vtuber`` / ``worker_easy``). The Phase C
switch-over collapses every session path onto the single
``Pipeline.from_manifest_async(manifest, adhoc_providers=[...])`` entry
point; this factory is the piece that turns a preset *name* into the
manifest that entry-point expects.

**Dead code.** Introduced by the Phase C safe-refactor PR. Nothing in
the current AgentSession code path imports this module; the
switch-over PR will replace the ``GenyPresets.*`` branches with a
call to :func:`build_default_manifest`.

Returned manifests deliberately carry **only what the manifest can
authoritatively express**: stage layout, built-in tool whitelist, and
(once the switch-over lands) the ``external`` names for Geny-provider
tools. Runtime-scoped objects — memory manager, curated-knowledge
callback, LLM reflect callback — remain the caller's responsibility
and are attached to the pipeline after construction; they are not
encoded in the manifest.
"""

from __future__ import annotations

from typing import Dict, List, Optional


# Core built-in tool set shared across presets. Mirrors the six tools
# ``AgentSession._build_pipeline`` currently registers before handing
# the registry to ``GenyPresets.*``. Kept as a module-level constant
# so the switch-over PR's tests can assert against a stable value.
_DEFAULT_BUILT_IN_TOOLS: List[str] = [
    "Read",
    "Write",
    "Edit",
    "Bash",
    "Glob",
    "Grep",
]


# Supported preset names. ``default`` is the alias used by
# :class:`AgentSession` for the adaptive worker path.
_VTUBER = "vtuber"
_WORKER_ADAPTIVE = "worker_adaptive"
_WORKER_EASY = "worker_easy"
_DEFAULT_ALIAS = "default"  # maps to worker_adaptive at session level

_KNOWN_PRESETS = frozenset(
    {_VTUBER, _WORKER_ADAPTIVE, _WORKER_EASY, _DEFAULT_ALIAS}
)


def build_default_manifest(
    preset: str,
    *,
    model: Optional[str] = None,
    external_tool_names: Optional[List[str]] = None,
) -> "object":
    """Materialize an :class:`EnvironmentManifest` for a preset name.

    Args:
        preset: One of ``"vtuber"`` / ``"worker_adaptive"`` /
            ``"worker_easy"`` / ``"default"``. Anything else raises
            :class:`ValueError` — we deliberately do not fall back to
            a hard-coded default, so a typo fails loudly.
        model: Override for the LLM model id. When omitted, the
            manifest carries an empty ``model`` block and the caller
            is expected to set it via ``PipelineConfig`` at session
            build time (the same contract the sync preset paths
            followed).
        external_tool_names: Names of Geny-provider tools to include
            in ``manifest.tools.external``. When a
            :class:`GenyToolProvider` is passed to
            :meth:`Pipeline.from_manifest_async` at session build,
            each name listed here gets registered if the provider
            claims it.

    Returns:
        An :class:`EnvironmentManifest` ready to feed
        :meth:`Pipeline.from_manifest_async`. The manifest carries
        ``tools.built_in`` populated from the shared default set and
        ``tools.external`` populated from *external_tool_names*. No
        ``mcp_servers`` are declared; callers that need MCP tools add
        them to the manifest explicitly.

    Raises:
        ValueError: If *preset* is not a known preset name.
        ImportError: If ``geny-executor`` is not installed in the
            current environment. This module imports the executor
            lazily so merely importing ``default_manifest`` is safe
            even on deployments that predate the v0.22.0 dependency
            bump.
    """
    if preset not in _KNOWN_PRESETS:
        raise ValueError(
            f"unknown preset '{preset}'. "
            f"Expected one of: {sorted(_KNOWN_PRESETS)}"
        )

    # Alias: the agent session layer uses "default" for the adaptive
    # worker flow. Collapse it so downstream code sees one canonical
    # name.
    effective = _WORKER_ADAPTIVE if preset == _DEFAULT_ALIAS else preset

    # Lazy import — keeps merely loading this module safe against
    # older executor versions during the pre-v0.22.0 dead-code
    # window.
    from geny_executor.core.environment import (
        EnvironmentManifest,
        EnvironmentMetadata,
        ToolsSnapshot,
    )

    metadata = EnvironmentMetadata(
        id="",  # non-env_id sessions are ephemeral; no id is persisted.
        name=f"preset:{effective}",
        description=f"Default manifest materialized from preset '{effective}'.",
        base_preset=effective,
    )

    tools = ToolsSnapshot(
        built_in=list(_DEFAULT_BUILT_IN_TOOLS),
        external=list(external_tool_names or []),
    )

    model_block: Dict[str, object] = {"model": model} if model else {}

    # The stage list is intentionally empty in the dead-code version.
    # The switch-over PR fills it in by walking the preset's stage
    # configuration — that requires the runtime plumbing to
    # reattach memory_manager / callbacks and belongs in the same
    # commit that deletes the legacy preset branches.
    return EnvironmentManifest(
        metadata=metadata,
        model=model_block,
        pipeline={},
        stages=[],
        tools=tools,
    )


def known_presets() -> List[str]:
    """Public accessor for the supported preset names — used by the
    frontend validation layer once the switch-over lands."""
    return sorted(_KNOWN_PRESETS)
