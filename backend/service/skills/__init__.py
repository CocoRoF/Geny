"""Geny adoption of geny-executor's Skills system (Phase 4).

A Skill is a ``SKILL.md`` (YAML frontmatter + markdown body) that
describes a prompt template + allowed tool list. The executor ships
the loader, registry, and SkillTool; Geny supplies:

- The disk layout (``~/.geny/skills/`` for user skills,
  ``backend/skills/bundled/`` for first-party bundled skills).
- The session-build wiring (``install_skill_registry`` populates a
  registry, registers a ``SkillToolProvider`` alongside
  ``GenyToolProvider``, and exposes ``Skill[]`` to the host).
- The opt-in env (``GENY_ALLOW_USER_SKILLS=1``) so user-supplied
  skills don't run unless the operator explicitly trusts them.

Bundled skills always load (low security risk — they're shipped in
the repo and reviewed alongside the code).
"""

from __future__ import annotations

from service.skills.install import (
    BUNDLED_SKILLS_DIR,
    SKILLS_OPT_IN_ENV,
    USER_SKILLS_DIR_NAME,
    bundled_skills_dir,
    install_skill_registry,
    list_skills,
    user_skills_dir,
)

__all__ = [
    "BUNDLED_SKILLS_DIR",
    "SKILLS_OPT_IN_ENV",
    "USER_SKILLS_DIR_NAME",
    "bundled_skills_dir",
    "install_skill_registry",
    "list_skills",
    "user_skills_dir",
]
