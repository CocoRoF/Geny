"""``ManifestSelector`` — session-start life-stage manifest resolver.

Plan/04 §7 models growth as *manifest replacement*: when a creature's
stats cross a transition predicate, the next session swaps the whole
manifest (tool roster, prompt tone, emotion thresholds) instead of
flipping scattered flags. This module provides the pure-logic part of
that flow:

- :class:`Transition` — one edge ``(from_stage, to_stage, predicate)``.
  ``predicate`` is a sync function of :class:`CreatureState`; keeping
  it sync simplifies tree authoring and is enough for the MVP — none
  of the default predicates need I/O.
- :class:`ManifestSelector` — walks the tree for a character's current
  ``life_stage`` and returns the manifest id to use next. Async not
  because today's lookup requires it but because :class:`AgentSession`
  is async-native; future trees loaded from storage can await without
  a signature break.

**Contract.** :meth:`ManifestSelector.select` must never raise.
Unknown ``growth_tree_id``, unknown ``life_stage``, predicate failures,
and missing character attributes all resolve to the caller's current
``progression.manifest_id`` so a turn never fails because of a
selector bug. The integration layer (PR-X4-5) can then compare "new
vs current" to decide whether to persist a transition mutation and
rebuild the pipeline.

Naming is decoupled from the tree — the selector accepts a
:data:`NamingFn` so the X4-2 manifest filenames can diverge from the
stage keyword without touching tree code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from backend.service.state.schema.creature_state import CreatureState

logger = logging.getLogger(__name__)


@runtime_checkable
class CharacterLike(Protocol):
    """Minimum character shape the selector reads.

    Kept as a :class:`Protocol` so the selector doesn't depend on the
    repository's :class:`Character` ORM model (which PR-X4-5 will
    extend with these attributes). Tests pass plain dataclasses.
    """

    species: str
    growth_tree_id: str
    personality_archetype: str


@dataclass(frozen=True)
class Transition:
    """One growth-tree edge.

    ``predicate`` inspects the *current* snapshot; the selector never
    calls it with stale data because it runs at session-start on the
    hydrated :class:`CreatureState`. Raising from a predicate is
    treated as "does not apply" — a buggy tree must not brick turns.
    """

    from_stage: str
    to_stage: str
    predicate: Callable[[CreatureState], bool]


NamingFn = Callable[[str, CharacterLike], str]


def default_manifest_naming(stage: str, character: CharacterLike) -> str:
    """Default mapping ``(stage, character) → manifest_id``.

    Emits ``"{stage}_{archetype}"`` when an archetype is set, else
    falls back to the bare stage name. Plan/04 §7.2 lists the intended
    filenames (``infant_cheerful``, ``teen_introvert``, …); species
    is captured by the ``growth_tree_id`` choice already, so it's not
    part of the id to avoid a combinatorial explosion in manifest
    files (species × archetype × stage).
    """
    archetype = getattr(character, "personality_archetype", None) or ""
    archetype = archetype.strip()
    if not archetype:
        return stage
    return f"{stage}_{archetype}"


class ManifestSelector:
    """Resolve a character's next-session manifest id.

    Parameters
    ----------
    trees:
        Mapping ``growth_tree_id → Sequence[Transition]``. Order inside
        a tree matters — the first matching edge wins. The selector
        uses ``DEFAULT_TREE_ID`` as a fallback only if the configured
        tree id is unknown (plan/04 §7.6 single-tree default).
    naming:
        Strategy for turning ``(stage, character)`` into a manifest id.
        Defaults to :func:`default_manifest_naming` for simple
        ``"{stage}_{archetype}"`` files; override for tests or when a
        deployment wants a different layout.
    default_tree_id:
        Fallback tree id consulted when ``character.growth_tree_id``
        isn't registered. Defaults to ``"default"`` — matches
        :data:`DEFAULT_TREE_ID`. Set ``None`` to return the current
        manifest id instead of walking any tree on unknown lookups.
    """

    def __init__(
        self,
        trees: Mapping[str, Sequence[Transition]],
        *,
        naming: NamingFn = default_manifest_naming,
        default_tree_id: str | None = "default",
    ) -> None:
        # Defensive copy — callers occasionally hand us a mutable dict
        # they later edit; the selector should snapshot its config at
        # construction.
        self._trees: dict[str, tuple[Transition, ...]] = {
            k: tuple(v) for k, v in trees.items()
        }
        self._naming = naming
        self._default_tree_id = default_tree_id

    @property
    def trees(self) -> Mapping[str, tuple[Transition, ...]]:
        """Read-only view of registered trees (for diagnostics / tests)."""
        return dict(self._trees)

    async def select(
        self, creature: CreatureState, character: CharacterLike,
    ) -> str:
        """Return the manifest id this session should use.

        When no transition applies (or any lookup fails) the caller's
        ``progression.manifest_id`` is returned unchanged — callers can
        diff against it to decide whether to commit a transition
        mutation. Predicate exceptions are logged at debug and treated
        as "does not apply"; they must not abort the turn.
        """
        current_manifest = self._current_manifest(creature)
        tree = self._resolve_tree(character)
        if not tree:
            return current_manifest

        current_stage = getattr(creature.progression, "life_stage", "") or ""
        for edge in tree:
            if edge.from_stage != current_stage:
                continue
            try:
                fires = bool(edge.predicate(creature))
            except Exception:
                logger.debug(
                    "predicate for %s→%s raised; skipping",
                    edge.from_stage,
                    edge.to_stage,
                    exc_info=True,
                )
                continue
            if fires:
                try:
                    return self._naming(edge.to_stage, character)
                except Exception:
                    logger.debug(
                        "naming fn failed for stage=%s; staying on %s",
                        edge.to_stage,
                        current_manifest,
                        exc_info=True,
                    )
                    return current_manifest

        return current_manifest

    def _current_manifest(self, creature: CreatureState) -> str:
        manifest_id = getattr(
            getattr(creature, "progression", None), "manifest_id", None,
        )
        if isinstance(manifest_id, str) and manifest_id:
            return manifest_id
        return "base"

    def _resolve_tree(
        self, character: CharacterLike,
    ) -> tuple[Transition, ...]:
        tree_id: Any = getattr(character, "growth_tree_id", None)
        if isinstance(tree_id, str) and tree_id in self._trees:
            return self._trees[tree_id]
        if (
            self._default_tree_id is not None
            and self._default_tree_id in self._trees
        ):
            return self._trees[self._default_tree_id]
        return ()
