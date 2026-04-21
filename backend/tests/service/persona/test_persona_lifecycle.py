"""Persona lifecycle end-to-end — create → character → custom → restore.

Exercises the CharacterPersonaProvider + DynamicPersonaSystemBuilder pair
the way AgentSessionManager + AgentSession use them. We avoid spinning up
a real pipeline here (that needs API keys / env service / DB wiring);
instead we simulate the manager's contract — create_agent_session seeds
the provider, mutations land on the provider, and each pipeline turn is
represented by a fresh ``builder.build(state)`` call.

Each test walks a realistic session shape so the ordering between
provider mutations and builder invocations is the part under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import (
    DateTimeBlock,
    MemoryContextBlock,
)

from backend.service.persona import (
    CharacterPersonaProvider,
    DynamicPersonaSystemBuilder,
)


_VTUBER_DEFAULT = "VTUBER_DEFAULT"
_WORKER_DEFAULT = "WORKER_DEFAULT"
_ADAPTIVE = "ADAPTIVE_TAIL"


@pytest.fixture
def chars_dir(tmp_path: Path) -> Path:
    d = tmp_path / "characters"
    d.mkdir()
    (d / "catgirl.md").write_text(
        "## Character Personality\nI am a catgirl.", encoding="utf-8"
    )
    (d / "robot.md").write_text(
        "## Character Personality\nI am a robot.", encoding="utf-8"
    )
    (d / "default.md").write_text(
        "## Character Personality\ndefault-body", encoding="utf-8"
    )
    return d


@pytest.fixture
def provider(chars_dir: Path) -> CharacterPersonaProvider:
    return CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )


def _builder_for(
    provider: CharacterPersonaProvider,
    session_id: str,
    *,
    is_vtuber: bool,
) -> DynamicPersonaSystemBuilder:
    """Emulate AgentSession._build_pipeline's wiring."""
    return DynamicPersonaSystemBuilder(
        provider,
        session_meta={
            "session_id": session_id,
            "is_vtuber": is_vtuber,
            "role": "vtuber" if is_vtuber else "worker",
            "owner_username": None,
        },
        tail_blocks=[DateTimeBlock(), MemoryContextBlock()],
    )


def _simulate_create(provider, session_id: str, initial_prompt: str | None) -> None:
    """Replay the manager's create_agent_session seed step."""
    provider.set_static_override(session_id, initial_prompt)


# ── Scenario 1 ─────────────────────────────────────────────────────────


def test_vtuber_session_lifecycle(provider, chars_dir: Path) -> None:
    """Create → character swap → PUT custom prompt → soft-delete → restore."""
    sid = "vtuber-1"
    built_initial = f"{_VTUBER_DEFAULT}\n\n(seeded by manager)"

    # 1. create_agent_session → provider seeded with the built prompt.
    _simulate_create(provider, sid, built_initial)
    builder = _builder_for(provider, sid, is_vtuber=True)

    turn1 = builder.build(PipelineState())
    assert isinstance(turn1, str)
    assert turn1.startswith(built_initial)
    assert "Current date:" in turn1  # tail block renders too

    # 2. PUT /vtuber/agents/{sid}/model catgirl
    provider.set_character(sid, "catgirl")
    turn2 = builder.build(PipelineState())
    assert "I am a catgirl" in turn2
    assert turn2.startswith(built_initial)

    # 3. PUT /system-prompt → static override replaces base.
    provider.set_static_override(sid, "CUSTOM_PROMPT")
    turn3 = builder.build(PipelineState())
    assert turn3.startswith("CUSTOM_PROMPT")
    # Adaptive is NOT added for vtuber role.
    assert _ADAPTIVE not in turn3
    # Character append survives override (independent state).
    assert "I am a catgirl" in turn3

    # 4. soft-delete clears provider state (manager does this).
    provider.reset(sid)
    turn4 = builder.build(PipelineState())
    # Now base is the role default (no override, no character).
    assert turn4.startswith(_VTUBER_DEFAULT)
    assert "I am a catgirl" not in turn4

    # 5. restore — manager recreates session with *original* built prompt
    #    (from sessions.json), then restore_session re-stages the *custom*
    #    override that was previously persisted.
    _simulate_create(provider, sid, built_initial)
    provider.set_static_override(sid, "CUSTOM_PROMPT")
    turn5 = builder.build(PipelineState())
    assert turn5.startswith("CUSTOM_PROMPT")
    # Character is NOT restored (legacy behavior — character append is not
    # persisted in sessions.json; user re-assigns model).
    assert "I am a catgirl" not in turn5


# ── Scenario 2 ─────────────────────────────────────────────────────────


def test_sub_worker_context_injection_on_vtuber(provider) -> None:
    """Manager creates a VTuber, pairs a sub-worker, and appends the
    delegation-notice context through provider.append_context."""
    sid = "vtuber-with-sub"
    _simulate_create(provider, sid, _VTUBER_DEFAULT)
    builder = _builder_for(provider, sid, is_vtuber=True)

    turn_before = builder.build(PipelineState())
    assert "Sub-Worker" not in turn_before

    # Manager's SD3 replacement after creating the sub-worker.
    vtuber_ctx = (
        "## Sub-Worker Agent\nDelegate complex tasks via "
        "send_direct_message_internal."
    )
    provider.append_context(sid, vtuber_ctx)
    turn_after = builder.build(PipelineState())
    assert "Sub-Worker Agent" in turn_after
    # Idempotence: re-calling append_context with the same text must not
    # duplicate the section.
    provider.append_context(sid, vtuber_ctx)
    turn_after_again = builder.build(PipelineState())
    assert turn_after_again.count("Sub-Worker Agent") == 1


# ── Scenario 3 ─────────────────────────────────────────────────────────


def test_session_isolation_and_cascade_restore(provider) -> None:
    """VTuber + linked worker restore independently — provider keyed on sid."""
    vid, wid = "vtuber-A", "worker-B"
    _simulate_create(provider, vid, _VTUBER_DEFAULT)
    _simulate_create(provider, wid, _WORKER_DEFAULT)

    # User customizes both independently.
    provider.set_static_override(vid, "VTUBER_CUSTOM")
    provider.set_static_override(wid, "WORKER_CUSTOM")

    # Soft-delete both.
    provider.reset(vid)
    provider.reset(wid)

    # Cascade restore (agent_controller's SD4 + SD5 replacement).
    _simulate_create(provider, vid, _VTUBER_DEFAULT)
    provider.set_static_override(vid, "VTUBER_CUSTOM")
    _simulate_create(provider, wid, _WORKER_DEFAULT)
    provider.set_static_override(wid, "WORKER_CUSTOM")

    vbuilder = _builder_for(provider, vid, is_vtuber=True)
    wbuilder = _builder_for(provider, wid, is_vtuber=False)
    vt = vbuilder.build(PipelineState())
    wt = wbuilder.build(PipelineState())
    assert vt.startswith("VTUBER_CUSTOM")
    assert "VTUBER_CUSTOM" not in wt
    assert wt.startswith("WORKER_CUSTOM")
    assert _ADAPTIVE in wt  # worker gets adaptive tail
    assert _ADAPTIVE not in vt  # vtuber does not


# ── Scenario 4 ─────────────────────────────────────────────────────────


def test_character_swap_between_turns(provider) -> None:
    """Live character change takes effect on the next turn only."""
    sid = "vtuber-swap"
    _simulate_create(provider, sid, _VTUBER_DEFAULT)
    builder = _builder_for(provider, sid, is_vtuber=True)

    provider.set_character(sid, "catgirl")
    t1 = builder.build(PipelineState())
    assert "I am a catgirl" in t1

    provider.set_character(sid, "robot")
    t2 = builder.build(PipelineState())
    assert "I am a robot" in t2
    assert "I am a catgirl" not in t2


# ── Scenario 5 ─────────────────────────────────────────────────────────


def test_empty_static_override_falls_back_to_role_default(provider) -> None:
    """Passing None/empty to set_static_override reverts to role default."""
    sid = "revert-test"
    _simulate_create(provider, sid, "INITIAL")
    builder = _builder_for(provider, sid, is_vtuber=False)

    t_initial = builder.build(PipelineState())
    assert t_initial.startswith("INITIAL")

    provider.set_static_override(sid, None)  # clear
    t_after_clear = builder.build(PipelineState())
    assert t_after_clear.startswith(_WORKER_DEFAULT)
    assert _ADAPTIVE in t_after_clear


# ── Scenario 6 ─────────────────────────────────────────────────────────


def test_cache_key_changes_with_mutations(provider) -> None:
    """Each provider mutation flips a flag in PersonaResolution.cache_key so
    the prompt-cache layer can detect a new persona shape deterministically.

    The cache_key tracks presence/absence of each mutation (role, override,
    character, context), not content-level diffs — so this test walks the
    flag-transition ladder instead of re-setting an already-set flag.
    """
    sid = "cache-key"
    meta = {"session_id": sid, "is_vtuber": True}

    keys = []
    # 0. Nothing staged yet → role default only.
    keys.append(provider.resolve(PipelineState(), session_meta=meta).cache_key)
    # 1. Override flag flips on.
    provider.set_static_override(sid, "OVERRIDE")
    keys.append(provider.resolve(PipelineState(), session_meta=meta).cache_key)
    # 2. Character flag flips on.
    provider.set_character(sid, "catgirl")
    keys.append(provider.resolve(PipelineState(), session_meta=meta).cache_key)
    # 3. Context flag flips on.
    provider.append_context(sid, "ctx")
    keys.append(provider.resolve(PipelineState(), session_meta=meta).cache_key)

    assert len(set(keys)) == 4  # each flip produces a distinct cache key
