"""Slash commands REST endpoints (PR-A.6.2).

Two endpoints under /api/slash-commands/:
    GET  ""         list every registered command (with category)
    POST "/execute" parse + dispatch a single input line
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slash-commands", tags=["slash-commands"])


class SlashCommandSummary(BaseModel):
    name: str
    description: str
    category: str
    aliases: List[str] = Field(default_factory=list)


class SlashListResponse(BaseModel):
    commands: List[SlashCommandSummary]


class SlashExecuteRequest(BaseModel):
    input_text: str = Field(min_length=1)


class SlashExecuteResponse(BaseModel):
    matched: bool
    success: bool
    content: Optional[str] = None
    follow_up_prompt: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _registry():
    try:
        from geny_executor.slash_commands import get_default_registry
        return get_default_registry()
    except ImportError:  # pragma: no cover
        return None


@router.get("", response_model=SlashListResponse)
async def list_slash_commands(_auth: dict = Depends(require_auth)):
    reg = _registry()
    if reg is None:
        return SlashListResponse(commands=[])
    return SlashListResponse(commands=[
        SlashCommandSummary(
            name=c.name,
            description=c.description or "",
            category=c.category.value,
            aliases=list(c.aliases or []),
        )
        for c in reg.list_all()
    ])


@router.post("/execute", response_model=SlashExecuteResponse)
async def execute_slash(
    body: SlashExecuteRequest,
    request: Request,
    auth: dict = Depends(require_auth),
):
    try:
        from geny_executor.slash_commands import (
            SlashContext,
            get_default_registry,
            parse_slash,
        )
    except ImportError:  # pragma: no cover
        return SlashExecuteResponse(matched=False, success=False)

    parsed = parse_slash(body.input_text)
    if parsed is None:
        return SlashExecuteResponse(matched=False, success=False)
    cmd = get_default_registry().resolve(parsed.command)
    if cmd is None:
        return SlashExecuteResponse(
            matched=False,
            success=False,
            content=f"Unknown slash command: /{parsed.command}",
        )

    user_id = (auth or {}).get("user_id") or (auth or {}).get("sub")
    ctx = SlashContext(
        pipeline=None,  # session-bound pipeline lookup is a follow-up
        user_id=user_id,
        extras={
            "task_registry": getattr(request.app.state, "task_registry", None),
            "task_runner": getattr(request.app.state, "task_runner", None),
            "cron_store": getattr(request.app.state, "cron_store", None),
        },
    )
    try:
        result = await cmd.execute(parsed.args, ctx)
    except Exception as exc:  # noqa: BLE001
        logger.exception("slash_execute_failed")
        return SlashExecuteResponse(matched=True, success=False, content=str(exc))

    return SlashExecuteResponse(
        matched=True,
        success=result.success,
        content=result.content,
        follow_up_prompt=result.follow_up_prompt,
        metadata=dict(result.metadata or {}),
    )
