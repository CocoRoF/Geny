"""Default environment templates — WORKER + VTUBER seeds.

Mirrors :mod:`service.tool_preset.templates` for the environment layer.
Every session the user creates runs through one of two seed
:class:`EnvironmentManifest` templates — ``template-worker-env`` (task
work) or ``template-vtuber-env`` (conversation). Sub-Worker / solo
Worker / developer / researcher / planner all resolve to the worker
seed; only the VTuber role gets the lightweight vtuber seed.

The seeds are **materialized on disk** at app boot via
:func:`install_environment_templates`. Reasoning (from
``plan/02_default_env_per_role.md``):

- The seeded env is inspectable — users can open the environment
  editor and see what their worker does.
- Edits to the seed env persist in the user's database and are
  picked up on next session create, matching how
  :class:`~service.tool_preset.store.ToolPresetStore` behaves today.
- Matches the user's directive: the default envs are *the envs
  users see in the UI*, not invisible defaults.

The manifests themselves come from
:func:`service.langgraph.default_manifest.build_default_manifest` — the
same factory the session path uses. So "what the seed looks like" and
"what an ephemeral session looks like" never diverge.
"""

from __future__ import annotations

from typing import List, Optional

from geny_executor import EnvironmentManifest

from service.environment.service import EnvironmentService
from service.langgraph.default_manifest import build_default_manifest

__all__ = [
    "WORKER_ENV_ID",
    "VTUBER_ENV_ID",
    "create_worker_env",
    "create_vtuber_env",
    "install_environment_templates",
]


WORKER_ENV_ID = "template-worker-env"
VTUBER_ENV_ID = "template-vtuber-env"


def create_worker_env(
    external_tool_names: Optional[List[str]] = None,
) -> EnvironmentManifest:
    """Default worker environment manifest.

    Uses the ``worker_adaptive`` stage chain — adaptive loop with
    ``binary_classify`` evaluation, ``aggressive_cache``, and
    ``max_turns=30``. Binds to every provider-backed tool supplied
    via *external_tool_names* — both Geny platform builtins
    (``geny_*``, ``memory_*``, ``knowledge_*``, ``opsidian_*``) and
    custom tools. The executor's manifest loader only registers
    names listed in ``.external``, so callers must pass the full
    union (not just the custom slice) to get platform tools into
    the session's tool registry.

    The ``model`` block is left empty — session creation fills it in
    via :class:`PipelineConfig` based on the user's LLM settings.
    """
    manifest = build_default_manifest(
        preset="worker_adaptive",
        external_tool_names=list(external_tool_names or []),
    )
    manifest.metadata.id = WORKER_ENV_ID
    manifest.metadata.name = "Worker Environment"
    manifest.metadata.description = (
        "Default environment for worker / developer / researcher / "
        "planner roles. Adaptive loop with binary_classify evaluator."
    )
    return manifest


def create_vtuber_env() -> EnvironmentManifest:
    """Default VTuber environment manifest.

    Uses the ``vtuber`` stage chain — no Stage 8 (Think), ``system_cache``,
    ``signal_based`` evaluation, ``max_turns=10``. Binds to the three
    conversation-oriented custom tools (``web_search``, ``news_search``,
    ``web_fetch``) that ``template-vtuber-tools`` whitelists.
    """
    manifest = build_default_manifest(
        preset="vtuber",
        external_tool_names=["web_search", "news_search", "web_fetch"],
    )
    manifest.metadata.id = VTUBER_ENV_ID
    manifest.metadata.name = "VTuber Environment"
    manifest.metadata.description = (
        "Lightweight conversational environment for the VTuber persona."
    )
    return manifest


def install_environment_templates(
    service: EnvironmentService,
    *,
    external_tool_names: Optional[List[str]] = None,
) -> int:
    """Save default environment manifests to disk, overwriting existing.

    Mirrors :func:`service.tool_preset.templates.install_templates`.
    Called once at app boot after the tool preset templates are
    installed and the :class:`ToolLoader` has enumerated tools — so
    *external_tool_names* should be ``tool_loader.get_all_names()``
    (builtin + custom) for the worker env. Anything that does not
    land in ``manifest.tools.external`` will never reach the
    session's tool registry.

    The two template seed envs (``template-worker-env`` /
    ``template-vtuber-env``) are rewritten every boot from the
    canonical :func:`build_default_manifest` output. Custom envs —
    any id other than the two template seeds — are never touched.
    This keeps the seeds in lockstep with manifest-builder changes
    (e.g. a new stage added to the default chain) without needing a
    migration framework.

    Returns the number of environment files written (always equal to
    the seed count after the write loop completes).
    """
    seeds: List[EnvironmentManifest] = [
        create_worker_env(external_tool_names=external_tool_names),
        create_vtuber_env(),
    ]
    for manifest in seeds:
        env_id = manifest.metadata.id
        service._write_manifest(env_id, manifest)
    return len(seeds)
