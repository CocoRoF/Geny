"""SectionLibrary.identity / build_agent_prompt — name-handling policy.

Cycle 20260422_6 PR3 verifies the structural separation between
``session_name`` (operational handle) and ``character_display_name``
(in-character name). This test guards against the regression where an
arbitrary user-typed slug like ``"ertsdfg"`` was being recited by the
VTuber as its own name (cycle matrix R2).
"""

from __future__ import annotations

import pytest

from service.prompt.sections import SectionLibrary, build_agent_prompt


# ── SectionLibrary.identity ────────────────────────────────────────


def test_identity_omits_name_lines_when_both_unset() -> None:
    """No name fields → no name-style lines. The persona stays anonymous
    until the first-encounter overlay (PR2) prompts the user."""
    section = SectionLibrary.identity(role="vtuber")
    content = section.content
    assert "name is" not in content.lower()
    assert "Session handle" not in content


def test_identity_uses_character_display_name_when_set() -> None:
    section = SectionLibrary.identity(
        role="vtuber",
        character_display_name="루나",
    )
    assert 'Your character name is "루나".' in section.content
    assert "Session handle" not in section.content


def test_identity_session_handle_includes_disclaimer() -> None:
    """``session_name`` alone must be exposed as a handle with an
    explicit 'NOT your character name' disclaimer — never as a name."""
    section = SectionLibrary.identity(
        role="vtuber",
        session_name="ertsdfg",
    )
    content = section.content
    assert 'Session handle: "ertsdfg"' in content
    assert "NOT your character name" in content
    # Critical: must NOT use the legacy "Your name is X" phrasing that
    # the model used to absorb as its own name.
    assert 'Your name is "ertsdfg"' not in content
    assert 'character name is "ertsdfg"' not in content


def test_identity_prefers_display_name_over_handle() -> None:
    """When both fields are set, display_name wins and the handle line
    is suppressed (otherwise the model would see two competing names)."""
    section = SectionLibrary.identity(
        role="vtuber",
        session_name="ertsdfg",
        character_display_name="루나",
    )
    content = section.content
    assert 'Your character name is "루나".' in content
    assert "ertsdfg" not in content
    assert "Session handle" not in content


def test_identity_role_line_unchanged_for_worker() -> None:
    section = SectionLibrary.identity(role="worker")
    assert section.content.startswith("You are a Geny Worker agent.")


def test_identity_includes_agent_id_when_provided() -> None:
    section = SectionLibrary.identity(role="vtuber", agent_id="abc-123")
    assert "Agent ID: abc-123" in section.content


# ── build_agent_prompt — end-to-end forwarding ─────────────────────


def test_build_agent_prompt_forwards_character_display_name() -> None:
    prompt = build_agent_prompt(
        role="vtuber",
        session_name="ertsdfg",
        character_display_name="루나",
    )
    assert 'Your character name is "루나".' in prompt
    # The handle line itself must NOT appear when display_name is set.
    assert 'Session handle: "ertsdfg"' not in prompt
    assert 'Your name is "ertsdfg"' not in prompt


def test_build_agent_prompt_keeps_handle_disclaimer_when_no_display_name() -> None:
    prompt = build_agent_prompt(
        role="vtuber",
        session_name="ertsdfg",
    )
    assert 'Session handle: "ertsdfg"' in prompt
    assert "NOT your character name" in prompt


def test_build_agent_prompt_is_anonymous_when_neither_set() -> None:
    prompt = build_agent_prompt(role="vtuber")
    # The anonymous persona has no name lines — the only place the
    # legacy "Your name is" phrasing could leak in is identity, which
    # must now be silent.
    assert 'Your name is "' not in prompt
    assert "Your character name is" not in prompt
