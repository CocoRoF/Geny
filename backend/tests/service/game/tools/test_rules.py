"""Rule-table tuning + fallback contract (cycle 20260421_9 PR-X3-6).

These tests lock the shape of the tuning numbers so a future tuning
pass can't silently flip a sign (e.g., ``feed`` that *increases*
hunger). They do NOT enforce specific magnitudes beyond sign /
ordering — tuning still moves freely within those bounds.
"""

from __future__ import annotations

from backend.service.game.tools.rules import (
    FEED_RULES,
    GIFT_RULES,
    PLAY_RULES,
    TALK_KINDS,
    feed_rule_for,
    gift_rule_for,
    play_rule_for,
)


# ── FEED ────────────────────────────────────────────────────────────

def test_feed_kinds_cover_expected_set() -> None:
    assert set(FEED_RULES) == {"snack", "meal", "favorite", "medicine"}


def test_feed_hunger_delta_is_non_positive_for_all_kinds() -> None:
    # Hunger is 0=sated / 100=starving, so feeding must *not* raise it.
    for kind, rule in FEED_RULES.items():
        assert rule.hunger_delta <= 0.0, (
            f"feed:{kind} increases hunger (delta={rule.hunger_delta}) "
            "— would starve the creature on every feed"
        )


def test_feed_affection_delta_is_non_negative() -> None:
    for kind, rule in FEED_RULES.items():
        assert rule.affection_delta >= 0.0, (
            f"feed:{kind} reduces affection (delta={rule.affection_delta})"
        )


def test_feed_favorite_gives_more_affection_than_snack() -> None:
    assert FEED_RULES["favorite"].affection_delta > FEED_RULES["snack"].affection_delta


def test_feed_meal_satiates_more_than_snack() -> None:
    # meal delta should be more *negative* than snack (bigger hunger cut).
    assert FEED_RULES["meal"].hunger_delta < FEED_RULES["snack"].hunger_delta


def test_feed_rule_for_unknown_falls_back_to_snack() -> None:
    assert feed_rule_for("unicorn_food") is FEED_RULES["snack"]
    assert feed_rule_for("") is FEED_RULES["snack"]


# ── PLAY ────────────────────────────────────────────────────────────

def test_play_kinds_cover_expected_set() -> None:
    assert set(PLAY_RULES) == {"cuddle", "fetch", "game", "tease"}


def test_play_energy_delta_is_non_positive() -> None:
    # Playing always costs energy.
    for kind, rule in PLAY_RULES.items():
        assert rule.energy_delta <= 0.0


def test_play_tease_is_the_only_stress_raiser() -> None:
    stress_raisers = {k for k, r in PLAY_RULES.items() if r.stress_delta > 0.0}
    assert stress_raisers == {"tease"}


def test_play_tease_reduces_affection_slightly() -> None:
    assert PLAY_RULES["tease"].affection_delta < 0.0


def test_play_rule_for_unknown_falls_back_to_cuddle() -> None:
    assert play_rule_for("parkour") is PLAY_RULES["cuddle"]


# ── GIFT ────────────────────────────────────────────────────────────

def test_gift_kinds_cover_expected_set() -> None:
    assert set(GIFT_RULES) == {"flower", "toy", "accessory", "letter"}


def test_gift_all_deltas_are_non_negative() -> None:
    # Gifts should never hurt — if that's ever desired it belongs in
    # tease/rejection, not under ``gift``.
    for kind, rule in GIFT_RULES.items():
        assert rule.affection_delta >= 0.0
        assert rule.trust_delta >= 0.0
        assert rule.joy_delta >= 0.0


def test_gift_letter_gives_most_trust() -> None:
    # Design promise: a letter is the archetype of trust-building.
    letter = GIFT_RULES["letter"]
    for kind, rule in GIFT_RULES.items():
        if kind == "letter":
            continue
        assert letter.trust_delta > rule.trust_delta


def test_gift_accessory_gives_most_affection() -> None:
    # Design promise: an accessory (wearable) is the archetype of
    # affection-building.
    accessory = GIFT_RULES["accessory"]
    for kind, rule in GIFT_RULES.items():
        if kind == "accessory":
            continue
        assert accessory.affection_delta > rule.affection_delta


def test_gift_rule_for_unknown_falls_back_to_flower() -> None:
    assert gift_rule_for("diamond_ring") is GIFT_RULES["flower"]


# ── TALK ────────────────────────────────────────────────────────────

def test_talk_kinds_cover_expected_meta_beats() -> None:
    assert set(TALK_KINDS) == {"greet", "topic_shift", "check_in", "farewell"}
