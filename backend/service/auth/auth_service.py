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
- Failed logins throttle, per source. One account on a public host means one
  username and one password to guess; bcrypt slows that down, and slowing is
  not the same as stopping.
- Changing the password invalidates every token issued before the change.
  A rotation that leaves other devices signed in has revoked nothing.
"""
import os
import secrets
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

import bcrypt
import jwt

from service.database.app_database_manager import AppDatabaseManager
from service.database.models.admin_user import AdminUserModel

logger = logging.getLogger("auth-service")

# Module-level singleton
_auth_service: Optional['AuthService'] = None


class TooManyAttempts(Exception):
    """Raised when a source must wait before trying to sign in again."""

    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"Too many attempts — retry in {retry_after_s:.0f}s")
        self.retry_after_s = max(1.0, retry_after_s)


class LoginThrottle:
    """Failed logins cost more each time, per source.

    A single-admin service has one username (usually the obvious one) and one
    password. bcrypt at 12 rounds makes each guess expensive for the server
    too — which is why the answer is not "hash harder" but "answer slower and
    then stop answering".

    The delay doubles with each failure from 1s to a minute, and after
    ``MAX_FAILURES`` the source is locked out for ``LOCKOUT_S`` regardless.
    A success clears the record: a legitimate user who mistyped twice is not
    punished for the rest of the hour.
    """

    MAX_FAILURES = 10
    LOCKOUT_S = 15 * 60
    BASE_DELAY_S = 1.0
    MAX_DELAY_S = 60.0

    def __init__(self) -> None:
        self._failures: Dict[str, Tuple[int, float]] = {}
        self._lock = threading.Lock()

    def check(self, source: str) -> Optional[float]:
        """Seconds this source must wait, or ``None`` when it may try now."""
        with self._lock:
            record = self._failures.get(source)
            if record is None:
                return None
            count, last = record
            if count >= self.MAX_FAILURES:
                remaining = self.LOCKOUT_S - (time.monotonic() - last)
                if remaining > 0:
                    return remaining
                # Served the lockout — start again rather than staying barred
                # forever, which would lock the only account out of its own
                # service after a bad afternoon.
                self._failures.pop(source, None)
                return None
            delay = min(self.MAX_DELAY_S, self.BASE_DELAY_S * (2 ** (count - 1)))
            remaining = delay - (time.monotonic() - last)
            return remaining if remaining > 0 else None

    def record_failure(self, source: str) -> None:
        with self._lock:
            count, _ = self._failures.get(source, (0, 0.0))
            self._failures[source] = (count + 1, time.monotonic())

    def record_success(self, source: str) -> None:
        with self._lock:
            self._failures.pop(source, None)

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            return {
                source: {"failures": count, "secondsAgo": round(now - last)}
                for source, (count, last) in self._failures.items()
            }


class AuthService:
    """
    Singleton authentication service.

    Manages admin user lifecycle: setup, login, token verification.
    """

    def __init__(self, app_db: AppDatabaseManager):
        self.app_db = app_db
        self.ALGORITHM = "HS256"
        # 30 days by default. The desktop connector is an always-on client that
        # stores the JWT in the OS keychain and reuses it across restarts; a short
        # (24h) lifetime made it silently log out between sessions. Override with
        # GENY_AUTH_TOKEN_HOURS. The connector also refreshes on each launch, so a
        # token stays alive indefinitely with regular use.
        self.TOKEN_EXPIRE_HOURS = int(os.getenv("GENY_AUTH_TOKEN_HOURS", "720"))
        self._secret_key: Optional[str] = None
        self.throttle = LoginThrottle()

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

        # 3. Generate new secret and persist it with owner-only perms
        #    (audit S10: was written world-readable at default umask; the
        #    JWT signing key leaking lets anyone forge tokens).
        secret = secrets.token_urlsafe(48)
        try:
            # Create/truncate at 0600 atomically via os.open, then write.
            fd = os.open(secret_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(fd, secret.encode("utf-8"))
            finally:
                os.close(fd)
            try:
                os.chmod(secret_file, 0o600)  # tighten if it pre-existed at 0644
            except OSError:
                pass
            logger.info("New auth secret generated and persisted (chmod 600)")
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
            if not users:
                return None
            user = users[0]
            # find_by_condition returns model objects, convert to dict
            if hasattr(user, 'to_dict'):
                return user.to_dict()
            return dict(user) if not isinstance(user, dict) else user
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

    def login(self, username: str, password: str, *, source: str = "unknown") -> Dict[str, Any]:
        """
        Authenticate admin user and return JWT token.

        Args:
            username: Admin username
            password: Admin password
            source: Who is asking (client IP). Failed attempts are throttled
                per source — one account means one password to guess.

        Returns:
            JWT token response dict

        Raises:
            TooManyAttempts: This source must wait before trying again
            ValueError: If credentials are invalid
        """
        wait = self.throttle.check(source)
        if wait is not None:
            raise TooManyAttempts(wait)

        def refuse() -> None:
            self.throttle.record_failure(source)
            raise ValueError("Invalid credentials")

        user = self.get_user_by_username(username)
        if not user:
            refuse()

        # Verify password
        stored_hash = user.get("password_hash", "")
        if not stored_hash:
            refuse()

        if not bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            refuse()

        self.throttle.record_success(source)

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

    def change_password(self, username: str, current_password: str, new_password: str) -> Dict[str, Any]:
        """Rotate the admin password, and revoke every token issued before it.

        The current password is required even though the caller already holds
        a valid token: the token is what a thief would have, and it is exactly
        what this is protecting against.

        The returned token is a fresh one — the caller's own session survives
        the rotation it just performed, and every other device does not.
        """
        user = self.get_user_by_username(username)
        if not user:
            raise ValueError("Invalid credentials")
        stored_hash = user.get("password_hash", "")
        if not stored_hash or not bcrypt.checkpw(
            current_password.encode("utf-8"), stored_hash.encode("utf-8")
        ):
            raise ValueError("Invalid credentials")
        if len(new_password) < 4:
            raise ValueError("New password must be at least 4 characters")
        if bcrypt.checkpw(new_password.encode("utf-8"), stored_hash.encode("utf-8")):
            raise ValueError("New password must differ from the current one")

        changed_at = datetime.now(timezone.utc)
        password_hash = bcrypt.hashpw(
            new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)
        ).decode("utf-8")
        user_id = user.get("id")
        if not user_id:
            raise ValueError("Admin account is missing its record id")
        self.app_db.update_record("admin_users", user_id, {
            "password_hash": password_hash,
            "password_changed_at": changed_at.isoformat(),
        })
        logger.info("Admin password changed for %s — earlier tokens revoked", username)
        # Stamped with the generation it belongs to, so the caller's own
        # session survives the rotation it just performed.
        return self._create_token(
            user.get("username", username),
            user.get("display_name", username),
            password_generation=changed_at.isoformat(),
        )

    def _password_generation(self, username: str) -> str:
        """Which password a token belongs to. Empty for an account that has
        never rotated — tokens from before this feature carry no ``pwd`` claim
        and must keep working."""
        user = self.get_user_by_username(username)
        return str((user or {}).get("password_changed_at") or "")

    # ================================================================
    #  Token Management
    # ================================================================

    def _create_token(
        self, username: str, display_name: str, *, password_generation: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate JWT token with expiry.

        ``pwd`` carries the password generation this token belongs to — the
        stored ``password_changed_at``, verbatim. Verification compares it by
        equality rather than comparing timestamps, because ``iat`` has
        one-second resolution: a token minted in the same second as the
        rotation is indistinguishable from one minted just before it, and one
        of those two must be revoked while the other must not.
        """
        expire = datetime.now(timezone.utc) + timedelta(hours=self.TOKEN_EXPIRE_HOURS)
        generation = (
            password_generation
            if password_generation is not None
            else self._password_generation(username)
        )
        payload = {
            "sub": username,
            "display_name": display_name,
            "pwd": generation,
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

    def refresh_token(self, username: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """Issue a fresh JWT for an already-authenticated user.

        Used by POST /api/auth/refresh — the caller has already proven a
        valid (non-expired) token via require_auth, so we simply mint a new
        token with a fresh expiry. No new token *kind* is created: this is the
        same account JWT, just extended. ``display_name`` falls back to the
        stored value (or the username) when not supplied.
        """
        if display_name is None:
            user = self.get_user_by_username(username)
            display_name = (user or {}).get("display_name", username) if user else username
        return self._create_token(username, display_name or username)

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
        # A token belonging to an older password is revoked. Without this the
        # rotation is cosmetic: whoever held a token still holds it, for up to
        # thirty days.
        current = self._password_generation(str(payload.get("sub") or ""))
        if current and str(payload.get("pwd") or "") != current:
            raise jwt.InvalidTokenError("token belongs to a previous password")
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
