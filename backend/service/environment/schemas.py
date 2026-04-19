"""Pydantic schemas for the Environment CRUD API.

Byte-compatible port of ``geny_executor_web.app.schemas.environment``. The
request / response shapes are identical so a frontend built against the web
console works against Geny unchanged.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

# Bulk-import caps — keep here so controller stays thin and the
# values are visible alongside the request schema. Kept generous;
# not meant as DoS protection, just a guardrail against accidental
# giant drops (e.g. dragging in a 300-env dump).
BULK_IMPORT_MAX_ENTRIES = 200
BULK_IMPORT_MAX_ENTRY_BYTES = 2 * 1024 * 1024  # 2 MiB per entry JSON


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


DIFF_BULK_MAX_PAIRS = 500


class DiffPairRequest(BaseModel):
    env_id_a: str
    env_id_b: str


class DiffBulkRequest(BaseModel):
    """Batch variant of DiffEnvironmentsRequest.

    Used by the frontend diff-matrix UI to fetch summaries for N·(N-1)/2
    pairs in a single HTTP round-trip instead of fanning out one request
    per pair. The response only carries per-pair `summary` + `identical`;
    callers that want full `entries` still use `/diff` for specific pairs.
    """

    pairs: List[DiffPairRequest]

    @model_validator(mode="after")
    def _enforce_caps(self) -> "DiffBulkRequest":
        n = len(self.pairs)
        if n > DIFF_BULK_MAX_PAIRS:
            raise ValueError(
                f"too many pairs: {n} > {DIFF_BULK_MAX_PAIRS}"
            )
        return self


class ImportEnvironmentRequest(BaseModel):
    data: Dict[str, Any]


class ImportBulkEntry(BaseModel):
    """One entry in the bulk-import payload.

    `env_id` is advisory — the backend regenerates ids for the
    inserted records. Clients can supply it so the response can be
    correlated back to the originating env in their UI.
    """

    env_id: Optional[str] = None
    data: Dict[str, Any]


class ImportEnvironmentsBulkRequest(BaseModel):
    """Batch variant of ImportEnvironmentRequest.

    Mirrors the client-side export bundle shape:
    `{ version: "1", exports: [{env_id, data}] }`.

    Validation caps (see module-level constants) protect the server
    from accidentally oversized drops — hit them and the whole batch
    is rejected with 422 before any entry is processed.
    """

    version: Optional[str] = None
    entries: List[ImportBulkEntry]

    @model_validator(mode="after")
    def _enforce_caps(self) -> "ImportEnvironmentsBulkRequest":
        n = len(self.entries)
        if n > BULK_IMPORT_MAX_ENTRIES:
            raise ValueError(
                f"too many entries: {n} > {BULK_IMPORT_MAX_ENTRIES}"
            )
        for idx, entry in enumerate(self.entries):
            # Cheap size estimate via JSON round-trip. The payloads
            # live in memory already, so this is O(N) not an extra IO.
            size = len(json.dumps(entry.data, ensure_ascii=False).encode("utf-8"))
            if size > BULK_IMPORT_MAX_ENTRY_BYTES:
                raise ValueError(
                    f"entry {idx} too large: {size} > {BULK_IMPORT_MAX_ENTRY_BYTES} bytes"
                )
        return self


class ImportBulkResultEntry(BaseModel):
    env_id: Optional[str] = None
    new_id: Optional[str] = None
    ok: bool
    error: Optional[str] = None


class ImportEnvironmentsBulkResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: List[ImportBulkResultEntry]


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


class DiffBulkResultEntry(BaseModel):
    env_id_a: str
    env_id_b: str
    ok: bool
    identical: bool = False
    summary: Dict[str, int] = {}
    error: Optional[str] = None


class DiffBulkResponse(BaseModel):
    total: int
    ok: int
    failed: int
    results: List[DiffBulkResultEntry]


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
    "DiffPairRequest",
    "DiffBulkRequest",
    "ImportEnvironmentRequest",
    "ImportBulkEntry",
    "ImportEnvironmentsBulkRequest",
    "ImportBulkResultEntry",
    "ImportEnvironmentsBulkResponse",
    "EnvironmentSummaryResponse",
    "EnvironmentDetailResponse",
    "EnvironmentListResponse",
    "CreateEnvironmentResponse",
    "DiffEntry",
    "EnvironmentDiffResponse",
    "DiffBulkResultEntry",
    "DiffBulkResponse",
    "ShareLinkResponse",
    "EnvironmentSessionSummary",
    "EnvironmentSessionsResponse",
    "EnvironmentSessionCountEntry",
    "EnvironmentSessionCountsResponse",
]
