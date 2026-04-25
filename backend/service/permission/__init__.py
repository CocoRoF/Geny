"""Geny adoption of geny-executor's permission matrix (Phase 1).

The executor ships a fully-formed permission system
(:mod:`geny_executor.permission` — rule matrix + YAML loader +
hierarchical sources) but Geny had been ignoring it. This package
loads the host-side rule files and forwards them to
:meth:`Pipeline.attach_runtime` via :func:`install_permission_rules`.

Coexists with the legacy :class:`service.tool_policy.policy.ToolPolicyEngine`:
- ``ToolPolicyEngine`` decides which tools a *role* may call (kept for
  per-role profile UI).
- The executor's permission matrix decides whether a *specific
  invocation* with *specific input* matches a rule (handles the
  ``Bash(git *)`` style pattern matching the legacy engine can't
  express).

Default mode is ``"advisory"`` — the matrix evaluates rules and emits
``permission.denied`` / ``.allowed`` events but never blocks. G6.4
flips ``worker_adaptive`` to ``"enforce"`` once the timeline UI shows
the events.
"""

from __future__ import annotations

from service.permission.install import (
    PERMISSION_MODES,
    install_permission_rules,
    permissions_yaml_path,
)

__all__ = [
    "PERMISSION_MODES",
    "install_permission_rules",
    "permissions_yaml_path",
]
