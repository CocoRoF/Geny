"""Curated/Global adapter — bridges legacy CuratedKnowledgeManager and
GlobalMemoryManager ↔ MemoryProvider.

Phase 5e scaffold. Wires the user-scoped curated knowledge layer
(``_curated_knowledge/*``) and the cross-user global memory layer
(``_global_memory/*``) write surfaces to a flag-gated adapter so a
follow-up PR can swap the bodies for real
``provider.write(scope=USER, ...)`` and ``provider.write(scope=GLOBAL,
...)`` calls without touching the caller.

Today every adapter declines (returns ``None``), keeping the legacy
markdown-on-disk paths authoritative — behavior is unchanged.

Wire point: the manager class methods themselves
(``CuratedKnowledgeManager.write_note`` etc.), so a single intercept
covers controllers, tools, scheduler, and agent_session callers in one
place rather than threading the adapter through 10+ entry points.
"""

from __future__ import annotations

from logging import getLogger
from typing import List, Optional

from service.memory_provider.flags import legacy_curated_enabled

logger = getLogger(__name__)

_WARNED_ONCE = False


def _maybe_warn() -> None:
    global _WARNED_ONCE
    if _WARNED_ONCE:
        return
    logger.warning(
        "MEMORY_LEGACY_CURATED=false but provider-backed curated/global "
        "memory is not yet implemented; falling back to legacy "
        "CuratedKnowledgeManager/GlobalMemoryManager. Set "
        "MEMORY_LEGACY_CURATED=true (or unset) to silence this."
    )
    _WARNED_ONCE = True


# ── Curated (USER scope) ─────────────────────────────────────────────


def try_curated_write_note(
    username: str,
    title: str,
    content: str,
    *,
    category: str = "topics",
    tags: Optional[List[str]] = None,
    importance: str = "medium",
    source: str = "curated",
    links_to: Optional[List[str]] = None,
    source_filename: Optional[str] = None,
) -> Optional[str]:
    """Attempt to route curated note write through provider.

    Returns:
        Filename if provider handled the write, ``None`` if the legacy
        path should run.
    """
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


def try_curated_update_note(
    username: str,
    filename: str,
    *,
    body: Optional[str] = None,
    tags: Optional[List[str]] = None,
    importance: Optional[str] = None,
    category: Optional[str] = None,
) -> Optional[bool]:
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


def try_curated_delete_note(username: str, filename: str) -> Optional[bool]:
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


# ── Global (GLOBAL scope) ────────────────────────────────────────────


def try_global_write_note(
    title: str,
    content: str,
    *,
    category: str = "topics",
    tags: Optional[List[str]] = None,
    importance: str = "medium",
    source: str = "global",
    source_session_id: Optional[str] = None,
) -> Optional[str]:
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


def try_global_update_note(
    filename: str,
    *,
    body: Optional[str] = None,
    tags: Optional[List[str]] = None,
    importance: Optional[str] = None,
) -> Optional[bool]:
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


def try_global_delete_note(filename: str) -> Optional[bool]:
    if legacy_curated_enabled():
        return None
    _maybe_warn()
    return None


__all__ = [
    "try_curated_write_note",
    "try_curated_update_note",
    "try_curated_delete_note",
    "try_global_write_note",
    "try_global_update_note",
    "try_global_delete_note",
]
