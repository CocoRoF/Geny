"""Session lifecycle event bus.

Cycle 20260421_8 X2 PR-X2-1 — pub/sub rail for the 7 canonical session
lifecycle events (see ``dev_docs/20260421_8/plan/01_bus_contract.md``).

This package only provides the container. Wiring existing call sites
(``AgentSessionManager.create_agent_session``, ``mark_idle``, the restore
endpoint, etc.) to emit through the bus is PR-X2-2.
"""

from __future__ import annotations

from .events import LifecycleEvent, LifecyclePayload
from .bus import Handler, SessionLifecycleBus, SubscriptionToken
from .ws_abandoned_detector import WSAbandonedDetector

__all__ = [
    "Handler",
    "LifecycleEvent",
    "LifecyclePayload",
    "SessionLifecycleBus",
    "SubscriptionToken",
    "WSAbandonedDetector",
]
