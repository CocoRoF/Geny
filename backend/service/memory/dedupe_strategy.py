"""``GenyDedupeStrategy`` — provider-driven, metadata-aware Stage 18 strategy.

Wraps the executor's ``ProviderDrivenStrategy`` (1.20.0+) with one
piece of Geny-specific behaviour: stamp the next user / assistant
message with the ``_pending_message_metadata`` hint pushed by
``AgentSession._invoke_pipeline`` so the executor's
``Turn.from_state_message`` lifts the InteractionEvent dimensions
onto ``Turn.metadata`` (and the typed interaction fields landed in
1.20.0 — ``event_id``, ``kind``, ``direction``, etc.).

Behaviour mirrors the legacy version: the *first* same-role message
in a batch gets the verbatim hint; *subsequent* same-role messages
in the same batch derive a fresh ``event_id`` from the same template
so a single VTuber turn that emits multiple assistant messages
doesn't share one event id across them.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from geny_executor.core.state import PipelineState
from geny_executor.memory.strategy import STM_RECORDED_KEY, ProviderDrivenStrategy

logger = logging.getLogger(__name__)


_PENDING_KEY = "_pending_message_metadata"


class GenyDedupeStrategy(ProviderDrivenStrategy):
    """Pre-stamp ``state.messages`` with InteractionEvent metadata
    before the executor's per-turn record fan-out runs.

    The parent ``ProviderDrivenStrategy.update`` walks the new tail of
    ``state.messages`` and forwards each entry to ``provider.record_turn``.
    ``Turn.from_state_message`` lifts top-level keys + ``metadata`` onto
    the typed interaction surface (1.20.0). This subclass guarantees
    those fields are present by stamping ``msg["metadata"]`` ahead of
    the parent walk.
    """

    @property
    def name(self) -> str:
        return "geny_dedupe"

    @property
    def description(self) -> str:
        return "Provider-driven STM record + InteractionEvent metadata stamping"

    async def update(self, state: PipelineState) -> None:
        self._stamp_pending_metadata(state)
        await super().update(state)

    # ── stamping ────────────────────────────────────────────────────

    def _stamp_pending_metadata(self, state: PipelineState) -> None:
        """Apply ``_pending_message_metadata`` to the next user /
        assistant entry in the un-recorded tail of ``state.messages``.
        """
        pending = state.metadata.get(_PENDING_KEY) or {}
        if not pending:
            return
        # The executor's own record watermark (one key since 2.74.1): the
        # un-recorded tail is exactly what the parent is about to record,
        # and it is the key compaction translates. Geny used to keep a
        # second cursor here, which a compaction left pointing past the end
        # of the shortened history — nothing got stamped after it.
        recorded_count = int(state.metadata.get(STM_RECORDED_KEY, 0) or 0)
        new_messages = state.messages[recorded_count:]

        applied = {"user": False, "assistant": False}
        for msg in new_messages:
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [
                    str(b.get("text", ""))
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(p for p in text_parts if p)
            if not content:
                continue

            hint = pending.get(role)
            metadata: Optional[Dict[str, Any]] = None
            if isinstance(hint, dict) and hint:
                metadata = hint if not applied[role] else _fresh_from_template(hint)
            applied[role] = True

            if metadata and isinstance(msg, dict) and "metadata" not in msg:
                # Mutate in place — the executor's ``Turn.from_state_message``
                # picks ``message["metadata"]`` up and lifts the typed
                # interaction fields onto the resulting Turn.
                msg["metadata"] = dict(metadata)

        # No cursor of our own: the parent advances the shared watermark
        # right after this, and a message that already carries metadata is
        # never stamped twice (see the ``"metadata" not in msg`` check).


def _fresh_from_template(hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a new InteractionEvent metadata dict using *hint* as a
    template (same kind / direction / counterpart_*) but a fresh
    ``event_id``. Returns ``None`` if anything goes wrong — caller
    falls through to the verbatim hint.
    """
    try:
        from service.memory.interaction_event import (
            CounterpartRole,
            Direction,
            Kind,
            make_event_metadata,
        )

        kind_v = hint.get("kind")
        direction_v = hint.get("direction")
        cp_role = hint.get("counterpart_role")

        kind = Kind(kind_v) if kind_v else None
        direction = Direction(direction_v) if direction_v else None
        counterpart_role = CounterpartRole(cp_role) if cp_role else None
        # make_event_metadata requires all three; a hint missing any of them
        # cannot describe an event. Checking here rather than letting the
        # required-argument violation surface as an AttributeError inside the
        # blanket except below, where it reads as an unknown failure.
        if kind is None or direction is None or counterpart_role is None:
            return None

        return make_event_metadata(
            kind=kind,
            direction=direction,
            counterpart_id=hint.get("counterpart_id"),
            counterpart_role=counterpart_role,
            linked_event_id=hint.get("linked_event_id"),
            payload=hint.get("payload"),
        )
    except Exception:  # noqa: BLE001
        logger.debug(
            "GenyDedupeStrategy: _fresh_from_template failed", exc_info=True
        )
        return None


__all__ = ["GenyDedupeStrategy"]
