"""Phase 5 feature flags — per-layer legacy/provider routing switches.

Each layer migration (STM, LTM, Notes, Vector, Curated/Global) rolls
out behind its own ``MEMORY_LEGACY_<LAYER>`` env flag. Flags are **on
by default** — Geny ships with the legacy ``SessionMemoryManager`` as
the authoritative path. Setting a flag to ``false`` (any of: ``0``,
``false``, ``no``, ``off``) routes the corresponding layer through the
executor ``MemoryProvider`` instead.

This module is the single source of truth. Each layer's adapter reads
its flag here rather than duplicating env parsing — operators get
consistent semantics across layers.

Lookup is not cached; callers happen on the create-session path (once
per session) or low-frequency retrieval paths, so re-reading env every
time keeps things toggleable without a restart for smoke testing.
"""

from __future__ import annotations

import os

_ON_VALUES = frozenset({"1", "true", "yes", "on"})
_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def _env(name: str, default: str) -> str:
    return (os.getenv(name, default) or default).strip().lower()


def _is_on(value: str, *, default: bool) -> bool:
    if value in _ON_VALUES:
        return True
    if value in _OFF_VALUES:
        return False
    return default


def legacy_stm_enabled() -> bool:
    """MEMORY_LEGACY_STM — default True (legacy STM writes/reads active)."""
    return _is_on(_env("MEMORY_LEGACY_STM", "true"), default=True)


def legacy_ltm_enabled() -> bool:
    """MEMORY_LEGACY_LTM — default True."""
    return _is_on(_env("MEMORY_LEGACY_LTM", "true"), default=True)


def legacy_notes_enabled() -> bool:
    """MEMORY_LEGACY_NOTES — default True."""
    return _is_on(_env("MEMORY_LEGACY_NOTES", "true"), default=True)


def legacy_vector_enabled() -> bool:
    """MEMORY_LEGACY_VECTOR — default True."""
    return _is_on(_env("MEMORY_LEGACY_VECTOR", "true"), default=True)


def legacy_curated_enabled() -> bool:
    """MEMORY_LEGACY_CURATED — default True."""
    return _is_on(_env("MEMORY_LEGACY_CURATED", "true"), default=True)


def snapshot() -> dict:
    """Return the current flag snapshot for diagnostic logging."""
    return {
        "stm": legacy_stm_enabled(),
        "ltm": legacy_ltm_enabled(),
        "notes": legacy_notes_enabled(),
        "vector": legacy_vector_enabled(),
        "curated": legacy_curated_enabled(),
    }


__all__ = [
    "legacy_stm_enabled",
    "legacy_ltm_enabled",
    "legacy_notes_enabled",
    "legacy_vector_enabled",
    "legacy_curated_enabled",
    "snapshot",
]
