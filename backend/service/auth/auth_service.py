"""
Auth Service — Core authentication logic for Geny admin system.

Implements:
- Single admin user model (only one account can exist)
- bcrypt password hashing
- JWT token creation and verification
- Secret key management (env var or auto-generated)

Security model:
- First user to call setup() becomes the admin
- setup() is permanently disabled once a user exists
- All subsequent access requires login() → JWT token
"""
import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

import bcrypt
import jwt

from service.database.app_database_manager import AppDatabaseManager
from service.database.models.admin_user import AdminUserModel

logger = logging.getLogger("auth-service")

# Module-level singleton
_auth_service: Optional['AuthService'] = None


class AuthService:
    """
    Singleton authentication service.

    Manages admin user lifecycle: setup, login, token verification.
    """

    def __init__(self, app_db: AppDatabaseManager):
        self.app_db = app_db
        self.ALGORITHM = "HS256"
        self.TOKEN_EXPIRE_HOURS = int(os.getenv("GENY_AUTH_TOKEN_HOURS", "24"))
        self._secret_key: Optional[str] = None

    @property
    def secret_key(self) -> str:
        """Lazy-load secret key from env or generate one."""
        if self._secret_key is None:
            self._secret_key = self._load_or_generate_secret()
        return self._secret_key

    def _load_or_generate_secret(self) -> str:
        """
        Load JWT secret from environment variable or generate a new one.
        Generated secrets are persisted to a file so they survive restarts.
        """
        # 1. Check environment variable
        env_secret = os.getenv("GENY_AUTH_SECRET")
        if env_secret:
            logger.info("Auth secret loaded from GENY_AUTH_SECRET environment variable")
            return env_secret

        # 2. Check persisted secret file
        secret_file = os.path.join(os.path.dirname(__file__), ".auth_secret")
        if os.path.exists(secret_file):
            try:
                with open(secret_file, "r") as f:
                    secret = f.read().strip()
                if secret:
                    logger.info("Auth secret loaded from persisted file")
                    return secret
            except Exception as e:
                logger.warning(f"Failed to read auth secret file: {e}")

        # 3. Generate new secret and persist it
        secret = secrets.token_urlsafe(48)
        try:
            with open(secret_file, "w") as f:
                f.write(secret)
            logger.info("New auth secret generated and persisted")
        except Exception as e:
            logger.warning(f"Failed to persist auth secret: {e} (will regenerate on restart)")

        return secret

    # ================================================================
    #  User Management
    # ================================================================

    def has_users(self) -> bool:
        """Check if any admin user exists in the database."""
        try:
            users = self.app_db.find_all(AdminUserModel)
            return len(users) > 0
        except Exception as e:
            logger.error(f"Failed to check users: {e}")
            return False

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Find admin user by username."""
        try:
            users = self.app_db.find_by_condition(AdminUserModel, {"username": username})
            return users[0] if users else None
        except Exception as e:
            logger.error(f"Failed to find user: {e}")
            return None

    def setup(self, username: str, password: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create the initial admin user.

        CRITICAL SECURITY: This method MUST fail if any user already exists.
        This is the primary guard against unauthorized account creation.

        Args:
            username: Admin username (3-50 chars)
            password: Admin password (4+ chars)
            display_name: Optional display name

        Returns:
            JWT token response dict

        Raises:
            ValueError: If setup is already completed (users exist)
        """
        # Double-check: refuse if any user exists
        if self.has_users():
            raise ValueError("Setup already completed. Cannot create additional users.")

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

        # Create user record
        user = AdminUserModel(
            username=username,
            password_hash=password_hash,
            display_name=display_name or username,
            last_login_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            self.app_db.insert(user)
            logger.info(f"Admin user created: {username}")
        except Exception as e:
            logger.error(f"Failed to create admin user: {e}")
            raise ValueError(f"Failed to create user: {e}")

        # Return JWT token (auto-login after setup)
        return self._create_token(username, display_name or username)

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """
        Authenticate admin user and return JWT token.

        Args:
            username: Admin username
            password: Admin password

        Returns:
            JWT token response dict

        Raises:
            ValueError: If credentials are invalid
        """
        user = self.get_user_by_username(username)
        if not user:
            raise ValueError("Invalid credentials")

        # Verify password
        stored_hash = user.get("password_hash", "")
        if not stored_hash:
            raise ValueError("Invalid credentials")

        if not bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            raise ValueError("Invalid credentials")

        # Update last login time
        try:
            user_id = user.get("id")
            if user_id:
                self.app_db.update_record(
                    "admin_users",
                    user_id,
                    {"last_login_at": datetime.now(timezone.utc).isoformat()}
                )
        except Exception as e:
            logger.warning(f"Failed to update last_login_at: {e}")

        display_name = user.get("display_name", username)
        logger.info(f"Admin login successful: {username}")
        return self._create_token(username, display_name)

    # ================================================================
    #  Token Management
    # ================================================================

    def _create_token(self, username: str, display_name: str) -> Dict[str, Any]:
        """Generate JWT token with expiry."""
        expire = datetime.now(timezone.utc) + timedelta(hours=self.TOKEN_EXPIRE_HOURS)
        payload = {
            "sub": username,
            "display_name": display_name,
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.ALGORITHM)
        return {
            "access_token": token,
            "token_type": "bearer",
            "username": username,
            "display_name": display_name,
        }

    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify JWT token and return decoded payload.

        Args:
            token: JWT token string

        Returns:
            Decoded payload dict with 'sub' (username) and 'display_name'

        Raises:
            jwt.ExpiredSignatureError: Token has expired
            jwt.InvalidTokenError: Token is invalid
        """
        payload = jwt.decode(token, self.secret_key, algorithms=[self.ALGORITHM])
        return payload

    def get_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verify token and return user info, or None if invalid.
        Non-throwing convenience method for status checks.
        """
        try:
            payload = self.verify_token(token)
            return {
                "username": payload.get("sub"),
                "display_name": payload.get("display_name"),
            }
        except Exception:
            return None


# ================================================================
#  Singleton Management
# ================================================================

def init_auth_service(app_db: AppDatabaseManager) -> 'AuthService':
    """Initialize the global AuthService singleton with a database connection."""
    global _auth_service
    _auth_service = AuthService(app_db)
    logger.info("AuthService initialized")
    return _auth_service


def get_auth_service() -> Optional['AuthService']:
    """Get the global AuthService singleton. Returns None if not initialized (no DB)."""
    return _auth_service
