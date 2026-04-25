"""Read-side counterpart of :mod:`service.persist.install`.

Stage 20 (Persist) writes checkpoints to disk; this module reads them
back. Two operations:

- :func:`list_checkpoints(storage_path)` — enumerate available
  checkpoint ids under a session's storage_path. Used by the frontend
  Restore modal to show "which point in history can I rewind to?".
- :func:`restore_checkpoint(storage_path, checkpoint_id)` — load a
  single checkpoint into a fresh :class:`PipelineState`. The state's
  runtime fields (``llm_client`` / ``session_runtime``) are
  intentionally left unbound — the caller rebinds them on the next
  pipeline run, exactly the same contract the executor's
  ``restore_state_from_checkpoint`` uses.

The actual rebuild lives inside the executor at
:mod:`geny_executor.stages.s20_persist.restore`; this module is the
host-side adapter that bundles it with Geny's filesystem layout.

Test helper :func:`make_persister_for_storage` builds a fresh
``FilePersister`` rooted at the same ``CHECKPOINT_SUBDIR`` the
install module uses — so reads and writes always agree on the path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List, Optional

from service.persist.install import CHECKPOINT_SUBDIR

logger = logging.getLogger(__name__)


class CheckpointNotFoundError(LookupError):
    """The requested checkpoint id doesn't exist under this session."""


def make_persister_for_storage(storage_path: str | Path) -> Any:
    """Construct a :class:`FilePersister` rooted at the same checkpoint
    directory the install module writes to.

    Returns ``None`` when the storage_path is missing or the executor
    isn't importable — callers treat ``None`` as "this host hasn't
    pinned a 1.0 executor yet".
    """
    if not storage_path:
        return None

    try:
        from geny_executor.stages.s20_persist import FilePersister
    except ImportError:
        logger.debug("make_persister_for_storage: geny_executor unavailable")
        return None

    base_dir = Path(storage_path) / CHECKPOINT_SUBDIR
    return FilePersister(base_dir=base_dir)


def list_checkpoints(storage_path: str | Path) -> List[dict]:
    """Enumerate checkpoints available for *storage_path*.

    Returns a list of ``{checkpoint_id, written_at, size_bytes}``
    dicts sorted newest-first. Returns ``[]`` when the directory
    doesn't exist or contains no checkpoints — never raises.
    """
    if not storage_path:
        return []

    base_dir = Path(storage_path) / CHECKPOINT_SUBDIR
    if not base_dir.exists():
        return []

    out: List[dict] = []
    for entry in base_dir.iterdir():
        if not entry.is_file():
            continue
        # FilePersister writes one file per checkpoint with the id as
        # filename stem (e.g. ``ckpt_<sha>.json``). Use the stem as the
        # public checkpoint_id.
        try:
            stat = entry.stat()
        except OSError:
            continue
        out.append({
            "checkpoint_id": entry.stem,
            "written_at": stat.st_mtime,
            "size_bytes": stat.st_size,
        })
    out.sort(key=lambda r: r["written_at"], reverse=True)
    return out


async def restore_checkpoint(
    storage_path: str | Path,
    checkpoint_id: str,
) -> Optional[Any]:
    """Rebuild a :class:`PipelineState` from a checkpoint id.

    Args:
        storage_path: Session storage root (same value
            ``install_file_persister`` was given).
        checkpoint_id: Stem of the checkpoint file (no extension).

    Returns:
        A populated :class:`PipelineState` ready for the caller to
        bind runtime fields onto.

    Raises:
        CheckpointNotFoundError: When the persister returns ``None``
            for the id.
        ImportError: When the executor's restore helper isn't
            importable (older host pin).
    """
    persister = make_persister_for_storage(storage_path)
    if persister is None:
        raise ImportError("checkpoint restoration requires geny-executor >= 1.0")

    try:
        from geny_executor.stages.s20_persist.restore import (
            CheckpointNotFound as _CheckpointNotFound,
            restore_state_from_checkpoint,
        )
    except ImportError as exc:
        raise ImportError(
            "geny_executor.stages.s20_persist.restore unavailable — host "
            "pin is older than 1.0.0."
        ) from exc

    try:
        state = await restore_state_from_checkpoint(persister, checkpoint_id)
    except _CheckpointNotFound as exc:
        raise CheckpointNotFoundError(checkpoint_id) from exc

    logger.info(
        "restore_checkpoint: restored state from %s/%s/%s",
        storage_path, CHECKPOINT_SUBDIR, checkpoint_id,
    )
    return state


__all__ = [
    "CheckpointNotFoundError",
    "list_checkpoints",
    "make_persister_for_storage",
    "restore_checkpoint",
]
