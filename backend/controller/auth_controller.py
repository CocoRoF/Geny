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

from service.auth.auth_service import get_auth_service
from service.auth.auth_middleware import require_auth, _extract_token
from service.auth.auth_models import (
    SetupRequest,
    LoginRequest,
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
        max_age=86400 * 7,  # 7 days
        samesite="lax",
        httponly=False,  # Frontend needs to read for API calls
    )

    logger.info(f"Admin setup completed: {request.username}")
    return AuthTokenResponse(**token_data)


@router.post("/login", response_model=AuthTokenResponse)
async def login(request: LoginRequest, response: Response):
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
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Set cookie
    response.set_cookie(
        key="geny_auth_token",
        value=token_data["access_token"],
        max_age=86400 * 7,  # 7 days
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
