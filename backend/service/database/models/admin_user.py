"""
Admin User Model — Database model for admin authentication.

Stores the single admin account for the Geny management system.
Only one user can exist (enforced at service level).
"""
from typing import Dict, List
from service.database.models.base_model import BaseModel


class AdminUserModel(BaseModel):
    """Model for storing admin user credentials."""

    def __init__(
        self,
        username: str = "",
        password_hash: str = "",
        display_name: str = "",
        last_login_at: str = "",
        password_changed_at: str = "",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.username = username
        self.password_hash = password_hash
        self.display_name = display_name
        self.last_login_at = last_login_at
        # When the password last changed. Tokens minted before this moment
        # stop verifying — a password change that leaves every other device
        # signed in has not actually revoked anything.
        self.password_changed_at = password_changed_at

    def get_table_name(self) -> str:
        return "admin_users"

    def get_schema(self) -> Dict[str, str]:
        return {
            "username": "VARCHAR(100) NOT NULL",
            "password_hash": "VARCHAR(255) NOT NULL",
            "display_name": "VARCHAR(200) DEFAULT ''",
            "last_login_at": "VARCHAR(100) DEFAULT ''",
            "password_changed_at": "VARCHAR(100) DEFAULT ''",
        }

    def get_indexes(self) -> List[tuple]:
        return [("idx_admin_users_username", "username")]
