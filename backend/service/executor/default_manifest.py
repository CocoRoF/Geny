"""Preset → :class:`EnvironmentManifest` factory.

Turns a preset *name* (``"worker_adaptive"`` / ``"vtuber"`` /
``"worker_easy"``) into the :class:`EnvironmentManifest` that
:meth:`Pipeline.from_manifest_async` expects.

The returned manifest carries **only declarative shape**: the stage
list, per-stage artifact names, slot strategy choices, and static
configs (e.g. ``loop.max_turns``). Runtime-scoped objects — the
per-session :class:`GenyMemoryRetriever` / :class:`GenyMemoryStrategy`
/ :class:`GenyPersistence` instances, the composable prompt builder
blocks, the ``llm_reflect`` / ``llm_gate`` callbacks, the curated
knowledge manager — stay out of the manifest and are wired in by
``Pipeline.attach_runtime(...)`` at session start. This is the
split the plan calls "declarative params only".

Layout (geny-executor 1.0+, Phase 9a/9b):

    1  input          | 12  agent           | 17  emit
    2  context        | 13  task_registry   | 18  memory
    3  system         | 14  evaluate        | 19  summarize
    4  guard          | 15  hitl            | 20  persist
    5  cache          | 16  loop            | 21  yield
    6  api
    7  token
    8  think
    9  parse
    10 tool
    11 tool_review

Five orders (11/13/15/19/20) are the new stages added in Sub-phase
9a. They default to ``active=False`` here — Geny opts each in via
its own follow-up integration sprints (G2.x). The executor's
v2→v3 manifest migration would auto-pad them anyway, but emitting
them explicitly keeps the manifest self-describing on disk.
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


# ── Sub-phase 9a scaffold entries ────────────────────────────────────

# These five orders are the new stages added by Sub-phase 9a. Each
# defaults to active=False here — opting in is the responsibility of
# the per-stage Geny integration (G2.x sprints). Strategies match the
# executor defaults so the entries are runnable as soon as a host
# flips ``active=True``.
_SCAFFOLD_ENTRIES_SPEC: List[Dict[str, Any]] = [
    {
        "order": 11,
        "name": "tool_review",
        "strategies": {},  # chain stage — strategies live on chain_order
        "chain_order": {
            "reviewers": [
                "schema",
                "sensitive",
                "destructive",
                "network",
                "size",
            ],
        },
    },
    {
        "order": 13,
        "name": "task_registry",
        "strategies": {
            "registry": "in_memory",
            "policy": "fire_and_forget",
        },
    },
    {
        "order": 15,
        "name": "hitl",
        "strategies": {
            "requester": "null",       # safe default — always-approve
            "timeout": "indefinite",
        },
    },
    {
        "order": 19,
        "name": "summarize",
        "strategies": {
            "summarizer": "no_summary",  # default off
            "importance": "fixed",
        },
    },
    {
        "order": 20,
        "name": "persist",
        "strategies": {
            "persister": "no_persist",  # default off
            "frequency": "every_turn",
        },
    },
]


# Per-preset opt-in for scaffold stages. Each value is a partial
# override for the matching :data:`_SCAFFOLD_ENTRIES_SPEC` entry.
# Setting ``"active": True`` turns the scaffold on; merging
# ``"strategies": {...}`` swaps the slot picks.
#
# Defaults below pick the *real* implementation strategies that ship
# with geny-executor 1.0+ so opting a stage in is one flag flip
# rather than a full strategy rewrite. New per-stage Geny integration
# sprints (G2.x) extend these tables as each stage matures.
_PRESET_SCAFFOLD_OVERRIDES: Dict[str, Dict[str, Dict[str, Any]]] = {
    _WORKER_ADAPTIVE: {
        # G2.2: turn-summary writer + heuristic importance grader.
        # Forwards to ``state.session_runtime.memory_provider.record_summary``
        # when the registry has provisioned one (G3.1).
        "summarize": {
            "active": True,
            "strategies": {
                "summarizer": "rule_based",
                "importance": "heuristic",
            },
        },
    },
    _WORKER_EASY: {
        # worker_easy is single-turn — summarising a single answer adds
        # little value, so leave it off. Future task: a one-shot
        # summarizer mode that emits only on terminal turns.
    },
    _VTUBER: {
        # VTuber turns are conversational — summary defers to host-side
        # mood/bond accumulation rather than a structured turn record.
    },
}


def _make_scaffold_entries(
    StageManifestEntry,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List["object"]:
    """Build the 5 scaffold entries with optional per-name overrides.

    ``overrides`` maps a scaffold name to a dict carrying any of:
    ``active`` (bool), ``strategies`` (dict — merged onto the spec
    defaults), ``strategy_configs`` (dict), ``chain_order`` (dict —
    replaces the spec default). Names not present in *overrides*
    keep the canonical scaffold defaults (active=False, no-op
    strategies).
    """
    overrides = overrides or {}
    out = []
    for spec in _SCAFFOLD_ENTRIES_SPEC:
        name = spec["name"]
        ov = overrides.get(name) or {}
        strategies = dict(spec.get("strategies") or {})
        strategies.update(ov.get("strategies") or {})
        out.append(
            StageManifestEntry(
                order=spec["order"],
                name=name,
                active=bool(ov.get("active", False)),
                strategies=strategies,
                strategy_configs=dict(ov.get("strategy_configs") or {}),
                chain_order=dict(
                    ov.get("chain_order")
                    if "chain_order" in ov
                    else spec.get("chain_order") or {}
                ),
            )
        )
    return out


def _merge_sorted(*entry_lists: List["object"]) -> List["object"]:
    """Concatenate and sort by ``order`` so the output is canonically ordered."""
    merged: List[Any] = []
    for el in entry_lists:
        merged.extend(el)
    merged.sort(key=lambda e: int(getattr(e, "order", 0)))
    return merged


def _build_stage_entries(preset: str) -> List["object"]:
    """Emit the :class:`StageManifestEntry` list for *preset*.

    Stage identities, artifact names, and slot choices mirror the
    pipelines that :class:`~geny_executor.memory.GenyPresets` builds
    today. Three runtime-swapped slots carry *default* strategies
    here — they are overwritten by :meth:`Pipeline.attach_runtime`
    at session start:

    - ``context.retriever`` → swapped to :class:`GenyMemoryRetriever`
    - ``memory.strategy`` → swapped to :class:`GenyMemoryStrategy`
    - ``memory.persistence`` → swapped to :class:`GenyPersistence`

    Stage 3 ``system.builder`` is declared as ``"composable"`` to
    match the preset; the block list (persona + datetime + memory
    context) is attached at runtime.

    Stages 10 (``tool``), 12 (``agent``), 14 (``evaluate``),
    16 (``loop``), 17 (``emit``) are declared unconditionally. Each
    stage's own ``should_bypass`` handles the no-work path.

    The 21-stage layout's five new orders (11/13/15/19/20) are
    appended via :func:`_make_scaffold_entries` with
    ``active=False`` — they are runnable as soon as a Geny
    integration sprint flips them on.
    """
    from geny_executor.core.environment import StageManifestEntry

    if preset == _VTUBER:
        base = _vtuber_stage_entries(StageManifestEntry)
    else:
        # worker_adaptive and worker_easy both inherit the adaptive
        # layout for now. worker_easy's single-turn behaviour is
        # expressed by the session layer setting ``max_turns=1`` at
        # attach time, not by a separate manifest variant.
        base = _worker_adaptive_stage_entries(StageManifestEntry)

    overrides = _PRESET_SCAFFOLD_OVERRIDES.get(preset, {})
    return _merge_sorted(
        base, _make_scaffold_entries(StageManifestEntry, overrides=overrides)
    )


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
                "router": "passthrough",  # S7.8: no model swap by default
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
            strategies={
                "processor": "extract_and_store",
                "budget_planner": "static",  # S7.10: fixed default
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
            order=12,
            name="agent",
            strategies={"orchestrator": "single_agent"},
            config={"max_delegations": 4},
        ),
        StageManifestEntry(
            order=14,
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
            order=16,
            name="loop",
            strategies={"controller": "standard"},
            config={"max_turns": _WORKER_ADAPTIVE_MAX_TURNS},
        ),
        StageManifestEntry(
            order=17,
            name="emit",
            strategies={},
            chain_order={"emitters": []},
        ),
        StageManifestEntry(
            order=18,
            name="memory",
            strategies={
                "strategy": "append_only",  # swapped by attach_runtime
                "persistence": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=21,
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
                "router": "passthrough",
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
            order=12,
            name="agent",
            strategies={"orchestrator": "single_agent"},
            config={"max_delegations": 4},
        ),
        StageManifestEntry(
            order=14,
            name="evaluate",
            strategies={"strategy": "signal_based", "scorer": "no_scorer"},
        ),
        StageManifestEntry(
            order=16,
            name="loop",
            strategies={"controller": "standard"},
            config={"max_turns": _VTUBER_MAX_TURNS},
        ),
        StageManifestEntry(
            order=17,
            name="emit",
            strategies={},
            chain_order={"emitters": []},
        ),
        StageManifestEntry(
            order=18,
            name="memory",
            strategies={
                "strategy": "append_only",  # swapped by attach_runtime
                "persistence": "null",  # swapped by attach_runtime
            },
        ),
        StageManifestEntry(
            order=21,
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
            build time.
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
            a conversational VTuber wants).

    Returns:
        An :class:`EnvironmentManifest` ready to feed
        :meth:`Pipeline.from_manifest_async`. Carries the full
        21-stage layout from geny-executor 1.0+ — the five new
        stages (11/13/15/19/20) ship with ``active=False`` and are
        promoted by per-stage Geny integration sprints (G2.x).
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
    # keeps them off. Worker gets ``["*"]`` (filesystem + Bash),
    # VTuber gets ``[]`` (pure conversational persona). ``.external``
    # carries the Geny-provider tool names the session should expose.
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
    frontend validation layer."""
    return sorted(_KNOWN_PRESETS)
