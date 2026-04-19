"""Vector adapter — bridges legacy VectorMemoryManager ↔ MemoryProvider.

Phase 5d scaffold. Wires the FAISS-backed semantic indexing path
(`VectorMemoryManager.index_text`) to a flag-gated adapter so a
follow-up PR can swap the body for a real
``provider.vector_chunks(...).index(...)`` call without touching the
caller.

Today the adapter always declines (returns ``None``), keeping the
legacy FAISS write path authoritative. Behavior is unchanged.

Vector migration is the heaviest of the five layers — switching
providers requires a re-embedding/migration pass over existing chunks.
This PR explicitly does not attempt that; it only lands the call site
+ flag gate so the migration script + provider routing can land
together in a follow-up without further surgery on the caller.
"""

from __future__ import annotations

from logging import getLogger
from typing import Optional

from service.memory_provider.flags import legacy_vector_enabled

logger = getLogger(__name__)

_WARNED_ONCE = False


def _maybe_warn() -> None:
    global _WARNED_ONCE
    if _WARNED_ONCE:
        return
    logger.warning(
        "MEMORY_LEGACY_VECTOR=false but provider-backed vector indexing "
        "is not yet implemented; falling back to legacy "
        "VectorMemoryManager. Set MEMORY_LEGACY_VECTOR=true (or unset) "
        "to silence this."
    )
    _WARNED_ONCE = True


async def try_index_text(
    session_id: Optional[str],
    text: str,
    source_file: str,
    *,
    replace: bool = False,
) -> Optional[int]:
    """Attempt to index text via the provider's vector layer.

    Returns:
        Number of chunks added if provider handled the index, ``None``
        if the legacy FAISS path should run.
    """
    if legacy_vector_enabled():
        return None
    _maybe_warn()
    return None


__all__ = ["try_index_text"]
