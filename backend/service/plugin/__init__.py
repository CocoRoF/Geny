"""Geny plugin layer — cycle 20260422 (X5).

See :mod:`backend.service.plugin.protocol` for the design rationale.
This package currently exposes the :class:`GenyPlugin` contract only;
:class:`PluginRegistry` and loader ship in PR-X5-2.
"""

from __future__ import annotations

from .protocol import (
    GenyPlugin,
    PluginBase,
    PluginLike,
    SessionContext,
    SessionListener,
)
from .registry import (
    AttachRuntimeKeyConflict,
    DuplicatePluginError,
    PluginRegistry,
    UnknownLifecycleEventError,
)

__all__ = [
    "AttachRuntimeKeyConflict",
    "DuplicatePluginError",
    "GenyPlugin",
    "PluginBase",
    "PluginLike",
    "PluginRegistry",
    "SessionContext",
    "SessionListener",
    "UnknownLifecycleEventError",
]
