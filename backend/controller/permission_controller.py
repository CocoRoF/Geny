"""Permission rule CRUD (PR-E.2.1).

Mutates ``~/.geny/settings.json`` — the user-scope file in the executor's
SettingsLoader cascade. The file is the single source of truth for the
``permissions.rules`` list once :func:`install_permission_rules` decides
to read from settings.json (PR-D.2.1 dual-read priority).

Design choices
==============
* **Index-addressed mutation.** Rules don't carry stable IDs in the
  on-disk schema — they are an ordered list, and order is meaningful for
  the matrix's first-match semantics. Add/replace/delete by 0-based
  index is the smallest API surface that preserves order.

* **Atomic writes.** Write to ``settings.json.tmp`` then ``rename`` so a
  crash mid-write doesn't corrupt the file.

* **Reload after each write** so the next session pickup gets the new
  rules without an executor restart. ``SettingsLoader.reload()`` is
  cheap (a re-read of the cascade).

* **Read endpoint already exists** at ``/api/permissions/list``
  (admin_controller). This controller intentionally stays write-only so
  the two surfaces don't drift.
"""

from __future__ import annotations

import json
import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

_BEHAVIORS = {"allow", "deny", "ask"}
_SOURCES = {"user", "project", "local", "cli", "preset"}


# ── Schemas ──────────────────────────────────────────────


class PermissionRulePayload(BaseModel):
    tool_name: str = Field(..., min_length=1)
    behavior: str  # allow | deny | ask
    pattern: Optional[str] = None
    source: str = "user"
    reason: Optional[str] = None


class RulesResponse(BaseModel):
    """Full rules list — returned after every mutation so the client
    re-renders without a follow-up GET."""
    rules: List[PermissionRulePayload]
    settings_path: str


# ── Helpers ──────────────────────────────────────────────


def _user_settings_path() -> Path:
    """User-scope settings.json. Same path the executor's SettingsLoader
    consults (added by ``install_geny_settings``)."""
    return Path.home() / ".geny" / "settings.json"


def _read_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as exc:
        raise HTTPException(
            500,
            f"settings.json at {path} is not valid JSON: {exc}",
        )


def _write_settings_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
            fp.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        # Best-effort cleanup of the temp file when rename fails.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _validate_payload(payload: PermissionRulePayload) -> Dict[str, Any]:
    if payload.behavior not in _BEHAVIORS:
        raise HTTPException(
            400,
            f"behavior must be one of {sorted(_BEHAVIORS)}; got {payload.behavior!r}",
        )
    if payload.source not in _SOURCES:
        raise HTTPException(
            400,
            f"source must be one of {sorted(_SOURCES)}; got {payload.source!r}",
        )
    out: Dict[str, Any] = {
        "tool_name": payload.tool_name,
        "behavior": payload.behavior,
        "source": payload.source,
    }
    if payload.pattern is not None:
        out["pattern"] = payload.pattern
    if payload.reason is not None:
        out["reason"] = payload.reason
    return out


def _get_rules_section(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        return []
    rules = perms.get("rules")
    return list(rules) if isinstance(rules, list) else []


def _set_rules_section(data: Dict[str, Any], rules: List[Dict[str, Any]]) -> None:
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    perms["rules"] = rules


def _reload_loader() -> None:
    """Best-effort: tell the executor's loader to re-read settings.json
    so live sessions see the new rules on next pickup. Failure here is
    not fatal — the file write is the durable signal."""
    try:
        from geny_executor.settings import get_default_loader

        get_default_loader().reload()
    except Exception as exc:  # noqa: BLE001
        logger.warning("permission_rules: loader reload failed: %s", exc)


def _build_response(data: Dict[str, Any], path: Path) -> RulesResponse:
    raw_rules = _get_rules_section(data)
    return RulesResponse(
        rules=[
            PermissionRulePayload(
                tool_name=str(r.get("tool_name", "*")),
                behavior=str(r.get("behavior", "ask")),
                pattern=r.get("pattern"),
                source=str(r.get("source", "user")),
                reason=r.get("reason"),
            )
            for r in raw_rules
            if isinstance(r, dict)
        ],
        settings_path=str(path),
    )


# ── Endpoints ────────────────────────────────────────────


@router.get("/rules", response_model=RulesResponse)
async def list_rules(_auth: dict = Depends(require_auth)):
    """Read the rules currently persisted in user-scope settings.json.

    Distinct from ``/api/permissions/list`` (admin viewer) which
    returns the full cascade after merging env vars and yaml. This
    endpoint shows only the editable file so the editor UI can
    round-trip it safely.
    """
    path = _user_settings_path()
    data = _read_settings(path)
    return _build_response(data, path)


@router.post("/rules", response_model=RulesResponse)
async def append_rule(
    body: PermissionRulePayload,
    _auth: dict = Depends(require_auth),
):
    """Append a rule. Returns the full updated list."""
    entry = _validate_payload(body)
    path = _user_settings_path()
    data = _read_settings(path)
    rules = _get_rules_section(data)
    rules.append(entry)
    _set_rules_section(data, rules)
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.put("/rules/{idx}", response_model=RulesResponse)
async def replace_rule(
    idx: int,
    body: PermissionRulePayload,
    _auth: dict = Depends(require_auth),
):
    """Replace the rule at the given 0-based index."""
    entry = _validate_payload(body)
    path = _user_settings_path()
    data = _read_settings(path)
    rules = _get_rules_section(data)
    if idx < 0 or idx >= len(rules):
        raise HTTPException(404, f"rule index {idx} out of range (0..{len(rules) - 1})")
    rules[idx] = entry
    _set_rules_section(data, rules)
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)


@router.delete("/rules/{idx}", response_model=RulesResponse)
async def delete_rule(
    idx: int,
    _auth: dict = Depends(require_auth),
):
    """Remove the rule at the given 0-based index."""
    path = _user_settings_path()
    data = _read_settings(path)
    rules = _get_rules_section(data)
    if idx < 0 or idx >= len(rules):
        raise HTTPException(404, f"rule index {idx} out of range (0..{len(rules) - 1})")
    rules.pop(idx)
    _set_rules_section(data, rules)
    _write_settings_atomic(path, data)
    _reload_loader()
    return _build_response(data, path)
