"""Plan/Phase04 — game tools degrade to narrated-only for non-VTubers.

Each tool consults the current_creature_role contextvar bound by
AgentSession; when the role isn't VTuber the tool returns a friendly
NARRATED_ONLY string and emits zero mutations. The tools must still
behave normally when the role contextvar is left at its default
(VTuber) — that's the legacy / classic-mode contract.
"""

from __future__ import annotations

from contextlib import contextmanager

from service.game.tools.feed import FeedTool
from service.game.tools.gift import GiftTool
from service.game.tools.play import PlayTool
from service.game.tools.talk import TalkTool
from service.state import (
    MutationBuffer,
    bind_creature_role,
    bind_mutation_buffer,
    reset_creature_role,
    reset_mutation_buffer,
)
from service.state.schema.creature_state import (
    CHARACTER_ROLE_VTUBER,
    CHARACTER_ROLE_WORKER,
)


@contextmanager
def bound(role: str):
    buf = MutationBuffer()
    btok = bind_mutation_buffer(buf)
    rtok = bind_creature_role(role)
    try:
        yield buf
    finally:
        reset_creature_role(rtok)
        reset_mutation_buffer(btok)


# ---------------------------------------------------------------------------
# Worker role: every tool returns NARRATED_ONLY and emits zero mutations
# ---------------------------------------------------------------------------

def test_feed_no_op_for_worker() -> None:
    with bound(CHARACTER_ROLE_WORKER) as buf:
        result = FeedTool().run(kind="meal")
    assert "FEED_NARRATED_ONLY" in result
    assert "non-vtuber" in result
    assert len(buf.items) == 0


def test_play_no_op_for_worker() -> None:
    with bound(CHARACTER_ROLE_WORKER) as buf:
        result = PlayTool().run(kind="cuddle")
    assert "PLAY_NARRATED_ONLY" in result
    assert "non-vtuber" in result
    assert len(buf.items) == 0


def test_gift_no_op_for_worker() -> None:
    with bound(CHARACTER_ROLE_WORKER) as buf:
        result = GiftTool().run(kind="flower")
    assert "GIFT_NARRATED_ONLY" in result
    assert "non-vtuber" in result
    assert len(buf.items) == 0


def test_talk_no_op_for_worker() -> None:
    with bound(CHARACTER_ROLE_WORKER) as buf:
        result = TalkTool().run(kind="greet")
    assert "TALK_NARRATED_ONLY" in result
    assert "non-vtuber" in result
    assert len(buf.items) == 0


# ---------------------------------------------------------------------------
# VTuber role: tools mutate normally
# ---------------------------------------------------------------------------

def test_feed_mutates_for_vtuber() -> None:
    with bound(CHARACTER_ROLE_VTUBER) as buf:
        result = FeedTool().run(kind="meal")
    assert "FEED_OK" in result
    assert len(buf.items) > 0


def test_play_mutates_for_vtuber() -> None:
    with bound(CHARACTER_ROLE_VTUBER) as buf:
        result = PlayTool().run(kind="cuddle")
    assert "PLAY_OK" in result
    assert len(buf.items) > 0


def test_gift_mutates_for_vtuber() -> None:
    with bound(CHARACTER_ROLE_VTUBER) as buf:
        result = GiftTool().run(kind="flower")
    assert "GIFT_OK" in result
    assert len(buf.items) > 0


def test_talk_mutates_for_vtuber() -> None:
    with bound(CHARACTER_ROLE_VTUBER) as buf:
        result = TalkTool().run(kind="greet")
    assert "TALK_OK" in result
    assert len(buf.items) > 0
