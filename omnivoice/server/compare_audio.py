"""Output-equivalence regression gate for Tier-A optimisations.

Used by ``staging_gate.sh``: every PR that *claims* to be Tier-A must
produce, for the same (text, voice, seed) inputs, PCM that lies within
``--atol`` of the captured baseline. fp16 non-determinism makes bit
equivalence impractical; ``atol=1e-4`` (≈ ±2 / 32768 LSB after int16
quantisation) is below the human-perception threshold.

Workflow
--------

1. **Capture baseline** (once, on staging GPU, against the *unmodified*
   server) ::

       python -m server.compare_audio capture \
           --output /baselines/sm_61/ \
           --texts scripts/texts_smoke.txt \
           --voice paimon_ko

2. **Regression check** (every Tier-A PR) ::

       python -m server.compare_audio check \
           --baseline /baselines/sm_61/ \
           --texts scripts/texts_smoke.txt \
           --atol 1e-4

   Exit code 0 = all cases within atol. Non-zero = at least one case
   regressed; the offending case is printed to stdout with diff stats.

The script talks to the running ``omnivoice`` HTTP service over
``--api-url`` so it transparently exercises the *whole* synthesis stack
(adapter, model, post-processing). It deliberately does *not* import
``torch``: the dev workstation can dry-run ``--help`` and unit tests
without a GPU.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

logger = logging.getLogger("compare_audio")


# ── PCM diff primitives (pure numpy, importable from tests) ─────────


@dataclasses.dataclass(frozen=True)
class CaseResult:
    case_id: str
    text: str
    voice: str
    n_samples_baseline: int
    n_samples_candidate: int
    max_abs_diff: float
    mean_abs_diff: float
    rms_diff: float
    within_atol: bool
    note: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def compare_pcm(
    baseline: np.ndarray,
    candidate: np.ndarray,
    *,
    atol: float,
    case_id: str,
    text: str,
    voice: str,
) -> CaseResult:
    """Diff two float32 PCM arrays. Mismatched lengths fail the case."""
    base = np.asarray(baseline, dtype=np.float32).reshape(-1)
    cand = np.asarray(candidate, dtype=np.float32).reshape(-1)

    if base.shape != cand.shape:
        return CaseResult(
            case_id=case_id,
            text=text,
            voice=voice,
            n_samples_baseline=int(base.size),
            n_samples_candidate=int(cand.size),
            max_abs_diff=float("inf"),
            mean_abs_diff=float("inf"),
            rms_diff=float("inf"),
            within_atol=False,
            note=f"length mismatch: baseline={base.size} candidate={cand.size}",
        )

    if base.size == 0:
        return CaseResult(
            case_id=case_id,
            text=text,
            voice=voice,
            n_samples_baseline=0,
            n_samples_candidate=0,
            max_abs_diff=0.0,
            mean_abs_diff=0.0,
            rms_diff=0.0,
            within_atol=True,
            note="both empty",
        )

    diff = np.abs(base - cand)
    max_d = float(diff.max())
    mean_d = float(diff.mean())
    rms = float(np.sqrt(np.mean(np.square(diff))))

    return CaseResult(
        case_id=case_id,
        text=text,
        voice=voice,
        n_samples_baseline=int(base.size),
        n_samples_candidate=int(cand.size),
        max_abs_diff=max_d,
        mean_abs_diff=mean_d,
        rms_diff=rms,
        within_atol=max_d <= atol,
    )


# ── Baseline file format ─────────────────────────────────────────────


def case_id_for(text: str, voice: str, language: Optional[str]) -> str:
    """Stable, filesystem-safe id for a (text, voice, lang) tuple."""
    import hashlib

    payload = f"{voice}\x1e{language or ''}\x1e{text}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:16]


def save_baseline(
    output_dir: Path,
    case_id: str,
    *,
    audio: np.ndarray,
    sample_rate: int,
    text: str,
    voice: str,
    language: Optional[str],
    extra_meta: Optional[dict] = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    npz_path = output_dir / f"{case_id}.npz"
    meta = {
        "case_id": case_id,
        "text": text,
        "voice": voice,
        "language": language or "",
        "sample_rate": int(sample_rate),
        "n_samples": int(np.asarray(audio).size),
    }
    if extra_meta:
        meta.update(extra_meta)
    np.savez(
        npz_path,
        audio=np.asarray(audio, dtype=np.float32).reshape(-1),
        meta=json.dumps(meta),
    )
    return npz_path


def load_baseline(path: Path) -> tuple[np.ndarray, dict]:
    with np.load(path, allow_pickle=False) as data:
        audio = np.asarray(data["audio"], dtype=np.float32)
        meta = json.loads(str(data["meta"]))
    return audio, meta


# ── Text loading ─────────────────────────────────────────────────────


def load_text_files(paths: Iterable[Path]) -> list[str]:
    out: list[str] = []
    for p in paths:
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                out.append(stripped)
    return out


# ── HTTP I/O — only imported from CLI paths so unit tests stay light ─


def _decode_wav_bytes(body: bytes) -> tuple[np.ndarray, int]:
    """Decode a WAV/PCM container to (float32 ndarray, sample_rate)."""
    import soundfile as sf  # lazy import

    audio, sr = sf.read(io.BytesIO(body), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    return audio.astype(np.float32, copy=False), int(sr)


def _post_tts(
    api_url: str,
    *,
    text: str,
    voice: str,
    language: Optional[str],
    timeout: float,
    num_step: int,
    guidance_scale: float,
    voices_root: str,
) -> tuple[np.ndarray, int]:
    import httpx  # lazy import

    payload: dict = {
        "text": text,
        "language": language or None,
        "num_step": num_step,
        "guidance_scale": guidance_scale,
        "audio_format": "wav",
    }
    if voice:
        # Default reference filename mirrors GPTSoVITSEngine convention.
        payload["mode"] = "clone"
        payload["ref_audio_path"] = f"{voices_root.rstrip('/')}/{voice}/ref_neutral.wav"
    else:
        payload["mode"] = "auto"

    with httpx.Client(timeout=timeout) as client:
        resp = client.post(f"{api_url.rstrip('/')}/tts", json=payload)
        resp.raise_for_status()
        return _decode_wav_bytes(resp.content)


# ── CLI ──────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.compare_audio",
        description="Capture / verify OmniVoice output PCM against a frozen baseline.",
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--api-url", default="http://localhost:9881")
    common.add_argument(
        "--texts",
        action="append",
        default=[],
        type=Path,
        help="Path(s) to text file(s); one prompt per line. May be passed multiple times.",
    )
    common.add_argument(
        "--voice",
        action="append",
        default=[],
        help="Voice profile id(s); empty -> auto mode.",
    )
    common.add_argument("--language", default=None)
    common.add_argument("--num-step", type=int, default=32)
    common.add_argument("--guidance-scale", type=float, default=2.0)
    common.add_argument("--timeout", type=float, default=300.0)
    common.add_argument(
        "--voices-root",
        default="/voices",
        help="Container path that the omnivoice service sees voice profiles under.",
    )

    cap = sub.add_parser("capture", parents=[common], help="Record a fresh baseline.")
    cap.add_argument("--output", type=Path, required=True)

    chk = sub.add_parser("check", parents=[common], help="Diff candidate against baseline.")
    chk.add_argument("--baseline", type=Path, required=True)
    chk.add_argument("--atol", type=float, default=1e-4)
    chk.add_argument(
        "--mode",
        choices=("equivalence", "quality-drift"),
        default="equivalence",
        help=(
            "equivalence (Tier-A): hard atol gate, exit non-zero on any miss. "
            "quality-drift (Tier-B): atol relaxed, prints stats only and exits 0."
        ),
    )
    chk.add_argument(
        "--report",
        type=Path,
        default=None,
        help="If set, write per-case results as JSON.",
    )
    return parser


def _voices_for_run(args) -> list[str]:
    voices = list(args.voice)
    if not voices:
        voices = [""]  # auto
    return voices


def _cmd_capture(args) -> int:
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)
    texts = load_text_files(args.texts)
    voices = _voices_for_run(args)
    if not texts:
        logger.error("no texts loaded; pass --texts <file>")
        return 2

    n = 0
    for voice in voices:
        for text in texts:
            cid = case_id_for(text, voice, args.language)
            audio, sr = _post_tts(
                args.api_url,
                text=text,
                voice=voice,
                language=args.language,
                timeout=args.timeout,
                num_step=args.num_step,
                guidance_scale=args.guidance_scale,
                voices_root=args.voices_root,
            )
            save_baseline(
                out,
                cid,
                audio=audio,
                sample_rate=sr,
                text=text,
                voice=voice,
                language=args.language,
                extra_meta={
                    "num_step": args.num_step,
                    "guidance_scale": args.guidance_scale,
                },
            )
            n += 1
            logger.info("captured %s (%d samples @ %dHz) voice=%r", cid, audio.size, sr, voice)
    logger.info("wrote %d baseline cases to %s", n, out)
    return 0


def _cmd_check(args) -> int:
    base_dir: Path = args.baseline
    if not base_dir.is_dir():
        logger.error("baseline dir not found: %s", base_dir)
        return 2

    texts = load_text_files(args.texts)
    voices = _voices_for_run(args)
    if not texts:
        logger.error("no texts loaded; pass --texts <file>")
        return 2

    results: list[CaseResult] = []
    missing = 0
    for voice in voices:
        for text in texts:
            cid = case_id_for(text, voice, args.language)
            base_path = base_dir / f"{cid}.npz"
            if not base_path.exists():
                logger.warning("no baseline for case %s (voice=%r text=%r)", cid, voice, text[:40])
                missing += 1
                continue
            base_audio, _meta = load_baseline(base_path)
            cand_audio, _sr = _post_tts(
                args.api_url,
                text=text,
                voice=voice,
                language=args.language,
                timeout=args.timeout,
                num_step=args.num_step,
                guidance_scale=args.guidance_scale,
                voices_root=args.voices_root,
            )
            r = compare_pcm(
                base_audio,
                cand_audio,
                atol=args.atol,
                case_id=cid,
                text=text,
                voice=voice,
            )
            results.append(r)
            mark = "OK" if r.within_atol else "FAIL"
            logger.info(
                "[%s] %s max=%.3e mean=%.3e rms=%.3e voice=%r text=%r",
                mark, cid, r.max_abs_diff, r.mean_abs_diff, r.rms_diff, voice, text[:60],
            )

    failures = [r for r in results if not r.within_atol]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "atol": args.atol,
                    "mode": args.mode,
                    "missing": missing,
                    "n_cases": len(results),
                    "n_failures": len(failures),
                    "results": [r.as_dict() for r in results],
                },
                fh,
                indent=2,
            )

    if missing:
        logger.error("missing %d baseline case(s)", missing)
        return 3
    if args.mode == "equivalence" and failures:
        logger.error("compare_audio: %d / %d cases regressed beyond atol=%g",
                     len(failures), len(results), args.atol)
        return 1
    logger.info(
        "compare_audio: %d / %d cases within atol=%g (mode=%s)",
        len(results) - len(failures), len(results), args.atol, args.mode,
    )
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(
        level=os.environ.get("COMPARE_AUDIO_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        return 0
    if args.cmd == "capture":
        return _cmd_capture(args)
    if args.cmd == "check":
        return _cmd_check(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
