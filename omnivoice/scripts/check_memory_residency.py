"""Persistent-residency regression gate (Phase 1d).

Reads two snapshots produced by ``GET /diag/memory`` (one taken right
after warmup, one taken after N synthesis calls) and asserts that the
runtime steady state is *truly* steady:

* ``allocated_bytes.all.current``    delta = 0  (±tolerance)  -- no leaks
* ``allocated_bytes.all.peak``       delta = 0                -- no transient growth
* ``reserved_bytes.all.current``     delta ≤ 64 MiB           -- expandable_segments slack
* ``reserved_bytes.all.peak``        delta ≤ 64 MiB           -- pool ceiling steady
* ``num_alloc_retries``              delta = 0
* ``num_ooms``                       absolute = 0
* fragmentation = (reserved - allocated) / reserved   ≤ ``--max-fragmentation``

The ``allocated_bytes`` invariants are the real "no per-request
allocation" gate. ``reserved_bytes`` has a tolerance because PyTorch's
``expandable_segments:True`` allocator extends its physical-backed
segment pool on demand and does not release pages between requests --
that growth is bounded and is not a leak.

Any violation indicates that a code path is still allocating new GPU
tensors per request — which negates the whole point of the lifespan
pre-allocation policy. The script exits non-zero and prints the
offending metric so operators can fix it before merging the PR.

The script never imports torch; it only consumes JSON dicts that the
``/diag/memory`` HTTP route emits. That keeps the dev workstation able
to dry-run ``--help`` without GPU drivers installed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("check_memory_residency")


@dataclass(frozen=True)
class Verdict:
    metric: str
    expected: str
    actual: str
    passed: bool


def _path(d: dict, dotted: str, default: Any = None) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _read_snapshot(p: Path) -> dict:
    with open(p, "r", encoding="utf-8") as fh:
        return json.load(fh)


def evaluate(
    before: dict,
    after: dict,
    *,
    max_allocated_delta_bytes: int,
    max_reserved_delta_bytes: int,
    max_retries_delta: int,
    max_fragmentation: float,
) -> list[Verdict]:
    """Return one :class:`Verdict` per checked metric. Pure function."""

    def _g(snap: dict, key: str, default: int = 0) -> int:
        v = _path(snap, key)
        if v is None:
            v = default
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    alloc_b = _g(before, "allocated_bytes.all.current")
    alloc_a = _g(after, "allocated_bytes.all.current")
    alloc_peak_b = _g(before, "allocated_bytes.all.peak")
    alloc_peak_a = _g(after, "allocated_bytes.all.peak")
    res_b = _g(before, "reserved_bytes.all.current")
    res_a = _g(after, "reserved_bytes.all.current")
    res_peak_b = _g(before, "reserved_bytes.all.peak")
    res_peak_a = _g(after, "reserved_bytes.all.peak")
    retries_b = _g(before, "num_alloc_retries")
    retries_a = _g(after, "num_alloc_retries")
    ooms_b = _g(before, "num_ooms")
    ooms_a = _g(after, "num_ooms")

    alloc_delta = alloc_a - alloc_b
    alloc_peak_delta = alloc_peak_a - alloc_peak_b
    res_delta = res_a - res_b
    res_peak_delta = res_peak_a - res_peak_b
    retries_delta = retries_a - retries_b

    if res_a > 0:
        frag = max(res_a - alloc_a, 0) / res_a
    else:
        frag = 0.0

    verdicts: list[Verdict] = [
        Verdict(
            metric="allocated_bytes.all.current delta",
            expected=f"≤ {max_allocated_delta_bytes} bytes",
            actual=f"{alloc_delta:+d} bytes",
            passed=alloc_delta <= max_allocated_delta_bytes,
        ),
        Verdict(
            metric="allocated_bytes.all.peak delta",
            expected=f"≤ {max_allocated_delta_bytes} bytes",
            actual=f"{alloc_peak_delta:+d} bytes",
            passed=alloc_peak_delta <= max_allocated_delta_bytes,
        ),
        Verdict(
            metric="reserved_bytes.all.current delta",
            expected=f"≤ {max_reserved_delta_bytes} bytes",
            actual=f"{res_delta:+d} bytes",
            passed=res_delta <= max_reserved_delta_bytes,
        ),
        Verdict(
            metric="reserved_bytes.all.peak delta",
            expected=f"≤ {max_reserved_delta_bytes} bytes",
            actual=f"{res_peak_delta:+d} bytes",
            passed=res_peak_delta <= max_reserved_delta_bytes,
        ),
        Verdict(
            metric="num_alloc_retries delta",
            expected=f"≤ {max_retries_delta}",
            actual=f"{retries_delta:+d}",
            passed=retries_delta <= max_retries_delta,
        ),
        Verdict(
            metric="num_ooms (after)",
            expected="0",
            actual=str(ooms_a),
            passed=ooms_a == 0 and ooms_b == 0,
        ),
        Verdict(
            metric="fragmentation (reserved-allocated)/reserved",
            expected=f"≤ {max_fragmentation:.3f}",
            actual=f"{frag:.3f}",
            passed=frag <= max_fragmentation,
        ),
    ]
    return verdicts


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="check_memory_residency",
        description="Compare two /diag/memory snapshots and gate persistent-residency invariants.",
    )
    p.add_argument("before", type=Path, help="JSON snapshot taken right after warmup.")
    p.add_argument("after", type=Path, help="JSON snapshot taken after N synthesis calls.")
    p.add_argument(
        "--max-allocated-delta-bytes",
        type=int,
        default=0,
        help="Tolerance on allocated_bytes growth. 0 = strict (recommended).",
    )
    p.add_argument(
        "--max-reserved-delta-bytes",
        type=int,
        default=64 * 1024 * 1024,
        help=(
            "Tolerance on reserved_bytes growth. Default 64 MiB accounts for "
            "PyTorch's expandable_segments allocator extending its segment "
            "pool on-demand without releasing pages between requests; this "
            "is not a leak. The strict no-leak invariant is allocated_bytes "
            "(both current and peak), which is checked separately."
        ),
    )
    p.add_argument(
        "--max-retries-delta",
        type=int,
        default=0,
        help="Tolerance on num_alloc_retries growth. 0 = strict.",
    )
    p.add_argument(
        "--max-fragmentation",
        type=float,
        default=0.05,
        help="Maximum allowed (reserved-allocated)/reserved ratio.",
    )
    p.add_argument(
        "--report",
        type=Path,
        default=None,
        help="If set, write the verdict list as JSON.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level="INFO",
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    args = _build_parser().parse_args(argv)
    before = _read_snapshot(args.before)
    after = _read_snapshot(args.after)

    verdicts = evaluate(
        before,
        after,
        max_allocated_delta_bytes=args.max_allocated_delta_bytes,
        max_reserved_delta_bytes=args.max_reserved_delta_bytes,
        max_retries_delta=args.max_retries_delta,
        max_fragmentation=args.max_fragmentation,
    )

    failed = [v for v in verdicts if not v.passed]
    for v in verdicts:
        mark = "OK" if v.passed else "FAIL"
        logger.info("[%s] %-50s expected %-25s actual %s",
                    mark, v.metric, v.expected, v.actual)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "passed": not failed,
                    "verdicts": [
                        {"metric": v.metric, "expected": v.expected,
                         "actual": v.actual, "passed": v.passed}
                        for v in verdicts
                    ],
                },
                fh,
                indent=2,
            )

    if failed:
        logger.error("residency gate FAILED on %d / %d checks", len(failed), len(verdicts))
        return 1
    logger.info("residency gate PASSED (%d checks)", len(verdicts))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
