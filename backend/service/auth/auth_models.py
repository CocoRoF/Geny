"""
Auth Request/Response Models — Pydantic schemas for auth endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional


class SetupRequest(BaseModel):
    """Request body for initial admin account creation."""
    username: str = Field(..., min_length=3, max_length=50, description="Admin username")
    password: str = Field(..., min_length=4, max_length=128, description="Admin password")
    display_name: Optional[str] = Field(None, max_length=100, description="Display name (optional)")


class LoginRequest(BaseModel):
    """Request body for admin login."""
    username: str = Field(..., description="Admin username")
    password: str = Field(..., description="Admin password")


class AuthStatusResponse(BaseModel):
    """Response for auth status check."""
    has_users: bool = Field(..., description="Whether any admin user exists")
    is_authenticated: bool = Field(..., description="Whether current request is authenticated")
    username: Optional[str] = Field(None, description="Authenticated username (if any)")
    display_name: Optional[str] = Field(None, description="Authenticated user display name")


class AuthTokenResponse(BaseModel):
    """Response containing JWT token."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    username: str = Field(..., description="Authenticated username")
    display_name: str = Field(..., description="User display name")


class AuthMessageResponse(BaseModel):
    """Simple message response."""
    success: bool
    message: str
