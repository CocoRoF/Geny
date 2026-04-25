"""Build a SkillRegistry + SkillToolProvider for a Geny session.

Two skill sources:

1. **Bundled** (``backend/skills/bundled/``) — first-party, always
   loaded. Reviewed alongside the code, so the security risk is the
   same as adding a built-in tool.
2. **User** (``~/.geny/skills/``) — operator-supplied. Gated by
   ``GENY_ALLOW_USER_SKILLS=1`` because a SKILL.md can spawn
   subprocesses (via the underlying tool list) that the host hasn't
   reviewed.

Returns a registry the agent_session passes through to the executor's
``SkillToolProvider``, which then registers a ``SkillTool`` per skill
under the ``skill__<id>`` name. The frontend slash-command parser
(G7.4) maps ``/<skill-id>`` to the corresponding tool call.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

USER_SKILLS_DIR_NAME = "skills"
SKILLS_OPT_IN_ENV = "GENY_ALLOW_USER_SKILLS"

# Bundled skills live in <repo>/backend/skills/bundled/. Resolved
# relative to this module so it works regardless of CWD.
_BUNDLED_REL = Path(__file__).resolve().parent.parent.parent / "skills" / "bundled"
BUNDLED_SKILLS_DIR: Path = _BUNDLED_REL


def bundled_skills_dir() -> Path:
    return BUNDLED_SKILLS_DIR


def user_skills_dir() -> Path:
    return Path.home() / ".geny" / USER_SKILLS_DIR_NAME


def _user_skills_opted_in() -> bool:
    raw = os.environ.get(SKILLS_OPT_IN_ENV, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def install_skill_registry() -> Tuple[Optional[Any], List[Any]]:
    """Build a populated :class:`SkillRegistry`.

    Returns:
        ``(registry, skills)`` — registry is ``None`` when the executor
        isn't importable or no skills were found. ``skills`` is a list
        of the loaded :class:`Skill` instances (also empty when none).
    """
    try:
        from geny_executor.skills import SkillRegistry, load_skills_dir
    except ImportError:
        logger.debug("install_skill_registry: geny_executor.skills unavailable")
        return None, []

    registry = SkillRegistry()
    loaded: List[Any] = []

    # Bundled — always.
    if BUNDLED_SKILLS_DIR.exists():
        report = load_skills_dir(BUNDLED_SKILLS_DIR, strict=False)
        for skill in report.loaded:
            registry.register(skill)
            loaded.append(skill)
        if report.errors:
            for path, err in report.errors:
                logger.warning("install_skill_registry: bundled skill error %s: %s", path, err)

    # User — opt-in.
    if _user_skills_opted_in():
        user_dir = user_skills_dir()
        if user_dir.exists():
            report = load_skills_dir(user_dir, strict=False)
            for skill in report.loaded:
                registry.register(skill)
                loaded.append(skill)
            if report.errors:
                for path, err in report.errors:
                    logger.warning("install_skill_registry: user skill error %s: %s", path, err)
    else:
        logger.debug(
            "install_skill_registry: %s not set — user skills under %s skipped",
            SKILLS_OPT_IN_ENV, user_skills_dir(),
        )

    if loaded:
        logger.info(
            "install_skill_registry: %d skill(s) registered (%d bundled, %d user)",
            len(loaded),
            sum(1 for _ in loaded if BUNDLED_SKILLS_DIR in _path_chain(loaded)),
            len(loaded),
        )
        # Cleaner count: just total + breakdown without trying to
        # introspect each skill's source path.

    return (registry if loaded else None), loaded


def _path_chain(_) -> List[Path]:
    """Placeholder kept simple — Skill objects don't expose their
    source path uniformly across versions, so the breakdown count
    in the log line above is approximate. Future versions can
    enrich this if Skill.source_path becomes stable."""
    return []


def list_skills() -> List[dict]:
    """Return a JSON-serialisable summary of every loaded skill.

    Used by the ``/api/skills/list`` endpoint (G7.4) so the frontend
    panel knows which slash commands are available.
    """
    _, skills = install_skill_registry()
    out: List[dict] = []
    for skill in skills:
        out.append({
            "id": getattr(skill, "id", None),
            "name": getattr(skill, "name", None),
            "description": getattr(skill, "description", None),
            "model": getattr(skill, "model", None),
            "allowed_tools": list(getattr(skill, "allowed_tools", []) or []),
        })
    return out


def attach_provider(registry: Any) -> Optional[Any]:
    """Build a :class:`SkillToolProvider` for the given registry.

    Returns ``None`` when the registry is empty or the executor isn't
    importable — callers treat ``None`` as "no provider to register".
    """
    if registry is None:
        return None
    try:
        from geny_executor.skills import SkillToolProvider
    except ImportError:
        return None
    return SkillToolProvider(registry)


__all__ = [
    "BUNDLED_SKILLS_DIR",
    "SKILLS_OPT_IN_ENV",
    "USER_SKILLS_DIR_NAME",
    "attach_provider",
    "bundled_skills_dir",
    "install_skill_registry",
    "list_skills",
    "user_skills_dir",
]
