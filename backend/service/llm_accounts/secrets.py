"""Where account secrets live — and why not in the database.

API keys, ``claude setup-token`` values and Codex OAuth token sets are
written to one 0600 JSON file outside the database. Two reasons:

* A database dump, a backup, a replica or a support query never carries
  them. The ``llm_accounts`` row only records that a secret exists.
* Codex rotates its refresh token on every use. The write path has to be
  atomic (write-and-rename) or a crash mid-write leaves the account with no
  usable token and no way back except a fresh login.

``GENY_LLM_SECRETS`` points the file at a mounted volume so a container
rebuild does not log every account out; otherwise it is
``~/.geny/llm_accounts.json`` next to the MCP credential store.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

__all__ = ["SecretStore", "get_secret_store", "secrets_path"]

SECRETS_FILE = "llm_accounts.json"


def secrets_path() -> Path:
    env = (os.environ.get("GENY_LLM_SECRETS") or "").strip()
    if env:
        return Path(env)
    return Path.home() / ".geny" / SECRETS_FILE


class SecretStore:
    """A tiny, process-shared, atomically-written secret file."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else secrets_path()
        self._lock = threading.RLock()
        self._cache: Optional[Dict[str, Any]] = None

    @property
    def path(self) -> Path:
        return self._path

    # ── io ───────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Drop the cache so the next read sees the file as it is now.

        The cache is never invalidated on its own, so a process that has read
        once can no longer observe a write by a SIBLING process. That is fine
        for ordinary reads and fatal for a single-use OAuth refresh: the
        whole point of re-reading inside the cross-process lock is to notice
        that another process already rotated the token, and a cached copy
        would hide exactly that.
        """
        with self._lock:
            self._cache = None

    def _load(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        data: Dict[str, Any] = {}
        try:
            if self._path.exists():
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
        except (OSError, json.JSONDecodeError) as exc:
            # Never crash the server over an unreadable secret file — the
            # accounts simply read as "no secret" and the user re-enters one.
            logger.error("llm secret store unreadable at %s: %s", self._path, exc)
        self._cache = data
        return data

    def _flush(self, data: Dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self._path)
        try:
            os.chmod(self._path, 0o600)
        except OSError:  # a mounted volume may refuse chmod
            pass
        self._cache = data

    # ── api ──────────────────────────────────────────────────────────
    def get(self, account_id: str) -> Optional[Any]:
        with self._lock:
            value = self._load().get(account_id)
            return value if value not in ("", None) else None

    def get_str(self, account_id: str) -> str:
        value = self.get(account_id)
        return value if isinstance(value, str) else ""

    def get_dict(self, account_id: str) -> Dict[str, Any]:
        value = self.get(account_id)
        return dict(value) if isinstance(value, dict) else {}

    def has(self, account_id: str) -> bool:
        return self.get(account_id) is not None

    def set(self, account_id: str, value: Any) -> None:
        with self._lock:
            data = dict(self._load())
            if value in ("", None):
                data.pop(account_id, None)
            else:
                data[account_id] = value
            self._flush(data)

    def delete(self, account_id: str) -> None:
        self.set(account_id, None)


_store: Optional[SecretStore] = None
_store_lock = threading.Lock()


def get_secret_store() -> SecretStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = SecretStore()
    return _store
