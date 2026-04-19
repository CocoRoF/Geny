"""Per-session memory REST surface (new in Phase 2).

Lives next to the legacy ``memory_controller`` (``/api/agents/{id}/memory``)
without replacing it — this new surface is mounted under
``/api/sessions/{id}/memory`` and is backed by the executor v0.20.0
:class:`MemoryProvider` contract via :class:`MemorySessionRegistry`.

Returns 503 when the registry is not configured (default until
``MEMORY_PROVIDER`` env plumbing lands in PR #4), 404 when the session
or its provider is missing, and 409 when the provider lacks the
capability required for the request. No silent degradation.
"""

from __future__ import annotations

from logging import getLogger

from fastapi import APIRouter, HTTPException, Request

from controller.agent_controller import agent_manager
from service.memory_provider.exceptions import MemorySessionNotFoundError
from service.memory_provider.schemas import (
    MemoryChunkPayload,
    MemoryClearResponse,
    MemoryDescriptorResponse,
    MemoryRetrievalRequest,
    MemoryRetrievalResponse,
)

logger = getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["session-memory"])


def _memory_registry(request: Request):
    registry = getattr(request.app.state, "memory_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=503,
            detail="Memory registry not configured",
        )
    return registry


def _require_session(session_id: str) -> None:
    if not agent_manager.has_agent(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


@router.get("/{session_id}/memory", response_model=MemoryDescriptorResponse)
async def get_memory(request: Request, session_id: str):
    _require_session(session_id)
    registry = _memory_registry(request)
    try:
        return registry.describe(session_id)
    except MemorySessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No memory provider attached to this session",
        )


@router.post(
    "/{session_id}/memory/retrieve",
    response_model=MemoryRetrievalResponse,
)
async def retrieve_memory(
    request: Request,
    session_id: str,
    body: MemoryRetrievalRequest,
):
    _require_session(session_id)
    registry = _memory_registry(request)
    try:
        provider = registry.require(session_id)
    except MemorySessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="No memory provider attached to this session",
        )

    # Import locally: keeps module import cheap for apps that never hit
    # this endpoint (e.g. legacy deployments with registry disabled).
    from geny_executor.memory.provider import Capability, Layer, RetrievalQuery

    if Capability.SEARCH not in provider.descriptor.capabilities:
        raise HTTPException(
            status_code=409,
            detail="This memory provider does not support retrieval",
        )

    if body.layers:
        try:
            layer_set = {Layer(x) for x in body.layers}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid layer: {exc}")
        query = RetrievalQuery(
            text=body.query,
            layers=layer_set,
            max_per_layer=body.top_k,
            tag_filter=set(body.tags or ()),
        )
    else:
        query = RetrievalQuery(
            text=body.query,
            max_per_layer=body.top_k,
            tag_filter=set(body.tags or ()),
        )

    result = await provider.retrieve(query)
    chunks = [
        MemoryChunkPayload(
            key=c.key,
            content=c.content,
            source=c.source,
            relevance_score=c.relevance_score,
            metadata=dict(c.metadata),
        )
        for c in result.chunks
    ]
    return MemoryRetrievalResponse(chunks=chunks)


@router.delete("/{session_id}/memory", response_model=MemoryClearResponse)
async def clear_memory(request: Request, session_id: str):
    _require_session(session_id)
    registry = _memory_registry(request)
    released = registry.release(session_id)
    if not released:
        raise HTTPException(
            status_code=404,
            detail="No memory provider attached to this session",
        )
    return MemoryClearResponse(cleared=True)
