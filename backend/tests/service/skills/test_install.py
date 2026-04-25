"""Coverage for G7.3 — skill registry construction + dual-source loading.

Two load sources:

1. Bundled (always) — backend/skills/bundled/<id>/SKILL.md.
2. User (opt-in via GENY_ALLOW_USER_SKILLS=1) — ~/.geny/skills/<id>/SKILL.md.

Skipped when geny-executor's skills subpackage isn't importable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("geny_executor.skills")

from service.skills import install as skill_install  # noqa: E402


@pytest.fixture
def isolated_user_dir(monkeypatch, tmp_path) -> Iterator[Path]:
    """HOME-rooted ~/.geny/skills/ pointed at tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".geny" / "skills").mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(skill_install.SKILLS_OPT_IN_ENV, raising=False)
    yield tmp_path


def _write_skill(dir_path: Path, skill_id: str, body: str = "") -> None:
    """Helper: drop a SKILL.md under dir_path/<skill_id>/SKILL.md."""
    skill_dir = dir_path / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = f"""---
id: {skill_id}
name: {skill_id.replace("_", " ").title()}
description: Test skill {skill_id}
allowed_tools: []
---
{body or f"This is the body of {skill_id}."}
"""
    (skill_dir / "SKILL.md").write_text(frontmatter, encoding="utf-8")


# ── User source gate ────────────────────────────────────────────────


def test_user_skills_skipped_when_env_off(isolated_user_dir: Path) -> None:
    user_dir = skill_install.user_skills_dir()
    _write_skill(user_dir, "test_user_skill")
    registry, skills = skill_install.install_skill_registry()
    # Bundled skills (under backend/skills/bundled/) may or may not
    # exist on this branch — the assertion is just that the user skill
    # we just dropped is *not* in the loaded set.
    ids = {getattr(s, "id", None) for s in skills}
    assert "test_user_skill" not in ids


def test_user_skills_loaded_when_env_on(isolated_user_dir: Path, monkeypatch) -> None:
    user_dir = skill_install.user_skills_dir()
    _write_skill(user_dir, "test_user_skill_a")
    _write_skill(user_dir, "test_user_skill_b")
    monkeypatch.setenv(skill_install.SKILLS_OPT_IN_ENV, "1")

    registry, skills = skill_install.install_skill_registry()
    assert registry is not None
    ids = {getattr(s, "id", None) for s in skills}
    assert "test_user_skill_a" in ids
    assert "test_user_skill_b" in ids


# ── No skills present at all ───────────────────────────────────────


def test_install_returns_none_registry_when_empty(
    isolated_user_dir: Path, monkeypatch
) -> None:
    """No bundled skills + no user skills → registry is None (so the
    caller can skip the SkillToolProvider registration entirely)."""
    monkeypatch.setattr(skill_install, "BUNDLED_SKILLS_DIR", isolated_user_dir / "no-such-bundled")
    # Don't set the opt-in env — user skills also skipped.
    registry, skills = skill_install.install_skill_registry()
    assert registry is None
    assert skills == []


# ── attach_provider ────────────────────────────────────────────────


def test_attach_provider_returns_none_for_empty_registry() -> None:
    assert skill_install.attach_provider(None) is None


def test_attach_provider_returns_provider_for_real_registry(
    isolated_user_dir: Path, monkeypatch
) -> None:
    user_dir = skill_install.user_skills_dir()
    _write_skill(user_dir, "tap_skill")
    monkeypatch.setenv(skill_install.SKILLS_OPT_IN_ENV, "1")

    registry, _ = skill_install.install_skill_registry()
    provider = skill_install.attach_provider(registry)
    assert provider is not None


# ── list_skills (used by the /api/skills/list endpoint in G7.4) ────


def test_is_bundled_skill_distinguishes_sources(isolated_user_dir: Path, monkeypatch) -> None:
    """R3 (audit 20260425_3 §1.1): the previous _path_chain helper
    returned [] unconditionally → log always reported "0 bundled".
    The replacement _is_bundled_skill must correctly classify a
    skill loaded from BUNDLED_SKILLS_DIR as bundled and a skill
    loaded from ~/.geny/skills as user."""
    user_dir = skill_install.user_skills_dir()
    _write_skill(user_dir, "user_only_skill")
    monkeypatch.setenv(skill_install.SKILLS_OPT_IN_ENV, "1")

    _, skills = skill_install.install_skill_registry()
    by_id = {getattr(s, "id", None): s for s in skills}

    user_skill = by_id.get("user_only_skill")
    assert user_skill is not None
    assert skill_install._is_bundled_skill(user_skill) is False

    # The bundled directory ships with the 3 G7.5 skills; if any is
    # present we should classify it as bundled.
    bundled_skills = [s for s in skills if skill_install._is_bundled_skill(s)]
    if skill_install.BUNDLED_SKILLS_DIR.exists() and any(
        (skill_install.BUNDLED_SKILLS_DIR / d).exists()
        for d in ("summarize_session", "search_web_and_summarize", "draft_pr")
    ):
        assert len(bundled_skills) >= 1


def test_list_skills_summary_shape(isolated_user_dir: Path, monkeypatch) -> None:
    user_dir = skill_install.user_skills_dir()
    _write_skill(user_dir, "summary_skill")
    monkeypatch.setenv(skill_install.SKILLS_OPT_IN_ENV, "1")

    out = skill_install.list_skills()
    summary = next((s for s in out if s["id"] == "summary_skill"), None)
    assert summary is not None
    assert "name" in summary
    assert "description" in summary
    assert "allowed_tools" in summary
    assert isinstance(summary["allowed_tools"], list)
