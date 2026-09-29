"""Per-session memory tuning knob resolver.

Reads ``settings.json:memory.tuning.*`` and falls back to historical
defaults that ``geny-executor``'s ``GenyMemoryRetriever`` /
``GenyMemoryStrategy`` expect when no policy is supplied.

This is *not* a provider-selection layer — provider construction lives
in ``service.memory.provider_bridge`` and the path-A migration
deleted the registry layer entirely. Only the tuning knob loader
remains because it's per-session settings business logic.
"""

from __future__ import annotations

from typing import Any, Dict


def _settings_section() -> Dict[str, Any]:
    """Best-effort read of ``settings.json:memory``. Returns ``{}``
    when unavailable so callers can fall back to defaults.
    """
    try:
        from geny_executor.settings import get_default_loader
    except ImportError:
        return {}
    section = get_default_loader().get_section("memory")
    if section is None:
        return {}
    if hasattr(section, "model_dump"):
        return section.model_dump(exclude_none=True)
    if isinstance(section, dict):
        return dict(section)
    return {}


def load_memory_tuning(*, is_vtuber: bool) -> Dict[str, Any]:
    """Return the per-session memory tuning knobs that
    ``agent_session._build_pipeline`` consumes.

    ``max_inject_chars`` accepts ``int`` OR
    ``{"vtuber": int, "worker": int}`` to match the executor's
    role-aware historical defaults.
    """
    tuning = (_settings_section().get("tuning") or {})
    if not isinstance(tuning, dict):
        tuning = {}

    raw_mic = tuning.get("max_inject_chars")
    default_mic = 8000 if is_vtuber else 10000
    if isinstance(raw_mic, int):
        max_inject_chars = raw_mic
    elif isinstance(raw_mic, dict):
        candidate = raw_mic.get("vtuber" if is_vtuber else "worker")
        max_inject_chars = candidate if isinstance(candidate, int) else default_mic
    else:
        max_inject_chars = default_mic

    pin_budget_ratio_raw = tuning.get("pin_budget_ratio")
    if isinstance(pin_budget_ratio_raw, (int, float)):
        pin_budget_ratio = max(0.0, min(0.7, float(pin_budget_ratio_raw)))
    else:
        pin_budget_ratio = 0.30

    category_boosts_raw = tuning.get("category_boosts")
    if isinstance(category_boosts_raw, dict):
        category_boosts = {
            str(k): float(v)
            for k, v in category_boosts_raw.items()
            if isinstance(v, (int, float))
        }
    else:
        category_boosts = {
            "insights": 1.2,
            "projects": 1.2,
            "critical": 1.5,
        }

    always_render_vault_map_raw = tuning.get("always_render_vault_map")
    if isinstance(always_render_vault_map_raw, bool):
        always_render_vault_map = always_render_vault_map_raw
    else:
        always_render_vault_map = True

    slim_mode_raw = tuning.get("slim_mode")
    slim_mode = bool(slim_mode_raw) if isinstance(slim_mode_raw, bool) else False

    return {
        "max_inject_chars": max_inject_chars,
        "recent_turns": (
            int(tuning["recent_turns"])
            if isinstance(tuning.get("recent_turns"), int)
            # Logical turns since executor 2.75 (it counted rows), and only
            # the text fallback for a turn the replay does not cover.
            else 3
        ),
        "enable_vector_search": (
            bool(tuning["enable_vector_search"])
            if isinstance(tuning.get("enable_vector_search"), bool)
            else True
        ),
        "enable_reflection": (
            bool(tuning["enable_reflection"])
            if isinstance(tuning.get("enable_reflection"), bool)
            else True
        ),
        "pin_budget_ratio": pin_budget_ratio,
        "category_boosts": category_boosts,
        "always_render_vault_map": always_render_vault_map,
        "slim_mode": slim_mode,
    }
