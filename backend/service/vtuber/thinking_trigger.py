"""
Thinking Trigger Service
========================

Manages when the VTuber should initiate self-driven thinking —
idle reflections, scheduled check-ins, or event-driven observations.

The service runs a lightweight background loop that periodically
checks whether any VTuber session should fire a [THINKING_TRIGGER].
"""

from __future__ import annotations

import asyncio
import math
import os
import random
from datetime import datetime
from logging import getLogger
from typing import Dict, List, Optional, Set

logger = getLogger(__name__)

# Minimum idle seconds before a thinking trigger fires
_DEFAULT_IDLE_THRESHOLD = 120  # 2 minutes
# Maximum idle threshold (adaptive ceiling)
_MAX_IDLE_THRESHOLD = 3600  # 1 hour
# Number of consecutive triggers to approach max threshold (log scale)
_ADAPTIVE_SCALE_TRIGGERS = 20
# Probability of using a time-of-day prompt instead of idle-stage prompt
_TIME_PROMPT_PROBABILITY = 0.2

# ---------------------------------------------------------------------------
# Trigger Prompt Catalog
# ---------------------------------------------------------------------------
# Structure: category → locale → list of prompt variants
# Each prompt starts with [THINKING_TRIGGER] so the agent recognises it.

_TRIGGER_PROMPTS: Dict[str, Dict[str, List[str]]] = {
    # ── First idle (consecutive == 0) ─────────────────────────────────
    "first_idle": {
        "en": [
            (
                "[THINKING_TRIGGER] It's been quiet for a bit. "
                "Think about recent conversations or anything interesting "
                "you might want to share when the user returns."
            ),
            (
                "[THINKING_TRIGGER] The user seems to have stepped away. "
                "Review what you've discussed today and prepare something "
                "helpful for when they're back."
            ),
            (
                "[THINKING_TRIGGER] A moment of quiet. Reflect on recent "
                "topics — is there anything you forgot to mention or a "
                "follow-up worth sharing?"
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 잠깐 조용해졌네. "
                "최근 대화를 돌아보거나, 사용자가 돌아왔을 때 "
                "공유할 만한 걸 생각해 봐."
            ),
            (
                "[THINKING_TRIGGER] 사용자가 잠깐 자리를 비운 것 같아. "
                "오늘 나눈 이야기를 정리하고, 돌아왔을 때 "
                "도움될 만한 걸 준비해 봐."
            ),
            (
                "[THINKING_TRIGGER] 여유가 생겼네. 최근 주제 중 "
                "빠뜨린 게 있었는지, 추가로 알려줄 만한 게 있는지 "
                "생각해 봐."
            ),
        ],
    },
    # ── Continued idle (1 ≤ consecutive ≤ 3) ──────────────────────────
    "continued_idle": {
        "en": [
            (
                "[THINKING_TRIGGER] Still quiet. Maybe think of something "
                "fun or useful to share — a tip, an observation, or just "
                "a friendly thought."
            ),
            (
                "[THINKING_TRIGGER] The user hasn't returned yet. Consider "
                "reviewing your memory for any pending items or interesting "
                "follow-ups."
            ),
            (
                "[THINKING_TRIGGER] Quiet time continues. If there's "
                "something lighthearted or encouraging you'd like to say, "
                "now's a good moment."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 아직 조용하네. 재미있는 팁이나 관찰, "
                "또는 따뜻한 한마디를 준비해 볼까?"
            ),
            (
                "[THINKING_TRIGGER] 사용자가 아직 안 돌아왔어. "
                "기억 속에 미처 전하지 못한 이야기가 있는지 확인해 봐."
            ),
            (
                "[THINKING_TRIGGER] 조용한 시간이 계속되고 있어. "
                "가벼운 이야기나 응원의 한마디를 건네고 싶다면 "
                "지금이 좋은 타이밍이야."
            ),
        ],
    },
    # ── Long idle (consecutive ≥ 4) ───────────────────────────────────
    "long_idle": {
        "en": [
            (
                "[THINKING_TRIGGER] It's been a while since the user was "
                "active. Keep a brief, warm thought ready — no need to be "
                "chatty."
            ),
            (
                "[THINKING_TRIGGER] Extended quiet time. Just stay ready "
                "with a gentle greeting for when the user returns. "
                "Keep it short and natural."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 사용자가 꽤 오래 자리를 비웠어. "
                "짧고 따뜻한 인사를 준비해 두면 돼. 길게 말할 필요 없어."
            ),
            (
                "[THINKING_TRIGGER] 오랫동안 조용하네. 돌아왔을 때 "
                "자연스럽게 반겨줄 준비만 해 두자. 간단하게."
            ),
        ],
    },
    # ── CLI agent is working ──────────────────────────────────────────
    "cli_working": {
        "en": [
            (
                "[THINKING_TRIGGER] The CLI agent is currently working on "
                "a task. Prepare to summarize the results clearly when "
                "it's done."
            ),
            (
                "[THINKING_TRIGGER] A task is being processed by the CLI "
                "agent right now. Think about how to present the results "
                "to the user when ready."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] CLI 에이전트가 지금 작업 중이야. "
                "작업이 끝나면 결과를 깔끔하게 정리해서 전달할 준비를 해 둬."
            ),
            (
                "[THINKING_TRIGGER] 지금 CLI 쪽에서 작업이 진행되고 있어. "
                "완료되면 사용자에게 어떻게 알려줄지 생각해 봐."
            ),
        ],
    },
    # ── Time-of-day prompts ───────────────────────────────────────────
    "time_morning": {
        "en": [
            (
                "[THINKING_TRIGGER] It's morning. If the user shows up, "
                "a fresh greeting and maybe a plan for the day could be "
                "nice."
            ),
            (
                "[THINKING_TRIGGER] Good morning hours. Think about what "
                "might be on the user's agenda today and how you can help."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 아침이야. 사용자가 오면 "
                "상쾌한 인사와 함께 오늘 계획을 이야기해 보면 좋겠다."
            ),
            (
                "[THINKING_TRIGGER] 좋은 아침 시간이야. 오늘 사용자에게 "
                "도움이 될 만한 게 뭐가 있을지 생각해 봐."
            ),
        ],
    },
    "time_afternoon": {
        "en": [
            (
                "[THINKING_TRIGGER] It's afternoon — a good time to think "
                "about what's been accomplished today or what's coming up."
            ),
            (
                "[THINKING_TRIGGER] Afternoon already. Consider if there's "
                "anything from earlier conversations you could follow up on."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 오후야. 오늘 뭘 했는지 돌아보거나, "
                "앞으로 할 일을 정리해 볼 시간이야."
            ),
            (
                "[THINKING_TRIGGER] 벌써 오후네. 오전에 나눈 대화 중 "
                "이어갈 만한 이야기가 있는지 생각해 봐."
            ),
        ],
    },
    "time_evening": {
        "en": [
            (
                "[THINKING_TRIGGER] Evening time. Reflect on the day's "
                "conversations and think about wrapping things up warmly."
            ),
            (
                "[THINKING_TRIGGER] The evening is here. If the user "
                "returns, a warm wrap-up or a kind word would be nice."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 저녁 시간이야. 오늘 대화를 되돌아보고 "
                "부드럽게 마무리할 준비를 해 봐."
            ),
            (
                "[THINKING_TRIGGER] 저녁이 됐네. 사용자가 돌아오면 "
                "따뜻한 마무리 인사나 한마디를 건네면 좋겠다."
            ),
        ],
    },
    "time_night": {
        "en": [
            (
                "[THINKING_TRIGGER] It's getting late. If the user is still "
                "here, a gentle check-in would be thoughtful. Keep it brief."
            ),
            (
                "[THINKING_TRIGGER] Late night. Keep things calm and short. "
                "A quiet, caring thought is enough."
            ),
        ],
        "ko": [
            (
                "[THINKING_TRIGGER] 늦은 시간이야. 사용자가 아직 있다면 "
                "가볍게 안부를 물어보는 게 좋겠어. 짧게."
            ),
            (
                "[THINKING_TRIGGER] 밤이 깊었네. 차분하고 간단하게. "
                "조용한 배려의 한마디면 충분해."
            ),
        ],
    },
}


class ThinkingTriggerService:
    """Background service that fires [THINKING_TRIGGER] for idle VTuber sessions."""

    def __init__(
        self,
        idle_threshold: float = _DEFAULT_IDLE_THRESHOLD,
        max_idle_threshold: float = _MAX_IDLE_THRESHOLD,
    ) -> None:
        self._base_threshold = idle_threshold
        self._max_threshold = max_idle_threshold
        self._task: Optional[asyncio.Task] = None
        self._stopped = False
        # session_id → last_activity_epoch  (updated externally)
        self._activity: Dict[str, float] = {}
        # Sessions explicitly disabled by user
        self._disabled_sessions: Set[str] = set()
        # session_id → consecutive trigger count (resets on user activity)
        self._consecutive_triggers: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling loop."""
        if self._task is not None:
            return
        self._stopped = False
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "ThinkingTriggerService started (base=%ss, max=%ss)",
            self._base_threshold, self._max_threshold,
        )

    def stop(self) -> None:
        """Stop the background loop gracefully."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None
        self._activity.clear()
        self._disabled_sessions.clear()
        self._consecutive_triggers.clear()
        logger.info("ThinkingTriggerService stopped")

    # ------------------------------------------------------------------
    # External hooks (called by other components)
    # ------------------------------------------------------------------

    def record_activity(self, session_id: str) -> None:
        """Record that a VTuber session just had user interaction."""
        import time
        self._activity[session_id] = time.time()
        # User activity resets adaptive frequency back to base
        self._consecutive_triggers.pop(session_id, None)

    def unregister(self, session_id: str) -> None:
        """Remove a session from tracking (e.g. on deletion)."""
        self._activity.pop(session_id, None)
        self._disabled_sessions.discard(session_id)
        self._consecutive_triggers.pop(session_id, None)

    def enable(self, session_id: str) -> None:
        """Enable thinking trigger for a session."""
        self._disabled_sessions.discard(session_id)
        logger.info("ThinkingTrigger enabled for %s", session_id)

    def disable(self, session_id: str) -> None:
        """Disable thinking trigger for a session."""
        self._disabled_sessions.add(session_id)
        logger.info("ThinkingTrigger disabled for %s", session_id)

    def is_enabled(self, session_id: str) -> bool:
        """Check if thinking trigger is enabled for a session."""
        return session_id not in self._disabled_sessions

    def get_status(self, session_id: str) -> dict:
        """Return thinking trigger status for a session."""
        return {
            "enabled": self.is_enabled(session_id),
            "registered": session_id in self._activity,
            "consecutive_triggers": self._consecutive_triggers.get(session_id, 0),
            "current_threshold_seconds": round(self._get_adaptive_threshold(session_id), 1),
            "base_threshold_seconds": self._base_threshold,
            "max_threshold_seconds": self._max_threshold,
        }

    def _get_adaptive_threshold(self, session_id: str) -> float:
        """Calculate adaptive idle threshold using log scale.

        Grows from base (120s) toward max (3600s / 1hr) as consecutive
        triggers accumulate without user interaction.
        """
        count = self._consecutive_triggers.get(session_id, 0)
        if count <= 0:
            return self._base_threshold
        scale = math.log1p(count) / math.log1p(_ADAPTIVE_SCALE_TRIGGERS)
        scale = min(scale, 1.0)
        return self._base_threshold + (self._max_threshold - self._base_threshold) * scale

    # ------------------------------------------------------------------
    # Background loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Poll every 30s and fire triggers for idle VTuber sessions."""
        import time

        while not self._stopped:
            try:
                await asyncio.sleep(30)
                now = time.time()

                for sid, last in list(self._activity.items()):
                    # Skip disabled sessions
                    if sid in self._disabled_sessions:
                        continue

                    idle = now - last
                    threshold = self._get_adaptive_threshold(sid)
                    if idle < threshold:
                        continue

                    # Fire a thinking trigger
                    await self._fire_trigger(sid)
                    # Reset to avoid immediate re-fire
                    self._activity[sid] = now

            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("ThinkingTrigger loop error", exc_info=True)

    async def _fire_trigger(self, session_id: str) -> None:
        """Send a context-aware [THINKING_TRIGGER] to the VTuber session.

        If the session has a chat_room_id, the response is also saved
        to the chat room so it appears in the VTuber chat panel in real-time.
        """
        try:
            from service.execution.agent_executor import (
                AlreadyExecutingError,
                AgentNotAliveError,
                AgentNotFoundError,
                execute_command,
                is_executing,
            )

            # Check if the linked CLI worker is busy
            prompt = self._build_trigger_prompt(session_id, is_executing)
            # Extract category for logging (prompt always starts with [THINKING_TRIGGER])
            prompt_preview = prompt[20:60].strip().replace("\n", " ")

            result = await execute_command(session_id, prompt)

            # Increment consecutive count (drives adaptive backoff)
            self._consecutive_triggers[session_id] = (
                self._consecutive_triggers.get(session_id, 0) + 1
            )

            # Save response to chat room (if available)
            if result.success and result.output and result.output.strip():
                self._save_to_chat_room(session_id, result)
                logger.info(
                    "Thinking trigger fired for %s (output=%d chars, consecutive=%d, "
                    "next_threshold=%.0fs, locale=%s, prompt='%s')",
                    session_id, len(result.output),
                    self._consecutive_triggers.get(session_id, 0),
                    self._get_adaptive_threshold(session_id),
                    self._get_locale(), prompt_preview,
                )
            else:
                logger.info(
                    "Thinking trigger fired for %s (success=%s, output_len=%s, "
                    "consecutive=%d, prompt='%s')",
                    session_id, result.success,
                    len(result.output) if result.output else 0,
                    self._consecutive_triggers.get(session_id, 0),
                    prompt_preview,
                )

        except AlreadyExecutingError:
            logger.debug("Thinking trigger skipped (busy): %s", session_id)
        except AgentNotFoundError:
            # Session deleted — permanently stop tracking
            logger.debug("Thinking trigger: session gone, unregistering %s", session_id)
            self.unregister(session_id)
        except AgentNotAliveError:
            # Process dead but session exists — back off, will retry next cycle
            # (auto-revival may succeed later; adaptive backoff limits frequency)
            logger.debug("Thinking trigger skipped (not alive, will retry): %s", session_id)
            self._consecutive_triggers[session_id] = (
                self._consecutive_triggers.get(session_id, 0) + 1
            )
        except Exception:
            logger.debug("Thinking trigger failed for %s", session_id, exc_info=True)
            self._consecutive_triggers[session_id] = (
                self._consecutive_triggers.get(session_id, 0) + 1
            )

    def _save_to_chat_room(self, session_id: str, result) -> None:
        """Persist the trigger response to the session's chat room.

        Also notifies SSE listeners so the VTuber chat panel updates live.
        """
        try:
            from service.langgraph import get_agent_session_manager
            agent = get_agent_session_manager().get_agent(session_id)
            if not agent:
                logger.warning("[ThinkingTrigger] No agent found for %s, skipping chat save", session_id)
                return

            chat_room_id = getattr(agent, '_chat_room_id', None)
            if not chat_room_id:
                logger.warning("[ThinkingTrigger] No chat_room_id on agent %s, skipping chat save", session_id)
                return

            from service.chat.conversation_store import get_chat_store
            store = get_chat_store()

            session_name = getattr(agent, '_session_name', None) or session_id
            role_val = getattr(agent, '_role', None)
            role = role_val.value if hasattr(role_val, 'value') else str(role_val or 'vtuber')

            msg = store.add_message(chat_room_id, {
                "type": "agent",
                "content": result.output.strip(),
                "session_id": session_id,
                "session_name": session_name,
                "role": role,
                "duration_ms": result.duration_ms,
                "cost_usd": result.cost_usd,
            })

            logger.info(
                "[ThinkingTrigger] Saved response to chat room %s (msg_id=%s, len=%d)",
                chat_room_id, msg.get("id", "?"), len(result.output),
            )

            # Notify SSE listeners
            try:
                from controller.chat_controller import _notify_room
                _notify_room(chat_room_id)
            except Exception:
                logger.warning("[ThinkingTrigger] _notify_room failed for %s", chat_room_id, exc_info=True)

        except Exception:
            logger.warning("[ThinkingTrigger] Failed to save trigger response to chat room", exc_info=True)

    def _build_trigger_prompt(self, session_id: str, is_executing_fn) -> str:
        """Select a context-aware, locale-aware trigger prompt.

        Selection priority:
        1. CLI agent working → ``cli_working``
        2. Time-of-day prompt (20 % chance) → ``time_*``
        3. Idle-stage prompt → ``first_idle`` / ``continued_idle`` / ``long_idle``

        The locale is determined by the ``GENY_LANGUAGE`` env var (default: en).
        """
        locale = self._get_locale()

        # 1. CLI working — highest priority
        try:
            from service.langgraph import get_agent_session_manager
            agent = get_agent_session_manager().get_agent(session_id)
            if agent:
                linked_id = getattr(agent, 'linked_session_id', None)
                if linked_id and is_executing_fn(linked_id):
                    return self._pick("cli_working", locale)
        except Exception:
            pass

        # 2. Determine idle stage
        count = self._consecutive_triggers.get(session_id, 0)
        if count <= 0:
            idle_category = "first_idle"
        elif count <= 3:
            idle_category = "continued_idle"
        else:
            idle_category = "long_idle"

        # 3. Time-of-day prompt (mixed in with some probability)
        if random.random() < _TIME_PROMPT_PROBABILITY:
            time_cat = self._get_time_category()
            return self._pick(time_cat, locale)

        return self._pick(idle_category, locale)

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_locale() -> str:
        """Return the current system locale (en or ko)."""
        lang = os.environ.get("GENY_LANGUAGE", "en")
        return lang if lang in ("en", "ko") else "en"

    @staticmethod
    def _get_time_category() -> str:
        """Return a time-of-day category based on the configured timezone hour."""
        from service.utils.utils import now_kst
        hour = now_kst().hour
        if 6 <= hour < 12:
            return "time_morning"
        if 12 <= hour < 18:
            return "time_afternoon"
        if 18 <= hour < 22:
            return "time_evening"
        return "time_night"

    @staticmethod
    def _pick(category: str, locale: str) -> str:
        """Pick a random prompt from the given category and locale."""
        prompts_by_locale = _TRIGGER_PROMPTS.get(category, {})
        prompts = prompts_by_locale.get(locale) or prompts_by_locale.get("en", [])
        if not prompts:
            return "[THINKING_TRIGGER] Reflect on recent conversations."
        return random.choice(prompts)


# ============================================================================
# Module-level singleton
# ============================================================================

_instance: Optional[ThinkingTriggerService] = None


def get_thinking_trigger_service() -> ThinkingTriggerService:
    """Get or create the singleton ThinkingTriggerService."""
    global _instance
    if _instance is None:
        _instance = ThinkingTriggerService()
    return _instance
