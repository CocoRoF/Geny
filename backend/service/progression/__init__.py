"""Progression / life-stage transition layer — cycle 20260421_10 (X4).

:class:`ManifestSelector` decides — once per session start — whether the
creature should graduate to a new life-stage manifest. Transitions are
expressed as :class:`Transition` predicates grouped into named
**growth trees**; :data:`DEFAULT_TREE` ships the baseline
``infant → child → teen → adult`` curve.

Exposed for plan/04 §7 consumers:

- :class:`Transition` — a single edge with a pure boolean predicate.
- :class:`CharacterLike` — structural protocol so the selector doesn't
  bind to a specific ORM model; any object with ``species``,
  ``growth_tree_id``, and ``personality_archetype`` works.
- :class:`ManifestSelector` — entry point. :meth:`select` is async
  (see module docstring) and never raises.
- :data:`DEFAULT_TREE` — the baseline tree, re-exported here for
  ergonomics.
"""

from __future__ import annotations

from .selector import (
    CharacterLike,
    ManifestSelector,
    NamingFn,
    Transition,
    default_manifest_naming,
)
from .trees.default import DEFAULT_TREE, DEFAULT_TREE_ID

__all__ = [
    "CharacterLike",
    "DEFAULT_TREE",
    "DEFAULT_TREE_ID",
    "ManifestSelector",
    "NamingFn",
    "Transition",
    "default_manifest_naming",
]
