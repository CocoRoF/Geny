"""TickEngine contract tests (plan/02 §2–§3).

Uses short real intervals (ms-scale) rather than a fake clock. This
keeps the tests honest — they exercise the real ``asyncio.sleep`` path
that production uses — and every test finishes well under 500 ms.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import pytest

from backend.service.tick import TickEngine, TickSpec


async def _noop() -> None:
    return None


def _make_counter_handler() -> tuple[list[float], "object"]:
    calls: list[float] = []

    async def handler() -> None:
        calls.append(time.monotonic())

    return calls, handler


# -- TickSpec validation ----------------------------------------------------


def test_tickspec_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        TickSpec(name="", interval=1.0, handler=_noop)


def test_tickspec_rejects_interval_below_floor() -> None:
    with pytest.raises(ValueError, match="interval"):
        TickSpec(name="t", interval=0.05, handler=_noop)


def test_tickspec_rejects_negative_jitter() -> None:
    with pytest.raises(ValueError, match="jitter"):
        TickSpec(name="t", interval=1.0, handler=_noop, jitter=-0.1)


def test_tickspec_rejects_jitter_ge_interval() -> None:
    with pytest.raises(ValueError, match="jitter"):
        TickSpec(name="t", interval=1.0, handler=_noop, jitter=1.0)


def test_tickspec_rejects_sync_handler() -> None:
    def sync_handler() -> None:  # type: ignore[return]
        pass

    with pytest.raises(TypeError, match="async"):
        TickSpec(name="t", interval=1.0, handler=sync_handler)  # type: ignore[arg-type]


# -- core behaviour ---------------------------------------------------------


@pytest.mark.asyncio
async def test_spec_fires_at_interval() -> None:
    calls, handler = _make_counter_handler()
    engine = TickEngine()
    engine.register(TickSpec(name="t", interval=0.1, handler=handler))
    await engine.start()
    await asyncio.sleep(0.55)
    await engine.stop()

    # interval=0.1s over 0.55s → expect ~5 ticks, accept 3–6 for scheduler slack.
    assert 3 <= len(calls) <= 6, f"unexpected tick count: {len(calls)}"


@pytest.mark.asyncio
async def test_run_on_start_fires_immediately() -> None:
    calls, handler = _make_counter_handler()
    engine = TickEngine()
    engine.register(
        TickSpec(name="t", interval=1.0, handler=handler, run_on_start=True)
    )
    await engine.start()
    # run_on_start should have already awaited one handler before returning
    # to the scheduler, but give the task one tick to register.
    await asyncio.sleep(0.05)
    await engine.stop()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_handler_exception_does_not_kill_loop() -> None:
    calls: list[int] = []

    async def handler() -> None:
        calls.append(1)
        raise RuntimeError("boom")

    engine = TickEngine()
    engine.register(TickSpec(name="t", interval=0.1, handler=handler))
    await engine.start()
    await asyncio.sleep(0.35)
    await engine.stop()
    # Despite every tick raising, the loop must keep scheduling.
    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_overrun_does_not_overlap_handler() -> None:
    in_flight: list[bool] = []
    max_concurrent = [0]

    async def handler() -> None:
        in_flight.append(True)
        max_concurrent[0] = max(max_concurrent[0], len(in_flight))
        # Overrun: handler takes 3× the interval.
        await asyncio.sleep(0.3)
        in_flight.pop()

    engine = TickEngine()
    engine.register(TickSpec(name="t", interval=0.1, handler=handler))
    await engine.start()
    await asyncio.sleep(0.5)
    await engine.stop(timeout=1.0)

    # Single in-flight guarantee: never > 1 concurrent invocation for the same spec.
    assert max_concurrent[0] == 1


@pytest.mark.asyncio
async def test_independent_specs_run_concurrently() -> None:
    a_calls, a = _make_counter_handler()

    async def b_handler() -> None:
        # b deliberately blocks — must not delay a.
        await asyncio.sleep(10.0)

    engine = TickEngine()
    engine.register(TickSpec(name="a", interval=0.1, handler=a))
    engine.register(TickSpec(name="b", interval=0.1, handler=b_handler))
    await engine.start()
    await asyncio.sleep(0.35)
    await engine.stop(timeout=0.5)
    # b was parked in sleep(10) but a kept ticking.
    assert len(a_calls) >= 2


@pytest.mark.asyncio
async def test_register_after_start_schedules_immediately() -> None:
    engine = TickEngine()
    await engine.start()
    calls, handler = _make_counter_handler()
    engine.register(TickSpec(name="late", interval=0.1, handler=handler))
    await asyncio.sleep(0.25)
    await engine.stop()
    assert len(calls) >= 1


@pytest.mark.asyncio
async def test_unregister_cancels_running_task() -> None:
    calls, handler = _make_counter_handler()
    engine = TickEngine()
    engine.register(TickSpec(name="t", interval=0.1, handler=handler))
    await engine.start()
    await asyncio.sleep(0.15)
    engine.unregister("t")
    before = len(calls)
    await asyncio.sleep(0.3)
    await engine.stop()
    # After unregister, count must not keep climbing meaningfully.
    assert len(calls) <= before + 1
    assert "t" not in engine.specs()


@pytest.mark.asyncio
async def test_unregister_unknown_is_noop() -> None:
    engine = TickEngine()
    engine.unregister("missing")  # must not raise


def test_register_duplicate_name_raises() -> None:
    engine = TickEngine()
    engine.register(TickSpec(name="t", interval=1.0, handler=_noop))
    with pytest.raises(ValueError, match="already"):
        engine.register(TickSpec(name="t", interval=1.0, handler=_noop))


@pytest.mark.asyncio
async def test_stop_is_idempotent() -> None:
    engine = TickEngine()
    await engine.start()
    await engine.stop()
    await engine.stop()
    assert not engine.is_running()


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    engine = TickEngine()
    calls, handler = _make_counter_handler()
    engine.register(TickSpec(name="t", interval=0.1, handler=handler))
    await engine.start()
    await engine.start()  # second start must not spawn a duplicate task
    await asyncio.sleep(0.25)
    await engine.stop()
    # Only one task → bounded count. If two tasks had been spawned we'd see
    # roughly 2× the tick count.
    assert len(calls) <= 4


@pytest.mark.asyncio
async def test_specs_returns_snapshot() -> None:
    engine = TickEngine()
    spec = TickSpec(name="t", interval=1.0, handler=_noop)
    engine.register(spec)
    snap = engine.specs()
    assert snap == {"t": spec}
    # Mutating the snapshot must not touch the engine.
    snap.clear()  # type: ignore[attr-defined]
    assert "t" in engine.specs()


@pytest.mark.asyncio
async def test_metric_hook_called_with_duration() -> None:
    engine = TickEngine()
    captured: list[tuple[str, float]] = []

    def _hook(name: str, duration_ms: float) -> None:
        captured.append((name, duration_ms))

    engine._on_tick_complete = _hook  # type: ignore[assignment]

    async def handler() -> None:
        await asyncio.sleep(0.02)

    engine.register(TickSpec(name="m", interval=0.1, handler=handler))
    await engine.start()
    await asyncio.sleep(0.35)
    await engine.stop()

    assert captured, "metric hook was never invoked"
    names = {n for n, _ in captured}
    assert names == {"m"}
    # The final tick may be cancelled by stop() mid-sleep; check that at
    # least one complete tick recorded the real ~20ms handler duration.
    assert any(d >= 15.0 for _, d in captured), captured


@pytest.mark.asyncio
async def test_jitter_produces_variance_in_sleep() -> None:
    # We can't observe internal sleep directly; observe call timestamps
    # and check that inter-call gaps have nonzero variance.
    calls, handler = _make_counter_handler()
    engine = TickEngine()
    engine.register(
        TickSpec(name="j", interval=0.1, handler=handler, jitter=0.05)
    )
    await engine.start()
    await asyncio.sleep(0.9)
    await engine.stop()

    assert len(calls) >= 4
    gaps = [b - a for a, b in zip(calls, calls[1:])]
    # With jitter=50ms over interval=100ms, stdev should be > 5ms.
    assert statistics.stdev(gaps) > 0.005, gaps
