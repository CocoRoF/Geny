"""
Curated Knowledge Controller — REST API for the curated knowledge vault.

Provides endpoints for browsing, searching, creating, updating, and
deleting curated knowledge notes. Also exposes the curation pipeline
for triggering curation from User Opsidian notes.

All endpoints require authentication and are scoped to the current user
via ``/api/curated/*``.
"""
from logging import getLogger
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/curated", tags=["curated-knowledge"])


# ============================================================================
# Request / Response Models
# ============================================================================

class WriteNoteRequest(BaseModel):
    title: str
    content: str
    category: str = "topics"
    tags: List[str] = Field(default_factory=list)
    importance: str = "medium"
    source: str = "user"
    links_to: List[str] = Field(default_factory=list)


class UpdateNoteRequest(BaseModel):
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    importance: Optional[str] = None
    category: Optional[str] = None


class LinkNotesRequest(BaseModel):
    source_filename: str
    target_filename: str


class CurateNoteRequest(BaseModel):
    """Request to curate a note from User Opsidian."""
    source_filename: str
    method: str = "auto"  # auto | direct | summary | extract | merge | restructure
    extra_tags: List[str] = Field(default_factory=list)
    use_llm: bool = True


class CurateBatchRequest(BaseModel):
    """Request to curate multiple notes."""
    filenames: List[str]
    use_llm: bool = True


class CurateAllRequest(BaseModel):
    """Request to curate all uncurated notes."""
    use_llm: bool = True


# ============================================================================
# Helpers
# ============================================================================

def _get_manager(username: str):
    """Get the CuratedKnowledgeManager for the authenticated user."""
    from service.memory.curated_knowledge import get_curated_knowledge_manager
    return get_curated_knowledge_manager(username)


def _get_opsidian_manager(username: str):
    """Get the UserOpsidianManager for the authenticated user."""
    from service.memory.user_opsidian import get_user_opsidian_manager
    return get_user_opsidian_manager(username)


# ============================================================================
# Endpoints — Index & Stats
# ============================================================================

@router.get("")
async def get_curated_index(auth: dict = Depends(require_auth)):
    """Get the user's curated knowledge index and stats."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    return {
        "index": mgr.get_index() or {"files": {}, "tag_map": {}, "total_files": 0, "total_chars": 0},
        "stats": mgr.get_stats(),
        "username": username,
    }


@router.get("/stats")
async def get_curated_stats(auth: dict = Depends(require_auth)):
    """Get curated knowledge statistics."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    return mgr.get_stats()


@router.get("/graph")
async def get_curated_graph(auth: dict = Depends(require_auth)):
    """Get link graph data for visualization."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    return mgr.get_graph()


@router.get("/tags")
async def get_curated_tags(auth: dict = Depends(require_auth)):
    """Get all tags and their file counts."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    idx = mgr.get_index()
    if idx is None:
        return {"tags": {}}
    return {"tags": idx.get("tag_map", {})}


# ============================================================================
# Endpoints — CRUD
# ============================================================================

@router.get("/files")
async def list_curated_files(
    category: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    auth: dict = Depends(require_auth),
):
    """List files in the user's curated knowledge vault."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    notes = mgr.list_notes(category=category, tag=tag)
    return {"files": notes, "total": len(notes)}


@router.get("/files/{filename:path}")
async def read_curated_file(
    filename: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Read a single curated knowledge note."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    result = mgr.read_note(filename)
    if result is None:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    return result


@router.post("/files")
async def create_curated_file(
    req: WriteNoteRequest,
    auth: dict = Depends(require_auth),
):
    """Create a new curated knowledge note."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    filename = mgr.write_note(
        title=req.title,
        content=req.content,
        category=req.category,
        tags=req.tags,
        importance=req.importance,
        source=req.source,
        links_to=req.links_to,
    )
    if filename is None:
        raise HTTPException(status_code=500, detail="Failed to create note")
    return {"filename": filename, "message": "Note created successfully"}


@router.put("/files/{filename:path}")
async def update_curated_file(
    req: UpdateNoteRequest,
    filename: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Update an existing curated knowledge note."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    ok = mgr.update_note(
        filename, body=req.content, tags=req.tags, importance=req.importance, category=req.category,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Update failed: {filename}")
    return {"filename": filename, "message": "Note updated successfully"}


@router.delete("/files/{filename:path}")
async def delete_curated_file(
    filename: str = Path(...),
    auth: dict = Depends(require_auth),
):
    """Delete a curated knowledge note."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    ok = mgr.delete_note(filename)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Delete failed: {filename}")
    return {"message": "Note deleted successfully"}


# ============================================================================
# Endpoints — Search
# ============================================================================

@router.get("/search")
async def search_curated(
    q: str = Query(..., min_length=1),
    max_results: int = Query(10, ge=1, le=50),
    auth: dict = Depends(require_auth),
):
    """Search across curated knowledge notes."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    results = mgr.search(q, max_results=max_results)
    return {"query": q, "results": results, "total": len(results)}


# ============================================================================
# Endpoints — Links & Reindex
# ============================================================================

@router.post("/links")
async def create_curated_link(
    req: LinkNotesRequest,
    auth: dict = Depends(require_auth),
):
    """Create a wikilink between two curated notes."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    ok = mgr.create_link(req.source_filename, req.target_filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Failed to create link")
    return {"message": "Link created"}


@router.post("/reindex")
async def reindex_curated(auth: dict = Depends(require_auth)):
    """Rebuild the full index from disk."""
    username = auth.get("sub", "anonymous")
    mgr = _get_manager(username)
    total = mgr.reindex()
    return {"message": "Reindex complete", "total_files": total}


# ============================================================================
# Endpoints — Curation Pipeline
# ============================================================================

@router.post("/curate")
async def curate_from_opsidian(
    req: CurateNoteRequest,
    auth: dict = Depends(require_auth),
):
    """Curate a note from User Opsidian through the 5-stage pipeline.

    Stages: Triage → LLM Analysis → Transform → Enrich → Store
    """
    username = auth.get("sub", "anonymous")
    curated_mgr = _get_manager(username)
    opsidian_mgr = _get_opsidian_manager(username)

    # Get LLM model for curation (optional)
    llm_model = None
    if req.use_llm:
        try:
            from service.config.sub_config.general.ltm_config import LTMConfig
            from service.config import get_config_manager
            ltm_cfg = get_config_manager().load_config(LTMConfig)
            if ltm_cfg and ltm_cfg.auto_curation_use_llm:
                from service.workflow.nodes.memory.memory_reflect_node import _get_memory_model
                llm_model = _get_memory_model()
        except Exception:
            pass  # Proceed without LLM

    from service.memory.curation_engine import CurationEngine

    engine = CurationEngine(
        curated_manager=curated_mgr,
        user_opsidian_manager=opsidian_mgr,
        llm_model=llm_model,
    )

    result = await engine.curate_note(
        req.source_filename,
        method=req.method,
        extra_tags=req.extra_tags,
        use_llm=req.use_llm,
    )

    if not result.success:
        return {
            "success": False,
            "reason": result.reason,
            "quality_score": result.quality_score,
        }

    return {
        "success": True,
        "curated_filename": result.curated_filename,
        "method_used": result.method_used,
        "quality_score": result.quality_score,
    }


@router.post("/curate/batch")
async def curate_batch_from_opsidian(
    req: CurateBatchRequest,
    auth: dict = Depends(require_auth),
):
    """Curate multiple notes from User Opsidian."""
    username = auth.get("sub", "anonymous")
    curated_mgr = _get_manager(username)
    opsidian_mgr = _get_opsidian_manager(username)

    llm_model = None
    if req.use_llm:
        try:
            from service.config.sub_config.general.ltm_config import LTMConfig
            from service.config import get_config_manager
            ltm_cfg = get_config_manager().load_config(LTMConfig)
            if ltm_cfg and ltm_cfg.auto_curation_use_llm:
                from service.workflow.nodes.memory.memory_reflect_node import _get_memory_model
                llm_model = _get_memory_model()
        except Exception:
            pass

    from service.memory.curation_engine import CurationEngine

    engine = CurationEngine(
        curated_manager=curated_mgr,
        user_opsidian_manager=opsidian_mgr,
        llm_model=llm_model,
    )

    results = await engine.curate_batch(req.filenames, use_llm=req.use_llm)

    return {
        "total": len(results),
        "success_count": sum(1 for r in results if r.success),
        "results": [
            {
                "success": r.success,
                "curated_filename": r.curated_filename,
                "method_used": r.method_used,
                "quality_score": r.quality_score,
                "reason": r.reason,
            }
            for r in results
        ],
    }


@router.post("/curate/all")
async def curate_all_from_opsidian(
    req: CurateAllRequest,
    auth: dict = Depends(require_auth),
):
    """Curate all uncurated notes from User Opsidian."""
    username = auth.get("sub", "anonymous")
    curated_mgr = _get_manager(username)
    opsidian_mgr = _get_opsidian_manager(username)

    # Get all User Opsidian filenames
    opsidian_index = opsidian_mgr.get_index()
    if not opsidian_index or not opsidian_index.get("files"):
        return {
            "total": 0,
            "success_count": 0,
            "results": [],
            "message": "No user opsidian notes found",
        }

    all_files = list(opsidian_index["files"].keys())

    # Prepare LLM model
    llm_model = None
    if req.use_llm:
        try:
            from service.config.sub_config.general.ltm_config import (
                LTMConfig,
            )
            from service.config import get_config_manager

            ltm_cfg = get_config_manager().load_config(LTMConfig)
            if ltm_cfg and ltm_cfg.auto_curation_use_llm:
                from service.workflow.nodes.memory.memory_reflect_node import (
                    _get_memory_model,
                )
                llm_model = _get_memory_model()
        except Exception:
            pass

    from service.memory.curation_engine import CurationEngine

    engine = CurationEngine(
        curated_manager=curated_mgr,
        user_opsidian_manager=opsidian_mgr,
        llm_model=llm_model,
    )

    results = await engine.curate_batch(
        all_files, use_llm=req.use_llm,
    )

    return {
        "total": len(results),
        "success_count": sum(1 for r in results if r.success),
        "results": [
            {
                "success": r.success,
                "curated_filename": r.curated_filename,
                "method_used": r.method_used,
                "quality_score": r.quality_score,
                "reason": r.reason,
            }
            for r in results
        ],
    }
