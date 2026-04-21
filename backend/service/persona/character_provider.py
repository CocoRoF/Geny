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
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from geny_executor.stages.s03_system.artifact.default.builders import PersonaBlock

from backend.service.persona.provider import PersonaResolution

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
    ):
        self._characters_dir = Path(characters_dir)
        self._default_vtuber = default_vtuber_prompt
        self._default_worker = default_worker_prompt
        self._adaptive = adaptive_prompt

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

        persona_text = "\n\n".join(p for p in parts if p)
        cache_key = self._compose_cache_key(session_id, is_vtuber)
        return PersonaResolution(
            persona_blocks=[PersonaBlock(persona_text)],
            cache_key=cache_key,
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _compose_cache_key(self, session_id: str, is_vtuber: bool) -> str:
        marker_static = "O" if session_id in self._static_override else "D"
        marker_char = "C" if self._character_append.get(session_id) else "_"
        marker_ctx = "X" if self._context_append.get(session_id) else "_"
        role = "V" if is_vtuber else "W"
        return f"{role}{marker_static}{marker_char}{marker_ctx}"
