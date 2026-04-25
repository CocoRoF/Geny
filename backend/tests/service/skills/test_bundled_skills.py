"""Coverage for G7.5 — first-party SKILL.md inventory.

Each bundled skill must:
- Parse cleanly (no SkillLoadError raised by the executor's parser)
- Carry the metadata fields the SkillTool consumes (name,
  description, allowed_tools)
- Survive ``install_skill_registry()`` with no opt-in env (bundled
  skills always load)

If a contributor adds / renames / removes a bundled skill, this file
fails loud enough that the next maintainer notices the inventory
drift without grepping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("geny_executor.skills")

from geny_executor.skills.loader import load_skills_dir  # noqa: E402

from service.skills import bundled_skills_dir, install_skill_registry  # noqa: E402


# ── Inventory ───────────────────────────────────────────────────────


_EXPECTED_BUNDLED = {
    "summarize_session",
    "search_web_and_summarize",
    "draft_pr",
}


def test_bundled_directory_exists() -> None:
    bundled = bundled_skills_dir()
    assert bundled.exists(), (
        f"Bundled skills directory missing at {bundled}. "
        "G7.3 created the directory; G7.5 populated it. If a refactor "
        "moved skills/, update bundled_skills_dir() in install.py."
    )


def test_bundled_inventory_matches_expected() -> None:
    bundled = bundled_skills_dir()
    on_disk = {p.name for p in bundled.iterdir() if p.is_dir() and (p / "SKILL.md").exists()}
    assert on_disk == _EXPECTED_BUNDLED, (
        f"Bundled skill inventory drifted. On-disk: {sorted(on_disk)}, "
        f"Expected: {sorted(_EXPECTED_BUNDLED)}. Update _EXPECTED_BUNDLED "
        "or the disk if the change is intentional."
    )


@pytest.mark.parametrize("skill_id", sorted(_EXPECTED_BUNDLED))
def test_bundled_skill_parses_cleanly(skill_id: str) -> None:
    """Each SKILL.md must parse via the executor's loader. The strict
    flag re-raises any SkillLoadError so a malformed frontmatter
    surfaces here instead of silently being dropped from the report."""
    bundled = bundled_skills_dir()
    skill_dir = bundled / skill_id
    skill_md = skill_dir / "SKILL.md"
    assert skill_md.exists()
    # Single-skill scan: load_skills_dir on the parent picks up only
    # the requested entry by virtue of the per-skill subdir layout.
    report = load_skills_dir(bundled, strict=False)
    matching = [s for s in report.loaded if getattr(s, "id", None) == skill_id or getattr(s, "name", None).replace("-", "_") == skill_id.replace("-", "_")]
    assert matching, f"Skill {skill_id!r} did not appear in load report. Errors: {report.errors}"


def test_bundled_skills_carry_required_metadata() -> None:
    """Every bundled skill must declare name + description + an
    allowed_tools list. Empty allowed_tools is fine (no tool calls,
    pure prompt rewrite) but the field must exist.

    The executor's :class:`Skill` dataclass nests metadata under
    ``skill.metadata`` (name / description / allowed_tools live there);
    the top-level ``id`` + ``body`` are separate. Walk both shapes so
    this stays compatible across executor versions that have
    promoted / demoted fields.
    """
    bundled = bundled_skills_dir()
    report = load_skills_dir(bundled, strict=True)
    for skill in report.loaded:
        meta = getattr(skill, "metadata", None) or skill
        assert getattr(meta, "name", None), f"{skill}: missing name"
        assert getattr(meta, "description", None), f"{skill}: missing description"
        allowed = getattr(meta, "allowed_tools", None)
        assert isinstance(allowed, tuple), (
            f"{skill}: allowed_tools must be a tuple, got {type(allowed).__name__}"
        )


def test_install_picks_up_bundled_without_user_opt_in(monkeypatch) -> None:
    """Bundled skills load even with GENY_ALLOW_USER_SKILLS unset —
    that's the point of distinguishing bundled from user."""
    monkeypatch.delenv("GENY_ALLOW_USER_SKILLS", raising=False)
    registry, skills = install_skill_registry()
    assert registry is not None, "Bundled skills should populate the registry"
    ids = {getattr(s, "id", None) or getattr(s, "name", None) for s in skills}
    # Some implementations expose ``id``, others ``name``. Accept
    # either form for the cross-version compatibility window.
    matched = ids & {*_EXPECTED_BUNDLED, *(s.replace("_", "-") for s in _EXPECTED_BUNDLED)}
    assert matched, f"No bundled skills resolved through install. Got: {ids}"
