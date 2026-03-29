"""
Avatar State Manager

Manages per-session avatar display state and notifies SSE subscribers
when the state changes.

Each agent session can have an associated avatar state containing:
- emotion name and expression index
- active motion group/index
- transition parameters
- trigger source (agent_output, state_change, user_interact, etc.)
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, asdict
from logging import getLogger

logger = getLogger(__name__)


@dataclass
class AvatarState:
    """Current display state of an avatar."""
    session_id: str
    emotion: str = "neutral"
    expression_index: int = 0
    motion_group: str = "Idle"
    motion_index: int = 0
    intensity: float = 1.0
    transition_ms: int = 300
    trigger: str = "system"
    timestamp: str = ""

    def to_sse_data(self) -> dict:
        """Convert to SSE-safe dictionary."""
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        return asdict(self)


class AvatarStateManager:
    """
    Manages avatar states for all active sessions
    and notifies registered SSE subscribers on state changes.
    """

    def __init__(self):
        self._states: Dict[str, AvatarState] = {}
        self._subscribers: Dict[str, List[Callable]] = {}

    def get_state(self, session_id: str) -> AvatarState:
        """Get current avatar state for a session. Creates default if missing."""
        if session_id not in self._states:
            self._states[session_id] = AvatarState(session_id=session_id)
        return self._states[session_id]

    async def update_state(
        self,
        session_id: str,
        emotion: Optional[str] = None,
        expression_index: Optional[int] = None,
        motion_group: Optional[str] = None,
        motion_index: Optional[int] = None,
        intensity: float = 1.0,
        transition_ms: int = 300,
        trigger: str = "system",
    ):
        """
        Update avatar state and notify all subscribers.

        Only changed fields are updated; others retain their previous values.
        """
        state = self.get_state(session_id)

        if emotion is not None:
            state.emotion = emotion
        if expression_index is not None:
            state.expression_index = expression_index
        if motion_group is not None:
            state.motion_group = motion_group
        if motion_index is not None:
            state.motion_index = motion_index

        state.intensity = intensity
        state.transition_ms = transition_ms
        state.trigger = trigger
        state.timestamp = datetime.now(timezone.utc).isoformat()

        await self._notify_subscribers(session_id, state)

    def subscribe(self, session_id: str, callback: Callable) -> None:
        """Register a callback to receive state change notifications."""
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        self._subscribers[session_id].append(callback)
        logger.debug(f"Avatar SSE subscriber added for session {session_id}")

    def unsubscribe(self, session_id: str, callback: Callable) -> None:
        """Remove a previously registered callback."""
        if session_id in self._subscribers:
            self._subscribers[session_id] = [
                cb for cb in self._subscribers[session_id] if cb is not callback
            ]
            logger.debug(f"Avatar SSE subscriber removed for session {session_id}")

    async def _notify_subscribers(self, session_id: str, state: AvatarState):
        """Send state update to all subscribers for a session."""
        callbacks = self._subscribers.get(session_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(state)
                else:
                    callback(state)
            except Exception as e:
                logger.warning(f"Avatar subscriber callback error: {e}")

    def cleanup_session(self, session_id: str):
        """Remove all state and subscribers for a session."""
        self._states.pop(session_id, None)
        self._subscribers.pop(session_id, None)
        logger.debug(f"Avatar state cleaned up for session {session_id}")

    def get_all_states(self) -> Dict[str, AvatarState]:
        """Return all current states (for debugging)."""
        return dict(self._states)
