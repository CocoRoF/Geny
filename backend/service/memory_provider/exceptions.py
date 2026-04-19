"""Exceptions for the Geny MemoryProvider integration layer.

Kept free of ``geny_executor`` imports so routers and tests can catch
these without pulling in the factory.
"""

from __future__ import annotations


class MemoryConfigError(ValueError):
    """Raised when a provider config dict is rejected by the factory
    (bad ``provider`` key, missing optional extras, invalid DSN, …)."""


class MemorySessionNotFoundError(LookupError):
    """Raised when a session id has no provider in the registry — either
    never provisioned, or already disposed via ``release()``."""
