"""Install a session-scoped :class:`FilePersister` into a built pipeline.

Stage 20 (Persist) carries a ``no_persist`` placeholder strategy in
the manifest because the real :class:`FilePersister` needs a
per-session ``storage_path`` that isn't manifest-serializable. This
helper runs after :meth:`Pipeline.attach_runtime` and swaps the
slot's strategy in place.

Mirrors ``service/emit/chain_install.py``: a tiny, explicit boundary
that keeps the executor oblivious to Geny's storage-layout concerns.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# geny-executor 1.0+ Sub-phase 9a: persist landed at order 20.
PERSIST_STAGE_ORDER: int = 20

# Subdirectory under the session's storage_path that file-backed
# checkpoints live under. Kept as a module constant so tests and
# follow-on tooling agree on the location without re-deriving it.
CHECKPOINT_SUBDIR: str = "checkpoints"


def _get_persist_stage(pipeline: Any) -> Any:
    getter = getattr(pipeline, "get_stage", None)
    if callable(getter):
        return getter(PERSIST_STAGE_ORDER)
    stages = getattr(pipeline, "_stages", None)
    if isinstance(stages, dict):
        return stages.get(PERSIST_STAGE_ORDER)
    return None


def install_file_persister(
    pipeline: Any,
    storage_path: Optional[str | Path],
) -> Optional[Any]:
    """Wire a per-session :class:`FilePersister` into Stage 20.

    Args:
        pipeline: A built :class:`Pipeline` (typically produced by
            :meth:`Pipeline.from_manifest_async`).
        storage_path: The session's host-side storage root. When
            ``None`` or empty the helper is a no-op — Stage 20 stays
            on the manifest's ``no_persist`` placeholder.

    Returns:
        The constructed :class:`FilePersister` instance on success,
        or ``None`` when the helper was a no-op (no storage path,
        no Persist stage, or no ``persister`` slot to swap).

    Idempotent — calling twice on the same pipeline reseats the
    persister with a fresh instance pointing at the same directory.
    """
    if not storage_path:
        logger.debug(
            "install_file_persister: no storage_path supplied; staying on no_persist"
        )
        return None

    stage = _get_persist_stage(pipeline)
    if stage is None:
        logger.debug(
            "install_file_persister: pipeline has no stage at order %d; skipping",
            PERSIST_STAGE_ORDER,
        )
        return None

    slots = stage.get_strategy_slots() if hasattr(stage, "get_strategy_slots") else None
    if not slots or "persister" not in slots:
        logger.debug(
            "install_file_persister: stage %r has no persister slot; skipping",
            getattr(stage, "name", type(stage).__name__),
        )
        return None

    # Local import keeps this module importable on hosts that haven't
    # yet pinned geny-executor 1.0 (e.g. CI lint without full deps).
    from geny_executor.stages.s20_persist import FilePersister

    base_dir = Path(storage_path) / CHECKPOINT_SUBDIR
    persister = FilePersister(base_dir=base_dir)
    slots["persister"].strategy = persister
    logger.info(
        "install_file_persister: Stage %d wired to FilePersister at %s",
        PERSIST_STAGE_ORDER,
        base_dir,
    )
    return persister


__all__ = [
    "CHECKPOINT_SUBDIR",
    "PERSIST_STAGE_ORDER",
    "install_file_persister",
]
