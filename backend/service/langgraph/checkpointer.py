"""
Checkpointer Factory — persistent or in-memory LangGraph checkpointer.

Provides a single factory function ``create_checkpointer()`` that:

1. **Persistent (default)** — creates a ``SqliteSaver`` (or async equivalent)
   backed by a ``.db`` file inside the session's storage directory.  This
   survives process restarts and allows graph resumption.
2. **In-memory fallback** — if ``langgraph-checkpoint-sqlite`` is not installed
   or the database path is not writable, falls back to ``MemorySaver`` and logs
   a warning.

Usage::

    from service.langgraph.checkpointer import create_checkpointer

    checkpointer = create_checkpointer(
        storage_path="/tmp/sessions/abc123",
        persistent=True,
    )
    graph = builder.compile(checkpointer=checkpointer)
"""

from __future__ import annotations

from logging import getLogger
from pathlib import Path
from typing import Optional

logger = getLogger(__name__)

# Type alias for any LangGraph-compatible checkpointer
Checkpointer = object


def create_checkpointer(
    storage_path: Optional[str] = None,
    persistent: bool = True,
    db_name: str = "langgraph_checkpoints.db",
) -> Checkpointer:
    """Create a LangGraph checkpointer.

    Args:
        storage_path: Directory where the SQLite database will be stored.
            Required when *persistent* is True.
        persistent: If True, attempt to create a SQLite-backed checkpointer.
            Falls back to MemorySaver on error.
        db_name: SQLite database filename.

    Returns:
        A LangGraph-compatible checkpointer instance.
    """
    if persistent and storage_path:
        try:
            return _create_sqlite_checkpointer(storage_path, db_name)
        except Exception as exc:
            logger.warning(
                "SqliteSaver unavailable (%s); falling back to MemorySaver",
                exc,
            )

    return _create_memory_checkpointer()


def _create_sqlite_checkpointer(
    storage_path: str,
    db_name: str,
) -> Checkpointer:
    """Create a SqliteSaver backed by a file in *storage_path*.

    Raises if the sqlite checkpoint package is not installed or the path is
    not writable.
    """
    # Ensure directory exists
    db_dir = Path(storage_path)
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / db_name

    # langgraph-checkpoint-sqlite ships SqliteSaver
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import-untyped]
    except ImportError as exc:
        # Older langgraph versions or missing optional dependency
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver as SqliteSaver  # type: ignore[import-untyped,no-redef]
        except ImportError:
            raise ImportError(
                "langgraph-checkpoint-sqlite is required for persistent "
                "checkpointing.  Install it with: "
                "pip install langgraph-checkpoint-sqlite"
            ) from exc

    conn_string = str(db_path)
    saver = SqliteSaver.from_conn_string(conn_string)

    logger.info("Persistent checkpointer: SqliteSaver at %s", db_path)
    return saver


def _create_memory_checkpointer() -> Checkpointer:
    """Volatile in-memory checkpointer (lost on restart)."""
    from langgraph.checkpoint.memory import MemorySaver

    logger.debug("In-memory checkpointer: MemorySaver")
    return MemorySaver()
