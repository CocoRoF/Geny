"""HTTP-driven RTF / TTFA / VRAM benchmark for the omnivoice service.

Runs against an *already-running* server (typically the staging GPU
container). Collects per-call timing + a single ``/diag/memory``
snapshot before and after, then dumps a JSON report that
``bench_to_md.py`` can fold into ``benchmarks.md``.

Why HTTP and not direct in-process synthesis? Because the staging gate
exercises the whole stack — adapter → uvicorn → FastAPI → engine —
exactly the way production runs it. Any optimization that only shows
up when called in-process is worth less than one that survives the HTTP
boundary.

Dev workstations (no GPU) can still ``python -m server.bench --help``
and the unit tests can import the pure-data helpers (``Stats`` etc.).
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import logging
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("bench")


# ── Pure helpers (importable, no IO) ─────────────────────────────────


@dataclasses.dataclass(frozen=True)
class CallTiming:
    text: str
    voice: str
    text_len: int
    audio_seconds: float
    wall_seconds: float
    rtf: float
    ttfa_seconds: float  # response first-byte; for non-streamed = wall_seconds


@dataclasses.dataclass(frozen=True)
class Stats:
    n: int
    mean: float
    p50: float
    p95: float
    p99: float
    minimum: float
    maximum: float

    @classmethod
    def from_samples(cls, samples: list[float]) -> "Stats":
        if not samples:
            return cls(n=0, mean=0, p50=0, p95=0, p99=0, minimum=0, maximum=0)
        s = sorted(samples)
        n = len(s)

        def _q(q: float) -> float:
            idx = max(0, min(n - 1, int(round(q * (n - 1)))))
            return s[idx]

        return cls(
            n=n,
            mean=statistics.fmean(s),
            p50=_q(0.50),
            p95=_q(0.95),
            p99=_q(0.99),
            minimum=s[0],
            maximum=s[-1],
        )


def summarise(timings: list[CallTiming]) -> dict:
    """Build a JSON-serialisable summary from a list of CallTimings."""
    if not timings:
        return {"n": 0}
    rtf = Stats.from_samples([t.rtf for t in timings])
    wall = Stats.from_samples([t.wall_seconds for t in timings])
    ttfa = Stats.from_samples([t.ttfa_seconds for t in timings])
    audio = Stats.from_samples([t.audio_seconds for t in timings])
    return {
        "n": len(timings),
        "rtf": dataclasses.asdict(rtf),
        "wall_seconds": dataclasses.asdict(wall),
        "ttfa_seconds": dataclasses.asdict(ttfa),
        "audio_seconds": dataclasses.asdict(audio),
    }


# ── HTTP I/O paths (lazy imports keep tests light) ───────────────────


def _decode_audio(body: bytes) -> tuple[int, float]:
    """Return (n_samples, audio_seconds) without bringing torch in."""
    import soundfile as sf  # lazy

    audio, sr = sf.read(io.BytesIO(body), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return int(audio.size), float(audio.size) / float(sr)


def _post_tts_timed(
    client,
    api_url: str,
    *,
    text: str,
    voice: str,
    voices_root: str,
    language: Optional[str],
    num_step: int,
    guidance_scale: float,
) -> CallTiming:
    payload: dict = {
        "text": text,
        "language": language or None,
        "num_step": num_step,
        "guidance_scale": guidance_scale,
        "audio_format": "wav",
    }
    if voice:
        payload["mode"] = "clone"
        payload["ref_audio_path"] = f"{voices_root.rstrip('/')}/{voice}/ref_neutral.wav"
    else:
        payload["mode"] = "auto"

    t0 = time.perf_counter()
    # client.stream lets us measure first-byte for chunked transfer; for
    # the legacy /tts route the whole body lands in one shot, so TTFA
    # collapses to the full wall time.
    with client.stream("POST", f"{api_url.rstrip('/')}/tts", json=payload) as resp:
        resp.raise_for_status()
        chunks: list[bytes] = []
        first_byte_t: Optional[float] = None
        for chunk in resp.iter_bytes():
            if not chunk:
                continue
            if first_byte_t is None:
                first_byte_t = time.perf_counter()
            chunks.append(chunk)
        body = b"".join(chunks)
    t1 = time.perf_counter()

    n_samples, audio_seconds = _decode_audio(body)
    wall = t1 - t0
    ttfa = (first_byte_t - t0) if first_byte_t is not None else wall
    rtf = wall / audio_seconds if audio_seconds > 0 else float("inf")
    return CallTiming(
        text=text,
        voice=voice,
        text_len=len(text),
        audio_seconds=audio_seconds,
        wall_seconds=wall,
        rtf=rtf,
        ttfa_seconds=ttfa,
    )


def _wait_for_phase_ok(client, api_url: str, *, timeout_s: float) -> Optional[dict]:
    """Poll ``/health`` until ``phase == 'ok'`` or timeout. Returns last body."""
    deadline = time.monotonic() + timeout_s
    last: Optional[dict] = None
    while time.monotonic() < deadline:
        try:
            resp = client.get(f"{api_url.rstrip('/')}/health")
            last = resp.json() if resp.status_code == 200 else None
        except Exception:
            last = None
        phase = (last or {}).get("phase") or (last or {}).get("status")
        if phase == "ok":
            return last
        time.sleep(2.0)
    return last


def _read_diag_memory(client, api_url: str) -> Optional[dict]:
    try:
        resp = client.get(f"{api_url.rstrip('/')}/diag/memory")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ── CLI ──────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m server.bench",
        description="HTTP RTF/TTFA benchmark for the omnivoice service.",
    )
    p.add_argument("--api-url", default="http://localhost:9881")
    p.add_argument(
        "--texts",
        action="append",
        default=[],
        type=Path,
        help="Path(s) to text file(s); one prompt per line.",
    )
    p.add_argument(
        "--voice",
        action="append",
        default=[],
        help="Voice profile id(s); empty -> auto.",
    )
    p.add_argument("--language", default=None)
    p.add_argument("--runs", type=int, default=3, help="Repeat the prompt set N times.")
    p.add_argument("--warmup", type=int, default=1, help="Discarded warmup runs.")
    p.add_argument("--num-step", type=int, default=32)
    p.add_argument("--guidance-scale", type=float, default=2.0)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--voices-root", default="/voices")
    p.add_argument("--health-timeout", type=float, default=120.0,
                   help="Seconds to wait for /health phase=ok before measuring.")
    p.add_argument("--json", type=Path, default=None,
                   help="Write the summary JSON to this path.")
    p.add_argument("--label", default="",
                   help="Free-form label stored in the report (e.g. 'phase-1d').")
    return p


def _load_texts(paths: list[Path]) -> list[str]:
    out: list[str] = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                out.append(stripped)
    return out


def _run_bench(args) -> dict:
    import httpx  # lazy

    texts = _load_texts(args.texts)
    if not texts:
        raise SystemExit("no texts loaded; pass --texts <file>")
    voices = list(args.voice) or [""]

    client = httpx.Client(timeout=args.timeout)
    try:
        health = _wait_for_phase_ok(client, args.api_url, timeout_s=args.health_timeout)
        if not health:
            raise SystemExit("server never reported phase=ok")
        logger.info("server ready: %s", health)

        mem_before = _read_diag_memory(client, args.api_url)

        # Warmup runs (discarded)
        for i in range(args.warmup):
            for voice in voices:
                for text in texts:
                    _post_tts_timed(
                        client, args.api_url,
                        text=text, voice=voice,
                        voices_root=args.voices_root,
                        language=args.language,
                        num_step=args.num_step,
                        guidance_scale=args.guidance_scale,
                    )
            logger.info("warmup run %d/%d done", i + 1, args.warmup)

        timings: list[CallTiming] = []
        for r in range(args.runs):
            for voice in voices:
                for text in texts:
                    t = _post_tts_timed(
                        client, args.api_url,
                        text=text, voice=voice,
                        voices_root=args.voices_root,
                        language=args.language,
                        num_step=args.num_step,
                        guidance_scale=args.guidance_scale,
                    )
                    timings.append(t)
            logger.info("run %d/%d done (%d calls)", r + 1, args.runs, len(timings))

        mem_after = _read_diag_memory(client, args.api_url)
    finally:
        client.close()

    summary = summarise(timings)
    summary.update({
        "label": args.label,
        "api_url": args.api_url,
        "voices": voices,
        "num_step": args.num_step,
        "guidance_scale": args.guidance_scale,
        "runs": args.runs,
        "warmup": args.warmup,
        "n_prompts": len(texts),
        "diag_memory_before": mem_before,
        "diag_memory_after": mem_after,
        "health": health,
    })
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=os.environ.get("BENCH_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    args = _build_parser().parse_args(argv)
    summary = _run_bench(args)
    out = json.dumps(summary, indent=2, default=str)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(out)
        logger.info("wrote summary -> %s", args.json)
    else:
        print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
