"""What changes every turn stays out of the cached system prompt.

Mood, vitals, bond, stage, acclimation, the event hint and the whiteboard
spotlight were rendered into the stable system prefix: every turn — and,
for the event hint, every step of a turn — rewrote the prompt the cache
keyed on, so a VTuber turn never read its system prompt from cache.
"""

from pathlib import Path

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import ComposablePromptBuilder

from service.game.events import EventSeed, EventSeedBlock, EventSeedPool
from service.persona import CharacterPersonaProvider
from service.persona.blocks import (
    AcclimationBlock,
    MoodBlock,
    ProgressionBlock,
    RelationshipBlock,
    VitalsBlock,
)
from service.memory.note_utils import is_silent_reply
from service.state import CREATURE_STATE_KEY, SESSION_META_KEY
from service.state.schema.creature_state import CreatureState
from service.whiteboard.spotlight_block import SpotlightContextBlock


def test_the_blocks_that_change_every_turn_are_volatile():
    for cls in (MoodBlock, RelationshipBlock, VitalsBlock, ProgressionBlock, AcclimationBlock, SpotlightContextBlock):
        assert getattr(cls, "volatile") is True, cls.__name__
    seed = EventSeedBlock(EventSeed(id="x", trigger=lambda c, m: True, hint_text="hi"))
    assert seed.volatile is True


def test_volatile_blocks_leave_the_stable_prefix():
    class _Stable(MoodBlock):
        def render(self, state):
            return "[Mood] joy 0.8"

    builder = ComposablePromptBuilder(blocks=[_Stable()])
    parts = builder.build_parts(PipelineState())
    assert parts and all(p["volatile"] for p in parts if "Mood" in p["text"])


def test_the_event_seed_is_picked_once_per_turn(tmp_path: Path):
    (tmp_path / "default.md").write_text("persona", encoding="utf-8")
    seeds = [EventSeed(id=f"s{i}", trigger=lambda c, m: True, hint_text=f"hint {i}") for i in range(8)]
    provider = CharacterPersonaProvider(
        characters_dir=tmp_path,
        default_vtuber_prompt="v",
        default_worker_prompt="w",
        adaptive_prompt="a",
        event_seed_pool=EventSeedPool(seeds),
    )
    state = PipelineState()
    state.shared[CREATURE_STATE_KEY] = CreatureState(character_id="c", owner_user_id="u")
    state.shared[SESSION_META_KEY] = {"session_id": "s", "is_vtuber": True}
    meta = {"session_id": "s", "is_vtuber": True}
    picks = {
        provider.resolve(state, session_meta=meta).persona_blocks[-1].seed.id for _ in range(12)
    }
    assert len(picks) == 1  # every step of the turn sees the same event


def test_silence_follows_the_executor_rule():
    assert is_silent_reply("[SILENT]")
    assert is_silent_reply("[neutral] [SILENT]")
    assert not is_silent_reply("[SILENT] 사실 할 말이 있어")
