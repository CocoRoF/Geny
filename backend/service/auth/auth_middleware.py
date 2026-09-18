"""
Auth Middleware — FastAPI dependency for requiring authentication.

Usage in controllers:
    from service.auth.auth_middleware import require_auth

    @router.post("/protected")
    async def protected_endpoint(auth: dict = Depends(require_auth)):
        username = auth["sub"]
        ...

Design:
- Extracts JWT from Authorization header or cookie
- Returns decoded payload on success
- Raises HTTPException(401) on failure
- If AuthService is not initialized (no DB), allows all requests (dev fallback)
"""
import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse

from service.auth.auth_service import get_auth_service

logger = logging.getLogger("auth-middleware")

# Subprotocol marker used to smuggle a JWT through the browser WebSocket
# handshake. Browsers cannot set arbitrary headers on `new WebSocket(...)`,
# but they CAN pass subprotocols: `new WebSocket(url, ['geny-auth', '<jwt>'])`.
# The marker MUST be echoed back via `accept(subprotocol='geny-auth')` or the
# browser handshake fails — see require_ws_auth().
WS_AUTH_SUBPROTOCOL = "geny-auth"

# Custom WebSocket close code for "unauthorized". 4000-4999 is the
# application-private range; 4401 mirrors HTTP 401 for readability.
WS_UNAUTHORIZED_CODE = 4401


def _auth_strict() -> bool:
    """True when GENY_AUTH_STRICT is set to a truthy value.

    When strict AND no AuthService is available (no DB), the WS path REFUSES
    connections instead of silently allowing anonymous access. Default (unset)
    preserves today's behavior exactly — anonymous allowed in no-DB mode.
    """
    return os.getenv("GENY_AUTH_STRICT", "").strip().lower() in ("1", "true", "yes", "on")


async def require_auth(request: Request) -> dict:
    """
    FastAPI dependency that requires a valid JWT token.

    Token sources (checked in order):
    1. Authorization: Bearer <token> header
    2. geny_auth_token cookie

    Returns:
        Decoded JWT payload dict containing 'sub' (username), 'display_name'

    Raises:
        HTTPException(401): If no valid token is found
    """
    auth_service = get_auth_service()

    # If auth service is not available (no DB / auth init failed):
    if auth_service is None:
        # Fail CLOSED under strict mode (audit S7): previously GENY_AUTH_STRICT
        # only gated the WebSocket path, so a DB outage silently turned every
        # "protected" HTTP endpoint anonymous. Strict now refuses HTTP too.
        if _auth_strict():
            raise HTTPException(
                status_code=503,
                detail="Authentication unavailable",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.debug("AuthService not initialized — skipping auth check (no DB mode)")
        return {"sub": "anonymous", "display_name": "Anonymous"}

    token = _extract_token(request)

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = auth_service.verify_token(token)
        return payload
    except Exception as e:
        error_type = type(e).__name__
        if "ExpiredSignature" in error_type:
            raise HTTPException(
                status_code=401,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _admin_users() -> set:
    """Usernames allowed to act on any session regardless of owner
    (audit S6). Comma-separated ``GENY_ADMIN_USERS``; empty by default."""
    raw = os.getenv("GENY_ADMIN_USERS", "")
    return {u.strip() for u in raw.split(",") if u.strip()}


def verify_session_ownership(auth: dict, owner_username: Optional[str]) -> None:
    """Raise 403 when ``auth`` doesn't own the session (audit S6).

    Fails OPEN when the session has no recorded owner (legacy / gateway
    sessions) so this can be rolled out without breaking pre-owner
    records; enforces once an owner is known. Admins (``GENY_ADMIN_USERS``)
    bypass. Under the current single-admin deployment the owner always
    matches ``auth["sub"]``, so this never fires — it protects the
    multi-user future.
    """
    if not owner_username:
        return  # unknown owner → allow (fail-open, back-compat)
    sub = (auth or {}).get("sub")
    if sub == owner_username:
        return
    if sub in _admin_users():
        return
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail="You do not own this session")


async def optional_auth(request: Request) -> dict | None:
    """
    FastAPI dependency that optionally extracts auth info.
    Returns decoded payload if authenticated, None otherwise.
    Never raises — used for endpoints that behave differently based on auth state.
    """
    auth_service = get_auth_service()
    if auth_service is None:
        return None

    token = _extract_token(request)
    if not token:
        return None

    return auth_service.get_user_from_token(token)


# Paths allowed to authenticate via ?token= (header-incapable clients).
QUERY_TOKEN_PATH_PREFIXES: tuple[str, ...] = (
    "/api/voice-studio/events",  # EventSource SSE
)


def _extract_token(request: Request) -> str | None:
    """Extract JWT token from request headers or cookies."""
    # 1. Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 2. Cookie: geny_auth_token=<token>
    token = request.cookies.get("geny_auth_token")
    if token:
        return token

    # 3. ?token=<jwt> query param — ONLY for paths where setting a header
    # is impossible (EventSource cannot carry Authorization). Deliberately
    # narrow: query strings land in uvicorn/proxy access logs, so a
    # blanket acceptance would write valid 30-day JWTs into logs on every
    # request that chose the lazy path. Add prefixes here consciously.
    if any(request.url.path.startswith(p) for p in QUERY_TOKEN_PATH_PREFIXES):
        token = request.query_params.get("token")
        if token:
            return token

    return None


# ================================================================
#  WebSocket authentication
# ================================================================


def _parse_subprotocol_token(websocket: WebSocket) -> str | None:
    """Pull a JWT out of the Sec-WebSocket-Protocol header.

    The browser sends `new WebSocket(url, ['geny-auth', '<jwt>'])`, which
    becomes the request header `Sec-WebSocket-Protocol: geny-auth, <jwt>`.
    We take the element that immediately follows the ``geny-auth`` marker.
    Returns None when the marker is absent or has no following element.
    """
    raw = websocket.headers.get("sec-websocket-protocol")
    if not raw:
        return None

    parts = [p.strip() for p in raw.split(",") if p.strip()]
    for i, part in enumerate(parts):
        if part == WS_AUTH_SUBPROTOCOL:
            if i + 1 < len(parts):
                return parts[i + 1]
            return None
    return None


def _extract_ws_token(websocket: WebSocket) -> str | None:
    """Extract a JWT from a WebSocket handshake, in priority order.

    1. ``Authorization: Bearer <token>`` header — the desktop connector can
       set arbitrary headers, so it uses this directly.
    2. ``Sec-WebSocket-Protocol: geny-auth, <token>`` — browsers cannot set
       arbitrary WS headers but CAN pass subprotocols via
       ``new WebSocket(url, ['geny-auth', '<jwt>'])``. This is the preferred
       browser path: it avoids leaking the token in URLs / proxy logs.
    3. ``?token=<token>`` query param — last-resort fallback for clients that
       can do neither of the above. NOTE: query strings frequently end up in
       access logs / proxy logs / browser history, so this leaks the token;
       prefer the subprotocol path. Kept only for compatibility.
    4. ``geny_auth_token`` cookie — same-origin browser fallback (the cookie
       set by /api/auth/login is sent automatically on same-origin WS).
    """
    # 1. Authorization: Bearer <token>
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:]

    # 2. Sec-WebSocket-Protocol: geny-auth, <token>
    sub_token = _parse_subprotocol_token(websocket)
    if sub_token:
        return sub_token

    # 3. ?token=<token>  (log-leak caveat — see docstring)
    qp_token = websocket.query_params.get("token")
    if qp_token:
        return qp_token

    # 4. Cookie: geny_auth_token=<token>
    cookie_token = websocket.cookies.get("geny_auth_token")
    if cookie_token:
        return cookie_token

    return None


class WSAuthResult:
    """Outcome of a WebSocket auth attempt.

    Attributes:
        authorized: True if the connection may proceed.
        payload: Decoded JWT payload (or the anonymous stub) when authorized.
        subprotocol: The subprotocol the endpoint MUST echo back in
            ``websocket.accept(subprotocol=...)``. This is ``'geny-auth'`` only
            when the token arrived via the subprotocol path (otherwise the
            browser handshake would fail); ``None`` for header/query/cookie/
            anonymous paths.
    """

    __slots__ = ("authorized", "payload", "subprotocol")

    def __init__(self, authorized: bool, payload: dict | None, subprotocol: str | None):
        self.authorized = authorized
        self.payload = payload
        self.subprotocol = subprotocol


def _negotiated_subprotocol(websocket: WebSocket) -> str | None:
    """Return 'geny-auth' iff the client offered it, else None.

    The server may only echo a subprotocol the client actually offered. We
    echo ``geny-auth`` whenever it was offered so the browser handshake
    completes — regardless of which source the token finally came from.
    """
    raw = websocket.headers.get("sec-websocket-protocol")
    if not raw:
        return None
    offered = {p.strip() for p in raw.split(",") if p.strip()}
    return WS_AUTH_SUBPROTOCOL if WS_AUTH_SUBPROTOCOL in offered else None


async def require_ws_auth(websocket: WebSocket) -> WSAuthResult:
    """Validate a WebSocket handshake WITHOUT accepting it.

    The caller is responsible for accept()/close() — this keeps subprotocol
    negotiation in the caller's hands. Returns a :class:`WSAuthResult`:

    * ``authorized=True``  → caller should
      ``await websocket.accept(subprotocol=result.subprotocol)`` and proceed.
    * ``authorized=False`` → caller should
      ``await websocket.close(code=4401, reason=...)`` and return.

    Behavior matrix (mirrors require_auth, but WS-aware):
    * AuthService present  → always enforce (valid token required).
    * AuthService absent + GENY_AUTH_STRICT truthy → REFUSE (close 4401).
    * AuthService absent + not strict → allow anonymous (back-compat, the
      same posture require_auth has today).
    """
    auth_service = get_auth_service()

    # No DB / no auth configured.
    if auth_service is None:
        if _auth_strict():
            logger.warning("WS auth: strict mode + no AuthService — refusing connection")
            return WSAuthResult(authorized=False, payload=None, subprotocol=None)
        logger.debug("WS auth: AuthService not initialized — allowing anonymous (no-DB mode)")
        # Still echo the subprotocol if the client offered it, so a browser
        # that already speaks 'geny-auth' completes its handshake.
        return WSAuthResult(
            authorized=True,
            payload={"sub": "anonymous", "display_name": "Anonymous"},
            subprotocol=_negotiated_subprotocol(websocket),
        )

    token = _extract_ws_token(websocket)
    if not token:
        logger.info("WS auth: no token presented — rejecting")
        return WSAuthResult(authorized=False, payload=None, subprotocol=None)

    try:
        payload = auth_service.verify_token(token)
    except Exception as e:
        logger.info("WS auth: token rejected (%s)", type(e).__name__)
        return WSAuthResult(authorized=False, payload=None, subprotocol=None)

    return WSAuthResult(
        authorized=True,
        payload=payload,
        subprotocol=_negotiated_subprotocol(websocket),
    )


async def ws_auth_or_close(websocket: WebSocket) -> WSAuthResult | None:
    """Convenience helper endpoints call at the very top of the handler.

    * On success → returns an authorized :class:`WSAuthResult`. The endpoint
      MUST then call ``await websocket.accept(subprotocol=result.subprotocol)``.
    * On failure → closes the socket with code 4401 and returns ``None``. The
      endpoint should simply ``return`` immediately.

    The socket is NOT accepted here on success, so the caller controls the
    accepted subprotocol echo (required for the browser handshake).
    """
    result = await require_ws_auth(websocket)
    if not result.authorized:
        try:
            await websocket.close(code=WS_UNAUTHORIZED_CODE, reason="Authentication required")
        except Exception:
            # Socket may already be gone; nothing to do.
            pass
        return None
    return result


# ================================================================
#  Global "login required" HTTP gate  (secure-by-default)
# ================================================================
#
# Rather than remembering to add ``Depends(require_auth)`` to every single
# endpoint (the pattern that let S1/S2 slip through unauthenticated), this
# middleware INVERTS the default: every HTTP request must carry a valid JWT
# UNLESS its path is on the small public allowlist below. A new or forgotten
# endpoint is therefore protected automatically. Per-endpoint ``require_auth``
# dependencies stay in place as defense-in-depth and to supply the decoded
# payload (owner checks, ``sub``, etc.).

# EXACT-match paths that bypass the gate. Keep this list minimal — everything
# not listed (and not matching a prefix below) requires a valid login.
PUBLIC_EXACT_PATHS: frozenset = frozenset(
    {
        "/",                     # redirects to /dashboard (itself gated)
        "/health",               # liveness/readiness probe — no data
        "/health/ready",         # readiness probe (503 when deps are down)
        "/favicon.ico",          # browser auto-request; avoids 401 log noise
        "/api/auth/status",      # "is first-run setup needed?" — asked before login
        "/api/auth/login",       # obtain a token
        "/api/auth/setup",       # first-run admin account creation
        "/api/auth/logout",      # idempotent cookie clear
        "/api/google/callback",  # Google OAuth external redirect (state-authenticated)
        # VTuber live-sync notification streams. These are consumed via a plain
        # browser EventSource (which CANNOT send an Authorization header) from
        # cookieless display surfaces — the OBS browser-source overlay and the
        # desktop connector bootstrap from a URL token into localStorage, so no
        # geny_auth_token cookie is present. They were public by design and
        # carry only low-sensitivity change signals: /models/stream emits a
        # bare "models_changed" ping (no data); /assignments/stream emits
        # {sessionId, modelName}. The underlying DATA and ACTION endpoints
        # (/api/vtuber/models, /assignments, interact, emotion, …) stay gated —
        # their callers send a Bearer token via apiCall. Keeping these two
        # notification streams public restores overlay/connector live re-sync
        # without weakening any data/action surface.
        "/api/vtuber/models/stream",
        "/api/vtuber/assignments/stream",
    }
)

# PREFIX paths that bypass the gate (``str.startswith``).
PUBLIC_PATH_PREFIXES: tuple = (
    "/static/",            # legacy dashboard assets — no data
    "/dav",                # WebDAV island — enforces its OWN auth (HTTP Basic
                           # against per-device app passwords; mount clients
                           # cannot send JWTs). Nothing under /dav is served
                           # without a valid app password.
)


def is_public_path(path: str) -> bool:
    """True when ``path`` may be reached without a login.

    Note: API docs (``/docs``, ``/redoc``, ``/openapi.json``) are deliberately
    NOT public — they enumerate the whole API surface and are never needed
    before login. A logged-in admin can still reach them (cookie/bearer).
    """
    if path in PUBLIC_EXACT_PATHS:
        return True
    return path.startswith(PUBLIC_PATH_PREFIXES)


class RequireLoginMiddleware:
    """Secure-by-default gate: every HTTP request needs a valid JWT unless its
    path is public (see :func:`is_public_path`).

    Implementation notes:

    * **Pure ASGI**, not ``BaseHTTPMiddleware`` — it never reads/buffers the
      response body, so SSE and other streaming endpoints pass straight through
      once the caller is authenticated.
    * **HTTP only.** WebSocket and lifespan scopes are forwarded untouched; WS
      routes enforce auth themselves via :func:`ws_auth_or_close`.
    * **Ordering.** Register this BEFORE ``CORSMiddleware`` so CORS wraps it and
      attaches ``Access-Control-*`` headers to the 401s emitted here (letting a
      cross-origin frontend read the 401 and redirect to login).
    * **No-DB posture** mirrors :func:`require_auth` (audit S7): fail CLOSED
      (503) under ``GENY_AUTH_STRICT``, else allow (dev/no-DB back-compat). In
      production the DB is present, so a valid login is always required.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "")

        # CORS preflight carries no credentials/data — let CORS answer it.
        if method == "OPTIONS" or is_public_path(path):
            await self.app(scope, receive, send)
            return

        auth_service = get_auth_service()
        if auth_service is None:
            if _auth_strict():
                await self._deny(scope, receive, send, 503, "Authentication unavailable")
                return
            # No DB / auth not configured → dev back-compat: allow through.
            await self.app(scope, receive, send)
            return

        token = _extract_token(Request(scope))
        if not token:
            await self._deny(scope, receive, send, 401, "Authentication required")
            return

        try:
            auth_service.verify_token(token)
        except Exception as e:
            detail = (
                "Token expired"
                if "ExpiredSignature" in type(e).__name__
                else "Invalid token"
            )
            await self._deny(scope, receive, send, 401, detail)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope, receive, send, status: int, detail: str) -> None:
        response = JSONResponse(
            {"detail": detail},
            status_code=status,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
