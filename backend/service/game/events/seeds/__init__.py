"""Event seed catalogue.

Kept as a subpackage so plan/04 §6.3's "per-species or per-campaign
seed set" can land later without crowding the pool module. Today the
only catalogue is :mod:`.default`, exposing
:data:`~backend.service.game.events.seeds.default.DEFAULT_SEEDS`.
"""

from __future__ import annotations

from .default import DEFAULT_SEEDS

__all__ = ["DEFAULT_SEEDS"]
