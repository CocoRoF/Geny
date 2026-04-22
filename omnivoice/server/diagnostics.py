"""Operational diagnostics endpoints.

Exposed under ``/diag/*`` so they don't collide with normal routes.
Two endpoints today:

* ``GET /diag/memory`` — filtered ``torch.cuda.memory_stats()`` snapshot
  used by ``check_memory_residency.py`` to gate persistent-residency
  invariants (zero allocator activity at steady state).
* ``GET /diag/phase`` — current engine phase (loading / warming / ok /
  error) as a tiny JSON, used by the bench harness and by the backend
  adapter to distinguish "still warming" from "broken".

The /diag/memory route degrades gracefully on CPU-only hosts (returns
``{"cuda_available": false}`` with HTTP 200) so dev workstations and
unit tests don't have to special-case it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from server import engine

router = APIRouter(prefix="/diag", tags=["diagnostics"])


def _safe_get(d: dict, dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _filter_memory_stats(stats: dict) -> dict:
    """Pick only the fields used by the residency gate.

    ``torch.cuda.memory_stats()`` is a flat dict with names like
    ``allocated_bytes.all.current``. PyTorch returns it as a *flat* dict
    keyed by those dotted strings — but for human readability and for
    the residency checker we re-nest the four fields we actually consume.
    """
    def _g(key: str) -> int:
        v = stats.get(key)
        return int(v) if v is not None else 0

    allocated_current = _g("allocated_bytes.all.current")
    allocated_peak = _g("allocated_bytes.all.peak")
    reserved_current = _g("reserved_bytes.all.current")
    reserved_peak = _g("reserved_bytes.all.peak")
    fragmentation = (
        max(reserved_current - allocated_current, 0) / reserved_current
        if reserved_current > 0
        else 0.0
    )
    return {
        "allocated_bytes": {
            "all": {"current": allocated_current, "peak": allocated_peak}
        },
        "reserved_bytes": {
            "all": {"current": reserved_current, "peak": reserved_peak}
        },
        "num_alloc_retries": _g("num_alloc_retries"),
        "num_ooms": _g("num_ooms"),
        "fragmentation": round(fragmentation, 6),
    }


@router.get("/memory")
def memory() -> dict:
    try:
        import torch  # local import; unit-test paths may not have it
    except Exception:
        return {"cuda_available": False, "reason": "torch_unavailable"}

    if not torch.cuda.is_available():
        return {"cuda_available": False}

    device = torch.cuda.current_device()
    stats = torch.cuda.memory_stats(device)
    payload = _filter_memory_stats(stats)
    payload["cuda_available"] = True
    payload["device_index"] = int(device)
    payload["device_name"] = torch.cuda.get_device_name(device)
    cap = torch.cuda.get_device_capability(device)
    payload["compute_capability"] = f"{cap[0]}.{cap[1]}"
    free, total = torch.cuda.mem_get_info(device)
    payload["device_free_bytes"] = int(free)
    payload["device_total_bytes"] = int(total)
    return payload


@router.get("/phase")
def phase() -> dict:
    return {"phase": engine.get_phase()}
