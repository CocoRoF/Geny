"""Model accounts — the API behind Settings › Models.

An account is one credential this server can reach a model with; a route is
which accounts a session uses, in order. Both the web UI and the connector
read this one surface, so "which models can I pick" has a single answer.

Login is streamed rather than returned, because neither subscription flow
can finish in a request: Claude Code prints a URL and waits for a code on
stdin, and Codex hands out a device code and waits for approval. The browser
that completes either one is on the user's machine, not this server — so
``GET /api/llm-accounts/events`` carries the flow and ``POST .../input``
carries the answer back.

Every route is behind ``require_auth``: these calls read and write live
credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth
from service.llm_accounts import KINDS, get_account_service
from service.llm_accounts.kinds import EFFORTS, FAMILIES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm-accounts", tags=["llm-accounts"])


# ── request shapes ───────────────────────────────────────────────────


class ClaudeOptions(BaseModel):
    authMethod: Optional[str] = Field(None, description="login | token | api_key | system")
    mode: Optional[str] = Field(None, description="token (harness runs tools) | agent (CLI does)")


class NewAccount(BaseModel):
    kind: str
    label: Optional[str] = None
    baseUrl: Optional[str] = None
    secret: Optional[str] = None
    effort: Optional[str] = None
    claude: Optional[ClaudeOptions] = None


class AccountPatch(BaseModel):
    label: Optional[str] = None
    enabled: Optional[bool] = None
    baseUrl: Optional[str] = None
    effort: Optional[str] = None
    secret: Optional[str] = None
    claude: Optional[ClaudeOptions] = None


class ReorderRequest(BaseModel):
    order: List[str]


class TestRequest(BaseModel):
    model: Optional[str] = None


class LoginRequest(BaseModel):
    #: Claude Code only — sign in with a Console account instead of a
    #: Claude.ai subscription.
    console: bool = False


class LoginInput(BaseModel):
    jobId: str
    text: str


# ── catalogue ────────────────────────────────────────────────────────


@router.get("/kinds")
async def list_kinds(_: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Every kind of account, what it needs, and the models it offers."""
    return {
        "kinds": {name: info.to_dict() for name, info in KINDS.items()},
        # The families, in the order a settings page should show them. Sent
        # rather than hard-coded in each client, so adding a kind is one edit.
        "families": [{"id": fid, "label": label} for fid, label in FAMILIES],
        "efforts": list(EFFORTS),
    }


# ── accounts ─────────────────────────────────────────────────────────


@router.get("")
async def list_accounts(_: Any = Depends(require_auth)) -> Dict[str, Any]:
    service = get_account_service()
    return {"accounts": service.list_accounts(), "defaultRoute": service.default_route()}


@router.post("")
async def create_account(body: NewAccount, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        account = get_account_service().create_account(body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"account": account}


@router.patch("/{account_id}")
async def update_account(account_id: str, body: AccountPatch, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        account = get_account_service().update_account(
            account_id, body.model_dump(exclude_none=True)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"account": account}


@router.delete("/{account_id}")
async def delete_account(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    if not get_account_service().delete_account(account_id):
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다")
    return {"ok": True}


@router.post("/reorder")
async def reorder(body: ReorderRequest, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    return {"accounts": get_account_service().reorder(body.order)}


# ── liveness ─────────────────────────────────────────────────────────


@router.get("/cli")
async def cli_info(refresh: bool = False, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Is a `claude` binary reachable from this server, and which version."""
    return await get_account_service().cli_info(refresh=refresh)


@router.post("/{account_id}/test")
async def test_account(account_id: str, body: TestRequest, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return await get_account_service().test_account(account_id, body.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc


@router.post("/{account_id}/discover-models")
async def discover_models(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return {"models": await get_account_service().discover_models(account_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc


# ── Claude Code ──────────────────────────────────────────────────────


@router.get("/{account_id}/claude/status")
async def claude_status(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return await get_account_service().claude_status(account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc


@router.post("/{account_id}/claude/login")
async def claude_login(account_id: str, body: LoginRequest, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return await get_account_service().start_claude_login(account_id, console=body.console)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/claude/logout")
async def claude_logout(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return {"ok": await get_account_service().claude_logout(account_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc


# ── Codex ────────────────────────────────────────────────────────────


@router.post("/{account_id}/codex/login")
async def codex_login(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    try:
        return await get_account_service().start_codex_login(account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{account_id}/codex/import-cli")
async def codex_import(account_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    """Adopt an existing ``~/.codex/auth.json`` on this server."""
    try:
        ok = get_account_service().import_codex_cli_login(account_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="이 서버에서 Codex CLI 로그인을 찾지 못했습니다")
    return {"ok": True, "account": get_account_service().get_account(account_id)}


# ── login flow ───────────────────────────────────────────────────────


@router.post("/login/input")
async def login_input(body: LoginInput, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    """The code the user pasted from the browser on their own machine."""
    if not get_account_service().send_login_input(body.jobId, body.text):
        raise HTTPException(status_code=404, detail="진행 중인 로그인이 없습니다")
    return {"ok": True}


@router.post("/login/{job_id}/cancel")
async def login_cancel(job_id: str, _: Any = Depends(require_auth)) -> Dict[str, Any]:
    return {"ok": get_account_service().cancel_login(job_id)}


@router.get("/events")
async def login_events(request: Request, job_id: Optional[str] = None,
                       _: Any = Depends(require_auth)) -> StreamingResponse:
    """Server-sent login events — URLs, device codes, CLI output, the verdict.

    Replays what this job has already emitted before going live, so opening
    the stream a moment late does not lose the URL the whole flow hangs on.

    A stream following one job ENDS when that job reports its verdict. A login
    is a bounded thing; holding the connection open afterwards leaks one per
    sign-in and leaves the client waiting for a frame that will never come.
    Following everything (no ``job_id``) stays open, because there is no such
    moment.
    """
    service = get_account_service()
    queue = service.events.subscribe()

    def frame(event: Dict[str, Any]) -> str:
        return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    async def stream():
        try:
            for event in service.events.replay(job_id):
                yield frame(event)
                if job_id and event.get("type") == "done":
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if job_id and event.get("jobId") != job_id:
                    continue
                yield frame(event)
                if job_id and event.get("type") == "done":
                    return
        finally:
            service.events.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })
