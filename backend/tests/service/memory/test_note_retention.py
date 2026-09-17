"""Bounding what the agent writes to itself — effect-proving tests.

The observation trigger writes a note every couple of minutes forever: 757
in one production day, 6,180 in total, and nothing ever removed any of it.
Without a ceiling, every indexing improvement is a delay rather than a fix.

Deletion is one-way, so most of these tests are about what must SURVIVE.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from service.memory import note_retention as nr

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def _meta(filename, *, category="observations", days_old=0, importance="low", now=NOW):
    """A note ``days_old`` days before *now*.

    ``now`` defaults to the fixed ``NOW`` the pure-function tests pin. Tests
    that go through the manager must pass the real clock instead — the sweep
    reads ``datetime.now()`` and cannot be told otherwise.
    """
    return SimpleNamespace(
        ref=SimpleNamespace(filename=filename, category=category),
        updated_at=now - timedelta(days=days_old),
        importance=importance,
    )


def _names(expired):
    return [e.filename for e in expired]


def test_old_autonomous_notes_are_selected():
    metas = [_meta("old.md", days_old=60), _meta("fresh.md", days_old=1)]
    assert _names(nr.select_expired(metas, now=NOW, days=30)) == ["old.md"]


def test_a_note_exactly_at_the_boundary_survives():
    """Off-by-one here silently deletes a day's worth every sweep."""
    metas = [_meta("edge.md", days_old=30)]
    assert nr.select_expired(metas, now=NOW, days=30) == []


def test_critical_notes_are_never_deleted():
    """The user's own never-forget marker. Age says nothing about it, and
    getting this wrong is unrecoverable."""
    metas = [_meta("keep.md", days_old=999, importance="critical")]
    assert nr.select_expired(metas, now=NOW, days=30) == []


def test_digests_and_ledgers_are_never_deleted():
    """`__`-prefixed files are the SUMMARY of what is being pruned; they
    have to outlive it."""
    metas = [
        _meta("__digest_2026-01-01__.md", days_old=999),
        _meta("__ledger__.md", category="daily", days_old=999),
    ]
    assert nr.select_expired(metas, now=NOW, days=30) == []


def test_human_categories_are_not_on_a_timer():
    """Conversations and hand-written notes are the record of what actually
    happened between the user and the agent."""
    metas = [
        _meta("chat.md", category="conversations", days_old=999),
        _meta("mine.md", category="note", days_old=999),
        _meta("must.md", category="critical", days_old=999),
        _meta("mem.md", category="memory", days_old=999),
    ]
    assert nr.select_expired(metas, now=NOW, days=30) == []


def test_daily_execution_records_are_included():
    metas = [_meta("execution-14-trigger.md", category="daily", days_old=90)]
    assert _names(nr.select_expired(metas, now=NOW, days=30)) == \
        ["execution-14-trigger.md"]


def test_zero_days_disables_the_whole_thing():
    """Off by configuration, not by a caller remembering to check."""
    metas = [_meta("ancient.md", days_old=9999)]
    assert nr.select_expired(metas, now=NOW, days=0) == []
    assert nr.select_expired(metas, now=NOW, days=-1) == []


def test_a_sweep_is_capped():
    """A delete is a write. An unbounded sweep holds the memory engine for
    as long as the backlog takes — the exact failure being removed."""
    metas = [_meta(f"n{i}.md", days_old=100) for i in range(50)]
    assert len(nr.select_expired(metas, now=NOW, days=30, limit=10)) == 10


def test_the_cap_takes_the_oldest_first():
    """Observation filenames sort chronologically; `daily/execution-14-…`
    does not. A capped sweep that picks by name would nibble the wrong end
    and never drain a real backlog."""
    metas = [
        _meta("execution-2.md", category="daily", days_old=40),
        _meta("execution-99.md", category="daily", days_old=400),
        _meta("execution-50.md", category="daily", days_old=200),
    ]
    picked = _names(nr.select_expired(metas, now=NOW, days=30, limit=2))
    assert picked == ["execution-99.md", "execution-50.md"]


def test_a_note_with_no_timestamp_is_left_alone():
    """Unknown age must never read as 'ancient'."""
    meta = SimpleNamespace(
        ref=SimpleNamespace(filename="odd.md", category="observations"),
        updated_at=None, created_at=None, importance="low",
    )
    assert nr.select_expired([meta], now=NOW, days=30) == []


def test_a_naive_timestamp_does_not_crash_the_sweep():
    meta = SimpleNamespace(
        ref=SimpleNamespace(filename="naive.md", category="observations"),
        updated_at=datetime(2020, 1, 1), importance="low",
    )
    assert _names(nr.select_expired([meta], now=NOW, days=30)) == ["naive.md"]


def test_the_default_window_is_generous():
    """Deletion is one-way; a short default would be discovered too late."""
    assert nr.DEFAULT_RETENTION_DAYS >= 14


def test_the_environment_can_turn_it_off(monkeypatch):
    monkeypatch.setenv("GENY_NOTE_RETENTION_DAYS", "0")
    assert nr.retention_days() == 0


def test_a_broken_setting_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("GENY_NOTE_RETENTION_DAYS", "몰라")
    assert nr.retention_days() == nr.DEFAULT_RETENTION_DAYS


# ── the manager actually deletes, through the store ─────────────────

class _Notes:
    def __init__(self, metas):
        self._metas = list(metas)
        self.deleted = []

    async def list(self):
        return self._metas

    async def delete(self, filename):
        self.deleted.append(filename)
        return True


def _mgr(notes):
    from service.memory.manager import SessionMemoryManager

    mgr = SessionMemoryManager.__new__(SessionMemoryManager)
    mgr._memory_provider = SimpleNamespace(notes=lambda: notes)
    return mgr


@pytest.mark.asyncio
async def test_the_sweep_deletes_through_the_store(monkeypatch):
    """Through `delete()`, not by unlinking: that is what carries the removal
    into the vector index and the sidecars.

    Ages are relative to the real clock here, not to ``NOW``. The sweep reads
    ``datetime.now()`` itself — and an earlier version of this test built its
    notes from ``NOW``, so it passed when written and began failing the day
    real time moved past the retention window. A test that expires on a
    calendar tells you nothing on the day it breaks.
    """
    monkeypatch.setattr(nr, "DEFAULT_RETENTION_DAYS", 30)
    today = datetime.now(timezone.utc)
    notes = _Notes([
        _meta("old.md", days_old=90, now=today),
        _meta("new.md", days_old=1, now=today),
    ])

    assert await _mgr(notes).prune_expired_notes() == 1
    assert notes.deleted == ["old.md"]


@pytest.mark.asyncio
async def test_the_sweep_is_off_when_configured_off(monkeypatch):
    monkeypatch.setenv("GENY_NOTE_RETENTION_DAYS", "0")
    notes = _Notes([_meta("ancient.md", days_old=9999)])

    assert await _mgr(notes).prune_expired_notes() == 0
    assert notes.deleted == []


@pytest.mark.asyncio
async def test_one_bad_file_does_not_abort_the_sweep():
    class _Flaky(_Notes):
        async def delete(self, filename):
            if filename == "bad.md":
                raise OSError("permission denied")
            return await super().delete(filename)

    notes = _Flaky([_meta("bad.md", days_old=90), _meta("good.md", days_old=90)])

    assert await _mgr(notes).prune_expired_notes() == 1
    assert notes.deleted == ["good.md"]


@pytest.mark.asyncio
async def test_a_failing_sweep_never_breaks_the_session():
    """Retention is housekeeping. A session must not fail to start over it."""
    class _Broken:
        async def list(self):
            raise RuntimeError("vault unreadable")

    assert await _mgr(_Broken()).prune_expired_notes() == 0


@pytest.mark.asyncio
async def test_the_sweep_stops_on_its_time_budget(monkeypatch):
    """Count is a poor proxy: a delete touches the notes store, the sidecar
    index and the vector index, and how long that takes depends on the disk.
    The first version had no clock, ran inside the session warm-up, and
    starved a live turn for 300 seconds."""
    import time as _t

    monkeypatch.setattr(nr, "DEFAULT_MAX_SECONDS", 0.0)

    class _Slow(_Notes):
        async def delete(self, filename):
            _t.sleep(0.01)
            return await super().delete(filename)

    notes = _Slow([_meta(f"n{i}.md", days_old=90) for i in range(40)])

    removed = await _mgr(notes).prune_expired_notes()

    assert removed < 40, "the sweep ignored its time budget"
    assert removed >= 1, "the budget stopped it before any progress"


def test_the_sweep_caps_are_modest():
    """Both ceilings exist so one sweep is bounded and the next resumes."""
    assert nr.DEFAULT_MAX_PER_SWEEP <= 500
    assert 5.0 <= nr.DEFAULT_MAX_SECONDS <= 120.0


@pytest.mark.asyncio
async def test_retention_is_not_part_of_the_boot_reconcile():
    """It must not sit on the path a waking session is gated on — that is
    what turned a 90-second warm-up budget into an abandoned turn."""
    import inspect

    from service.memory.manager import SessionMemoryManager

    src = inspect.getsource(SessionMemoryManager._vector_initialize_and_index)
    assert "prune_expired_notes" not in src


# ── the count ceiling: what actually bounds the vault ───────────────

def test_surplus_notes_go_even_when_they_are_young():
    """An age window does not bound anything. At the measured 757
    observations/day a 30-day window settles at ~22,700 notes — four times
    the vault this was meant to stop growing. The count rule is the only
    guarantee that survives a change in write rate."""
    metas = [_meta(f"n{i}.md", days_old=i) for i in range(10)]

    picked = _names(nr.select_expired(metas, now=NOW, days=0,
                                      keep_per_category=4))

    assert len(picked) == 6
    assert "n9.md" in picked, "the oldest was not dropped first"
    assert "n0.md" not in picked, "the newest was dropped"


def test_the_ceiling_is_per_category():
    """`observations` and `daily` fill at different rates; one budget shared
    between them would let the faster one evict the slower one's history."""
    metas = ([_meta(f"o{i}.md", days_old=i) for i in range(6)] +
             [_meta(f"d{i}.md", category="daily", days_old=i) for i in range(2)])

    picked = _names(nr.select_expired(metas, now=NOW, days=0,
                                      keep_per_category=4))

    assert sorted(picked) == ["o4.md", "o5.md"]


def test_the_ceiling_still_spares_critical_and_digests():
    """The count rule must not become a back door around the protections."""
    metas = ([_meta("__digest__.md", days_old=99)] +
             [_meta("keep.md", days_old=98, importance="critical")] +
             [_meta(f"n{i}.md", days_old=i) for i in range(10)])

    picked = _names(nr.select_expired(metas, now=NOW, days=0,
                                      keep_per_category=2))

    assert "__digest__.md" not in picked
    assert "keep.md" not in picked


def test_age_and_count_are_independent():
    """Either reason alone is enough; neither disables the other."""
    metas = [_meta("ancient.md", days_old=999)] + \
            [_meta(f"n{i}.md", days_old=1) for i in range(5)]

    by_age = _names(nr.select_expired(metas, now=NOW, days=30,
                                      keep_per_category=0))
    assert by_age == ["ancient.md"]

    both = _names(nr.select_expired(metas, now=NOW, days=30,
                                    keep_per_category=3))
    assert "ancient.md" in both and len(both) == 3


def test_both_rules_off_selects_nothing():
    metas = [_meta(f"n{i}.md", days_old=999) for i in range(10)]
    assert nr.select_expired(metas, now=NOW, days=0, keep_per_category=0) == []


def test_the_default_ceiling_bounds_the_measured_write_rate():
    """757 observations/day measured in production. The ceiling has to be a
    number of notes, not a number of days."""
    assert 1000 <= nr.DEFAULT_MAX_PER_CATEGORY <= 20000
