"""Geny-side helpers for the geny-executor 1.0 Stage 20 Persist slot.

The executor ships :class:`FilePersister` / :class:`NoPersister` and a
``persister`` slot on :class:`PersistStage`. This package owns the
session-scoped wiring — in particular constructing a per-session
:class:`FilePersister` rooted at the agent's ``storage_path`` and
swapping it into a manifest-built pipeline.
"""

from service.persist.install import (
    PERSIST_STAGE_ORDER,
    install_file_persister,
)

__all__ = ["PERSIST_STAGE_ORDER", "install_file_persister"]
