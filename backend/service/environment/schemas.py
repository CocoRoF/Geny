"""Pydantic schemas for the Environment CRUD API.

Byte-compatible port of ``geny_executor_web.app.schemas.environment``. The
request / response shapes are identical so a frontend built against the web
console works against Geny unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ── Requests ─────────────────────────────────────────────


class SaveEnvironmentRequest(BaseModel):
    """Legacy save-from-session payload (preserved for v0.7.x callers)."""

    session_id: str
    name: str
    description: str = ""
    tags: List[str] = []


class CreateEnvironmentRequest(BaseModel):
    """Unified create endpoint — supports blank, preset, or from-session modes.

    *mode* is optional: when omitted, it is inferred from the payload
    (``session_id`` → from_session, ``preset_name`` → from_preset,
    otherwise → blank).
    """

    mode: Optional[Literal["blank", "from_session", "from_preset"]] = None
    name: str
    description: str = ""
    tags: List[str] = []

    # from_session mode
    session_id: Optional[str] = None

    # from_preset / blank-with-base mode
    preset_name: Optional[str] = None

    @model_validator(mode="after")
    def _resolve_and_validate_mode(self) -> "CreateEnvironmentRequest":
        if self.mode is None:
            if self.session_id:
                self.mode = "from_session"
            elif self.preset_name:
                self.mode = "from_preset"
            else:
                self.mode = "blank"
        if self.mode == "from_session" and not self.session_id:
            raise ValueError("session_id is required when mode='from_session'")
        if self.mode == "from_preset" and not self.preset_name:
            raise ValueError("preset_name is required when mode='from_preset'")
        return self


class UpdateEnvironmentRequest(BaseModel):
    """Patch top-level metadata only (name/description/tags)."""

    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None


class UpdateManifestRequest(BaseModel):
    """Replace the manifest payload wholesale (whole-template edit)."""

    manifest: Dict[str, Any]


class UpdateStageTemplateRequest(BaseModel):
    """Partial per-stage update — any field left None stays as-is."""

    artifact: Optional[str] = None
    strategies: Optional[Dict[str, str]] = None
    strategy_configs: Optional[Dict[str, Dict[str, Any]]] = None
    config: Optional[Dict[str, Any]] = None
    tool_binding: Optional[Dict[str, Any]] = None
    model_override: Optional[Dict[str, Any]] = None
    chain_order: Optional[Dict[str, List[str]]] = None
    active: Optional[bool] = None


class DuplicateEnvironmentRequest(BaseModel):
    new_name: str


class DiffEnvironmentsRequest(BaseModel):
    env_id_a: str
    env_id_b: str


class ImportEnvironmentRequest(BaseModel):
    data: Dict[str, Any]


# ── Responses ────────────────────────────────────────────


class EnvironmentSummaryResponse(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str]
    created_at: str
    updated_at: str
    stage_count: int
    active_stage_count: int = 0
    model: str
    base_preset: str = ""


class EnvironmentDetailResponse(BaseModel):
    id: str
    name: str
    description: str
    tags: List[str]
    created_at: str
    updated_at: str
    manifest: Optional[Dict[str, Any]] = None
    snapshot: Optional[Dict[str, Any]] = None


class EnvironmentListResponse(BaseModel):
    environments: List[EnvironmentSummaryResponse]


class CreateEnvironmentResponse(BaseModel):
    id: str


class DiffEntry(BaseModel):
    path: str
    change_type: str  # "added" | "removed" | "changed"
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None


class EnvironmentDiffResponse(BaseModel):
    identical: bool
    entries: List[DiffEntry]
    summary: Dict[str, int]


# ── Share schemas ────────────────────────────────────────


class ShareLinkResponse(BaseModel):
    url: str


# ── Reverse-lookup: sessions bound to an environment ─────


class EnvironmentSessionSummary(BaseModel):
    """Per-session snippet surfaced in the env → sessions reverse lookup."""

    session_id: str
    session_name: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None
    env_id: Optional[str] = None
    created_at: Optional[str] = None
    is_deleted: bool = False
    deleted_at: Optional[str] = None
    error_message: Optional[str] = None


class EnvironmentSessionsResponse(BaseModel):
    """Response for ``GET /api/environments/{id}/sessions``.

    Sourced authoritatively from SessionStore; unlike the client-side
    aggregation over ``useAppStore.sessions`` it can include soft-deleted
    records (via ``include_deleted=true``).
    """

    env_id: str
    sessions: List[EnvironmentSessionSummary]
    active_count: int
    deleted_count: int
    error_count: int


class EnvironmentSessionCountEntry(BaseModel):
    """Per-env count snapshot used by the Environments tab card grid."""

    env_id: str
    active_count: int
    deleted_count: int
    error_count: int


class EnvironmentSessionCountsResponse(BaseModel):
    """Response for ``GET /api/environments/session-counts``.

    One pass over SessionStore, bucketed by env_id — avoids the
    N-card × one-RTT explosion the single-env endpoint would cause
    when rendering many environment cards.
    """

    counts: List[EnvironmentSessionCountEntry]


__all__ = [
    "SaveEnvironmentRequest",
    "CreateEnvironmentRequest",
    "UpdateEnvironmentRequest",
    "UpdateManifestRequest",
    "UpdateStageTemplateRequest",
    "DuplicateEnvironmentRequest",
    "DiffEnvironmentsRequest",
    "ImportEnvironmentRequest",
    "EnvironmentSummaryResponse",
    "EnvironmentDetailResponse",
    "EnvironmentListResponse",
    "CreateEnvironmentResponse",
    "DiffEntry",
    "EnvironmentDiffResponse",
    "ShareLinkResponse",
    "EnvironmentSessionSummary",
    "EnvironmentSessionsResponse",
    "EnvironmentSessionCountEntry",
    "EnvironmentSessionCountsResponse",
]
