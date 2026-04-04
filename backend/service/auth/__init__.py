"""
Auth Module — Admin authentication for Geny.

Provides JWT-based authentication with bcrypt password hashing.
Designed for a single-admin model: only the first user can create an account.
"""
from service.auth.auth_service import AuthService, get_auth_service, init_auth_service

__all__ = ['AuthService', 'get_auth_service', 'init_auth_service']
