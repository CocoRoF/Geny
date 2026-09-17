"""Signing a ChatGPT (Codex) plan in to a server, and keeping it signed in.

The device-code flow rather than a localhost redirect, for the same reason
this server cannot catch a Claude Code callback: the browser is on the
user's machine, not here. They enter a short code at auth.openai.com and the
server polls until it is approved.

Tokens live in this server's secret store, never in ``~/.codex``. The Codex
refresh token is **single-use**: if the operator's own Codex CLI and this
server shared one file they would rotate each other out, and both would be
logged out with no error until the next call.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

__all__ = [
    "CLIENT_ID",
    "DEVICE_URL",
    "DeviceLoginJobs",
    "ensure_fresh",
    "identity_of",
    "refresh_tokens",
    "token_expiry",
]

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
ISSUER = "https://auth.openai.com"
TOKEN_URL = f"{ISSUER}/oauth/token"
DEVICE_URL = f"{ISSUER}/codex/device"
BASE_URL = "https://chatgpt.com/backend-api/codex"
USER_AGENT = "Geny (server)"


def jwt_claims(token: str) -> Dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode()))
    except Exception:  # noqa: BLE001 — any malformed token reads as "no claims"
        return {}


def token_expiry(token: str) -> float:
    exp = jwt_claims(token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) else 0.0


def identity_of(tokens: Dict[str, Any]) -> Dict[str, Any]:
    claims = jwt_claims(str(tokens.get("id_token") or "")) or jwt_claims(
        str(tokens.get("access_token") or "")
    )
    auth = claims.get("https://api.openai.com/auth") or {}
    profile = claims.get("https://api.openai.com/profile") or {}
    email = claims.get("email") or (profile.get("email") if isinstance(profile, dict) else None)
    plan = auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None
    account_id = tokens.get("account_id") or (
        auth.get("chatgpt_account_id") if isinstance(auth, dict) else None
    )
    return {
        "email": email if isinstance(email, str) else None,
        "plan": plan if isinstance(plan, str) else None,
        "accountId": str(account_id) if account_id else None,
    }


async def refresh_tokens(tokens: Dict[str, Any], *, client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise ValueError("refresh token 이 없습니다 — 다시 로그인하세요")
    owned = client is None
    http = client or httpx.AsyncClient(timeout=30.0)
    try:
        resp = await http.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh, "client_id": CLIENT_ID},
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
    finally:
        if owned:
            await http.aclose()
    data = resp.json() if resp.content else {}
    if resp.status_code != 200 or not data.get("access_token"):
        reason = data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}"
        raise ValueError(f"Codex 토큰 갱신 실패: {reason}")
    return {
        **tokens,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token") or tokens.get("refresh_token"),
        "id_token": data.get("id_token") or tokens.get("id_token"),
        "last_refresh": time.time(),
    }


async def ensure_fresh(tokens: Dict[str, Any], *, skew_s: float = 30 * 60) -> tuple[Dict[str, Any], bool]:
    """Refresh when the access token has less than *skew_s* left.

    The default is generous on purpose: a turn can run for many minutes, and
    a token that expires mid-pipeline surfaces as an auth failure the router
    then fails over for — burning another account for nothing.
    """
    expiry = token_expiry(str(tokens.get("access_token") or ""))
    if not expiry or expiry - time.time() > skew_s:
        return tokens, False
    return await refresh_tokens(tokens), True


class DeviceLoginJobs:
    """The device-code flow, as a streamed job."""

    def __init__(self, emit: Callable[[Dict[str, Any]], None]) -> None:
        self._emit = emit
        self._cancelled: set = set()
        self._active: Dict[str, str] = {}

    def cancel(self, job_id: str) -> bool:
        if job_id not in self._active:
            return False
        self._cancelled.add(job_id)
        self._active.pop(job_id, None)
        return True

    async def start(
        self,
        account_id: str,
        on_tokens: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> Dict[str, Any]:
        """Ask for a code and return it; approval continues in the background."""
        async with httpx.AsyncClient(timeout=30.0) as http:
            resp = await http.post(
                f"{ISSUER}/api/accounts/deviceauth/usercode",
                json={"client_id": CLIENT_ID},
                headers={"User-Agent": USER_AGENT},
            )
            data = resp.json() if resp.content else {}
        user_code = data.get("user_code") or data.get("usercode")
        device_auth_id = data.get("device_auth_id")
        if resp.status_code != 200 or not user_code or not device_auth_id:
            raise ValueError(f"Codex 로그인 코드를 받지 못했습니다 (HTTP {resp.status_code})")

        job_id = uuid.uuid4().hex
        self._active[job_id] = account_id
        expires_at = time.time() + 15 * 60
        interval = max(3.0, float(data.get("interval") or 5))
        self._emit({"jobId": job_id, "accountId": account_id, "type": "device",
                    "userCode": user_code, "verificationUrl": DEVICE_URL,
                    "expiresAt": int(expires_at * 1000)})
        # Through ``spawn_background``: a bare ``create_task`` is held only by
        # a weak reference, so this poll can be collected mid-flow and the
        # user waits at a code page for fifteen minutes for nothing.
        from service.utils.background import spawn_background

        spawn_background(
            self._poll(job_id, account_id, str(device_auth_id), str(user_code),
                       interval, expires_at, on_tokens),
            name=f"codex.device_login:{account_id}",
        )
        return {"jobId": job_id, "userCode": user_code, "verificationUrl": DEVICE_URL,
                "expiresAt": int(expires_at * 1000)}

    async def _poll(
        self, job_id: str, account_id: str, device_auth_id: str, user_code: str,
        interval: float, expires_at: float,
        on_tokens: Callable[[Dict[str, Any]], Awaitable[None]],
    ) -> None:
        def finish(ok: bool, error: Optional[str] = None) -> None:
            self._active.pop(job_id, None)
            self._cancelled.discard(job_id)
            self._emit({"jobId": job_id, "accountId": account_id, "type": "done",
                        "ok": ok, "error": error})

        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                while job_id not in self._cancelled and time.time() < expires_at:
                    await asyncio.sleep(interval)
                    if job_id in self._cancelled:
                        return
                    resp = await http.post(
                        f"{ISSUER}/api/accounts/deviceauth/token",
                        json={"device_auth_id": device_auth_id, "user_code": user_code},
                        headers={"User-Agent": USER_AGENT},
                    )
                    if resp.status_code in (403, 404, 428):
                        continue  # still waiting for the user
                    if resp.status_code == 429:
                        await asyncio.sleep(interval)
                        continue
                    grant = resp.json() if resp.content else {}
                    code = grant.get("authorization_code")
                    verifier = grant.get("code_verifier")
                    if resp.status_code != 200 or not code or not verifier:
                        finish(False, f"승인 확인 실패 (HTTP {resp.status_code})")
                        return
                    exchange = await http.post(
                        TOKEN_URL,
                        data={
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": f"{ISSUER}/deviceauth/callback",
                            "client_id": CLIENT_ID,
                            "code_verifier": verifier,
                        },
                        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    )
                    payload = exchange.json() if exchange.content else {}
                    if exchange.status_code != 200 or not payload.get("access_token"):
                        reason = payload.get("error_description") or payload.get("error") or exchange.status_code
                        finish(False, f"토큰 교환 실패: {reason}")
                        return
                    tokens = {
                        "access_token": payload["access_token"],
                        "refresh_token": payload.get("refresh_token"),
                        "id_token": payload.get("id_token"),
                        "last_refresh": time.time(),
                    }
                    tokens["account_id"] = identity_of(tokens).get("accountId")
                    await on_tokens(tokens)
                    finish(True)
                    return
            if job_id not in self._cancelled:
                finish(False, "로그인 시간이 만료됐습니다 (15분) — 다시 시도하세요")
        except Exception as exc:  # noqa: BLE001 — the job reports, never crashes the loop
            logger.warning("codex device login failed: %s", exc)
            finish(False, str(exc))
