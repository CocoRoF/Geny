"""Single-use OAuth refresh tokens, and how not to lose an account to one.

Some providers rotate on redemption: the refresh POST mints a new pair and
**revokes the old one**. That makes a refresh token a one-shot resource, and
it turns three ordinary situations into a permanent lockout:

  * Two turns refresh the same account at once. Both read the same token,
    both POST it, and the loser gets ``invalid_grant`` — the account is out
    until someone signs in again.
  * The POST succeeds but the write-back fails. The old pair is already
    dead server-side, so every later attempt replays a spent token.
  * Two processes share the secret file. Same as the first case, except no
    in-process lock can see it.

This module is the one place that knows the rule. It gives callers:

  * :data:`SINGLE_USE_REFRESH_KINDS` — which account kinds rotate.
  * :func:`refresh_guard` — a cross-process lock around read → POST →
    write-back, so those three steps are atomic against every other Geny
    process sharing the file.
  * a spent-token registry — one-way fingerprints of tokens whose POST
    succeeded but whose replacement never landed, kept in-process AND in a
    sidecar next to the secret file so sibling processes fail closed too.
  * :class:`CredentialPersistError` — the failure a caller must never
    swallow, because swallowing it is what strands the account.

The shape is Hermes's (``agent/credential_pool.py`` / ``anthropic_credentials``);
the reasoning is the same and the hazard is identical.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "CredentialPersistError",
    "SINGLE_USE_REFRESH_KINDS",
    "fingerprint",
    "is_spent",
    "mark_spent",
    "refresh_guard",
]

#: Account kinds whose OAuth refresh token is revoked the moment it is
#: redeemed. Redeeming one from two places strands whichever loses the race.
#: ``claude_code`` is absent on purpose: its login is a config dir the CLI
#: owns and rotates itself, so Geny never POSTs a refresh for it.
SINGLE_USE_REFRESH_KINDS = frozenset({"codex"})

#: How long to wait for another process to finish its refresh. Generous: the
#: alternative to waiting is redeeming the same token twice.
LOCK_TIMEOUT_S = 30.0

_SPENT_MAX_TRACKED = 64
_SPENT_LOCK = threading.Lock()
_SPENT: "OrderedDict[str, None]" = OrderedDict()

_SIDECAR_NOTE = (
    "One-way fingerprints of OAuth credentials whose refresh was consumed "
    "server-side but never durably written back. Geny writes this so a "
    "sibling process sharing this secret file fails closed instead of "
    "replaying a spent single-use refresh token. Contains no secrets."
)


class CredentialPersistError(RuntimeError):
    """A rotated single-use pair could not be written back.

    The refresh POST already spent the old token, so swallowing this leaves a
    dead pair on disk that replays as ``invalid_grant`` forever.
    """

    def __init__(self, path: Any, cause: BaseException) -> None:
        super().__init__(f"could not persist rotated credentials to {path}: {cause}")
        self.path = path
        self.cause = cause


def fingerprint(secret: Any) -> Optional[str]:
    """A short, non-reversible id for a secret, or ``None`` if there isn't one."""
    text = str(secret or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _sidecar_path(store_path: Path) -> Path:
    return store_path.with_name(store_path.name + ".spent-rotations.json")


def _read_sidecar(store_path: Optional[Path]) -> set:
    if store_path is None:
        return set()
    try:
        raw = json.loads(_sidecar_path(store_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    entries = raw.get("fingerprints") if isinstance(raw, dict) else None
    return set(entries) if isinstance(entries, list) else set()


def _append_sidecar(store_path: Path, new: list) -> None:
    path = _sidecar_path(store_path)
    known = _read_sidecar(store_path) | set(new)
    payload = {"_note": _SIDECAR_NOTE, "fingerprints": sorted(known)}
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # best effort: the in-process set still guards us
        logger.warning("spent-rotation sidecar not written to %s: %s", path, exc)


def mark_spent(*secrets: Any, store_path: Optional[Path] = None) -> None:
    """Record that these secrets belong to a rotation that was consumed but
    never committed, so nothing replays them."""
    recorded = [fp for fp in map(fingerprint, secrets) if fp]
    if not recorded:
        return
    with _SPENT_LOCK:
        for fp in recorded:
            _SPENT.pop(fp, None)
            _SPENT[fp] = None
            while len(_SPENT) > _SPENT_MAX_TRACKED:
                _SPENT.popitem(last=False)
    if store_path is not None:
        _append_sidecar(store_path, recorded)


def is_spent(secret: Any, *, store_path: Optional[Path] = None) -> bool:
    """True when *secret* was already redeemed without its replacement landing."""
    fp = fingerprint(secret)
    if not fp:
        return False
    with _SPENT_LOCK:
        if fp in _SPENT:
            return True
    return fp in _read_sidecar(store_path)


@contextlib.asynccontextmanager
async def refresh_guard(
    store_path: Optional[Path], *, timeout_s: float = LOCK_TIMEOUT_S
) -> AsyncIterator[bool]:
    """Serialize read → refresh → write-back across every process.

    Async on purpose. The lock is held across an HTTPS refresh, so a waiter
    can be here for a few hundred milliseconds; waiting with ``time.sleep``
    would block the event loop for every other request in this process —
    the shape of more than one past incident. The retry sleeps on the loop
    instead, so only the coroutine that wants this account waits.

    Yields ``True`` when the lock is held. Where ``flock`` is unavailable or
    the wait times out it yields ``False`` rather than raising: an
    unsynchronised refresh still beats no refresh, and the caller's in-lock
    re-read plus the spent registry remain in force.
    """
    if store_path is None:
        yield False
        return
    lock_path = Path(store_path).with_name(Path(store_path).name + ".lock")
    handle = None
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        os.chmod(lock_path, 0o600)
    except OSError as exc:
        logger.warning("refresh lock unavailable at %s: %s", lock_path, exc)
        if handle is not None:
            handle.close()
        yield False
        return

    try:
        import fcntl
    except ImportError:  # non-POSIX
        handle.close()
        yield False
        return

    deadline = time.monotonic() + timeout_s
    acquired = False
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            break
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                logger.warning("refresh lock failed on %s: %s", lock_path, exc)
                break
            if time.monotonic() >= deadline:
                logger.warning(
                    "refresh lock still held after %.0fs (%s) — proceeding "
                    "unsynchronised; the in-lock re-read still guards the token",
                    timeout_s, lock_path,
                )
                break
            await asyncio.sleep(0.05)

    try:
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            handle.close()
