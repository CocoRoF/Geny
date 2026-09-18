"""Claude Code CLI version management — keep up-to-date + roll back.

The ``claude`` binary backs geny-executor's ``geny_claude_code`` provider.
The Docker image installs ``@anthropic-ai/claude-code@latest`` at build
time, which freezes the version until the next image rebuild. This module
adds a *runtime* mechanism so an operator can:

  * see the installed version vs. the latest published on npm,
  * update to the latest (or a specific) version, and
  * roll back to the previously-installed version,

with the chosen version PERSISTED (``backend/data/claude_code_version.json``)
and re-applied on boot — so a rollback survives a container restart and a
"keep latest" choice re-pulls latest on startup.

All shell-outs are best-effort + bounded; failures surface as ``ok:false``
with a message rather than raising, so a broken npm/network never takes the
app down.
"""

from __future__ import annotations

import asyncio
import json
import re
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = getLogger(__name__)

_PKG = "@anthropic-ai/claude-code"
# backend/service/claude_code/version_service.py → backend/data/…
_PIN_PATH = Path(__file__).resolve().parents[2] / "data" / "claude_code_version.json"
_HISTORY_MAX = 10

# Serialise npm mutations — concurrent ``npm install -g`` corrupts the global tree.
_lock = asyncio.Lock()


async def _run(cmd: List[str], timeout: float) -> Tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


async def current_version() -> Optional[str]:
    """The installed Claude Code version, or ``None`` if not found."""
    try:
        rc, out, _ = await _run(["claude", "--version"], 20)
        if rc == 0:
            m = re.search(r"\d+\.\d+\.\d+", out)
            if m:
                return m.group(0)
    except Exception:  # noqa: BLE001
        logger.debug("claude --version failed", exc_info=True)
    # Fallback: ask npm.
    try:
        rc, out, _ = await _run(["npm", "ls", "-g", _PKG, "--json", "--depth=0"], 30)
        data = json.loads(out or "{}")
        return (data.get("dependencies", {}).get(_PKG, {}) or {}).get("version")
    except Exception:  # noqa: BLE001
        return None


async def latest_version() -> Optional[str]:
    """The latest version published on npm, or ``None``."""
    try:
        rc, out, _ = await _run(["npm", "view", _PKG, "version"], 30)
        if rc == 0 and out.strip():
            return out.strip()
    except Exception:  # noqa: BLE001
        logger.debug("npm view failed", exc_info=True)
    return None


def _load_pin() -> Dict[str, Any]:
    try:
        return json.loads(_PIN_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_pin(data: Dict[str, Any]) -> None:
    try:
        _PIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PIN_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("claude_code: failed to persist version pin", exc_info=True)


async def install(version: str = "latest") -> Dict[str, Any]:
    """Install ``@anthropic-ai/claude-code@<version>`` globally and persist
    the choice. Records the previous version for rollback. Returns
    ``{ok, installed?, previous?, error?}``."""
    version = (version or "latest").strip()
    if not re.fullmatch(r"latest|\d+\.\d+\.\d+", version):
        return {"ok": False, "error": f"invalid version {version!r} (use 'latest' or x.y.z)"}
    async with _lock:
        prev = await current_version()
        try:
            rc, out, err = await _run(
                ["npm", "install", "-g", "--silent", f"{_PKG}@{version}"], 300
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": "npm install timed out"}
        if rc != 0:
            return {"ok": False, "error": (err or out or "npm install failed").strip()[-600:]}
        new = await current_version()
        pin = _load_pin()
        history = pin.get("history", [])
        if prev and prev != new and prev not in history:
            history = ([prev] + history)[:_HISTORY_MAX]
        _save_pin({
            "pinned": version,          # "latest" or a concrete x.y.z
            "installed": new,
            "previous": prev,
            "history": history,
        })
        logger.info("claude_code: installed %s (was %s) via pin=%s", new, prev, version)
        return {"ok": True, "installed": new, "previous": prev}


async def rollback() -> Dict[str, Any]:
    """Reinstall the previously-installed version (or the newest in history)."""
    pin = _load_pin()
    target = pin.get("previous") or next(iter(pin.get("history", [])), None)
    if not target:
        return {"ok": False, "error": "no previous version recorded to roll back to"}
    return await install(target)


async def status() -> Dict[str, Any]:
    """Full version status for the settings UI."""
    cur = await current_version()
    lat = await latest_version()
    pin = _load_pin()
    return {
        "package": _PKG,
        "current": cur,
        "latest": lat,
        "pinned": pin.get("pinned"),
        "previous": pin.get("previous"),
        "history": pin.get("history", []),
        "update_available": bool(cur and lat and cur != lat),
        "can_rollback": bool(pin.get("previous") or pin.get("history")),
    }


async def apply_pin_on_boot() -> None:
    """Re-apply the persisted version pin at startup (best-effort, background).

    'manual + apply-pin-on-boot' semantics: a pin set by the operator is
    re-applied so a rollback (or an explicit 'keep latest') survives a
    container restart/rebuild. No pin → leave the image's built-in version
    untouched (no surprise auto-updates)."""
    pin = _load_pin().get("pinned")
    if not pin:
        return
    try:
        cur = await current_version()
        if pin == "latest":
            lat = await latest_version()
            if lat and cur != lat:
                logger.info("claude_code: boot pin=latest → updating %s → %s", cur, lat)
                await install("latest")
        elif cur != pin:
            logger.info("claude_code: boot pin=%s → reinstalling (was %s)", pin, cur)
            await install(pin)
    except Exception:  # noqa: BLE001
        logger.warning("claude_code: apply_pin_on_boot failed", exc_info=True)
