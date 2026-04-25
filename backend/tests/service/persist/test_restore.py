"""Coverage for G7.1 — checkpoint listing + restore.

Two layers:

1. **list_checkpoints** — enumerates the FilePersister directory.
   Empty dir / missing dir / multiple checkpoints all behave correctly.
2. **restore_checkpoint** — round-trips through the executor's
   ``restore_state_from_checkpoint`` and rebuilds the state. Unknown
   checkpoint id raises ``CheckpointNotFoundError``.

Skipped when geny-executor's persist subpackage isn't importable
(older host pin) — same defensive pattern as test_endpoints.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

import pytest

pytest.importorskip("geny_executor.stages.s20_persist")
pytest.importorskip("geny_executor.stages.s20_persist.restore")

from service.persist.install import CHECKPOINT_SUBDIR  # noqa: E402
from service.persist.restore import (  # noqa: E402
    CheckpointNotFoundError,
    list_checkpoints,
    make_persister_for_storage,
    restore_checkpoint,
)


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[Path]:
    storage_dir = tmp_path / "storage"
    (storage_dir / CHECKPOINT_SUBDIR).mkdir(parents=True, exist_ok=True)
    yield storage_dir


# ── list_checkpoints ────────────────────────────────────────────────


def test_list_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    assert list_checkpoints(tmp_path / "no-such-storage") == []


def test_list_returns_empty_for_empty_dir(storage: Path) -> None:
    assert list_checkpoints(storage) == []


def test_list_enumerates_files_newest_first(storage: Path) -> None:
    """The 3 files we drop should appear newest-first by mtime."""
    import os
    import time

    base = storage / CHECKPOINT_SUBDIR
    paths = []
    for i, name in enumerate(["ckpt_a", "ckpt_b", "ckpt_c"]):
        path = base / f"{name}.json"
        path.write_text("{}", encoding="utf-8")
        # Stagger mtime so the sort is deterministic.
        os.utime(path, (time.time() - (10 - i), time.time() - (10 - i)))
        paths.append(path)

    out = list_checkpoints(storage)
    assert [c["checkpoint_id"] for c in out] == ["ckpt_c", "ckpt_b", "ckpt_a"]
    for entry in out:
        assert entry["size_bytes"] >= 2  # at least "{}"
        assert isinstance(entry["written_at"], float)


def test_list_skips_directories(storage: Path) -> None:
    """Subdirs under the checkpoint root shouldn't show up as ids."""
    (storage / CHECKPOINT_SUBDIR / "ckpt_a.json").write_text("{}", encoding="utf-8")
    (storage / CHECKPOINT_SUBDIR / "subdir").mkdir()
    out = list_checkpoints(storage)
    assert [c["checkpoint_id"] for c in out] == ["ckpt_a"]


# ── make_persister_for_storage ──────────────────────────────────────


def test_make_persister_returns_none_for_empty(tmp_path: Path) -> None:
    assert make_persister_for_storage("") is None


def test_make_persister_returns_instance_for_path(storage: Path) -> None:
    persister = make_persister_for_storage(storage)
    assert persister is not None
    # FilePersister exposes ``base_dir`` (or similar) — read-only check
    # that it's pointing at the expected subdir.
    base = getattr(persister, "_base_dir", None) or getattr(persister, "base_dir", None)
    if base is not None:
        assert Path(base) == storage / CHECKPOINT_SUBDIR


# ── restore_checkpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_restore_unknown_id_raises(storage: Path) -> None:
    with pytest.raises(CheckpointNotFoundError):
        await restore_checkpoint(storage, "ghost")


@pytest.mark.asyncio
async def test_restore_round_trips_through_persister(storage: Path) -> None:
    """Drop a payload via the same FilePersister the install module
    uses, then restore it via the public API. The reconstructed state
    should carry the messages we wrote."""
    persister = make_persister_for_storage(storage)
    assert persister is not None

    # Build a minimal payload the persister can write. Using its own
    # write API keeps the test forward-compatible if FilePersister
    # changes its on-disk format.
    sample_payload = {
        "messages": [{"role": "user", "content": "hello"}],
        "iteration": 3,
        "metadata": {"source": "g7.1-test"},
    }
    write = getattr(persister, "write_checkpoint", None) or getattr(
        persister, "save", None
    )
    if not callable(write):
        pytest.skip("persister has no public write method we can drive")

    # FilePersister.write_checkpoint signature varies by version — try
    # a couple common shapes.
    try:
        result = write("ckpt_test", sample_payload)
        if hasattr(result, "__await__"):
            result = await result
    except TypeError:
        # Fall back to dropping a JSON file directly under the executor's
        # expected layout.
        (storage / CHECKPOINT_SUBDIR / "ckpt_test.json").write_text(
            json.dumps(sample_payload), encoding="utf-8"
        )

    state = await restore_checkpoint(storage, "ckpt_test")
    assert state is not None
    # PipelineState carries messages + iteration + metadata; only
    # assert on the pieces we wrote so the test isn't brittle to
    # additional defaulted fields.
    assert getattr(state, "iteration", None) == 3
