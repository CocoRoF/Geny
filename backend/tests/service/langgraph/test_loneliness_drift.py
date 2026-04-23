"""Plan/Phase02 §4 — loneliness drift on autonomous turns.
Plan/Phase01 §3.2 — attention recovery on user turns.

When a VTuber session runs a TRIGGER turn (no user input — autonomous
wake), the bond should *decay* slightly. When it runs a USER turn,
the attention deficit (hunger) should refund. The two helpers are the
unit under test; AgentSession wires them into
``_pipeline_events_scoped`` so they land on the same MutationBuffer
the pipeline writes to.
"""

from __future__ import annotations

from service.langgraph.agent_session import (
    _LONELINESS_AFFECTION_LOSS,
    _LONELINESS_FAMILIARITY_LOSS,
    _USER_MSG_FAMILIARITY_GAIN,
    _USER_MSG_HUNGER_RECOVERY,
    _apply_attention_recovery,
    _apply_loneliness_drift,
)
from service.state import MutationBuffer


def _by_path(buf: MutationBuffer, path: str):
    return [m for m in buf.items if m.path == path]


# ---------------------------------------------------------------------------
# Loneliness drift (TRIGGER turns)
# ---------------------------------------------------------------------------

def test_drift_pushes_negative_affection_and_familiarity() -> None:
    buf = MutationBuffer()
    _apply_loneliness_drift(buf)
    aff = _by_path(buf, "bond.affection")
    fam = _by_path(buf, "bond.familiarity")
    assert len(aff) == 1
    assert aff[0].value == _LONELINESS_AFFECTION_LOSS
    assert aff[0].source == "loneliness:thinking_trigger"
    assert len(fam) == 1
    assert fam[0].value == _LONELINESS_FAMILIARITY_LOSS
    assert fam[0].source == "loneliness:thinking_trigger"


def test_drift_uses_add_op_so_clamp_at_zero_applies() -> None:
    buf = MutationBuffer()
    _apply_loneliness_drift(buf)
    for m in buf.items:
        assert m.op == "add"


def test_drift_constants_are_small_negative() -> None:
    """Magnitudes must be small enough to feel like drift, not punishment."""
    assert -0.5 < _LONELINESS_AFFECTION_LOSS < 0
    assert -0.5 < _LONELINESS_FAMILIARITY_LOSS < 0


def test_repeated_drift_accumulates_independently() -> None:
    """Two consecutive trigger turns => 2× the drift in the buffer."""
    buf = MutationBuffer()
    _apply_loneliness_drift(buf)
    _apply_loneliness_drift(buf)
    aff = _by_path(buf, "bond.affection")
    fam = _by_path(buf, "bond.familiarity")
    assert len(aff) == 2
    assert len(fam) == 2
    assert sum(m.value for m in aff) == 2 * _LONELINESS_AFFECTION_LOSS
    assert sum(m.value for m in fam) == 2 * _LONELINESS_FAMILIARITY_LOSS


# ---------------------------------------------------------------------------
# Attention recovery (USER turns)
# ---------------------------------------------------------------------------

def test_attention_recovery_pushes_hunger_down_and_familiarity_up() -> None:
    buf = MutationBuffer()
    _apply_attention_recovery(buf)
    hun = _by_path(buf, "vitals.hunger")
    fam = _by_path(buf, "bond.familiarity")
    assert len(hun) == 1
    assert hun[0].value == _USER_MSG_HUNGER_RECOVERY
    assert hun[0].source == "attention:user_message"
    assert len(fam) == 1
    assert fam[0].value == _USER_MSG_FAMILIARITY_GAIN


def test_attention_recovery_constants_have_correct_signs() -> None:
    assert _USER_MSG_HUNGER_RECOVERY < 0  # hunger goes DOWN
    assert _USER_MSG_FAMILIARITY_GAIN > 0  # familiarity goes UP
    # Magnitudes within "feels rewarding but not absurd" bounds.
    assert -10.0 < _USER_MSG_HUNGER_RECOVERY < 0
    assert 0 < _USER_MSG_FAMILIARITY_GAIN < 1.0


def test_attention_recovery_uses_add_op() -> None:
    buf = MutationBuffer()
    _apply_attention_recovery(buf)
    for m in buf.items:
        assert m.op == "add"


def test_attention_recovery_does_not_touch_affection() -> None:
    """Plan/Phase02 §5.2 — plain dialogue must not auto-bump affection."""
    buf = MutationBuffer()
    _apply_attention_recovery(buf)
    assert _by_path(buf, "bond.affection") == []

