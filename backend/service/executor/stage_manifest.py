"""Stage-specific manifest factory — life-stage variants of the VTuber preset.

Plan/04 §7 treats growth as *manifest replacement*: when a creature
crosses a transition predicate (PR-X4-1's :class:`ManifestSelector`
nominates a new manifest id), the next session rebuilds the pipeline
from a different manifest rather than flipping scattered flags. This
module resolves a stage manifest id like ``"infant_cheerful"`` into
the :class:`EnvironmentManifest` the executor expects.

What the manifest DOES encode per stage:

- ``loop.max_turns`` — infant runs short reactive loops (2); adolescents
  and adults allow richer deliberation (up to 10).
- ``cache.strategy`` — infant / child stay on ``"system_cache"`` (simpler,
  lower churn); teen / adult graduate to ``"aggressive_cache"`` so their
  longer dialogue re-uses prefix tokens.
- ``tools.external`` — default tool roster narrows for infants (plan/04
  §7.1: "infant 은 feed/play 만") and expands through adolescence. Callers
  retain the same ``external_tool_names=`` override :func:`build_default_manifest`
  offers, so deployment-specific tool additions still work.
- ``evaluate.strategy`` — infant / child use ``"signal_based"`` (matches
  vtuber default; less LLM overhead); teen / adult use
  ``"binary_classify"`` so their higher-stakes dialogue gets adaptive
  termination.

What the manifest deliberately does NOT fork on per stage — keeping drift
bounded (plan/05 §4.4 "Manifest drift"):

- Stage chain shape — all stage manifests mirror the 15-entry VTuber
  layout (no Stage 8 think), so a reviewer can diff exactly the four
  knobs above.
- Archetype (``cheerful`` / ``introvert`` / ...) — the suffix in
  ``"infant_cheerful"`` is carried through to ``metadata.name`` /
  ``metadata.description`` for traceability, but does NOT rebuild the
  pipeline. Archetype-coloured prompt text belongs to
  :class:`PersonaBlock` (personality tone) and
  :class:`ProgressionBlock` (stage descriptor — PR-X4-3), not to the
  manifest. Forking the pipeline per archetype too would push the
  combinatorial (species × stage × archetype) manifest count into
  double digits for MVP with no behavioural reward.

Coexistence. ``build_default_manifest(preset)`` continues to serve
deployment presets (``"vtuber"`` / ``"worker_adaptive"`` / ``"worker_easy"``
/ ``"default"``). ``build_stage_manifest(manifest_id)`` serves the
selector's growth ids. PR-X4-5 picks between the two at session-start:
selector-nominated ids route here; falling back to the legacy path
routes to :func:`build_default_manifest`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


# ── Stage knobs ───────────────────────────────────────────────────────

STAGE_INFANT = "infant"
STAGE_CHILD = "child"
STAGE_TEEN = "teen"
STAGE_ADULT = "adult"

# Ordered tuple — also the canonical progression order. External callers
# (tests, selector plan docs) can rely on the index for "older-than"
# comparisons without reaching into this module.
STAGE_ORDER: Tuple[str, ...] = (
    STAGE_INFANT,
    STAGE_CHILD,
    STAGE_TEEN,
    STAGE_ADULT,
)
_STAGE_KEYS = frozenset(STAGE_ORDER)

# Loop max_turns per stage. Infant keeps it very short so a reactive
# "feed → reply → stop" beat stays crisp; adult matches the VTuber
# default (10). Numbers mirror plan/04 §7.1's progression intuition
# ("infant 은 짧은 답, teen 은 풍부한 표현").
_STAGE_MAX_TURNS: Dict[str, int] = {
    STAGE_INFANT: 2,
    STAGE_CHILD: 5,
    STAGE_TEEN: 8,
    STAGE_ADULT: 10,
}

# Cache strategy per stage. Infant / child's shorter loops don't amortize
# aggressive caching (fewer repeated prefixes within a turn); teen /
# adult's longer loops do. Also keeps early-stage deployments simpler
# — one fewer moving part during initial playtests.
_STAGE_CACHE: Dict[str, str] = {
    STAGE_INFANT: "system_cache",
    STAGE_CHILD: "system_cache",
    STAGE_TEEN: "aggressive_cache",
    STAGE_ADULT: "aggressive_cache",
}

# Evaluator per stage. Signal-based is cheap (regex on the LLM output);
# binary_classify calls the LLM again to decide "done vs keep-looping".
# Infant / child don't need the extra round-trip — their turns are
# short enough that running to max_turns is fine. Teen / adult loop
# longer, so an adaptive terminator matters.
_STAGE_EVALUATOR: Dict[str, str] = {
    STAGE_INFANT: "signal_based",
    STAGE_CHILD: "signal_based",
    STAGE_TEEN: "binary_classify",
    STAGE_ADULT: "binary_classify",
}

# Default tool roster per stage (maps to the PR-X3-6 game tool names).
# Plan/04 §7.1: infant is limited to feed/play; child adds gift;
# teen / adult unlock talk. Callers can still override via
# ``external_tool_names=`` (deployment-specific additions like
# ``send_direct_message_external``).
_STAGE_TOOL_DEFAULTS: Dict[str, Tuple[str, ...]] = {
    STAGE_INFANT: ("feed", "play"),
    STAGE_CHILD: ("feed", "play", "gift"),
    STAGE_TEEN: ("feed", "play", "gift", "talk"),
    STAGE_ADULT: ("feed", "play", "gift", "talk"),
}

# Short human-readable per-stage descriptor for manifest metadata.
# Kept distinct from :class:`ProgressionBlock`'s prompt-facing copy
# (PR-X4-3) so the manifest stays operator-facing (logs, diagnostics).
_STAGE_DESCRIPTIONS: Dict[str, str] = {
    STAGE_INFANT: "infant life-stage — short reactive loops, feed/play only",
    STAGE_CHILD: "child life-stage — curious, gift unlocked",
    STAGE_TEEN: "teen life-stage — richer dialogue, adaptive termination",
    STAGE_ADULT: "adult life-stage — full tool roster, aggressive cache",
}

# Plan/04 §7.2 — the canonical (stage, archetype) combinations the
# integration layer expects to see from :func:`default_manifest_naming`.
# :func:`known_stage_manifest_ids` returns these in sorted order so
# the frontend / validators can surface the enumeration. Unknown
# archetypes are still acceptable (see :func:`build_stage_manifest`),
# this is just the documented "paved road".
_CANONICAL_ARCHETYPES: Dict[str, Tuple[str, ...]] = {
    STAGE_INFANT: ("cheerful",),
    STAGE_CHILD: ("curious",),
    STAGE_TEEN: ("introvert", "extrovert"),
    STAGE_ADULT: ("artisan",),
}

# Base preset tag. Every stage manifest inherits vtuber's chain shape
# (no stage 8 think), so the metadata honestly reflects that. Keeps
# ops folks who grep base_preset grouped correctly.
_BASE_PRESET = "vtuber"


# ── Public API ────────────────────────────────────────────────────────


def parse_stage_manifest_id(manifest_id: str) -> Tuple[str, str]:
    """Split a stage manifest id into ``(stage, archetype)``.

    ``"teen_introvert"`` → ``("teen", "introvert")``.
    ``"infant"`` → ``("infant", "")``.
    ``"adult_artisan_hermit"`` → ``("adult", "artisan_hermit")`` — the
    archetype is whatever follows the first underscore, verbatim.

    The selector's :func:`default_manifest_naming` uses
    ``"{stage}_{archetype}"`` so an archetype without underscores is the
    common case; preserving underscores in the tail lets a future
    compound archetype ("artisan_hermit") round-trip without breaking.
    """
    if not isinstance(manifest_id, str) or not manifest_id:
        return "", ""
    head, sep, tail = manifest_id.partition("_")
    if not sep:
        return head, ""
    return head, tail


def is_stage_manifest_id(manifest_id: str) -> bool:
    """True iff the id's stage prefix is a known life-stage.

    Caller (PR-X4-5) routes known ids into :func:`build_stage_manifest`
    and unknown ids back to :func:`build_default_manifest`, so this
    predicate is the dispatch key.
    """
    stage, _ = parse_stage_manifest_id(manifest_id)
    return stage in _STAGE_KEYS


def known_stage_manifest_ids() -> List[str]:
    """Return the canonical stage manifest ids from plan/04 §7.2, sorted.

    Includes bare stages (``"infant"`` …) plus each stage × documented
    archetype combination. Useful for enumeration / validation layers
    (frontend dropdowns, admin tooling). Unknown combinations at
    runtime are still accepted — see :func:`build_stage_manifest`.
    """
    ids: List[str] = list(STAGE_ORDER)
    for stage in STAGE_ORDER:
        for archetype in _CANONICAL_ARCHETYPES.get(stage, ()):
            ids.append(f"{stage}_{archetype}")
    return sorted(ids)


def build_stage_manifest(
    manifest_id: str,
    *,
    model: Optional[str] = None,
    external_tool_names: Optional[List[str]] = None,
    built_in_tool_names: Optional[List[str]] = None,
) -> "object":
    """Materialize an :class:`EnvironmentManifest` for a stage id.

    Args:
        manifest_id: Stage manifest id — ``"infant"``, ``"infant_cheerful"``,
            ``"teen_introvert"``, etc. The stage prefix must be one of
            infant/child/teen/adult; the archetype suffix (if any) is
            carried through to metadata but does not fork the pipeline.
            Unknown stages raise :class:`ValueError` — consistent with
            :func:`build_default_manifest`'s "typos fail loudly" stance.
        model: Optional LLM model id override. Same semantics as
            :func:`build_default_manifest`.
        external_tool_names: If provided, overrides the stage's default
            tool roster verbatim — use this for deployments that need
            to add (or subtract) tools beyond the MVP set. ``None``
            triggers the per-stage default (plan/04 §7.1).
        built_in_tool_names: Same passthrough as
            :func:`build_default_manifest` — executor-side built-ins.
            Stage manifests leave this caller-supplied; VTuber-style
            deployments typically pass ``[]``.

    Returns:
        An :class:`EnvironmentManifest` with:

        - ``metadata.name = f"stage:{manifest_id}"`` (for log grep).
        - ``metadata.description`` — operator-facing descriptor combining
          the stage intent and archetype (if any).
        - ``metadata.base_preset = "vtuber"`` — every stage manifest
          mirrors vtuber's chain.
        - ``metadata.tags`` — ``["stage:<stage>", "archetype:<archetype>"]``
          so metrics / logs can slice by growth axis without re-parsing
          the id.
        - ``stages`` — the vtuber 15-stage chain with per-stage tunings
          swapped in for cache / evaluate / loop stages.
        - ``tools.external`` — the stage default or caller override.

    Raises:
        ValueError: If the stage prefix is not infant/child/teen/adult.
    """
    stage, archetype = parse_stage_manifest_id(manifest_id)
    if stage not in _STAGE_KEYS:
        raise ValueError(
            f"unknown stage manifest id '{manifest_id}'. "
            f"Stage prefix must be one of: {sorted(_STAGE_KEYS)}"
        )

    from geny_executor.core.environment import (
        EnvironmentManifest,
        EnvironmentMetadata,
        ToolsSnapshot,
    )

    # External tools — caller override wins; otherwise the stage default.
    if external_tool_names is None:
        effective_external = list(_STAGE_TOOL_DEFAULTS[stage])
    else:
        effective_external = list(external_tool_names)

    stage_desc = _STAGE_DESCRIPTIONS[stage]
    if archetype:
        description = f"Stage manifest '{manifest_id}': {stage_desc}; archetype={archetype}."
    else:
        description = f"Stage manifest '{manifest_id}': {stage_desc}."

    tags = [f"stage:{stage}"]
    if archetype:
        tags.append(f"archetype:{archetype}")

    metadata = EnvironmentMetadata(
        id="",
        name=f"stage:{manifest_id}",
        description=description,
        tags=tags,
        base_preset=_BASE_PRESET,
    )

    tools = ToolsSnapshot(
        built_in=list(built_in_tool_names or []),
        external=effective_external,
    )

    model_block: Dict[str, Any] = {"model": model} if model else {}

    entries = _build_stage_entries(stage)

    return EnvironmentManifest(
        metadata=metadata,
        model=model_block,
        pipeline={},
        stages=[e.to_dict() for e in entries],
        tools=tools,
    )


# ── Internals ─────────────────────────────────────────────────────────


def _build_stage_entries(stage: str) -> List["object"]:
    """Emit the stage-entry list for *stage*.

    Mirrors :func:`_vtuber_stage_entries` in :mod:`default_manifest`
    (same chain, no stage 8 think) but with three entries
    stage-parameterised:

    - Stage 5 (cache): swapped based on :data:`_STAGE_CACHE`.
    - Stage 14 (evaluate): swapped based on :data:`_STAGE_EVALUATOR`.
    - Stage 16 (loop): ``max_turns`` from :data:`_STAGE_MAX_TURNS`.

    Kept inline rather than importing the vtuber variant so changing
    one preset doesn't silently move the other. The duplication is
    small and the diff across stage manifests stays legible.

    Layout updated for geny-executor 1.0+ — agent moved 11→12,
    evaluate 12→14, loop 13→16, emit 14→17, memory 15→18,
    yield 16→21. The five new scaffold stages (11/13/15/19/20)
    are emitted with ``active=False`` for parity with
    :func:`default_manifest._build_stage_entries`.
    """
    from geny_executor.core.environment import StageManifestEntry

    base = [
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
            strategies={"strategy": _STAGE_CACHE[stage]},
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
        # Stage 8 (think) intentionally omitted — matches vtuber.
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
            strategies={
                "strategy": _STAGE_EVALUATOR[stage],
                "scorer": "no_scorer",
            },
        ),
        StageManifestEntry(
            order=16,
            name="loop",
            strategies={"controller": "standard"},
            config={"max_turns": _STAGE_MAX_TURNS[stage]},
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
    # Append Sub-phase 9a scaffold entries (active=False) by reusing
    # the default_manifest helper so the two builders never drift.
    from service.executor.default_manifest import _make_scaffold_entries

    base.extend(_make_scaffold_entries(StageManifestEntry))
    base.sort(key=lambda e: int(getattr(e, "order", 0)))
    return base


__all__ = [
    "STAGE_ADULT",
    "STAGE_CHILD",
    "STAGE_INFANT",
    "STAGE_ORDER",
    "STAGE_TEEN",
    "build_stage_manifest",
    "is_stage_manifest_id",
    "known_stage_manifest_ids",
    "parse_stage_manifest_id",
]
