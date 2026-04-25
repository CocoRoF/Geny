"""Geny adoption of geny-executor's MCP credential store (Phase 8).

Builds a :class:`FileCredentialStore` rooted at
``~/.geny/credentials.json`` and forwards it to the session's
``MCPManager`` so OAuth-required servers (Google Drive, etc.) can
persist their tokens across pipeline restarts.

Future: swap in OS Keychain backend on macOS / Linux Secret Service.
"""

from __future__ import annotations

from service.credentials.install import (
    CREDENTIALS_FILE,
    credentials_path,
    install_credential_store,
)

__all__ = [
    "CREDENTIALS_FILE",
    "credentials_path",
    "install_credential_store",
]
