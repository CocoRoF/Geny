"""
Auth Controller — REST API for admin authentication.

Endpoints:
    GET  /api/auth/status  — Check auth state (has users? authenticated?)
    POST /api/auth/setup   — Create initial admin account (one-time only)
    POST /api/auth/login   — Authenticate and get JWT token
    POST /api/auth/logout  — Clear auth cookie
    GET  /api/auth/me      — Get current authenticated user info
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Request, Response

from service.auth.auth_service import TooManyAttempts, get_auth_service
from service.auth.auth_middleware import require_auth, _extract_token
from service.auth.auth_models import (
    SetupRequest,
    LoginRequest,
    ChangePasswordRequest,
    AuthStatusResponse,
    AuthTokenResponse,
    AuthMessageResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatusResponse)
async def get_auth_status(request: Request):
    """
    Check the current authentication state.

    Called on app startup to determine the initial UI state:
    - has_users=false → redirect to setup page
    - has_users=true, is_authenticated=false → show login button
    - has_users=true, is_authenticated=true → full access
    """
    auth_service = get_auth_service()

    # If auth service not available (no DB), report no auth required
    if auth_service is None:
        return AuthStatusResponse(
            has_users=False,
            is_authenticated=True,
            username="anonymous",
            display_name="Anonymous (No DB)",
        )

    has_users = auth_service.has_users()

    # Check if current request has a valid token
    token = _extract_token(request)
    user_info = None
    if token:
        user_info = auth_service.get_user_from_token(token)

    return AuthStatusResponse(
        has_users=has_users,
        is_authenticated=user_info is not None,
        username=user_info["username"] if user_info else None,
        display_name=user_info["display_name"] if user_info else None,
    )


@router.post("/setup", response_model=AuthTokenResponse)
async def setup_admin(request: SetupRequest, response: Response):
    """
    Create the initial admin account.

    SECURITY CONSTRAINTS:
    - Only works when admin_users table has 0 rows
    - Once a user exists, this endpoint permanently returns 403
    - Both frontend and backend enforce this constraint
    """
    auth_service = get_auth_service()

    if auth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not available (database required)"
        )

    # Critical check: refuse if users already exist
    if auth_service.has_users():
        raise HTTPException(
            status_code=403,
            detail="Setup already completed. Cannot create additional users."
        )

    try:
        token_data = auth_service.setup(
            username=request.username,
            password=request.password,
            display_name=request.display_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Set cookie for automatic auth on subsequent requests
    response.set_cookie(
        key="geny_auth_token",
        value=token_data["access_token"],
        # Cookie MUST outlive the JWT. It used to be pinned at 7 days
        # while the token lives TOKEN_EXPIRE_HOURS (default 30d) — after
        # day 7 every cookie-authenticated surface (bare <audio> tags,
        # EventSource, headerless GETs) silently 401'd while Bearer
        # calls kept working: the 2026-08-16 Voice Studio outage.
        max_age=60 * 60 * (get_auth_service().TOKEN_EXPIRE_HOURS if get_auth_service() else 720),
        samesite="lax",
        httponly=False,  # Frontend needs to read for API calls
    )

    logger.info(f"Admin setup completed: {request.username}")
    return AuthTokenResponse(**token_data)


def _client_source(request: Request) -> str:
    """Who is asking, for throttling purposes.

    Behind a reverse proxy every request arrives from the proxy, so
    ``X-Forwarded-For``'s first hop is the real client. It is client-supplied
    and therefore forgeable — which is fine here: a forged value splits an
    attacker's own budget across buckets, and the global lockout still holds.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=AuthTokenResponse)
async def login(request: LoginRequest, response: Response, http: Request):
    """
    Authenticate admin and return JWT token.

    Token is returned both in response body and as a Set-Cookie header.
    """
    auth_service = get_auth_service()

    if auth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not available (database required)"
        )

    try:
        token_data = auth_service.login(
            username=request.username,
            password=request.password,
            source=_client_source(http),
        )
    except TooManyAttempts as exc:
        # 429 with Retry-After, not 401: the caller needs to know that waiting
        # is the fix, or a legitimate user retries into a longer lockout.
        raise HTTPException(
            status_code=429,
            detail=f"로그인 시도가 너무 잦습니다 — {int(exc.retry_after_s)}초 뒤에 다시 시도하세요",
            headers={"Retry-After": str(int(exc.retry_after_s))},
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Set cookie
    response.set_cookie(
        key="geny_auth_token",
        value=token_data["access_token"],
        # Cookie MUST outlive the JWT. It used to be pinned at 7 days
        # while the token lives TOKEN_EXPIRE_HOURS (default 30d) — after
        # day 7 every cookie-authenticated surface (bare <audio> tags,
        # EventSource, headerless GETs) silently 401'd while Bearer
        # calls kept working: the 2026-08-16 Voice Studio outage.
        max_age=60 * 60 * (get_auth_service().TOKEN_EXPIRE_HOURS if get_auth_service() else 720),
        samesite="lax",
        httponly=False,
    )

    return AuthTokenResponse(**token_data)


@router.post("/refresh", response_model=AuthTokenResponse)
async def refresh(response: Response, auth: dict = Depends(require_auth)):
    """
    Issue a fresh JWT for the current valid user.

    Additive endpoint for always-on clients (e.g. the desktop connector):
    present a still-valid token via require_auth and receive a new token with
    a fresh expiry, avoiding a full re-login. Returns the same shape as
    /login (body token + refreshed cookie). The browser is unaffected unless
    it explicitly calls this.
    """
    auth_service = get_auth_service()

    if auth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not available (database required)"
        )

    username = auth.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token")

    token_data = auth_service.refresh_token(
        username=username,
        display_name=auth.get("display_name"),
    )

    # Refresh the cookie so same-origin browser clients also extend.
    response.set_cookie(
        key="geny_auth_token",
        value=token_data["access_token"],
        # Cookie MUST outlive the JWT. It used to be pinned at 7 days
        # while the token lives TOKEN_EXPIRE_HOURS (default 30d) — after
        # day 7 every cookie-authenticated surface (bare <audio> tags,
        # EventSource, headerless GETs) silently 401'd while Bearer
        # calls kept working: the 2026-08-16 Voice Studio outage.
        max_age=60 * 60 * (get_auth_service().TOKEN_EXPIRE_HOURS if get_auth_service() else 720),
        samesite="lax",
        httponly=False,
    )

    return AuthTokenResponse(**token_data)


@router.post("/password", response_model=AuthTokenResponse)
async def change_password(
    request: ChangePasswordRequest,
    response: Response,
    auth: dict = Depends(require_auth),
):
    """Rotate the admin password and sign every other device out.

    The current password is required even though the caller already holds a
    valid token — the token is what a thief would have, and it is what this
    protects against. Tokens issued before the change stop verifying, so the
    rotation actually revokes; the caller gets a fresh one so its own session
    survives the change it just made.
    """
    auth_service = get_auth_service()
    if auth_service is None:
        raise HTTPException(
            status_code=503,
            detail="Authentication service not available (database required)",
        )
    try:
        token_data = auth_service.change_password(
            username=auth.get("username", ""),
            current_password=request.current_password,
            new_password=request.new_password,
        )
    except ValueError as exc:
        message = str(exc)
        status = 401 if message == "Invalid credentials" else 400
        raise HTTPException(status_code=status, detail=message)

    response.set_cookie(
        key="geny_auth_token",
        value=token_data["access_token"],
        max_age=60 * 60 * auth_service.TOKEN_EXPIRE_HOURS,
        samesite="lax",
        httponly=False,
    )
    return AuthTokenResponse(**token_data)


@router.post("/logout", response_model=AuthMessageResponse)
async def logout(response: Response):
    """
    Clear the auth cookie.

    Frontend should also clear localStorage token.
    """
    response.delete_cookie(key="geny_auth_token")
    return AuthMessageResponse(success=True, message="Logged out successfully")


@router.get("/me")
async def get_current_user(auth: dict = Depends(require_auth)):
    """
    Get the currently authenticated user's info.

    Requires valid JWT token.
    """
    return {
        "username": auth.get("sub"),
        "display_name": auth.get("display_name"),
    }


# ── App passwords (protocol clients: WebDAV mounts) ─────────────────────
#
# Mount clients speak HTTP Basic, not Bearer. Each device gets its own
# generated secret (shown exactly once), individually revocable. The DAV
# endpoint (/dav) authenticates against these — never against the account
# password, so a leaked mount credential can be cut off without touching
# the account.

@router.post("/app-passwords")
async def create_app_password(payload: dict, auth: dict = Depends(require_auth)):
    from service.auth.app_password_service import get_app_password_service

    svc = get_app_password_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="App passwords unavailable (no database)")
    username = auth.get("sub") or ""
    if not username:
        raise HTTPException(status_code=401, detail="No user in token")
    label = str((payload or {}).get("label") or "").strip()
    return svc.create(username, label)


@router.get("/app-passwords")
async def list_app_passwords(auth: dict = Depends(require_auth)):
    from service.auth.app_password_service import get_app_password_service

    svc = get_app_password_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="App passwords unavailable (no database)")
    return {"items": svc.list_for(auth.get("sub") or "")}


@router.delete("/app-passwords/{rec_id}")
async def revoke_app_password(rec_id: int, auth: dict = Depends(require_auth)):
    from service.auth.app_password_service import get_app_password_service

    svc = get_app_password_service()
    if svc is None:
        raise HTTPException(status_code=503, detail="App passwords unavailable (no database)")
    if not svc.revoke(auth.get("sub") or "", rec_id):
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}
