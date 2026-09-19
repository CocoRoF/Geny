"""Model accounts — every way this server can reach a model.

See :mod:`service.llm_accounts.service` for the shape of an account and a
route; :mod:`service.llm_accounts.kinds` for the catalogue of kinds and
their models.
"""

from service.llm_accounts.adopt_legacy import adopt_legacy_credentials
from service.llm_accounts.kinds import (
    ACCOUNT_KINDS,
    EFFORTS,
    KINDS,
    default_model_for,
    model_choices,
)
from service.llm_accounts.secrets import SecretStore, get_secret_store, secrets_path
from service.llm_accounts.service import (
    AccountService,
    accounts_root,
    get_account_service,
    route_context_window,
)

__all__ = [
    "ACCOUNT_KINDS",
    "adopt_legacy_credentials",
    "AccountService",
    "EFFORTS",
    "KINDS",
    "SecretStore",
    "accounts_root",
    "default_model_for",
    "get_account_service",
    "route_context_window",
    "get_secret_store",
    "model_choices",
    "secrets_path",
]
