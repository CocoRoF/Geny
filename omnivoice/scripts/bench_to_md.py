"""Render bench JSON summaries (from ``server.bench``) into a benchmarks.md row.

Usage::

    python -m scripts.bench_to_md --label phase-1d --json /tmp/bench.json >> benchmarks.md

The script intentionally outputs *just* the markdown table row + an
optional Markdown subsection so the operator can paste it into
``dev_docs/20260422_OmniVoice_Perf/benchmarks.md`` under the matching
phase header. We do not auto-edit that file because the document is
under review.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def _fmt(x, suffix="") -> str:
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.3f}{suffix}"
    return f"{x}{suffix}"


def _row(summary: dict, label: str) -> str:
    rtf = summary.get("rtf") or {}
    wall = summary.get("wall_seconds") or {}
    ttfa = summary.get("ttfa_seconds") or {}
    n = summary.get("n", 0)
    return (
        f"| {label} | {n} | "
        f"{_fmt(rtf.get('mean'))} | {_fmt(rtf.get('p50'))} | {_fmt(rtf.get('p95'))} | "
        f"{_fmt(wall.get('mean'), 's')} | {_fmt(ttfa.get('mean'), 's')} |"
    )


def _residency_block(summary: dict) -> str:
    before = summary.get("diag_memory_before") or {}
    after = summary.get("diag_memory_after") or {}

    def _g(d, k):
        cur = d
        for part in k.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    rows: list[str] = ["", "**VRAM residency**", ""]
    rows.append("| Metric | Before | After | Δ |")
    rows.append("|---|---:|---:|---:|")
    for label, key in [
        ("allocated_bytes.all.current", "allocated_bytes.all.current"),
        ("reserved_bytes.all.current", "reserved_bytes.all.current"),
        ("num_alloc_retries", "num_alloc_retries"),
        ("num_ooms", "num_ooms"),
    ]:
        a = _g(before, key)
        b = _g(after, key)
        delta = (b - a) if (isinstance(a, int) and isinstance(b, int)) else None
        rows.append(f"| {label} | {_fmt(a)} | {_fmt(b)} | {_fmt(delta)} |")
    return "\n".join(rows)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bench_to_md")
    p.add_argument("--json", type=Path, required=True, help="Path to bench summary JSON.")
    p.add_argument("--label", default=None, help="Override label column.")
    p.add_argument("--no-residency", action="store_true",
                   help="Skip the VRAM residency block.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    with open(args.json, "r", encoding="utf-8") as fh:
        summary = json.load(fh)
    label = args.label or summary.get("label") or "(unlabeled)"
    print("| Run | N | RTF mean | RTF p50 | RTF p95 | Wall mean | TTFA mean |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    print(_row(summary, label))
    if not args.no_residency:
        print(_residency_block(summary))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
