"""Growth trees — named :class:`~backend.service.service.progression.selector.Transition` sequences.

Trees live in their own subpackage so plan/04 §7's "growth nursery"
(multiple archetype-specific trees per species) can grow without
crowding the selector module. Each tree is a module exposing a
module-level constant, intentionally keeping them declarative so a
reviewer can diff the curve without reading control flow.
"""

from __future__ import annotations

from .default import DEFAULT_TREE, DEFAULT_TREE_ID

__all__ = ["DEFAULT_TREE", "DEFAULT_TREE_ID"]
