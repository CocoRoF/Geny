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
:func:`service.executor.default_manifest.build_default_manifest` — the
same factory the session path uses. So "what the seed looks like" and
"what an ephemeral session looks like" never diverge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from geny_executor import EnvironmentManifest

from service.environment.service import EnvironmentService
from service.executor.default_manifest import build_default_manifest

if TYPE_CHECKING:
    from service.tool_loader import ToolLoader

__all__ = [
    "WORKER_ENV_ID",
    "VTUBER_ENV_ID",
    "create_worker_env",
    "create_vtuber_env",
    "install_environment_templates",
]


WORKER_ENV_ID = "template-worker-env"
VTUBER_ENV_ID = "template-vtuber-env"


# Custom tools the VTuber persona should keep access to. Distinct
# from platform-layer builtins (which are identified via
# :data:`_PLATFORM_TOOL_SOURCES` — the file stem under
# ``backend/tools/built_in/*.py``) — this whitelist only controls
# which *custom* (``tools/custom/``) tools make it through. Excludes
# ``browser_*`` on purpose: the conversational persona shouldn't
# spawn a playwright browser on casual questions. Matches
# ``backend/tool_presets/template-vtuber-tools.json``.
_VTUBER_CUSTOM_TOOL_WHITELIST = frozenset(
    {"web_search", "news_search", "web_fetch"}
)


# Platform built-in source stems. :class:`ToolLoader` records each
# tool's source file stem in ``_tool_source`` — tools whose stem
# lives in this set are treated as platform-layer and always
# included in both worker and VTuber rosters. Cycle 20260420_8/
# plan/01 dropped the ``geny_`` prefix from tool names (so prefix
# matching no longer works); stem-based identification is stable
# against rename churn. New platform tools added under
# ``backend/tools/built_in/<stem>.py`` are picked up automatically
# as long as *stem* is listed here.
_PLATFORM_TOOL_SOURCES = frozenset({
    "geny_tools",
    "memory_tools",
    "knowledge_tools",
})


# Legacy prefix heuristic — only used by the fallback code path
# (callers that have not yet switched to the tool_loader-aware
# signature, e.g. older unit tests). Post-rename only ``memory_*``
# and ``knowledge_*`` actually carry prefixes; geny_* built-ins now
# ship un-prefixed. The fallback therefore under-matches — which is
# why callers in production must pass the tool_loader.
_LEGACY_PLATFORM_TOOL_PREFIXES = ("memory_", "knowledge_", "opsidian_")


# Framework-shipped built-in tool selection per role.
#
# Worker seeds get the full set (``["*"]``) — ``Read`` / ``Write`` /
# ``Edit`` / ``Bash`` / ``Glob`` / ``Grep``. This fixes the Sub-Worker
# file-creation gap: previously "create test.txt" fell back to
# ``memory_write`` because no filesystem tool was in the roster. The
# executor sandboxes every write to ``ToolContext.working_dir`` —
# which :class:`AgentSession` sets to the session's ``storage_path``
# — so Worker writes land in ``backend/storage/<session_id>/``.
#
# VTuber seeds get ``[]``. The conversational persona must not touch
# files directly; every file operation is delegated to its bound
# Sub-Worker via :func:`send_direct_message_internal` (Plan/01).
_WORKER_BUILT_IN_TOOL_NAMES: List[str] = ["*"]
_VTUBER_BUILT_IN_TOOL_NAMES: List[str] = []


# Platform tools a VTuber persona should *not* see even though they
# live in a :data:`_PLATFORM_TOOL_SOURCES` file. The VTuber already
# has a runtime-bound Sub-Worker (``AgentSession._linked_session_id``).
#
# - ``session_create`` tempts the LLM to mint a spurious new session
#   when it reads "## Sub-Worker Agent" literally as a name, routing
#   subsequent DMs to the wrong target.
# - ``session_list`` / ``session_info`` are address-discovery primitives
#   the VTuber shouldn't need; they exist for Sub-Worker use cases.
#   Exposing them invites the LLM to treat VTuber↔Sub-Worker DMing as
#   a discovery problem ("let me list sessions first…") instead of a
#   one-shot call to ``send_direct_message_internal``.
# - ``send_direct_message_external`` is the addressed DM variant; the
#   VTuber should *never* need to address anyone other than its own
#   counterpart. Leaving it on the VTuber's tool surface was the root
#   cause of the 01:15:28 → 01:15:37 trial-and-error log in cycle
#   20260420_8 (see analysis/01).
#
# Sub-Workers retain all of these.
_VTUBER_PLATFORM_DENY = frozenset({
    "session_create",
    "session_list",
    "session_info",
    "send_direct_message_external",
})


def _vtuber_tool_roster(
    all_tool_names: List[str],
    tool_loader: Optional["ToolLoader"] = None,
) -> List[str]:
    """Filter *all_tool_names* down to the set the VTuber should see.

    A tool lands in the roster when either:

    1. Its source stem is in :data:`_PLATFORM_TOOL_SOURCES` and its
       name is not in :data:`_VTUBER_PLATFORM_DENY`, **or**
    2. Its name is in :data:`_VTUBER_CUSTOM_TOOL_WHITELIST`.

    Anything else — notably ``browser_*`` — is excluded.

    *tool_loader* supplies the source-stem lookup
    (:meth:`ToolLoader.get_tool_source`). When omitted (test callers
    that do not have a loader around), the filter falls back to a
    legacy prefix heuristic that only catches ``memory_*`` /
    ``knowledge_*`` — correct for those tools but incomplete for the
    post-rename geny built-ins. Production call sites (boot path in
    ``main.py``) must pass the loader.

    Order is preserved from the input so the manifest's external
    list is stable across boots (helps diff-based review of the
    written ``.json`` seed).
    """
    if tool_loader is not None:
        def _is_platform(name: str) -> bool:
            return tool_loader.get_tool_source(name) in _PLATFORM_TOOL_SOURCES
    else:
        def _is_platform(name: str) -> bool:
            return name.startswith(_LEGACY_PLATFORM_TOOL_PREFIXES)

    return [
        name
        for name in all_tool_names
        if (_is_platform(name) and name not in _VTUBER_PLATFORM_DENY)
        or name in _VTUBER_CUSTOM_TOOL_WHITELIST
    ]


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

    Worker seeds additionally opt into every framework built-in tool
    (:data:`_WORKER_BUILT_IN_TOOL_NAMES` = ``["*"]``). This gives
    Sub-Workers ``Write`` / ``Read`` / ``Edit`` / ``Bash`` / ``Glob`` /
    ``Grep`` — required to actually create files in the session's
    ``storage_path`` instead of falling back to ``memory_write``.

    The ``model`` block is left empty — session creation fills it in
    via :class:`PipelineConfig` based on the user's LLM settings.
    """
    manifest = build_default_manifest(
        preset="worker_adaptive",
        external_tool_names=list(external_tool_names or []),
        built_in_tool_names=list(_WORKER_BUILT_IN_TOOL_NAMES),
    )
    manifest.metadata.id = WORKER_ENV_ID
    manifest.metadata.name = "Worker Environment"
    manifest.metadata.description = (
        "Default environment for worker / developer / researcher / "
        "planner roles. Adaptive loop with binary_classify evaluator."
    )
    return manifest


def create_vtuber_env(
    all_tool_names: Optional[List[str]] = None,
    tool_loader: Optional["ToolLoader"] = None,
) -> EnvironmentManifest:
    """Default VTuber environment manifest.

    Uses the ``vtuber`` stage chain — no Stage 8 (Think),
    ``system_cache``, ``signal_based`` evaluation, ``max_turns=10``.

    *all_tool_names* is the full roster the boot-time
    :class:`ToolLoader` knows about (builtin + custom). The VTuber
    filter (:func:`_vtuber_tool_roster`) narrows that to platform-
    layer tools plus the three conversational web tools. When
    *all_tool_names* is omitted (e.g. tests) the factory falls back
    to the legacy three-web-tool roster, preserving prior
    behaviour for any caller that hasn't yet switched to the new
    signature.

    *tool_loader* is the same :class:`ToolLoader` instance that
    produced *all_tool_names*. Passing it enables stem-based platform
    identification (:data:`_PLATFORM_TOOL_SOURCES`). When omitted,
    the filter falls back to the legacy prefix heuristic — correct
    for ``memory_*`` / ``knowledge_*`` but blind to the post-rename
    ``geny_tools`` built-ins. Production call sites must pass it.

    Platform tools (``send_direct_message_internal`` etc.) must
    reach the VTuber: without them the VTuber cannot DM its
    Sub-Worker, read its inbox, store memories, or consult curated
    knowledge — every piece of functionality the VTuber↔Sub-Worker
    delegation relies on.
    """
    if all_tool_names:
        external = _vtuber_tool_roster(all_tool_names, tool_loader=tool_loader)
    else:
        external = ["web_search", "news_search", "web_fetch"]

    manifest = build_default_manifest(
        preset="vtuber",
        external_tool_names=external,
        built_in_tool_names=list(_VTUBER_BUILT_IN_TOOL_NAMES),
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
    tool_loader: Optional["ToolLoader"] = None,
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
    all_names = list(external_tool_names or [])
    seeds: List[EnvironmentManifest] = [
        create_worker_env(external_tool_names=all_names),
        create_vtuber_env(all_tool_names=all_names, tool_loader=tool_loader),
    ]
    for manifest in seeds:
        env_id = manifest.metadata.id
        service._write_manifest(env_id, manifest)
    return len(seeds)
