"""Preset → :class:`EnvironmentManifest` factory.

Turns a preset *name* (``"worker_adaptive"`` / ``"vtuber"`` /
``"worker_easy"``) into the :class:`EnvironmentManifest` that
:meth:`Pipeline.from_manifest_async` expects. Called from the
manifest-first session build path once that lands in a later PR —
until then this module produces manifests that tests can exercise
for parity against :class:`~geny_executor.memory.GenyPresets`.

The returned manifest carries **only declarative shape**: the stage
list, per-stage artifact names, slot strategy choices, and static
configs (e.g. ``loop.max_turns``). Runtime-scoped objects — the
per-session :class:`GenyMemoryRetriever` / :class:`GenyMemoryStrategy`
/ :class:`GenyPersistence` instances, the composable prompt builder
blocks, the ``llm_reflect`` / ``llm_gate`` callbacks, the curated
knowledge manager — stay out of the manifest and are wired in by
``Pipeline.attach_runtime(...)`` at session start. This is the
split the plan calls "declarative params only".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Supported preset names. ``default`` is the alias used by
# :class:`AgentSession` for the adaptive worker path.
_VTUBER = "vtuber"
_WORKER_ADAPTIVE = "worker_adaptive"
_WORKER_EASY = "worker_easy"
_DEFAULT_ALIAS = "default"  # maps to worker_adaptive at session level

_KNOWN_PRESETS = frozenset(
    {_VTUBER, _WORKER_ADAPTIVE, _WORKER_EASY, _DEFAULT_ALIAS}
)


# Defaults that ``GenyPresets`` passes into the adaptive evaluator.
# Matches ``geny_executor.memory.presets.GenyPresets.worker_adaptive``.
_WORKER_ADAPTIVE_EASY_MAX_TURNS = 1
_WORKER_ADAPTIVE_NOT_EASY_MAX_TURNS = 30

# Loop max_turns defaults per preset. Mirror GenyPresets.* directly.
_WORKER_ADAPTIVE_MAX_TURNS = 30
_VTUBER_MAX_TURNS = 10


def _build_stage_entries(preset: str) -> List["object"]:
    """Emit the :class:`StageManifestEntry` list for *preset*.

    Stage identities, artifact names, and slot choices mirror the
    pipelines that :class:`~geny_executor.memory.GenyPresets` builds
    today (see ``geny_executor/memory/presets.py``). Three runtime-
    swapped slots carry *default* strategies here — they are
    overwritten by :meth:`Pipeline.attach_runtime` at session start:

    - ``context.retriever`` → swapped to :class:`GenyMemoryRetriever`
    - ``memory.strategy`` → swapped to :class:`GenyMemoryStrategy`
    - ``memory.persistence`` → swapped to :class:`GenyPersistence`

    Stage 3 ``system.builder`` is declared as ``"composable"`` to
    match the preset; the block list (persona + datetime + memory
    context) is attached at runtime in a later PR.

    Stages 10 (``tool``), 11 (``agent``), and 14 (``emit``) are
    declared unconditionally. Each stage's own ``should_bypass``
    handles the no-work path: ``ToolStage`` bypasses when
    ``state.pending_tool_calls`` is empty, ``EmitStage`` bypasses
    when its emitter chain is empty, and ``AgentStage`` is a
    single-agent no-op by default. Omitting them from the manifest
    silently disables tool execution — avoided by always emitting
    them and relying on runtime bypass instead.
    """
    from geny_executor.core.environment import StageManifestEntry

    if preset == _VTUBER:
        return _vtuber_stage_entries(StageManifestEntry)
    # worker_adaptive and worker_easy both inherit the adaptive layout
    # for now. worker_easy's single-turn behaviour is expressed by the
    # session layer setting ``max_turns=1`` on the loop at attach time,
    # not by a separate manifest variant.
    return _worker_adaptive_stage_entries(StageManifestEntry)


def _worker_adaptive_stage_entries(StageManifestEntry) -> List["object"]:
    """Mirror :meth:`GenyPresets.worker_adaptive` stage chain."""
    return [
        StageManifestEntry(
            order=1,
            name="input",
            strategies={"validator": "default", "normalizer": "default"},
        ),
        StageManifestEntry(
            order=2,
            name="context",
            strategies={
                "strategy": "simple_load",
                "compactor": "truncate",
                "retriever": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=3,
            name="system",
            strategies={"builder": "composable"},
        ),
        StageManifestEntry(
            order=4,
            name="guard",
        ),
        StageManifestEntry(
            order=5,
            name="cache",
            strategies={"strategy": "aggressive_cache"},
        ),
        StageManifestEntry(
            order=6,
            name="api",
            strategies={
                "provider": "anthropic",
                "retry": "exponential_backoff",
            },
        ),
        StageManifestEntry(
            order=7,
            name="token",
            strategies={
                "tracker": "default",
                "calculator": "anthropic_pricing",
            },
        ),
        StageManifestEntry(
            order=8,
            name="think",
            strategies={"processor": "extract_and_store"},
        ),
        StageManifestEntry(
            order=9,
            name="parse",
            strategies={"parser": "default", "signal_detector": "regex"},
        ),
        StageManifestEntry(
            order=10,
            name="tool",
            strategies={"executor": "sequential", "router": "registry"},
        ),
        StageManifestEntry(
            order=11,
            name="agent",
            strategies={"orchestrator": "single_agent"},
            config={"max_delegations": 4},
        ),
        StageManifestEntry(
            order=12,
            name="evaluate",
            strategies={"strategy": "binary_classify", "scorer": "no_scorer"},
            strategy_configs={
                "strategy": {
                    "easy_max_turns": _WORKER_ADAPTIVE_EASY_MAX_TURNS,
                    "not_easy_max_turns": _WORKER_ADAPTIVE_NOT_EASY_MAX_TURNS,
                },
            },
        ),
        StageManifestEntry(
            order=13,
            name="loop",
            strategies={"controller": "standard"},
            config={"max_turns": _WORKER_ADAPTIVE_MAX_TURNS},
        ),
        StageManifestEntry(
            order=14,
            name="emit",
            strategies={},
            chain_order={"emitters": []},
        ),
        StageManifestEntry(
            order=15,
            name="memory",
            strategies={
                "strategy": "append_only",  # swapped by attach_runtime
                "persistence": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=16,
            name="yield",
            strategies={"formatter": "default"},
        ),
    ]


def _vtuber_stage_entries(StageManifestEntry) -> List["object"]:
    """Mirror :meth:`GenyPresets.vtuber` stage chain.

    Diff vs worker_adaptive: no Stage 8 (think), cache is
    ``system_cache`` (not ``aggressive_cache``), evaluator is
    ``signal_based`` (not ``binary_classify``), and loop
    ``max_turns`` is 10 (not 30).
    """
    return [
        StageManifestEntry(
            order=1,
            name="input",
            strategies={"validator": "default", "normalizer": "default"},
        ),
        StageManifestEntry(
            order=2,
            name="context",
            strategies={
                "strategy": "simple_load",
                "compactor": "truncate",
                "retriever": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=3,
            name="system",
            strategies={"builder": "composable"},
        ),
        StageManifestEntry(
            order=4,
            name="guard",
        ),
        StageManifestEntry(
            order=5,
            name="cache",
            strategies={"strategy": "system_cache"},
        ),
        StageManifestEntry(
            order=6,
            name="api",
            strategies={
                "provider": "anthropic",
                "retry": "exponential_backoff",
            },
        ),
        StageManifestEntry(
            order=7,
            name="token",
            strategies={
                "tracker": "default",
                "calculator": "anthropic_pricing",
            },
        ),
        StageManifestEntry(
            order=9,
            name="parse",
            strategies={"parser": "default", "signal_detector": "regex"},
        ),
        StageManifestEntry(
            order=10,
            name="tool",
            strategies={"executor": "sequential", "router": "registry"},
        ),
        StageManifestEntry(
            order=11,
            name="agent",
            strategies={"orchestrator": "single_agent"},
            config={"max_delegations": 4},
        ),
        StageManifestEntry(
            order=12,
            name="evaluate",
            strategies={"strategy": "signal_based", "scorer": "no_scorer"},
        ),
        StageManifestEntry(
            order=13,
            name="loop",
            strategies={"controller": "standard"},
            config={"max_turns": _VTUBER_MAX_TURNS},
        ),
        StageManifestEntry(
            order=14,
            name="emit",
            strategies={},
            chain_order={"emitters": []},
        ),
        StageManifestEntry(
            order=15,
            name="memory",
            strategies={
                "strategy": "append_only",  # swapped by attach_runtime
                "persistence": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=16,
            name="yield",
            strategies={"formatter": "default"},
        ),
    ]


def build_default_manifest(
    preset: str,
    *,
    model: Optional[str] = None,
    external_tool_names: Optional[List[str]] = None,
    built_in_tool_names: Optional[List[str]] = None,
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
        built_in_tool_names: Names of framework-shipped built-in tools
            (from ``geny_executor.tools.built_in.BUILT_IN_TOOL_CLASSES``)
            to register on the session. ``["*"]`` opts into every
            framework tool — ``Read`` / ``Write`` / ``Edit`` / ``Bash`` /
            ``Glob`` / ``Grep``. ``[]`` / ``None`` disables them (what
            a conversational VTuber wants). The executor resolves these
            inside :meth:`Pipeline.from_manifest_async` against its
            built-in registry; see ``geny-executor`` v0.27.0 changelog.

    Returns:
        An :class:`EnvironmentManifest` ready to feed
        :meth:`Pipeline.from_manifest_async`. The manifest carries a
        populated stage list (mirroring the preset's stage chain),
        ``tools.built_in`` populated from *built_in_tool_names*, and
        ``tools.external`` populated from *external_tool_names*.
        No ``mcp_servers`` are declared; callers that need MCP tools
        add them to the manifest explicitly.

    Raises:
        ValueError: If *preset* is not a known preset name.
        ImportError: If ``geny-executor`` is not installed in the
            current environment. This module imports the executor
            lazily so merely importing ``default_manifest`` is safe
            even on deployments that predate the v0.25.0 dependency
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

    # ``.built_in`` is resolved by the executor (v0.27.0+) against its
    # shipped tool registry inside ``Pipeline.from_manifest_async``.
    # ``["*"]`` expands to every framework tool; ``[]`` / missing
    # keeps them off. The seed env factories choose per role — Worker
    # gets ``["*"]`` (filesystem + Bash), VTuber gets ``[]`` (pure
    # conversational persona). ``.external`` carries the Geny-provider
    # tool names (platform + custom) the session should also expose.
    tools = ToolsSnapshot(
        built_in=list(built_in_tool_names or []),
        external=list(external_tool_names or []),
    )

    model_block: Dict[str, Any] = {"model": model} if model else {}

    entries = _build_stage_entries(effective)

    return EnvironmentManifest(
        metadata=metadata,
        model=model_block,
        pipeline={},
        stages=[e.to_dict() for e in entries],
        tools=tools,
    )


def known_presets() -> List[str]:
    """Public accessor for the supported preset names — used by the
    frontend validation layer once the switch-over lands."""
    return sorted(_KNOWN_PRESETS)
