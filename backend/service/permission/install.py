"""Install host-side permission rules into a Geny session.

Reads YAML / JSON rule files from a hierarchy of well-known paths and
returns ``(rules, mode)`` for :meth:`Pipeline.attach_runtime`.

Rule file resolution order (later sources override earlier when the
matrix evaluates priority):

1. ``$GENY_PERMISSIONS_PATH`` env override (single absolute path).
2. ``~/.geny/permissions.yaml`` — user scope.
3. ``<repo>/permissions.yaml`` — project scope (CWD).
4. ``./permissions.local.yaml`` — local override (CWD, gitignored).

All four are optional. When none exist, the loader returns an empty
list — every tool stays allowed by default and the executor's matrix
becomes a no-op. This matches the executor's convention: the rule
file's *absence* is a signal, not an error.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

PERMISSION_MODES = ("advisory", "enforce")
_DEFAULT_MODE = "advisory"
_MODE_ENV_VAR = "GENY_PERMISSION_MODE"


def permissions_yaml_path() -> Path:
    """User-scope rule file path. Used by tooling / UI to surface
    "where would I edit my rules?" without duplicating the convention."""
    return Path.home() / ".geny" / "permissions.yaml"


def _resolve_mode() -> str:
    raw = os.environ.get(_MODE_ENV_VAR, _DEFAULT_MODE).strip().lower()
    if raw not in PERMISSION_MODES:
        logger.warning(
            "install_permission_rules: unknown %s=%r; falling back to %r",
            _MODE_ENV_VAR, raw, _DEFAULT_MODE,
        )
        return _DEFAULT_MODE
    return raw


def _candidate_paths() -> List[Tuple[Path, str]]:
    """Each entry is (path, source-name). source-name maps to executor's
    ``PermissionSource`` enum.

    The CLI / preset slots stay empty for now — Geny doesn't have CLI
    rules and presets are kept on the legacy ToolPolicyEngine.
    """
    out: List[Tuple[Path, str]] = []
    env_override = os.environ.get("GENY_PERMISSIONS_PATH")
    if env_override:
        out.append((Path(env_override), "user"))
    out.append((permissions_yaml_path(), "user"))
    out.append((Path.cwd() / "permissions.yaml", "project"))
    out.append((Path.cwd() / "permissions.local.yaml", "local"))
    return out


def install_permission_rules() -> Tuple[List, str]:
    """Resolve and load every permission rule source into a flat list.

    Returns:
        ``(rules, mode)`` — rules is the executor's
        ``List[PermissionRule]`` (empty when no file was found); mode
        is one of :data:`PERMISSION_MODES`. Both are forwarded as
        ``Pipeline.attach_runtime(permission_rules=…, permission_mode=…)``.

    Failures (malformed YAML, unreadable file) degrade to an empty list
    with a logged warning — the session must still boot. Use
    ``GENY_PERMISSIONS_STRICT=1`` to re-raise instead.
    """
    mode = _resolve_mode()

    try:
        # Local import keeps this module importable on hosts that haven't
        # yet pinned geny-executor 1.0.
        from geny_executor.permission import (
            PermissionSource,
            load_permission_rules,
        )
    except ImportError:
        logger.debug(
            "install_permission_rules: geny_executor.permission unavailable; skipping"
        )
        return [], mode

    source_map = {
        "user": PermissionSource.USER,
        "project": PermissionSource.PROJECT,
        "local": PermissionSource.LOCAL,
    }

    strict = os.environ.get("GENY_PERMISSIONS_STRICT", "").strip() == "1"
    rules: List = []
    for path, source_name in _candidate_paths():
        try:
            loaded = load_permission_rules(path, source=source_map[source_name])
        except Exception as exc:
            msg = f"install_permission_rules: failed to load {path}: {exc}"
            if strict:
                raise
            logger.warning(msg)
            continue
        if loaded:
            logger.info(
                "install_permission_rules: loaded %d rule(s) from %s [%s]",
                len(loaded), path, source_name,
            )
            rules.extend(loaded)

    if rules:
        logger.info(
            "install_permission_rules: %d rule(s) total, mode=%s",
            len(rules), mode,
        )
    return rules, mode


def attach_kwargs() -> dict:
    """Convenience for ``agent_session._build_pipeline``.

    Returns the ``{permission_rules, permission_mode}`` kwargs subset,
    skipping the entry entirely when no rules are loaded so older
    executor builds without the kwarg keep working.
    """
    rules, mode = install_permission_rules()
    if not rules:
        return {}
    return {"permission_rules": rules, "permission_mode": mode}


# G6.4 — Stage 4 guard chain population
# =====================================
# The manifest's ``chain_order`` only reorders items that already exist
# in the chain (executor's ``reorder_chain``). The default GuardStage
# constructs an empty chain, so populating the chain has to happen
# *after* pipeline build via ``add_to_chain``. Same pattern as
# ``install_file_persister`` for Stage 20 — a runtime swap that
# manifest serialization can't express.
GUARD_STAGE_ORDER: int = 4


def populate_guard_chain(pipeline, chain: Optional[list] = None) -> int:
    """Add the requested guards to the pipeline's Stage 4 chain.

    Returns the number of guards actually added (idempotent — guards
    already in the chain are skipped). Returns ``0`` and logs a debug
    message when the pipeline has no Stage 4 (custom manifest dropped
    it) or the chain doesn't exist.

    The default chain (when *chain* is None) matches the manifest
    declaration in ``default_manifest._worker_adaptive_stage_entries``:
    ``["token_budget", "cost_budget", "iteration", "permission"]``.
    Hosts can pass their own list to install a different mix.
    """
    if chain is None:
        chain = ["token_budget", "cost_budget", "iteration", "permission"]

    if pipeline is None:
        return 0

    getter = getattr(pipeline, "get_stage", None)
    stage = None
    if callable(getter):
        stage = getter(GUARD_STAGE_ORDER)
    if stage is None:
        stages = getattr(pipeline, "_stages", None)
        if isinstance(stages, dict):
            stage = stages.get(GUARD_STAGE_ORDER)
    if stage is None:
        logger.debug(
            "populate_guard_chain: pipeline has no stage at order %d; skipping",
            GUARD_STAGE_ORDER,
        )
        return 0

    chains = stage.get_strategy_chains() if hasattr(stage, "get_strategy_chains") else None
    if not chains or "guards" not in chains:
        logger.debug(
            "populate_guard_chain: stage %r has no guards chain; skipping",
            getattr(stage, "name", type(stage).__name__),
        )
        return 0

    existing = {getattr(g, "name", None) for g in chains["guards"].items}
    added = 0
    for guard_name in chain:
        if guard_name in existing:
            continue
        try:
            stage.add_to_chain("guards", guard_name)
            added += 1
        except Exception as exc:
            logger.warning(
                "populate_guard_chain: failed to add %r: %s",
                guard_name, exc,
            )
    if added:
        logger.info(
            "populate_guard_chain: added %d guard(s) — chain now: %s",
            added,
            [getattr(g, "name", None) for g in chains["guards"].items],
        )
    return added


__all__ = [
    "PERMISSION_MODES",
    "attach_kwargs",
    "install_permission_rules",
    "permissions_yaml_path",
]


def _coerce(rules: Iterable) -> List:
    """Hook for tests — turn a generator into a list once.

    Public surface only takes lists, but the loader internally builds
    iterables in some code paths.
    """
    return list(rules)
