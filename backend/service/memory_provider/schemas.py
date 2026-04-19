"""Pydantic request/response models for the per-session memory REST surface.

Kept in the service package (rather than a separate ``app/schemas``
tree) because Geny does not centralize its pydantic models — each
controller ships its own. Exposing them from the service package
makes them importable both from the controller and from tests.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MemoryBackendInfo(BaseModel):
    layer: str
    backend: str


class MemoryDescriptorResponse(BaseModel):
    """Mirror of :class:`MemoryDescriptor` trimmed for JSON.

    ``config`` is the factory config dict the session's provider was
    built with (minus the auto-injected ``session_id``). Round-trippable
    into a duplicate-session form by the UI.
    """

    session_id: str
    provider: str
    version: str = ""
    scope: str
    layers: List[str] = Field(default_factory=list)
    capabilities: List[str]
    backends: List[MemoryBackendInfo]
    metadata: Dict[str, Any] = Field(default_factory=dict)
    config: Optional[Dict[str, Any]] = None


class MemoryRetrievalRequest(BaseModel):
    """Ad-hoc retrieval against the session's unified provider."""

    query: str = ""
    top_k: int = Field(default=5, ge=1, le=50)
    layers: Optional[List[str]] = None
    tags: Optional[List[str]] = None


class MemoryChunkPayload(BaseModel):
    key: str
    content: str
    source: str
    relevance_score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryRetrievalResponse(BaseModel):
    chunks: List[MemoryChunkPayload]


class MemoryClearResponse(BaseModel):
    cleared: bool
