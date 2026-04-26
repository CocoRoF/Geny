"""Custom MCP server CRUD (Cycle G — MCP custom server 추가 UI).

Writes JSON server definitions into ``backend/mcp/custom/`` so the
operator doesn't need shell access to add a server. Reloads the
MCPLoader after every mutation so live sessions pick the new server up
on next reconnect.

Designed to read what's already there + write what's safe — no schema
gymnastics, the operator is editing structured JSON either way.
"""

from __future__ import annotations

import json
import re
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/mcp/custom", tags=["mcp"])


def _custom_dir() -> Path:
    # Mirror MCPLoader's default: <PROJECT_ROOT>/mcp/custom/
    here = Path(__file__).resolve().parent.parent
    return here / "mcp" / "custom"


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


def _resolve_path(name: str) -> Path:
    if not _NAME_RE.match(name):
        raise HTTPException(
            400,
            f"invalid server name {name!r}; use lower-case alnum / dash / underscore (2-64 chars)",
        )
    return _custom_dir() / f"{name}.json"


class CustomServerSummary(BaseModel):
    name: str
    path: str
    type: Optional[str] = None
    description: Optional[str] = None


class CustomServerListResponse(BaseModel):
    servers: List[CustomServerSummary] = Field(default_factory=list)
    custom_dir: str


class CustomServerUpsertRequest(BaseModel):
    name: str
    config: Dict[str, Any]
    description: Optional[str] = None


class CustomServerDetail(BaseModel):
    name: str
    path: str
    config: Dict[str, Any]


def _reload_loader() -> None:
    try:
        from service.mcp_loader import get_mcp_loader_instance

        loader = get_mcp_loader_instance()
        if loader is not None and hasattr(loader, "load_all"):
            loader.load_all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("custom MCP reload failed: %s", exc)


@router.get("", response_model=CustomServerListResponse)
async def list_custom(_auth: dict = Depends(require_auth)):
    d = _custom_dir()
    rows: List[CustomServerSummary] = []
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                rows.append(CustomServerSummary(name=f.stem, path=str(f), description="(invalid JSON)"))
                continue
            rows.append(CustomServerSummary(
                name=f.stem,
                path=str(f),
                type=str(data.get("type") or data.get("transport") or "?"),
                description=data.get("description"),
            ))
    return CustomServerListResponse(servers=rows, custom_dir=str(d))


@router.get("/{name}", response_model=CustomServerDetail)
async def get_custom(name: str, _auth: dict = Depends(require_auth)):
    p = _resolve_path(name)
    if not p.exists():
        raise HTTPException(404, f"custom MCP server {name!r} not found at {p}")
    try:
        config = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"{p} is not valid JSON: {exc}")
    return CustomServerDetail(name=name, path=str(p), config=config)


@router.post("", response_model=CustomServerDetail)
async def create_custom(
    body: CustomServerUpsertRequest,
    _auth: dict = Depends(require_auth),
):
    p = _resolve_path(body.name)
    if p.exists():
        raise HTTPException(409, f"server {body.name!r} already exists at {p}")
    payload = dict(body.config)
    if body.description is not None:
        payload.setdefault("description", body.description)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _reload_loader()
    return CustomServerDetail(name=body.name, path=str(p), config=payload)


@router.put("/{name}", response_model=CustomServerDetail)
async def replace_custom(
    name: str,
    body: CustomServerUpsertRequest,
    _auth: dict = Depends(require_auth),
):
    if body.name != name:
        raise HTTPException(400, "URL name differs from body name")
    p = _resolve_path(name)
    if not p.exists():
        raise HTTPException(404, f"server {name!r} not found at {p}")
    payload = dict(body.config)
    if body.description is not None:
        payload.setdefault("description", body.description)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _reload_loader()
    return CustomServerDetail(name=name, path=str(p), config=payload)


@router.delete("/{name}")
async def delete_custom(name: str, _auth: dict = Depends(require_auth)):
    p = _resolve_path(name)
    if not p.exists():
        raise HTTPException(404, f"server {name!r} not found at {p}")
    p.unlink()
    _reload_loader()
    return {"deleted": True, "name": name}
