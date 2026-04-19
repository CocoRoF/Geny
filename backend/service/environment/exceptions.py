"""Exceptions for the Geny Environment layer.

Mirrors ``geny_executor_web.app.services.exceptions`` so routers and test
fakes can catch them without importing ``geny_executor`` transitively.
"""

from __future__ import annotations


class EnvironmentNotFoundError(LookupError):
    """Raised when an environment id does not exist in the store."""


class StageValidationError(ValueError):
    """Raised when a PATCH / PUT payload fails stage-level schema validation."""
