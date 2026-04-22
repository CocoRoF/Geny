"""HTTP routes for the geny-omnivoice service."""

from __future__ import annotations

import base64
import json
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from server import engine, voices
from server.schemas import (
    HealthResponse,
    LanguagesResponse,
    ServiceInfoResponse,
    TTSRequest,
    TTSStreamRequest,
    VoicesResponse,
)
from server.settings import Settings, get_settings
from server.streaming import encode, media_type_for
from server.text_split import split_sentences

logger = logging.getLogger(__name__)

router = APIRouter()


def _service_version() -> str:
    try:
        return version("geny-omnivoice")
    except PackageNotFoundError:  # pragma: no cover - editable installs
        return "0.0.0+local"


@router.get("/", response_model=ServiceInfoResponse)
def root(settings: Annotated[Settings, Depends(get_settings)]) -> ServiceInfoResponse:
    return ServiceInfoResponse(
        service="geny-omnivoice",
        version=_service_version(),
        model=settings.model,
        device=settings.device,
        dtype=settings.dtype,
    )


@router.get("/health", response_model=HealthResponse)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    phase = engine.get_phase()
    # ``status`` is the legacy field; collapse intermediate phases to
    # ``loading`` so old clients that only inspect ``status`` keep
    # working. New clients should consume ``phase`` directly.
    if phase == "ok":
        legacy_status: str = "ok"
    elif phase == "error":
        legacy_status = "error"
    else:
        legacy_status = "loading"

    if not engine.is_loaded():
        return HealthResponse(
            status=legacy_status,  # type: ignore[arg-type]
            phase=phase,  # type: ignore[arg-type]
            model=settings.model,
            device=settings.device,
            dtype=settings.dtype,
            sampling_rate=0,
            auto_asr=settings.auto_asr,
            max_concurrency=settings.max_concurrency,
        )
    state = engine.get_state()
    return HealthResponse(
        status=legacy_status,  # type: ignore[arg-type]
        phase=phase,  # type: ignore[arg-type]
        model=settings.model,
        device=settings.device,
        dtype=settings.dtype,
        sampling_rate=state.sampling_rate,
        auto_asr=settings.auto_asr,
        max_concurrency=settings.max_concurrency,
    )


@router.get("/voices", response_model=VoicesResponse)
def get_voices(settings: Annotated[Settings, Depends(get_settings)]) -> VoicesResponse:
    return VoicesResponse(voices=voices.list_profiles(settings.voices_dir))


@router.get("/languages", response_model=LanguagesResponse)
def get_languages() -> LanguagesResponse:
    from omnivoice_core.utils.lang_map import LANG_NAMES

    return LanguagesResponse(languages=sorted(LANG_NAMES))


@router.post("/tts")
async def tts(req: TTSRequest) -> Response:
    if not engine.is_loaded():
        raise HTTPException(status_code=503, detail="model_not_ready")

    import time as _time
    t0 = _time.monotonic()
    logger.info(
        "tts: starting single-shot synthesis chars=%d mode=%s ref=%s",
        len(req.text or ""), req.mode, req.ref_audio_path or "<none>",
    )

    try:
        audio, sample_rate = await engine.synthesize(
            text=req.text,
            mode=req.mode,
            ref_audio_path=req.ref_audio_path,
            ref_text=req.ref_text,
            instruct=req.instruct,
            language=req.language,
            speed=req.speed,
            duration=req.duration,
            num_step=req.num_step,
            guidance_scale=req.guidance_scale,
            denoise=req.denoise,
            preprocess_prompt=req.preprocess_prompt,
            postprocess_output=req.postprocess_output,
            seed=req.seed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Synthesis failed")
        raise HTTPException(status_code=500, detail=f"synthesis_failed: {exc}") from exc

    synth_dt = _time.monotonic() - t0
    body = encode(audio, sample_rate, req.audio_format)
    audio_seconds = audio.size / float(sample_rate) if sample_rate else 0.0
    rtf = synth_dt / audio_seconds if audio_seconds else float("inf")
    logger.info(
        "tts: done synth=%.2fs audio=%.2fs rtf=%.2f chars=%d",
        synth_dt, audio_seconds, rtf, len(req.text or ""),
    )
    headers = {
        "X-OmniVoice-Sample-Rate": str(sample_rate),
        "X-OmniVoice-Mode": req.mode,
        "X-OmniVoice-Synth-Seconds": f"{synth_dt:.3f}",
        "X-OmniVoice-Audio-Seconds": f"{audio_seconds:.3f}",
        "X-OmniVoice-RTF": f"{rtf:.3f}",
    }
    return Response(content=body, media_type=media_type_for(req.audio_format), headers=headers)


@router.post("/tts/stream")
async def tts_stream(req: TTSStreamRequest) -> StreamingResponse:
    """Sentence-streaming TTS — yields one NDJSON frame per sentence.

    Wire format (each line a complete JSON object, newline-terminated):

    * ``{"seq": 0, "text": "Hello.", "format": "wav", "sample_rate": 24000,
      "audio_b64": "<base64 of WAV bytes>", ...}``
    * ``{"seq": 1, "text": "How are you?", ...}``
    * ``{"done": true, "total": 2, "sample_rate": 24000}``
      — terminator frame so clients know the stream finished cleanly.

    On a per-sentence error: a ``{"seq": N, "error": "..."}`` frame is
    emitted but the loop continues; subsequent sentences are still
    streamed. The terminator frame still includes the per-sentence
    success ``total``.

    Latency model: client receives sentence #1 once it's fully
    synthesised (single-GPU semaphore prevents pipelining), then #2,
    etc. For a 3-sentence response that would take ~25s as a single
    /tts call, the listener now hears speech start at ~8s instead.
    """
    if not engine.is_loaded():
        raise HTTPException(status_code=503, detail="model_not_ready")

    sentences = split_sentences(
        req.text,
        max_chars=req.max_sentence_chars,
        min_chars=req.min_sentence_chars,
    )
    if not sentences:
        raise HTTPException(status_code=400, detail="empty_text")

    sample_rate = req.sample_rate
    media = media_type_for(req.audio_format)
    total_chars = sum(len(s) for s in sentences)
    logger.info(
        "tts/stream: starting %d sentences, %d total chars "
        "(input_len=%d, max=%d, min=%d, mode=%s, ref=%s)",
        len(sentences), total_chars, len(req.text or ""),
        req.max_sentence_chars, req.min_sentence_chars,
        req.mode, req.ref_audio_path or "<none>",
    )
    # Per-sentence char counts at debug level — invaluable for tuning
    # the min_sentence_chars knob ("did the merge actually fire?").
    logger.debug(
        "tts/stream: chunk lengths = %s",
        [len(s) for s in sentences],
    )

    async def _gen():
        import time as _time
        success = 0
        stream_t0 = _time.monotonic()
        for seq, sentence in enumerate(sentences):
            sentence_seed = (
                req.seed + seq if (req.seed is not None and req.seed_jitter)
                else req.seed
            )
            sent_t0 = _time.monotonic()
            try:
                audio, sr = await engine.synthesize(
                    text=sentence,
                    mode=req.mode,
                    ref_audio_path=req.ref_audio_path,
                    ref_text=req.ref_text,
                    instruct=req.instruct,
                    language=req.language,
                    speed=req.speed,
                    duration=None,  # let model size each sentence naturally
                    num_step=req.num_step,
                    guidance_scale=req.guidance_scale,
                    denoise=req.denoise,
                    preprocess_prompt=req.preprocess_prompt,
                    postprocess_output=req.postprocess_output,
                    seed=sentence_seed,
                )
                synth_dt = _time.monotonic() - sent_t0
                body = encode(audio, sr, req.audio_format)
                audio_seconds = audio.size / float(sr) if sr else 0.0
                rtf = synth_dt / audio_seconds if audio_seconds else float("inf")
                logger.info(
                    "tts/stream: seq=%d/%d synth=%.2fs audio=%.2fs rtf=%.2f chars=%d text=%r",
                    seq, len(sentences) - 1, synth_dt, audio_seconds, rtf,
                    len(sentence), sentence[:60],
                )
                frame = {
                    "seq": seq,
                    "text": sentence,
                    "format": req.audio_format,
                    "media_type": media,
                    "sample_rate": int(sr),
                    "n_samples": int(audio.size),
                    "audio_b64": base64.b64encode(body).decode("ascii"),
                }
                success += 1
            except Exception as exc:  # pragma: no cover - logged below
                logger.exception(
                    "tts/stream: seq=%d failed after %.2fs",
                    seq, _time.monotonic() - sent_t0,
                )
                frame = {"seq": seq, "text": sentence, "error": str(exc)}
            yield (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
        total_dt = _time.monotonic() - stream_t0
        logger.info(
            "tts/stream: done %d/%d sentences in %.2fs (avg %.2fs/sentence)",
            success, len(sentences), total_dt,
            (total_dt / max(1, len(sentences))),
        )
        terminator = {
            "done": True,
            "total": success,
            "requested": len(sentences),
            "sample_rate": int(sample_rate),
            "elapsed_seconds": round(total_dt, 3),
        }
        yield (json.dumps(terminator) + "\n").encode("utf-8")

    return StreamingResponse(
        _gen(),
        media_type="application/x-ndjson",
        headers={
            "X-OmniVoice-Streaming": "sentence-ndjson",
            "X-OmniVoice-Sample-Rate": str(sample_rate),
            "X-OmniVoice-Sentence-Count": str(len(sentences)),
            "Cache-Control": "no-cache",
        },
    )
