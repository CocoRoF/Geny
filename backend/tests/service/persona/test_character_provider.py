"""CharacterPersonaProvider — role routing, character load, overrides, context."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import PersonaBlock
from geny_executor.stages.s03_system.interface import PromptBlock

from service.game.events import EventSeed, EventSeedBlock, EventSeedPool
from service.persona import CharacterPersonaProvider, PersonaProvider
from service.state import CREATURE_STATE_KEY, SESSION_META_KEY
from service.state.schema.creature_state import CreatureState


_VTUBER_DEFAULT = "VDEFAULT"
_WORKER_DEFAULT = "WDEFAULT"
_ADAPTIVE = "ADAPTIVE"


@pytest.fixture
def chars_dir(tmp_path: Path) -> Path:
    d = tmp_path / "characters"
    d.mkdir()
    (d / "catgirl.md").write_text("## Character Personality\ncatgirl-body", encoding="utf-8")
    (d / "default.md").write_text("## Character Personality\ndefault-body", encoding="utf-8")
    return d


@pytest.fixture
def provider(chars_dir: Path) -> CharacterPersonaProvider:
    return CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )


def _persona_text(resolution) -> str:
    assert len(resolution.persona_blocks) == 1
    block = resolution.persona_blocks[0]
    assert isinstance(block, PersonaBlock)
    return block.render(PipelineState())


def test_implements_persona_provider(provider: CharacterPersonaProvider) -> None:
    assert isinstance(provider, PersonaProvider)


def test_vtuber_role_default_persona(provider) -> None:
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert text == _VTUBER_DEFAULT
    # Adaptive must NOT be included for vtuber role.
    assert _ADAPTIVE not in text


def test_worker_role_appends_adaptive(provider) -> None:
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": False})
    text = _persona_text(r)
    assert text == f"{_WORKER_DEFAULT}\n\n{_ADAPTIVE}"


def test_static_override_replaces_default(provider) -> None:
    provider.set_static_override("s", "CUSTOM-BASE")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": False})
    text = _persona_text(r)
    assert text.startswith("CUSTOM-BASE\n\n")
    assert _ADAPTIVE in text
    assert _WORKER_DEFAULT not in text


def test_static_override_cleared_restores_default(provider) -> None:
    provider.set_static_override("s", "CUSTOM")
    provider.set_static_override("s", None)
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r) == _VTUBER_DEFAULT


def test_set_character_loads_named_file(provider) -> None:
    provider.set_character("s", "catgirl")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert "catgirl-body" in text
    assert text.startswith(_VTUBER_DEFAULT)


def test_set_character_fallback_to_default_md(provider) -> None:
    provider.set_character("s", "nonexistent")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert "default-body" in _persona_text(r)


def test_missing_character_and_no_default(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    p = CharacterPersonaProvider(
        characters_dir=empty,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )
    p.set_character("s", "ghost")
    r = p.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r) == _VTUBER_DEFAULT  # silently skipped


def test_append_context_concatenates(provider) -> None:
    provider.append_context("s", "sub-worker-notice")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert text.endswith("sub-worker-notice")


def test_append_context_is_idempotent(provider) -> None:
    provider.append_context("s", "once")
    provider.append_context("s", "once")  # duplicate must be rejected
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r).count("once") == 1


def test_sessions_are_isolated(provider) -> None:
    provider.set_static_override("A", "ONLY-A")
    provider.set_character("B", "catgirl")

    text_a = _persona_text(provider.resolve(PipelineState(), session_meta={"session_id": "A", "is_vtuber": False}))
    text_b = _persona_text(provider.resolve(PipelineState(), session_meta={"session_id": "B", "is_vtuber": True}))

    assert "ONLY-A" in text_a and "catgirl-body" not in text_a
    assert "catgirl-body" in text_b and "ONLY-A" not in text_b


def test_reset_clears_all_session_state(provider) -> None:
    provider.set_static_override("s", "CUSTOM")
    provider.set_character("s", "catgirl")
    provider.append_context("s", "ctx")
    provider.reset("s")
    text = _persona_text(
        provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    )
    assert text == _VTUBER_DEFAULT


def test_cache_key_encodes_flags(provider) -> None:
    r_default = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    provider.set_static_override("s", "X")
    r_override = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert r_default.cache_key != r_override.cache_key
    assert r_default.cache_key.startswith("V")
    assert r_override.cache_key.startswith("V")


def test_character_file_is_cached_after_first_read(provider, chars_dir: Path) -> None:
    provider.set_character("s1", "catgirl")
    # Remove the file to prove subsequent loads hit the cache.
    (chars_dir / "catgirl.md").unlink()
    provider.set_character("s2", "catgirl")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s2", "is_vtuber": True})
    assert "catgirl-body" in _persona_text(r)


# ── live_blocks + event_seed_pool integration (PR-X4-5) ───────────────


class _StubBlock(PromptBlock):
    """Stateless block with a fixed name + render string — used in place of
    the real Mood/Vitals/Relationship/Progression blocks so these tests
    don't depend on CreatureState field plumbing."""

    def __init__(self, name: str, text: str = "") -> None:
        self._name = name
        self._text = text

    @property
    def name(self) -> str:
        return self._name

    def render(self, state: PipelineState) -> str:
        return self._text


def _make_provider_with_blocks(
    chars_dir: Path,
    *,
    live_blocks=None,
    event_seed_pool=None,
) -> CharacterPersonaProvider:
    return CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
        live_blocks=live_blocks,
        event_seed_pool=event_seed_pool,
    )


def test_live_blocks_appended_after_persona(chars_dir: Path) -> None:
    """live_blocks follow the PersonaBlock in the returned block list."""
    b1 = _StubBlock("mood", "[Mood] calm")
    b2 = _StubBlock("vitals", "[Vitals] ok")
    p = _make_provider_with_blocks(chars_dir, live_blocks=[b1, b2])
    r = p.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 3
    assert isinstance(r.persona_blocks[0], PersonaBlock)
    assert r.persona_blocks[1] is b1
    assert r.persona_blocks[2] is b2


def test_live_blocks_stay_intact_without_creature_state(chars_dir: Path) -> None:
    """The provider does not gate live blocks on creature_state — blocks
    themselves are expected to render empty when unhydrated (plan/04 §5)."""
    b = _StubBlock("mood", "")
    p = _make_provider_with_blocks(chars_dir, live_blocks=[b])
    state = PipelineState()  # .shared empty — no creature_state
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 2  # persona + live block
    assert r.persona_blocks[1] is b


def _fresh_creature() -> CreatureState:
    """CreatureState with sensible defaults — only used as a non-None
    marker in state.shared so the pool path fires."""
    return CreatureState(character_id="c1", owner_user_id="u1")


def test_event_seed_pool_appends_block_when_creature_present(chars_dir: Path) -> None:
    """With a firing seed + hydrated creature, an EventSeedBlock is appended."""
    seed = EventSeed(
        id="always",
        trigger=lambda c, m: True,
        hint_text="always fires",
        weight=1.0,
    )
    pool = EventSeedPool([seed])
    p = _make_provider_with_blocks(chars_dir, event_seed_pool=pool)

    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    state.shared[SESSION_META_KEY] = {"session_id": "s", "is_vtuber": True}
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})

    assert len(r.persona_blocks) == 2
    assert isinstance(r.persona_blocks[1], EventSeedBlock)
    assert r.persona_blocks[1].seed.id == "always"


def test_event_seed_pool_skipped_without_creature_state(chars_dir: Path) -> None:
    """No creature_state in state.shared → no EventSeedBlock appended."""
    seed = EventSeed(id="always", trigger=lambda c, m: True, hint_text="hi")
    p = _make_provider_with_blocks(chars_dir, event_seed_pool=EventSeedPool([seed]))
    r = p.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 1


def test_event_seed_pool_skipped_when_no_seed_fires(chars_dir: Path) -> None:
    """Creature present but every trigger returns False → no EventSeedBlock."""
    seed = EventSeed(id="never", trigger=lambda c, m: False, hint_text="nope")
    p = _make_provider_with_blocks(chars_dir, event_seed_pool=EventSeedPool([seed]))
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 1


def test_event_seed_pool_exception_is_swallowed(chars_dir: Path) -> None:
    """A pool whose ``pick`` raises must not break the persona resolve —
    turn continues with no EventSeedBlock."""

    class _BoomPool:
        def pick(self, creature: Any, meta: Mapping[str, Any]):
            raise RuntimeError("pool exploded")

    p = _make_provider_with_blocks(chars_dir, event_seed_pool=_BoomPool())
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    # Must not raise.
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 1


def test_cache_key_includes_picked_seed_id(chars_dir: Path) -> None:
    """Picked seed's id is folded into cache_key so a different seed
    doesn't hit a stale entry."""
    seed = EventSeed(
        id="quiet_night", trigger=lambda c, m: True, hint_text="shh", weight=1.0,
    )
    p = _make_provider_with_blocks(chars_dir, event_seed_pool=EventSeedPool([seed]))

    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert r.cache_key.endswith("+E:quiet_night")


def test_cache_key_unchanged_when_pool_picks_nothing(chars_dir: Path) -> None:
    """No seed fires → cache_key keeps the baseline shape (no +E: suffix)."""
    seed = EventSeed(id="nope", trigger=lambda c, m: False, hint_text="x")
    p = _make_provider_with_blocks(chars_dir, event_seed_pool=EventSeedPool([seed]))
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert "+E:" not in r.cache_key


def test_live_blocks_and_event_seed_coexist(chars_dir: Path) -> None:
    """PersonaBlock → live_blocks → EventSeedBlock ordering is stable."""
    live = _StubBlock("mood", "[Mood] calm")
    seed = EventSeed(id="ev", trigger=lambda c, m: True, hint_text="pop")
    p = _make_provider_with_blocks(
        chars_dir, live_blocks=[live], event_seed_pool=EventSeedPool([seed]),
    )
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": True})
    assert len(r.persona_blocks) == 3
    assert isinstance(r.persona_blocks[0], PersonaBlock)
    assert r.persona_blocks[1] is live
    assert isinstance(r.persona_blocks[2], EventSeedBlock)


# ── First-encounter overlay (cycle 20260422_6 PR2) ─────────────────


def _make_provider_with_overlay(
    chars_dir: Path, overlay_path: Path,
) -> CharacterPersonaProvider:
    return CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
        first_encounter_overlay_path=overlay_path,
    )


def _state_with_familiarity(familiarity: float) -> PipelineState:
    state = PipelineState()
    creature = CreatureState(character_id="c1", owner_user_id="u1")
    creature.bond.familiarity = familiarity
    state.shared[CREATURE_STATE_KEY] = creature
    return state


def test_overlay_appended_for_vtuber_at_low_familiarity(
    chars_dir: Path, tmp_path: Path,
) -> None:
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FIRST-ENCOUNTER-BODY", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    r = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    text = _persona_text(r)
    assert "FIRST-ENCOUNTER-BODY" in text
    assert r.cache_key.endswith("+FE")


def test_overlay_omitted_above_threshold(chars_dir: Path, tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    r = p.resolve(
        _state_with_familiarity(1.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert "FE" not in _persona_text(r)
    assert "+FE" not in r.cache_key


def test_overlay_threshold_is_inclusive_at_half(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """``familiarity == 0.5`` is the upper bound of the first-encounter
    band (consistent with AcclimationBlock); overlay must still fire."""
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    r = p.resolve(
        _state_with_familiarity(0.5),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert "FE" in _persona_text(r)
    assert r.cache_key.endswith("+FE")


def test_overlay_omitted_for_worker_even_at_low_familiarity(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """Worker sessions never receive the overlay — consistent with
    Principle B (Worker has no persona). Even with a hydrated bond,
    is_vtuber=False short-circuits the overlay."""
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    r = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": False},
    )
    assert "FE" not in _persona_text(r)
    assert "+FE" not in r.cache_key


def test_overlay_omitted_when_no_creature_state(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """Classic-mode VTuber (no creature_state in shared) gets no overlay
    — there is no familiarity signal to act on."""
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    r = p.resolve(
        PipelineState(),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert "FE" not in _persona_text(r)
    assert "+FE" not in r.cache_key


def test_overlay_cache_key_changes_when_threshold_crossed(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """cache_key must invalidate when familiarity crosses 0.5 → cached
    persona text doesn't get reused after first-encounter ends."""
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)

    low = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    high = p.resolve(
        _state_with_familiarity(1.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert low.cache_key != high.cache_key


def test_missing_overlay_path_disables_feature_silently(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """A misconfigured overlay path must not break session construction
    or resolve — the feature simply turns off."""
    p = _make_provider_with_overlay(chars_dir, tmp_path / "does-not-exist.md")
    r = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert "+FE" not in r.cache_key


def test_overlay_auto_loaded_from_default_filename(
    chars_dir: Path,
) -> None:
    """When no explicit overlay path is given, the provider auto-loads
    ``<characters_dir>/_shared_first_encounter.md`` if present."""
    (chars_dir / "_shared_first_encounter.md").write_text(
        "AUTO-OVERLAY", encoding="utf-8",
    )
    p = CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )
    r = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert "AUTO-OVERLAY" in _persona_text(r)


# ── PR4: Worker strip — Principle B (worker is a tool, not persona) ─


def test_resolve_worker_omits_live_blocks(chars_dir: Path) -> None:
    """is_vtuber=False → live_blocks must NOT be appended.

    The base PersonaBlock (the assembled worker prompt + adaptive tail)
    survives — this is what carries identity, geny_platform, worker.md
    behavior, etc. Only the persona-layer signals are stripped.
    """
    b1 = _StubBlock("mood", "[Mood] would-leak")
    b2 = _StubBlock("vitals", "[Vitals] would-leak")
    p = _make_provider_with_blocks(chars_dir, live_blocks=[b1, b2])
    r = p.resolve(
        PipelineState(),
        session_meta={"session_id": "s", "is_vtuber": False},
    )
    # Only the persona block — no live blocks dragged in.
    assert len(r.persona_blocks) == 1
    assert isinstance(r.persona_blocks[0], PersonaBlock)
    text = _persona_text(r)
    # Worker base + adaptive tail must still be there.
    assert _WORKER_DEFAULT in text
    assert _ADAPTIVE in text
    # Live block content must not have been folded into the persona text.
    assert "would-leak" not in text


def test_resolve_worker_omits_event_seed(chars_dir: Path) -> None:
    """A firing event seed must not produce an EventSeedBlock for workers."""
    seed = EventSeed(
        id="ev",
        trigger=lambda c, m: True,
        hint_text="should-not-appear",
        weight=1.0,
    )
    p = _make_provider_with_blocks(
        chars_dir, event_seed_pool=EventSeedPool([seed]),
    )
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = _fresh_creature()
    r = p.resolve(state, session_meta={"session_id": "s", "is_vtuber": False})
    assert len(r.persona_blocks) == 1
    assert "+E:" not in r.cache_key


def test_resolve_worker_cache_key_carries_w_marker(provider) -> None:
    """Worker resolutions must be distinguishable in cache from a (
    hypothetical) VTuber resolution sharing the same session_id."""
    r_w = provider.resolve(
        PipelineState(),
        session_meta={"session_id": "s", "is_vtuber": False},
    )
    r_v = provider.resolve(
        PipelineState(),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert r_w.cache_key.endswith("+W")
    assert "+W" not in r_v.cache_key
    assert r_w.cache_key != r_v.cache_key


def test_resolve_worker_skips_first_encounter_overlay(
    chars_dir: Path, tmp_path: Path,
) -> None:
    """Even with a hydrated low-familiarity bond, workers receive no overlay.
    (Already covered indirectly by another test; explicit assertion here for
    PR4 completeness.)"""
    overlay = tmp_path / "overlay.md"
    overlay.write_text("FE-WORKER-LEAK", encoding="utf-8")
    p = _make_provider_with_overlay(chars_dir, overlay)
    r = p.resolve(
        _state_with_familiarity(0.0),
        session_meta={"session_id": "s", "is_vtuber": False},
    )
    text = _persona_text(r)
    assert "FE-WORKER-LEAK" not in text
    assert "+FE" not in r.cache_key


def test_resolve_vtuber_path_keeps_live_blocks(chars_dir: Path) -> None:
    """Regression guard: PR4's worker-strip must not also strip VTuber
    live_blocks. The VTuber path stays intact."""
    b = _StubBlock("mood", "[Mood] kept")
    p = _make_provider_with_blocks(chars_dir, live_blocks=[b])
    r = p.resolve(
        PipelineState(),
        session_meta={"session_id": "s", "is_vtuber": True},
    )
    assert len(r.persona_blocks) == 2
    assert r.persona_blocks[1] is b
