"""Generic periodic tick engine.

Cycle 20260421_8 X2 PR-X2-3 — one ``asyncio.Task`` per spec with
independent interval + optional jitter. Replaces ad-hoc ``while True:
await asyncio.sleep(N)`` patterns scattered across ``thinking_trigger``
and ``_idle_monitor_loop``. See
``dev_docs/20260421_8/plan/02_tick_engine_contract.md``.

Spec migrations land in subsequent PRs (X2-4 thinking_trigger, X2-5 idle
monitor, X2-6 ws abandoned detector). This package only ships the
container.
"""

from __future__ import annotations

from .engine import TickEngine, TickHandler, TickSpec

__all__ = ["TickEngine", "TickHandler", "TickSpec"]
