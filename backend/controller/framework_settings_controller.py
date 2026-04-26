"""Framework settings section editor (PR-F.1.x).

Generic CRUD over the executor's SettingsLoader sections — one endpoint
family that works for every Pydantic section schema registered via
``register_section`` (in ``install_geny_settings`` and the per-section
modules added in PR-F.1.1..F.1.5).

Reads come from the resolved cascade (settings.json + env_sync) so the
operator sees what's actually loaded. Writes always land in user-scope
``~/.geny/settings.json`` — same file PermissionsController and
HookController write to, atomically rewritten.

Endpoints:
  GET   /api/framework-settings                 — list registered sections
  GET   /api/framework-settings/{name}          — current values + schema
  PATCH /api/framework-settings/{name}          — merge keys into the section
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

router = APIRouter(prefix="/api/framework-settings", tags=["framework-settings"])


# ── Schemas ──────────────────────────────────────────────


class FrameworkSectionSummary(BaseModel):
    name: str
    has_schema: bool = True
    has_data: bool = False
    # D.2 (cycle 20260426_1) — runtime reader modules for this section.
    # Empty list means either the section name is unknown to the
    # ``known_sections`` map (likely dead registration) or no module
    # reads it at runtime — either way a yellow flag for the operator.
    readers: List[str] = Field(default_factory=list)


class FrameworkSectionListResponse(BaseModel):
    sections: List[FrameworkSectionSummary] = Field(default_factory=list)


class FrameworkSectionResponse(BaseModel):
    name: str
    has_schema: bool
    # ``schema`` shadows BaseModel's reserved attribute on Pydantic v2;
    # keep the on-the-wire key but use a non-shadowing python name.
    json_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        alias="schema",
        description="JSON Schema of the section model (Pydantic .model_json_schema()).",
        serialization_alias="schema",
    )
    values: Dict[str, Any] = Field(default_factory=dict)
    settings_path: str

    model_config = {"populate_by_name": True}


class FrameworkSectionPatch(BaseModel):
    values: Dict[str, Any]


# ── Helpers ──────────────────────────────────────────────


def _user_settings_path() -> Path:
    return Path.home() / ".geny" / "settings.json"


def _read_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as exc:
        raise HTTPException(500, f"settings.json at {path} is not valid JSON: {exc}")


def _write_settings_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(data, fp, indent=2, ensure_ascii=False)
            fp.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _reload_loader() -> None:
    try:
        from geny_executor.settings import get_default_loader

        get_default_loader().reload()
    except Exception as exc:  # noqa: BLE001
        logger.warning("framework_settings: loader reload failed: %s", exc)


def _registry_names() -> List[str]:
    try:
        from geny_executor.settings.section_registry import list_section_names

        return list_section_names()
    except Exception:
        return []


def _schema_for(name: str):
    try:
        from geny_executor.settings.section_registry import get_section_schema

        return get_section_schema(name)
    except Exception:
        return None


def _section_json_schema(schema: Any) -> Optional[Dict[str, Any]]:
    """Pydantic v2: ``.model_json_schema()``. Pydantic v1 fallback:
    ``.schema()``. Other callables: no schema available."""
    if schema is None:
        return None
    method = getattr(schema, "model_json_schema", None) or getattr(schema, "schema", None)
    if not callable(method):
        return None
    try:
        return method()
    except Exception as exc:  # noqa: BLE001
        logger.warning("framework_settings: schema export failed for %r: %s", schema, exc)
        return None


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """In-place deep-merge — overlay values overwrite scalars, dicts
    merge recursively, lists are replaced wholesale (UI sends the
    full new array when editing a list-typed field)."""
    for k, v in overlay.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# ── Endpoints ────────────────────────────────────────────


@router.get("", response_model=FrameworkSectionListResponse)
async def list_sections(_auth: dict = Depends(require_auth)):
    """List every registered section + whether it currently has data
    in user-scope settings.json + which modules read it at runtime
    (per ``service.settings.known_sections.SECTION_READERS``)."""
    from service.settings.known_sections import readers_for

    names = _registry_names()
    path = _user_settings_path()
    data = _read_settings(path)
    return FrameworkSectionListResponse(
        sections=[
            FrameworkSectionSummary(
                name=n,
                has_schema=True,
                has_data=isinstance(data.get(n), dict) and bool(data.get(n)),
                readers=readers_for(n),
            )
            for n in names
        ],
    )


@router.get("/{name}", response_model=FrameworkSectionResponse)
async def get_section(name: str, _auth: dict = Depends(require_auth)):
    """Return the schema + currently-resolved values for one section."""
    if name not in _registry_names():
        raise HTTPException(404, f"unknown section {name!r}; registry: {_registry_names()}")

    path = _user_settings_path()
    data = _read_settings(path)
    raw = data.get(name)
    values: Dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}

    return FrameworkSectionResponse(
        name=name,
        has_schema=True,
        json_schema=_section_json_schema(_schema_for(name)),
        values=values,
        settings_path=str(path),
    )


@router.patch("/{name}", response_model=FrameworkSectionResponse)
async def patch_section(
    name: str,
    body: FrameworkSectionPatch,
    _auth: dict = Depends(require_auth),
):
    """Deep-merge the given values into the section. Validates against
    the registered schema by re-instantiating after the merge — invalid
    values surface as 400 without touching disk."""
    if name not in _registry_names():
        raise HTTPException(404, f"unknown section {name!r}; registry: {_registry_names()}")

    path = _user_settings_path()
    data = _read_settings(path)
    section = data.get(name)
    if not isinstance(section, dict):
        section = {}
    merged = _deep_merge(dict(section), body.values)

    # Validate before writing.
    schema = _schema_for(name)
    if schema is not None:
        try:
            schema(**merged)
        except Exception as exc:  # noqa: BLE001 — surface every validation error as 400
            raise HTTPException(400, f"section {name!r} validation failed: {exc}")

    data[name] = merged
    _write_settings_atomic(path, data)
    _reload_loader()
    return FrameworkSectionResponse(
        name=name,
        has_schema=True,
        json_schema=_section_json_schema(schema),
        values=merged,
        settings_path=str(path),
    )
