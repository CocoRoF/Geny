"""Build a FileCredentialStore and attach it to the MCPManager.

Tokens land in ``~/.geny/credentials.json`` (the executor's
``FileCredentialStore`` writes atomically). The store is process-
shared, not session-scoped — once an operator authorises a server
they don't need to re-auth on every new session.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CREDENTIALS_FILE = "credentials.json"


def credentials_path() -> Path:
    return Path.home() / ".geny" / CREDENTIALS_FILE


def install_credential_store(pipeline: Any) -> Optional[Any]:
    """Attach a :class:`FileCredentialStore` to the pipeline's MCPManager.

    Returns the store instance on success, or ``None`` when the
    pipeline has no MCPManager (no MCP servers declared) or the
    executor pin is older than 1.0.

    The MCPManager exposes credential storage via either
    ``set_credential_store`` (newer) or a public ``credential_store``
    attribute (older); both shapes are handled.
    """
    try:
        from geny_executor.tools.mcp.credentials import FileCredentialStore
    except ImportError:
        logger.debug("install_credential_store: geny_executor credentials unavailable")
        return None

    manager = getattr(pipeline, "_mcp_manager", None) or getattr(
        pipeline, "mcp_manager", None
    )
    if manager is None:
        logger.debug("install_credential_store: pipeline has no MCPManager; skipping")
        return None

    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    store = FileCredentialStore(path=path)

    setter = getattr(manager, "set_credential_store", None)
    if callable(setter):
        setter(store)
    elif hasattr(manager, "credential_store"):
        manager.credential_store = store
    else:
        logger.debug(
            "install_credential_store: MCPManager has no credential_store hook; "
            "store created but not attached"
        )
    logger.info("install_credential_store: FileCredentialStore at %s wired to MCPManager", path)
    return store


__all__ = [
    "CREDENTIALS_FILE",
    "credentials_path",
    "install_credential_store",
]
