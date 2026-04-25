"""Geny adoption of geny-executor's hooks subsystem (Phase 5).

Loads ``~/.geny/hooks.yaml`` (gated by ``GENY_ALLOW_HOOKS=1``),
constructs a :class:`HookRunner`, and forwards it to
:meth:`Pipeline.attach_runtime` so Stage 4 / Stage 10 fire
PRE_TOOL_USE / POST_TOOL_USE / PERMISSION_REQUEST events into the
configured subprocesses.

Hooks are dual-gated:
1. ``GENY_ALLOW_HOOKS`` env var must be truthy.
2. ``HookConfig.enabled`` field in the YAML must be true.

Both default off — fresh installs are safe even with a hook config
file present.
"""

from __future__ import annotations

from service.hooks.install import (
    HOOKS_YAML_NAME,
    attach_kwargs,
    hooks_yaml_path,
    install_hook_runner,
)

__all__ = [
    "HOOKS_YAML_NAME",
    "attach_kwargs",
    "hooks_yaml_path",
    "install_hook_runner",
]
