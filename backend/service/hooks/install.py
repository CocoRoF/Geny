"""Install a HookRunner from ~/.geny/hooks.yaml into a Geny session.

Two gates:

1. ``GENY_ALLOW_HOOKS=1`` env var (the host operator opts in to
   running subprocess hooks at all).
2. ``enabled: true`` in the hooks YAML file (the rule file itself
   says the hooks should fire).

Both default off. Returning ``None`` (no runner) leaves the
pipeline running with no hooks — same shape as a host that has
never seen the executor's hooks subsystem.

The runner instance is session-scoped: each ``_build_pipeline`` call
gets a fresh runner so per-session config edits take effect on the
next session creation, not the next turn of an existing session.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

HOOKS_YAML_NAME = "hooks.yaml"


def hooks_yaml_path() -> Path:
    """User-scope hooks file path. Convention shared with the
    permissions install — ``~/.geny/`` is the per-user config root."""
    return Path.home() / ".geny" / HOOKS_YAML_NAME


def install_hook_runner() -> Optional[Any]:
    """Resolve the env opt-in + YAML config and build a HookRunner.

    Returns:
        A :class:`HookRunner` instance when both gates open and the
        YAML resolves to an enabled config; ``None`` otherwise.

    Failures (malformed YAML, unreadable file) are surfaced as a
    single warning + ``None`` return so the session still boots.
    """
    try:
        from geny_executor.hooks import (
            HookRunner,
            hooks_opt_in_from_env,
            load_hooks_config,
        )
    except ImportError:
        logger.debug("install_hook_runner: geny_executor.hooks unavailable; skipping")
        return None

    if not hooks_opt_in_from_env():
        # Quiet — most environments will not set the env var.
        return None

    path = hooks_yaml_path()
    try:
        config = load_hooks_config(path)
    except Exception as exc:
        logger.warning(
            "install_hook_runner: failed to load %s: %s — hooks disabled",
            path, exc,
        )
        return None

    if not getattr(config, "enabled", False):
        logger.debug(
            "install_hook_runner: %s parsed but enabled=false — no runner",
            path,
        )
        return None

    runner = HookRunner(config=config)
    logger.info(
        "install_hook_runner: HookRunner active (config=%s, %d event(s))",
        path,
        sum(len(v) for v in (config.entries or {}).values()),
    )
    return runner


def attach_kwargs() -> dict:
    """Convenience for ``agent_session._build_pipeline``.

    Returns ``{"hook_runner": runner}`` when a runner was built,
    else ``{}`` so older executor builds without the kwarg keep
    working.
    """
    runner = install_hook_runner()
    if runner is None:
        return {}
    return {"hook_runner": runner}


__all__ = [
    "HOOKS_YAML_NAME",
    "attach_kwargs",
    "hooks_yaml_path",
    "install_hook_runner",
]
