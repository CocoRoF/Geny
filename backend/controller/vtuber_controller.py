"""
VTuber Controller

REST API endpoints for:
- Live2D model CRUD and listing
- Agent-model assignment
- Avatar state queries
- Touch interaction events
- Manual emotion override (debugging/demo)

Avatar state streaming is handled by ws/avatar_stream.py (WebSocket).
"""

import json
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from logging import getLogger

logger = getLogger(__name__)

router = APIRouter(prefix="/api/vtuber", tags=["vtuber"])


def _inject_character_prompt(session_id: str, model_name: str) -> None:
    """Stage a per-model character prompt through the PersonaProvider.

    Replaces the legacy ``agent._system_prompt`` append (cycle 20260421_7
    PR-X1-3). The provider owns file caching and duplicate-write
    suppression; the pipeline picks up the change on the next turn via
    ``DynamicPersonaSystemBuilder``.
    """
    try:
        from service.langgraph import get_agent_session_manager
        manager = get_agent_session_manager()
        agent = manager.get_agent(session_id)
        if not agent or getattr(agent, '_session_type', None) != 'vtuber':
            return
        manager.persona_provider.set_character(session_id, model_name)
        logger.info(
            f"[{session_id}] Character persona staged via PersonaProvider "
            f"(model={model_name})"
        )
    except Exception as e:
        logger.debug(f"Character prompt injection failed: {e}", exc_info=True)


# ── Request/Response Models ──────────────────────────────────


class ModelAssignRequest(BaseModel):
    model_name: str


class InteractRequest(BaseModel):
    hit_area: str  # "HitAreaHead", "HitAreaBody"
    x: Optional[float] = None
    y: Optional[float] = None


class EmotionOverrideRequest(BaseModel):
    emotion: str
    intensity: float = 1.0
    transition_ms: int = 300


# ── Model Management ────────────────────────────────────────


@router.get("/models")
async def list_models(request: Request):
    """List all registered Live2D models."""
    manager = request.app.state.live2d_model_manager
    models = manager.list_models()
    return {"models": [m.to_dict() for m in models]}


@router.get("/models/{name}")
async def get_model(name: str, request: Request):
    """Get details for a specific Live2D model."""
    manager = request.app.state.live2d_model_manager
    model = manager.get_model(name)
    if not model:
        raise HTTPException(404, f"Model not found: {name}")
    return model.to_dict()


# ── Agent-Model Assignment ──────────────────────────────────


@router.put("/agents/{session_id}/model")
async def assign_model(session_id: str, req: ModelAssignRequest, request: Request):
    """Assign a Live2D model to an agent session."""
    manager = request.app.state.live2d_model_manager
    try:
        manager.assign_model_to_agent(session_id, req.model_name)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Register per-model emotion→motion mapping if available
    model = manager.get_model(req.model_name)
    if model and model.emotionMotionMap and hasattr(request.app.state, "avatar_state_manager"):
        request.app.state.avatar_state_manager.set_emotion_motion_map(
            session_id, model.emotionMotionMap
        )

    # Inject per-model character prompt into VTuber system prompt
    _inject_character_prompt(session_id, req.model_name)

    return {"status": "ok", "session_id": session_id, "model_name": req.model_name}


@router.get("/agents/{session_id}/model")
async def get_agent_model(session_id: str, request: Request):
    """Get the model currently assigned to an agent session."""
    manager = request.app.state.live2d_model_manager
    model = manager.get_agent_model(session_id)
    if not model:
        return {"session_id": session_id, "model": None}
    return {"session_id": session_id, "model": model.to_dict()}


@router.delete("/agents/{session_id}/model")
async def unassign_model(session_id: str, request: Request):
    """Remove model assignment from an agent session."""
    manager = request.app.state.live2d_model_manager
    manager.unassign_model(session_id)
    return {"status": "ok", "session_id": session_id}


@router.get("/assignments")
async def list_assignments(request: Request):
    """List all agent-model assignments."""
    manager = request.app.state.live2d_model_manager
    return {"assignments": manager.get_all_assignments()}


# ── Avatar State ────────────────────────────────────────────


@router.get("/agents/{session_id}/state")
async def get_avatar_state(session_id: str, request: Request):
    """Get current avatar display state for a session."""
    state_manager = request.app.state.avatar_state_manager
    state = state_manager.get_state(session_id)
    return state.to_sse_data()


# ── Touch Interaction ───────────────────────────────────────


@router.post("/agents/{session_id}/interact")
async def interact_with_avatar(
    session_id: str, req: InteractRequest, request: Request
):
    """Handle touch/click interaction with the Live2D avatar."""
    model_manager = request.app.state.live2d_model_manager
    state_manager = request.app.state.avatar_state_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        raise HTTPException(404, "No model assigned to this session")

    # Look up tap motion for the hit area
    tap_motions = model.tapMotions.get(req.hit_area, {})
    if tap_motions:
        motion_index = list(tap_motions.values())[0]
        motion_group = "TapBody" if "Body" in req.hit_area else "TapHead"
        await state_manager.update_state(
            session_id=session_id,
            motion_group=motion_group,
            motion_index=motion_index,
            trigger="user_interact",
        )

    return {"status": "ok", "hit_area": req.hit_area}


# ── Emotion Override (Debug/Demo) ───────────────────────────


@router.post("/agents/{session_id}/emotion")
async def override_emotion(
    session_id: str, req: EmotionOverrideRequest, request: Request
):
    """
    Manually set avatar emotion (for debugging and demo purposes).
    Maps the emotion name to the model's emotionMap index.
    """
    model_manager = request.app.state.live2d_model_manager
    state_manager = request.app.state.avatar_state_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        raise HTTPException(404, "No model assigned to this session")

    emotion_map = model.emotionMap
    expression_index = emotion_map.get(req.emotion, 0)

    await state_manager.update_state(
        session_id=session_id,
        emotion=req.emotion,
        expression_index=expression_index,
        intensity=req.intensity,
        transition_ms=req.transition_ms,
        trigger="manual_override",
    )

    return {
        "status": "ok",
        "emotion": req.emotion,
        "expression_index": expression_index,
    }
