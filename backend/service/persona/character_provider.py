"""CharacterPersonaProvider — default ``PersonaProvider`` for Geny.

Models three legacy side-doors on top of the provider contract:

  SD1 (vtuber_controller._inject_character_prompt)
        → ``set_character(session_id, character_name)`` loads
          ``prompts/vtuber_characters/{name}.md`` (fallback ``default.md``)
          and appends it after the base persona text.

  SD2 (agent_controller PUT /system-prompt)
        → ``set_static_override(session_id, text)`` replaces the base
          persona text for that session. Passing ``None`` clears the
          override back to the role default.

  SD3 (agent_session_manager sub-worker context)
        → ``append_context(session_id, text)`` appends free-form context
          after everything else. Used for sub-worker delegation notices.

The role default (VTuber vs worker) is decided per turn from
``session_meta['is_vtuber']`` so the same provider instance serves both.

State keyed on ``session_id``; no locking — controllers already serialise
writes per session and the pipeline runs single-threaded per session.

Live game blocks
----------------

When ``live_blocks`` is supplied, those :class:`PromptBlock` instances
are appended after the assembled persona text on every ``resolve``
call. They are expected to be stateless readers of ``state.shared`` —
typically :class:`MoodBlock` / :class:`RelationshipBlock` /
:class:`VitalsBlock` / :class:`ProgressionBlock` — and drop to an empty
string when ``creature_state`` isn't hydrated, which keeps classic
(non-game) sessions visually identical to pre-X4 output.

When ``event_seed_pool`` is supplied **and** ``creature_state`` is
present in ``state.shared``, the provider picks one seed per turn and
appends an :class:`EventSeedBlock` at the end. The pool itself is
never-raises (plan/04 §6.2), so a misconfigured seed can't break a
turn. The picked seed id is folded into ``cache_key`` so downstream
caches don't serve stale hints.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from geny_executor.stages.s03_system.artifact.default.builders import PersonaBlock
from geny_executor.stages.s03_system.interface import PromptBlock

from service.persona.provider import PersonaResolution

logger = logging.getLogger(__name__)

_CHARACTER_MARKER = "## Character Personality"


class CharacterPersonaProvider:
    """Default ``PersonaProvider`` replicating the legacy side-door behavior."""

    def __init__(
        self,
        *,
        characters_dir: Path,
        default_vtuber_prompt: str,
        default_worker_prompt: str,
        adaptive_prompt: str,
        live_blocks: Optional[Sequence[PromptBlock]] = None,
        event_seed_pool: Optional[Any] = None,
        first_encounter_overlay_path: Optional[Path] = None,
    ):
        self._characters_dir = Path(characters_dir)
        self._default_vtuber = default_vtuber_prompt
        self._default_worker = default_worker_prompt
        self._adaptive = adaptive_prompt
        self._live_blocks: tuple[PromptBlock, ...] = tuple(live_blocks or ())
        self._event_seed_pool = event_seed_pool

        # First-encounter overlay (cycle 20260422_6 PR2). When set and
        # the active VTuber session has ``Bond.familiarity ≤ 0.5``,
        # ``resolve`` appends this text to the persona body and folds
        # a ``+FE`` marker into the cache key so caching invalidates
        # the moment familiarity crosses the threshold.
        if first_encounter_overlay_path is None:
            default_overlay = self._characters_dir / "_shared_first_encounter.md"
            if default_overlay.exists():
                first_encounter_overlay_path = default_overlay
        self._first_encounter_overlay: Optional[str] = self._load_overlay(
            first_encounter_overlay_path
        )

        self._static_override: Dict[str, Optional[str]] = {}
        self._character_append: Dict[str, str] = {}
        self._context_append: Dict[str, str] = {}

        self._character_file_cache: Dict[str, Optional[str]] = {}

    # ── SD2 equivalent ────────────────────────────────────────────────

    def set_static_override(self, session_id: str, text: Optional[str]) -> None:
        """Replace (or clear) the base persona text for a session."""
        if text is None or text == "":
            self._static_override.pop(session_id, None)
        else:
            self._static_override[session_id] = text

    def get_static_override(self, session_id: str) -> Optional[str]:
        return self._static_override.get(session_id)

    # ── SD1 equivalent ────────────────────────────────────────────────

    def set_character(self, session_id: str, character_name: str) -> None:
        """Load a character markdown file by name and arm it for this session.

        Looks up ``<dir>/<name>.md`` then falls back to ``<dir>/default.md``.
        Missing / empty files are silently ignored (same as legacy behavior).
        """
        text = self._load_character_markdown(character_name)
        if text:
            self._character_append[session_id] = text

    def clear_character(self, session_id: str) -> None:
        self._character_append.pop(session_id, None)

    def _load_character_markdown(self, name: str) -> Optional[str]:
        cached = self._character_file_cache.get(name)
        if cached is not None or name in self._character_file_cache:
            return cached
        candidate = self._characters_dir / f"{name}.md"
        if not candidate.exists():
            candidate = self._characters_dir / "default.md"
        if not candidate.exists():
            self._character_file_cache[name] = None
            return None
        try:
            text = candidate.read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            logger.warning("persona: failed to read %s: %s", candidate, exc)
            text = None
        self._character_file_cache[name] = text
        return text

    @staticmethod
    def _load_overlay(path: Optional[Path]) -> Optional[str]:
        """Read a static overlay markdown file once at construction.

        Returns ``None`` on any I/O error so a misconfigured overlay
        path silently disables the feature rather than breaking session
        construction. Logged at WARNING for operational visibility.
        """
        if path is None:
            return None
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("persona: failed to read overlay %s: %s", path, exc)
            return None
        return text or None

    # ── SD3 equivalent ────────────────────────────────────────────────

    def append_context(self, session_id: str, text: str) -> None:
        """Append free-form context (e.g. sub-worker delegation notice)."""
        if not text:
            return
        existing = self._context_append.get(session_id, "")
        if text in existing:
            return
        separator = "\n\n" if existing else ""
        self._context_append[session_id] = existing + separator + text

    # ── Lifecycle ─────────────────────────────────────────────────────

    def reset(self, session_id: str) -> None:
        """Forget all session-scoped state (static override / character / context)."""
        self._static_override.pop(session_id, None)
        self._character_append.pop(session_id, None)
        self._context_append.pop(session_id, None)

    # ── PersonaProvider contract ──────────────────────────────────────

    def resolve(self, state: Any, *, session_meta: dict) -> PersonaResolution:
        session_id = str(session_meta.get("session_id", ""))
        is_vtuber = bool(session_meta.get("is_vtuber", False))

        base = self._static_override.get(session_id)
        if base is None:
            base = self._default_vtuber if is_vtuber else self._default_worker

        parts: list[str] = [base]
        if not is_vtuber:
            parts.append(self._adaptive)

        char_text = self._character_append.get(session_id, "")
        if char_text:
            marker_block = (
                char_text
                if char_text.lstrip().startswith(_CHARACTER_MARKER)
                else char_text
            )
            parts.append(marker_block)

        ctx_text = self._context_append.get(session_id, "")
        if ctx_text:
            parts.append(ctx_text)

        # First-encounter overlay (cycle 20260422_6 PR2).
        # When this is a VTuber session and the bond is still in the
        # ``first-encounter`` band (familiarity ≤ 0.5), append a short
        # overlay that explicitly forbids newborn-baby tropes. Folded
        # into ``cache_key`` so the persona section is re-cached the
        # moment familiarity rises above the threshold.
        first_encounter_active = False
        if (
            is_vtuber
            and self._first_encounter_overlay
            and self._is_first_encounter(state)
        ):
            parts.append(self._first_encounter_overlay)
            first_encounter_active = True

        persona_text = "\n\n".join(p for p in parts if p)

        blocks: list[PromptBlock] = [PersonaBlock(persona_text)]

        # Principle B (cycle 20260422_6 PR4) — Worker is a tool, not a
        # persona. Live state blocks (Mood / Vitals / Bond /
        # Progression / Acclimation) and event seeds are persona-layer
        # signals; surfacing them on the Worker side is pure waste.
        # Workers are also never paired with a CreatureState provider
        # by the manager (`_state_provider_vtuber_only=True`), so the
        # blocks would render empty anyway — but skipping them
        # structurally enforces the invariant for tests and future
        # callers that might wire a creature provider differently.
        picked_seed_id: Optional[str] = None
        if is_vtuber:
            blocks.extend(self._live_blocks)

            if self._event_seed_pool is not None:
                picked = self._pick_event_seed(state)
                if picked is not None:
                    from service.game.events import EventSeedBlock

                    blocks.append(EventSeedBlock(picked))
                    picked_seed_id = getattr(picked, "id", None)

        cache_key = self._compose_cache_key(session_id, is_vtuber)
        if not is_vtuber:
            # Cache key marker so the worker resolution never collides
            # with a (defensively renamed) prior VTuber resolution for
            # the same session_id.
            cache_key = f"{cache_key}+W"
        if first_encounter_active:
            cache_key = f"{cache_key}+FE"
        if picked_seed_id:
            cache_key = f"{cache_key}+E:{picked_seed_id}"
        return PersonaResolution(
            persona_blocks=blocks,
            cache_key=cache_key,
        )

    @staticmethod
    def _is_first_encounter(state: Any) -> bool:
        """Return True when the hydrated bond's familiarity is ≤ 0.5.

        Returns False on any read failure (no shared, no creature, no
        bond, attribute missing) so a misconfigured state doesn't
        accidentally trigger the overlay.
        """
        from service.state import CREATURE_STATE_KEY

        shared = getattr(state, "shared", None)
        if not isinstance(shared, dict):
            return False
        creature = shared.get(CREATURE_STATE_KEY)
        if creature is None:
            return False
        bond = getattr(creature, "bond", None)
        if bond is None:
            return False
        try:
            familiarity = float(getattr(bond, "familiarity", 0.0))
        except (TypeError, ValueError):
            return False
        return familiarity <= 0.5

    def _pick_event_seed(self, state: Any) -> Any:
        """Invoke the event-seed pool against the hydrated creature state.

        Returns ``None`` when the pool raises, when no ``creature_state``
        is in ``state.shared``, or when no seed fires. Pool construction
        already wraps trigger exceptions (plan/04 §6.2); this layer only
        handles the surrounding read.
        """
        from service.state import (
            CREATURE_STATE_KEY,
            SESSION_META_KEY,
        )

        shared = getattr(state, "shared", None)
        if not isinstance(shared, dict):
            return None
        creature = shared.get(CREATURE_STATE_KEY)
        if creature is None:
            return None
        meta = shared.get(SESSION_META_KEY) or {}
        try:
            return self._event_seed_pool.pick(creature, meta)
        except Exception:
            logger.debug(
                "event seed pool raised during pick — suppressing",
                exc_info=True,
            )
            return None

    # ── Internals ─────────────────────────────────────────────────────

    def _compose_cache_key(self, session_id: str, is_vtuber: bool) -> str:
        marker_static = "O" if session_id in self._static_override else "D"
        marker_char = "C" if self._character_append.get(session_id) else "_"
        marker_ctx = "X" if self._context_append.get(session_id) else "_"
        role = "V" if is_vtuber else "W"
        return f"{role}{marker_static}{marker_char}{marker_ctx}"
