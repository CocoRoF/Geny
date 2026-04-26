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
    """settings.json:hooks reader (H.1, cycle 20260426_2 rewrite).

    Returns a parsed :class:`HookConfig` when settings.json declares
    one, ``None`` otherwise. Routes the section through
    ``geny_executor.hooks.parse_hook_config`` so the result is
    type-correct (events as :class:`HookEvent`, entries as
    :class:`HookConfigEntry`) — the prior path returned a
    HookConfig with raw dicts that the runner couldn't dispatch.

    Three issues were fixed in H.1:
      1. ``get_section`` returns the registered Pydantic model
         (:class:`HooksConfigSection`) when the section is registered,
         not a dict. The prior ``isinstance(section, dict)`` check
         short-circuited the modern path.
      2. The fallback constructor path stored raw dicts as
         ``entries`` values; ``HookRunner.fire`` reads them as
         :class:`HookConfigEntry` objects → silent no-op.
      3. ``parse_hook_config`` expects the wrapper shape
         ``{"enabled": ..., "hooks": {event: [...]}}`` while Geny
         persists ``{"enabled": ..., "entries": {EVENT: [...]}}``.
         We rebuild the wrapper here so settings.json keeps the
         (more discoverable) ``entries`` key while the executor sees
         what it expects.
    """
    try:
        from geny_executor.settings import get_default_loader
        from geny_executor.hooks import parse_hook_config
    except ImportError:
        return None

    raw_section = get_default_loader().get_section("hooks")
    if raw_section is None:
        return None

    # ``get_section`` may return a Pydantic model (when the section is
    # registered) or a raw dict (when it isn't). Both have the keys we
    # need; coerce to a dict so the rest of this function is uniform.
    if hasattr(raw_section, "model_dump"):
        section = raw_section.model_dump(exclude_none=True)
    elif isinstance(raw_section, dict):
        section = dict(raw_section)
    else:
        logger.warning(
            "install_hook_runner: unexpected settings.json:hooks shape %r — "
            "ignoring", type(raw_section).__name__,
        )
        return None

    # Translate Geny's on-disk shape into the wrapper
    # ``parse_hook_config`` consumes. Event keys are normalized to
    # lowercase here so legacy uppercase ("PRE_TOOL_USE") records keep
    # working until the controller rewrites them on the next save.
    entries_raw = section.get("entries") or {}
    if not isinstance(entries_raw, dict):
        logger.warning(
            "install_hook_runner: settings.json:hooks.entries must be a "
            "mapping, got %r — ignoring section", type(entries_raw).__name__,
        )
        return None
    hooks_lower: Dict[str, Any] = {}
    for event_name, raw_list in entries_raw.items():
        if not isinstance(event_name, str):
            continue
        hooks_lower[event_name.strip().lower()] = raw_list

    wrapper: Dict[str, Any] = {
        "enabled": bool(section.get("enabled", False)),
        "hooks": hooks_lower,
    }
    audit_log_path = section.get("audit_log_path")
    if audit_log_path:
        wrapper["audit_log_path"] = audit_log_path

    try:
        return parse_hook_config(wrapper, source="settings.json:hooks")
    except Exception as exc:
        logger.warning(
            "install_hook_runner: settings.json:hooks parse failed: %s; "
            "ignoring section", exc,
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
