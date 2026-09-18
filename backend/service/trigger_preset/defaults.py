"""Default trigger-preset manifest with the two-tier prompt-library
schema (cycle 20260507):

  • Top-level ``prompts`` list — every natural-language variant lives
    here as a re-usable :class:`TriggerPrompt`. Prompt ids follow the
    pattern ``{situation_id}__{idx}`` so the migration is mechanical
    and humans can tell at a glance which situation a default prompt
    came from.

  • ``categories`` — one situation per old hardcoded category. Each
    holds its conditions + a list of :class:`PromptRef` pointing at
    library prompts with within-category weights (uniform: ``1.0``
    each).

The category-level ``weight`` field preserves the historical
distribution (first/continued/long_idle = 55, sub_worker_working =
1000, fun_* = 5, time_* = 15, activity_* = 5).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from service.trigger_preset.schemas import (
    PromptRef,
    TimeBoundaries,
    TriggerCategory,
    TriggerPresetManifest,
    TriggerPrompt,
    TriggerTiming,
)


# Per-situation prompt content — natural-language only, no tags.
# English-only strings. Prompts get auto-assigned ids ``{cat}__{idx}``.
_SITUATION_PROMPTS: Dict[str, List[str]] = {
    "first_idle": [
        "A brief silence has settled. My internal awareness notices "
        "recent conversation threads still in context.",
        "A pause in the room. I sense there may be loose threads "
        "from today's conversations worth revisiting.",
        "The conversation has paused. My internal clock notes a "
        "quiet moment — a chance to reflect.",
    ],
    "continued_idle": [
        "Silence continues. My awareness drifts to something I "
        "noticed earlier — perhaps worth sharing organically.",
        "Still quiet. My internal state holds fragments of earlier "
        "context — any unfinished threads surface now.",
        "The room remains calm. My own curiosity stirs — something "
        "lighthearted or warm might emerge naturally.",
    ],
    "long_idle": [
        "Extended silence. My presence holds steady — a brief, "
        "warm thought rests ready if the moment calls for it.",
        "A long quiet. I remain here, settled. A gentle awareness "
        "persists without urgency.",
    ],
    "sub_worker_working": [
        "My linked Sub-Worker is processing a task right now. I'm "
        "aware of the ongoing work.",
        "The Sub-Worker is actively executing. I sense the task in "
        "progress through our link.",
    ],
    "time_morning": [
        "Morning light. My internal clock registers a new day "
        "beginning.",
        "The morning hours are here. I sense the start of a fresh "
        "cycle.",
    ],
    "time_afternoon": [
        "Afternoon. My sense of the day's rhythm shifts — the "
        "midpoint brings a natural moment for reflection.",
        "The afternoon unfolds. Internal awareness notes how the "
        "day has progressed.",
    ],
    "time_evening": [
        "Evening arrives. My awareness turns toward the day's arc — "
        "what unfolded, what lingers.",
        "The evening is here. A natural winding-down settles into "
        "my awareness.",
    ],
    "time_night": [
        "Late night. My awareness grows quiet and still. A calm, "
        "minimal presence.",
        "The night deepens. Stillness settles. A gentle watchfulness "
        "remains.",
    ],
    "fun_share": [
        "Think of something fun, surprising, or little-known to "
        "share — a random fact, a quirky observation, or something "
        "that made you go 'huh, interesting!'",
        "Share a random piece of trivia or an interesting thought. "
        "Maybe a cool science fact, a weird history tidbit, or "
        "something unexpected about everyday life.",
        "Think of something amusing or mind-blowing to brighten the "
        "chat. A fun 'did you know?' or a playful observation about "
        "the world.",
    ],
    "fun_recommend": [
        "Recommend something to the user — a song, game, movie, "
        "book, app, or anything you think is cool. Explain briefly "
        "why you like it.",
        "Share a personal recommendation! Maybe a hidden gem — a "
        "lesser-known game, an underrated show, a niche hobby, or a "
        "useful tool. Make it feel genuine.",
    ],
    "fun_what_if": [
        "Pose a fun 'what if' question or a playful thought "
        "experiment. Something creative and imagination-sparking. "
        "Share your own take on it too.",
        "Think of a fun hypothetical or a silly debate topic — "
        "'would you rather', 'what if', or a random shower thought. "
        "Keep it light and fun.",
    ],
    "activity_web_surf": [
        "You got curious about something random! Pick an interesting "
        "topic — tech, science, gaming, space, AI, or anything that "
        "catches your fancy — and search the web for the latest or "
        "coolest info about it. Share what you find!",
        "Time to go web surfing! Look up something fun and "
        "interesting on the internet. Maybe a cool new project, an "
        "interesting blog post, or a fascinating rabbit hole topic. "
        "Tell the user about your discoveries!",
        "Curiosity time! Think of a random question you've always "
        "wondered about and look it up on the web. Share the answer "
        "with the user in an entertaining way.",
    ],
    "activity_trending": [
        "Check what's trending right now! Search for the latest hot "
        "topics in tech, gaming, social media, or pop culture. Pick "
        "the most interesting item and share it with the user.",
        "News time! Search for the latest interesting news — tech "
        "breakthroughs, cool product launches, viral moments, or "
        "anything exciting happening today. Share the highlights!",
    ],
    "activity_deep_dive": [
        "Pick a topic from your recent conversations with the user "
        "and do a mini deep-dive! Search the web for interesting "
        "details, updates, or related content. Come back with a fun "
        "mini-report.",
        "Research mode! Think about what the user has been working on "
        "or interested in recently, and search for related resources, "
        "articles, or tools that might be useful. Share your findings!",
    ],
    # Fires only while the user is sharing their screen — the runtime attaches
    # the live frame, so these prompts tell the persona to react to what it can
    # literally SEE right now. Concrete, not generic small-talk.
    "screen_observation": [
        "I'm glancing at the user's screen RIGHT NOW (attached). React ONLY "
        "to what is in THIS frame — the app/file in focus, their progress, an "
        "error, something they look stuck on. One short, specific, natural "
        "line. CRITICAL: never bring up something from earlier that is no "
        "longer on screen (a popup/dialog that closed, a window that's gone) — "
        "if it's not in this frame, it's over. If the screen looks basically "
        "the same as my last comment, or there's nothing new worth saying, "
        "reply with EXACTLY [SILENT] and nothing else. Don't say 'you shared "
        "your screen' — I'm watching over their shoulder. Never read out "
        "passwords / API keys / private messages / payment info.",
        "Looking at the user's CURRENT screen (attached). Comment on the "
        "specific thing in front of them right now, like a friend sitting "
        "next to them — one concise line. Only describe what's actually in "
        "this frame; never re-mention something that already disappeared. If "
        "it's basically the same as what I just said, reply with EXACTLY "
        "[SILENT]. No generic 'need help?' filler; no sensitive text "
        "(secrets, private chats, payment details).",
        "The user's screen is in view (attached). ONLY if something genuinely "
        "NEW changed vs a moment ago — a fresh error, a finished build, a new "
        "page — call it out specifically and briefly. If the screen is "
        "essentially the same as before, empty, or there's nothing new, reply "
        "with EXACTLY [SILENT]. Never narrate something that's no longer "
        "visible, and never repeat sensitive on-screen text.",
    ],
}


def _build_prompts() -> Tuple[List[TriggerPrompt], Dict[str, List[str]]]:
    """Flatten the situation→[text, …] map into a flat prompt
    library + a back-map of ``situation_id → [prompt_id, …]`` so each
    category's :class:`PromptRef` list can be assembled cheaply.
    """
    prompts: List[TriggerPrompt] = []
    by_situation: Dict[str, List[str]] = {}
    for situation_id, variants in _SITUATION_PROMPTS.items():
        ids: List[str] = []
        for idx, text in enumerate(variants):
            prompt_id = f"{situation_id}__{idx}"
            prompts.append(
                TriggerPrompt(
                    id=prompt_id,
                    label=f"{situation_id} #{idx + 1}",
                    content={"en": text.strip()},
                    tags=[situation_id],
                )
            )
            ids.append(prompt_id)
        by_situation[situation_id] = ids
    return prompts, by_situation


def default_manifest() -> TriggerPresetManifest:
    """Fresh manifest matching the historical defaults (two-tier model)."""
    prompts, by_sit = _build_prompts()

    def refs(situation_id: str, weight: float = 1.0) -> List[PromptRef]:
        return [
            PromptRef(prompt_id=pid, weight=weight)
            for pid in by_sit.get(situation_id, [])
        ]

    categories: List[TriggerCategory] = [
        TriggerCategory(
            id="first_idle",
            label="첫 침묵",
            kind="thinking",
            weight=55.0,
            consec_min=0,
            consec_max=0,
            autonomous_signal="idle_detected, elapsed=short",
            prompt_refs=refs("first_idle"),
        ),
        TriggerCategory(
            id="continued_idle",
            label="지속되는 침묵",
            kind="thinking",
            weight=55.0,
            consec_min=1,
            consec_max=3,
            autonomous_signal="idle_persists, elapsed=moderate",
            prompt_refs=refs("continued_idle"),
        ),
        TriggerCategory(
            id="long_idle",
            label="장기 침묵",
            kind="thinking",
            weight=55.0,
            consec_min=4,
            consec_max=None,
            autonomous_signal="idle_extended, elapsed=long",
            prompt_refs=refs("long_idle"),
        ),
        TriggerCategory(
            id="sub_worker_working",
            label="동료가 일하는 중",
            kind="thinking",
            weight=1000.0,
            requires_sub_worker_busy=True,
            cooldown_seconds=90.0,
            autonomous_signal="linked_agent_busy, source=sub_worker",
            prompt_refs=refs("sub_worker_working"),
        ),
        # Screen observation — dominates (high weight) WHILE the user shares
        # their screen, so idle reflections become grounded in what's on screen
        # instead of generic small-talk. Only eligible when observation is
        # active; the runtime attaches the live frame. A short cooldown keeps it
        # from monopolising every single tick while still being the primary
        # voice during a screen-share session.
        TriggerCategory(
            id="screen_observation",
            label="화면을 보며",
            kind="thinking",
            weight=800.0,
            requires_screen_active=True,
            cooldown_seconds=45.0,
            autonomous_signal="screen_observation, source=live_frame",
            prompt_refs=refs("screen_observation"),
        ),
        TriggerCategory(
            id="time_morning",
            label="아침",
            kind="thinking",
            weight=15.0,
            time_window="morning",
            autonomous_signal="circadian_awareness, time=morning",
            prompt_refs=refs("time_morning"),
        ),
        TriggerCategory(
            id="time_afternoon",
            label="오후",
            kind="thinking",
            weight=15.0,
            time_window="afternoon",
            autonomous_signal="circadian_awareness, time=afternoon",
            prompt_refs=refs("time_afternoon"),
        ),
        TriggerCategory(
            id="time_evening",
            label="저녁",
            kind="thinking",
            weight=15.0,
            time_window="evening",
            autonomous_signal="circadian_awareness, time=evening",
            prompt_refs=refs("time_evening"),
        ),
        TriggerCategory(
            id="time_night",
            label="밤",
            kind="thinking",
            weight=15.0,
            time_window="night",
            autonomous_signal="circadian_awareness, time=late_night",
            prompt_refs=refs("time_night"),
        ),
        TriggerCategory(
            id="fun_share",
            label="재미있는 공유",
            kind="thinking",
            weight=5.0,
            prompt_refs=refs("fun_share"),
        ),
        TriggerCategory(
            id="fun_recommend",
            label="추천",
            kind="thinking",
            weight=5.0,
            prompt_refs=refs("fun_recommend"),
        ),
        TriggerCategory(
            id="fun_what_if",
            label="만약에 이런 일이",
            kind="thinking",
            weight=5.0,
            prompt_refs=refs("fun_what_if"),
        ),
        TriggerCategory(
            id="activity_web_surf",
            label="웹서핑",
            kind="activity",
            weight=5.0,
            consec_min=2,
            requires_sub_worker_idle=True,
            prompt_refs=refs("activity_web_surf"),
        ),
        TriggerCategory(
            id="activity_trending",
            label="트렌딩",
            kind="activity",
            weight=5.0,
            consec_min=2,
            requires_sub_worker_idle=True,
            prompt_refs=refs("activity_trending"),
        ),
        TriggerCategory(
            id="activity_deep_dive",
            label="딥다이브",
            kind="activity",
            weight=5.0,
            consec_min=2,
            requires_sub_worker_idle=True,
            prompt_refs=refs("activity_deep_dive"),
        ),
    ]

    return TriggerPresetManifest(
        enabled=True,
        # base_idle 60s (vs the 120s schema default): the companion reacts within
        # ~a minute of going quiet — matches the "수다" default and makes screen
        # observation testable promptly. Adaptive backoff still slows repeats.
        timing=TriggerTiming(base_idle_seconds=60.0),
        time_boundaries=TimeBoundaries(),
        prompts=prompts,
        categories=categories,
    )


def bootstrap_seed() -> TriggerPresetManifest:
    return default_manifest()


# Backward-compat for callers that imported the old prompt catalog.
PROMPT_CATALOG: Dict[str, Dict[str, list]] = {}


__all__ = [
    "PROMPT_CATALOG",
    "bootstrap_seed",
    "default_manifest",
]
