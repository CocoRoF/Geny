"""Unit tests for :func:`service.executor.stage_manifest`.

Covers the four PR-X4-2 invariants from cycle 20260421_10:

1. **Parse / predicate contract.** ``parse_stage_manifest_id`` and
   ``is_stage_manifest_id`` round-trip ids the way the PR-X4-1
   selector emits them — including bare stages (no archetype) and
   compound archetypes that retain underscores.
2. **Stage tunings.** The four deliberate knobs (loop.max_turns,
   cache.strategy, evaluate.strategy, tools.external default) match
   plan/04 §7.1's progression intuition for every stage.
3. **Chain shape parity with vtuber.** Stage manifests mirror the
   vtuber 15-entry layout (no stage 8 think); any regression that
   adds stages or drops the mandatory tool/agent/emit triad fails.
4. **Metadata traceability.** ``base_preset="vtuber"``, tags carry
   ``stage:*`` / ``archetype:*``, and description reflects the id —
   so ops can ``jq`` logs without re-parsing the id string.
"""

from __future__ import annotations

import pytest


# ── parse / predicate ─────────────────────────────────────────────────


def test_parse_bare_stage_returns_empty_archetype() -> None:
    from service.executor.stage_manifest import parse_stage_manifest_id

    assert parse_stage_manifest_id("infant") == ("infant", "")
    assert parse_stage_manifest_id("adult") == ("adult", "")


def test_parse_stage_with_archetype_splits_on_first_underscore() -> None:
    from service.executor.stage_manifest import parse_stage_manifest_id

    assert parse_stage_manifest_id("infant_cheerful") == ("infant", "cheerful")
    assert parse_stage_manifest_id("teen_introvert") == ("teen", "introvert")
    assert parse_stage_manifest_id("adult_artisan") == ("adult", "artisan")


def test_parse_preserves_underscores_in_archetype_tail() -> None:
    """Compound archetype like ``"adult_artisan_hermit"`` should yield
    ``("adult", "artisan_hermit")`` — the first underscore is the
    separator, everything after is the archetype verbatim. Guards
    against a naïve ``.split("_")`` that would drop the tail."""
    from service.executor.stage_manifest import parse_stage_manifest_id

    assert parse_stage_manifest_id("adult_artisan_hermit") == (
        "adult",
        "artisan_hermit",
    )


def test_parse_empty_string_returns_empty_tuple() -> None:
    """Defensive: the selector's ``_current_manifest`` falls back to
    ``"base"`` when manifest_id is empty, but callers might still
    round-trip an unset id. Empty input must not raise."""
    from service.executor.stage_manifest import parse_stage_manifest_id

    assert parse_stage_manifest_id("") == ("", "")


def test_is_stage_manifest_id_accepts_documented_stages() -> None:
    from service.executor.stage_manifest import is_stage_manifest_id

    for mid in (
        "infant", "infant_cheerful",
        "child", "child_curious",
        "teen", "teen_introvert", "teen_extrovert",
        "adult", "adult_artisan",
    ):
        assert is_stage_manifest_id(mid), f"expected {mid!r} to be stage-like"


def test_is_stage_manifest_id_rejects_presets_and_unknowns() -> None:
    """The caller (PR-X4-5) dispatches on this predicate: stage ids go
    through ``build_stage_manifest``; legacy preset names / unknowns
    fall back to ``build_default_manifest``. Misclassifying a preset
    as a stage would route it to the wrong builder."""
    from service.executor.stage_manifest import is_stage_manifest_id

    assert not is_stage_manifest_id("vtuber")
    assert not is_stage_manifest_id("worker_adaptive")
    assert not is_stage_manifest_id("default")
    assert not is_stage_manifest_id("")
    assert not is_stage_manifest_id("geriatric")  # future stage not yet defined


def test_known_stage_manifest_ids_includes_all_plan_documented() -> None:
    """Plan/04 §7.2 enumerates: infant_cheerful, child_curious,
    teen_introvert, teen_extrovert, adult_artisan. Any regression
    that drops one breaks the frontend enumeration contract."""
    from service.executor.stage_manifest import known_stage_manifest_ids

    ids = set(known_stage_manifest_ids())
    for required in (
        "infant", "infant_cheerful",
        "child", "child_curious",
        "teen", "teen_introvert", "teen_extrovert",
        "adult", "adult_artisan",
    ):
        assert required in ids, f"missing canonical id {required!r}"


def test_known_stage_manifest_ids_returns_sorted() -> None:
    from service.executor.stage_manifest import known_stage_manifest_ids

    ids = known_stage_manifest_ids()
    assert ids == sorted(ids)


# ── Stage tunings ─────────────────────────────────────────────────────


_STAGES = ("infant", "child", "teen", "adult")


@pytest.mark.parametrize("stage", _STAGES)
def test_bare_stage_builds(stage: str) -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest(stage)
    assert manifest is not None
    assert manifest.metadata.base_preset == "vtuber"


@pytest.mark.parametrize(
    "manifest_id,archetype",
    [
        ("infant_cheerful", "cheerful"),
        ("child_curious", "curious"),
        ("teen_introvert", "introvert"),
        ("teen_extrovert", "extrovert"),
        ("adult_artisan", "artisan"),
    ],
)
def test_canonical_archetype_combos_build(manifest_id: str, archetype: str) -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest(manifest_id)
    assert f"archetype:{archetype}" in manifest.metadata.tags
    assert archetype in manifest.metadata.description


def test_unknown_archetype_still_builds_with_metadata_reflection() -> None:
    """Unknown archetypes must NOT hard-fail — the selector's naming
    strategy is pluggable (PR-X4-1's ``NamingFn``), and deployments
    may experiment with archetypes outside plan/04 §7.2's whitelist.
    The manifest should just carry the archetype in metadata so logs
    trace it."""
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("teen_melancholic")
    assert "archetype:melancholic" in manifest.metadata.tags
    assert "melancholic" in manifest.metadata.description


def test_unknown_stage_raises_valueerror() -> None:
    """Unknown stage prefixes fail loudly — :func:`build_default_manifest`
    uses the same "typos fail" policy for preset names and we mirror
    it here. ``"elder_wise"`` (no such stage in plan/04 §7.3) is the
    most plausible typo."""
    from service.executor.stage_manifest import build_stage_manifest

    with pytest.raises(ValueError, match="unknown stage manifest id"):
        build_stage_manifest("elder_wise")

    with pytest.raises(ValueError, match="unknown stage manifest id"):
        build_stage_manifest("baby")


def _loop_max_turns(manifest) -> int:
    entry = next(s for s in manifest.stages if s["order"] == 13)
    return entry["config"]["max_turns"]


@pytest.mark.parametrize(
    "stage,expected",
    [("infant", 2), ("child", 5), ("teen", 8), ("adult", 10)],
)
def test_loop_max_turns_scales_with_stage(stage: str, expected: int) -> None:
    """Progression from 2 → 5 → 8 → 10 turns matches plan/04 §7.1's
    "infant 은 짧은 답, teen 은 풍부한 표현" intuition. Regression guard:
    if someone flattens this to a single constant, short-reactive
    infant beats regress into long reflective monologues."""
    from service.executor.stage_manifest import build_stage_manifest

    assert _loop_max_turns(build_stage_manifest(stage)) == expected


def _cache_strategy(manifest) -> str:
    entry = next(s for s in manifest.stages if s["order"] == 5)
    return entry["strategies"]["strategy"]


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("infant", "system_cache"),
        ("child", "system_cache"),
        ("teen", "aggressive_cache"),
        ("adult", "aggressive_cache"),
    ],
)
def test_cache_strategy_matches_stage(stage: str, expected: str) -> None:
    from service.executor.stage_manifest import build_stage_manifest

    assert _cache_strategy(build_stage_manifest(stage)) == expected


def _evaluator_strategy(manifest) -> str:
    entry = next(s for s in manifest.stages if s["order"] == 12)
    return entry["strategies"]["strategy"]


@pytest.mark.parametrize(
    "stage,expected",
    [
        ("infant", "signal_based"),
        ("child", "signal_based"),
        ("teen", "binary_classify"),
        ("adult", "binary_classify"),
    ],
)
def test_evaluator_strategy_matches_stage(stage: str, expected: str) -> None:
    from service.executor.stage_manifest import build_stage_manifest

    assert _evaluator_strategy(build_stage_manifest(stage)) == expected


@pytest.mark.parametrize(
    "stage,expected_tools",
    [
        ("infant", ["feed", "play"]),
        ("child", ["feed", "play", "gift"]),
        ("teen", ["feed", "play", "gift", "talk"]),
        ("adult", ["feed", "play", "gift", "talk"]),
    ],
)
def test_default_tool_roster_matches_plan(
    stage: str, expected_tools: list[str],
) -> None:
    """Plan/04 §7.1: "infant 은 feed/play 만, teen 은 확장 도구 포함".
    Defaults flow into ``manifest.tools.external`` so PR-X4-5's session
    builder can register them through the existing
    :class:`GenyToolProvider` path."""
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest(stage)
    assert list(manifest.tools.external) == expected_tools


def test_external_tool_override_takes_precedence() -> None:
    """Explicit ``external_tool_names=`` wins verbatim — matches
    :func:`build_default_manifest`'s semantics, so deployments that
    need an extra custom tool don't have to fork the factory."""
    from service.executor.stage_manifest import build_stage_manifest

    custom = ["feed", "send_direct_message_external"]
    manifest = build_stage_manifest("infant", external_tool_names=custom)
    assert list(manifest.tools.external) == custom


def test_empty_external_override_disables_tools() -> None:
    """``external_tool_names=[]`` is distinct from ``None`` — callers
    sometimes want zero tools (voice-only deployments). The default
    roster must not leak back in for an explicit empty list."""
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("child", external_tool_names=[])
    assert list(manifest.tools.external) == []


def test_built_in_tools_flow_through_untouched() -> None:
    """``built_in_tool_names`` is an executor-side passthrough matching
    :func:`build_default_manifest`. Stage manifests don't populate
    built-ins by default (vtuber-derived, conversational)."""
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("teen", built_in_tool_names=["Read", "Write"])
    assert list(manifest.tools.built_in) == ["Read", "Write"]

    default_manifest = build_stage_manifest("teen")
    assert list(default_manifest.tools.built_in) == []


# ── Chain shape parity with vtuber ────────────────────────────────────


@pytest.mark.parametrize("stage", _STAGES)
def test_mandatory_tool_agent_emit_stages_present(stage: str) -> None:
    """Same invariant as :mod:`test_default_manifest`: stages 10 (tool),
    11 (agent), 14 (emit) are non-negotiable — dropping them silently
    disables tool execution."""
    from service.executor.stage_manifest import build_stage_manifest

    orders = {e["order"] for e in build_stage_manifest(stage).stages}
    assert {10, 11, 14}.issubset(orders), (
        f"{stage}: missing mandatory stages; got {sorted(orders)}"
    )


@pytest.mark.parametrize("stage", _STAGES)
def test_stage_8_think_omitted(stage: str) -> None:
    """All stage manifests are vtuber-derived; vtuber intentionally
    omits stage 8 (think). Re-introducing it would contradict
    plan/04 §7's "no think stage in growth manifests" design (it's a
    lifecycle concern, not a per-turn reflection one)."""
    from service.executor.stage_manifest import build_stage_manifest

    orders = {e["order"] for e in build_stage_manifest(stage).stages}
    assert 8 not in orders, (
        f"{stage}: stage 8 (think) should be omitted; got {sorted(orders)}"
    )


@pytest.mark.parametrize("stage", _STAGES)
def test_tool_stage_strategies_match_preset(stage: str) -> None:
    """Tool stage strategies are identical to the vtuber preset —
    there is no growth-axis knob here. Regression guard: if a future
    PR tries to fork ``executor`` / ``router`` per stage, this fails."""
    from service.executor.stage_manifest import build_stage_manifest

    entry = next(e for e in build_stage_manifest(stage).stages if e["order"] == 10)
    assert entry["name"] == "tool"
    assert entry["strategies"] == {"executor": "sequential", "router": "registry"}


@pytest.mark.parametrize("stage", _STAGES)
def test_emit_chain_starts_empty(stage: str) -> None:
    """Emitters are attached at runtime (``attach_runtime``) — the
    manifest declares an empty chain so :class:`EmitStage` bypasses
    until the session layer fills it. Matches vtuber."""
    from service.executor.stage_manifest import build_stage_manifest

    entry = next(e for e in build_stage_manifest(stage).stages if e["order"] == 14)
    assert entry["chain_order"] == {"emitters": []}


# ── Metadata traceability ────────────────────────────────────────────


def test_metadata_carries_stage_tag_only_when_archetype_missing() -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("infant")
    assert "stage:infant" in manifest.metadata.tags
    assert not any(
        t.startswith("archetype:") for t in manifest.metadata.tags
    ), manifest.metadata.tags


def test_metadata_carries_both_stage_and_archetype_tags() -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("teen_introvert")
    assert "stage:teen" in manifest.metadata.tags
    assert "archetype:introvert" in manifest.metadata.tags


def test_metadata_name_carries_full_manifest_id() -> None:
    """``metadata.name`` is what ops greps in logs; embedding the raw
    id means a transition event surfaces as ``stage:teen_introvert``
    without requiring a secondary lookup."""
    from service.executor.stage_manifest import build_stage_manifest

    assert build_stage_manifest("teen_introvert").metadata.name == (
        "stage:teen_introvert"
    )


def test_metadata_description_mentions_archetype_when_present() -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("adult_artisan")
    assert "adult" in manifest.metadata.description
    assert "artisan" in manifest.metadata.description


def test_model_override_flows_into_manifest() -> None:
    """Matches :func:`build_default_manifest`'s contract — caller-supplied
    model id lands in ``manifest.model``."""
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("child", model="claude-haiku-4-5-20251001")
    assert manifest.model.get("model") == "claude-haiku-4-5-20251001"


def test_model_absent_when_not_overridden() -> None:
    from service.executor.stage_manifest import build_stage_manifest

    manifest = build_stage_manifest("adult")
    assert "model" not in manifest.model
