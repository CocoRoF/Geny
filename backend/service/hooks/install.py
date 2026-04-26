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


def _build_config_from_settings_section() -> Optional[Any]:
    """PR-D.2.2 — settings.json:hooks reader.

    Returns a HookConfig when settings.json declares one, ``None``
    when the section is absent. Schema mirrors the yaml form so the
    migrator output (B.3.3) parses cleanly via the executor's existing
    HookConfig.from_mapping (or equivalent dict ingest)."""
    try:
        from geny_executor.settings import get_default_loader
        from geny_executor.hooks import HookConfig
    except ImportError:
        return None
    section = get_default_loader().get_section("hooks")
    if section is None or not isinstance(section, dict):
        return None
    # Try the executor's dict ingest if available; otherwise build via
    # constructor with defensive defaults.
    from_mapping = getattr(HookConfig, "from_mapping", None)
    if callable(from_mapping):
        try:
            return from_mapping(section)
        except Exception as exc:
            logger.warning(
                "install_hook_runner: settings.json:hooks parse failed: %s; "
                "ignoring section", exc,
            )
            return None
    # Defensive: construct directly. The executor's HookConfig always
    # accepts enabled / entries / audit_log_path.
    try:
        return HookConfig(
            enabled=bool(section.get("enabled", False)),
            entries=dict(section.get("entries") or {}),
            audit_log_path=section.get("audit_log_path"),
        )
    except Exception as exc:
        logger.warning(
            "install_hook_runner: settings.json:hooks construct failed: %s",
            exc,
        )
        return None


def install_hook_runner() -> Optional[Any]:
    """Resolve the env opt-in + config source (settings.json wins) and
    build a HookRunner.

    Returns:
        A :class:`HookRunner` instance when both gates open and the
        config resolves to an enabled state; ``None`` otherwise.

    PR-D.2.2 — dual-read priority:
      1. settings.json:hooks section
      2. legacy ~/.geny/hooks.yaml fallback

    Failures (malformed config / unreadable file) are surfaced as a
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

    # 1. settings.json:hooks (preferred).
    config = _build_config_from_settings_section()
    config_source = "settings.json:hooks"
    if config is not None:
        path = hooks_yaml_path()
        if path.exists():
            logger.warning(
                "install_hook_runner: settings.json:hooks wins; legacy "
                "%s still present (consider deleting after migration)",
                path,
            )
    else:
        # 2. Legacy yaml fallback.
        path = hooks_yaml_path()
        try:
            config = load_hooks_config(path)
        except Exception as exc:
            logger.warning(
                "install_hook_runner: failed to load %s: %s — hooks disabled",
                path, exc,
            )
            return None
        config_source = str(path)
        # Hint the operator about the migration path.
        if path.exists():
            logger.info(
                "install_hook_runner: yaml-only (consider migrating to "
                "settings.json via service.settings.migrator)",
            )

    if not getattr(config, "enabled", False):
        logger.debug(
            "install_hook_runner: %s parsed but enabled=false — no runner",
            config_source,
        )
        return None

    runner = HookRunner(config=config)
    logger.info(
        "install_hook_runner: HookRunner active (config=%s, %d event(s))",
        config_source,
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
