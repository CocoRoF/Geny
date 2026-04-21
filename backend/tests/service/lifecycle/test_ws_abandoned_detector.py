"""WSAbandonedDetector contract (cycle 20260421_8 PR-X2-6).

The detector bridges WS connect/disconnect (transport-level) to the
``SESSION_ABANDONED`` lifecycle event by waiting for a configurable
threshold before emitting. These tests drive it by monkey-patching
``time.time`` so we don't sleep — the detector uses wall-clock epoch,
not event-loop time.
"""

from __future__ import annotations

from typing import List

import pytest

from backend.service.lifecycle import (
    LifecycleEvent,
    LifecyclePayload,
    SessionLifecycleBus,
    WSAbandonedDetector,
)


def _make_recorder(bus: SessionLifecycleBus) -> List[LifecyclePayload]:
    events: List[LifecyclePayload] = []

    async def handler(payload: LifecyclePayload) -> None:
        events.append(payload)

    bus.subscribe(LifecycleEvent.SESSION_ABANDONED, handler)
    return events


# -- basic tracker state ----------------------------------------------------


def test_is_connected_reflects_connect_disconnect() -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    assert not det.is_connected("sid")
    det.connect("sid")
    assert det.is_connected("sid")
    det.disconnect("sid")
    assert not det.is_connected("sid")


def test_multiple_ws_keeps_session_connected() -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    det.connect("sid")
    det.connect("sid")  # second WS on same session
    det.disconnect("sid")
    assert det.is_connected("sid")  # still one active
    assert det.pending_count() == 0
    det.disconnect("sid")
    assert not det.is_connected("sid")
    assert det.pending_count() == 1


def test_reconnect_cancels_pending_abandoned(monkeypatch) -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    det.connect("sid")
    det.disconnect("sid")
    assert det.pending_count() == 1
    det.connect("sid")
    assert det.pending_count() == 0


def test_threshold_must_be_positive() -> None:
    bus = SessionLifecycleBus()
    with pytest.raises(ValueError):
        WSAbandonedDetector(bus, threshold_seconds=0)
    with pytest.raises(ValueError):
        WSAbandonedDetector(bus, threshold_seconds=-1)


# -- scan emission ----------------------------------------------------------


@pytest.mark.asyncio
async def test_scan_no_pending_is_noop() -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    events = _make_recorder(bus)
    await det.scan()
    assert events == []


@pytest.mark.asyncio
async def test_scan_skips_sessions_within_threshold(monkeypatch) -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    events = _make_recorder(bus)

    # Simulate disconnect at t=1000, scan at t=1030 — only 30s gap.
    import backend.service.lifecycle.ws_abandoned_detector as mod

    t = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: t[0])

    det.connect("sid")
    det.disconnect("sid")
    t[0] = 1030.0
    await det.scan()
    assert events == []
    assert det.pending_count() == 1  # still pending


@pytest.mark.asyncio
async def test_scan_emits_after_threshold(monkeypatch) -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    events = _make_recorder(bus)

    import backend.service.lifecycle.ws_abandoned_detector as mod

    t = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: t[0])

    det.connect("sid")
    det.disconnect("sid")
    t[0] = 1061.0  # 61s since disconnect — past threshold
    await det.scan()

    assert len(events) == 1
    p = events[0]
    assert p.event is LifecycleEvent.SESSION_ABANDONED
    assert p.session_id == "sid"
    assert p.meta["disconnect_gap_seconds"] == pytest.approx(61.0)
    assert p.meta["threshold_seconds"] == 60.0
    # Episode cleared — a second scan at the same time must not re-emit.
    assert det.pending_count() == 0
    await det.scan()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_reconnect_after_emit_starts_fresh_episode(monkeypatch) -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    events = _make_recorder(bus)

    import backend.service.lifecycle.ws_abandoned_detector as mod

    t = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: t[0])

    det.connect("sid")
    det.disconnect("sid")
    t[0] = 1100.0
    await det.scan()
    assert len(events) == 1

    # User comes back, reconnects, then drops again → new episode.
    det.connect("sid")
    det.disconnect("sid")
    assert det.pending_count() == 1
    t[0] = 1200.0  # 100s after second disconnect at t=1100
    await det.scan()
    assert len(events) == 2


@pytest.mark.asyncio
async def test_scan_multiple_sessions(monkeypatch) -> None:
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    events = _make_recorder(bus)

    import backend.service.lifecycle.ws_abandoned_detector as mod

    t = [1000.0]
    monkeypatch.setattr(mod.time, "time", lambda: t[0])

    det.connect("a")
    det.connect("b")
    det.connect("c")
    det.disconnect("a")  # disconnect_ts=1000
    t[0] = 1050.0
    det.disconnect("b")  # disconnect_ts=1050
    t[0] = 1070.0
    det.disconnect("c")  # disconnect_ts=1070

    t[0] = 1125.0
    # Gaps: a=125s (>60), b=75s (>60), c=55s (<60)
    await det.scan()
    fired = {p.session_id for p in events}
    assert fired == {"a", "b"}
    assert det.pending_count() == 1  # c still pending


def test_unbalanced_disconnect_is_tolerated() -> None:
    """Disconnect without prior connect — count goes to 0, session enters pending."""
    bus = SessionLifecycleBus()
    det = WSAbandonedDetector(bus, threshold_seconds=60)
    det.disconnect("stray")
    assert not det.is_connected("stray")
    # Because we track ``active - 1 <= 0 → pending``, a bare disconnect
    # records a pending episode. This is intentional and harmless:
    # worst case the detector fires SESSION_ABANDONED once for a session
    # that wasn't really being watched.
    assert det.pending_count() == 1
