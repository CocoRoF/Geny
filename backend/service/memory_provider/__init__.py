"""Geny-side MemoryProvider integration.

Bridges geny-executor v0.20.0's :class:`MemoryProviderFactory` into Geny's
session lifecycle. Mirrors the layout used by geny-executor-web, but kept
in its own namespace to avoid colliding with the legacy
``service.memory.*`` package (which wraps ``SessionMemoryManager``).

Phase 2 scope: registry + default ephemeral provisioning only. Actual
Stage-2 attach, env plumbing, and legacy-layer cutover arrive in later
phases (see ``plan/03_memory_migration.md``).
"""

from service.memory_provider.exceptions import (
    MemoryConfigError,
    MemorySessionNotFoundError,
)
from service.memory_provider.registry import MemorySessionRegistry

__all__ = [
    "MemoryConfigError",
    "MemorySessionNotFoundError",
    "MemorySessionRegistry",
]
