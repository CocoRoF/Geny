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
from fastapi import Depends, HTTPException, Request

from service.auth.auth_service import get_auth_service

logger = logging.getLogger("auth-middleware")


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

    # If auth service is not available (no DB), allow all requests
    if auth_service is None:
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

    return None
