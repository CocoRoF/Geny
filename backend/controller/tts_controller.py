"""
TTS Controller

REST API endpoints for Text-to-Speech:
- POST /api/tts/agents/{session_id}/speak — Stream audio synthesis
- GET  /api/tts/agents/{session_id}/profile — Get session voice profile
- PUT  /api/tts/agents/{session_id}/profile — Assign voice profile to session
- DELETE /api/tts/agents/{session_id}/profile — Remove session voice profile
- GET  /api/tts/voices                     — List available voices
- GET  /api/tts/voices/{engine}/{voice_id}/preview — Preview a voice
- GET  /api/tts/status                     — Engine health status
- GET  /api/tts/engines                    — List registered engines
- GET  /api/tts/cache/stats                — Cache statistics
- DELETE /api/tts/cache                    — Clear cache
- GET  /api/tts/profiles                   — List voice profiles
- GET  /api/tts/profiles/{name}            — Get profile detail
- POST /api/tts/profiles                   — Create profile
- PUT  /api/tts/profiles/{name}            — Update profile
"""

import json
import os
import shutil
from logging import getLogger
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

from service.auth.auth_middleware import require_auth
from service.utils.text_sanitizer import sanitize_for_display

logger = getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


def sanitize_tts_text(text: str) -> str:
    """Back-compat shim — delegates to the shared display sanitizer.

    Kept under this name so any external caller / stable import path
    continues to work. The underlying behaviour (strip routing tags +
    emotion tags + ``<think>`` blocks, collapse whitespace) is
    identical to ``sanitize_for_display``.
    """
    return sanitize_for_display(text)


def _atomic_write_json(path: Path, data: dict) -> None:
    """profile.json을 atomic하게 쓰기. tmp 파일에 쓴 후 rename하여 TOCTOU 방지."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(str(tmp), str(path))


class SpeakRequest(BaseModel):
    """Request body for TTS speak endpoint"""
    text: str
    emotion: str = "neutral"
    language: Optional[str] = None
    engine: Optional[str] = None


@router.post("/agents/{session_id}/speak")
async def speak(session_id: str, body: SpeakRequest):
    """
    Synthesize text to speech and return streaming audio.

    The active TTS engine is determined by Config (tts_general.provider),
    unless overridden by the `engine` field in the request body.
    Uses per-session voice profile if assigned, else global config.
    """
    # 시스템 마커, 감정 태그, think 블록 제거
    cleaned_text = sanitize_tts_text(body.text)
    if not cleaned_text:
        return JSONResponse(status_code=204, content={"detail": "No speakable text after sanitization"})

    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()

    # Look up per-session voice profile
    session_voice_profile = None
    try:
        from service.claude_manager.session_store import get_session_store
        session = get_session_store().get(session_id)
        if session:
            session_voice_profile = session.get("tts_voice_profile")
    except Exception as e:
        logger.debug(f"Failed to look up session voice profile: {e}")

    # Determine content type from Config
    content_type = "audio/mpeg"
    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

        general = get_config_manager().load_config(TTSGeneralConfig)
        content_type = {
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
        }.get(general.audio_format, "audio/mpeg")
        default_language = general.default_language
        current_provider = general.provider

        # GPT-SoVITS v1 api.py always returns wav regardless of config
        if current_provider == "gpt_sovits":
            content_type = "audio/wav"
    except Exception:
        default_language = "ko"
        current_provider = "edge_tts"

    async def audio_generator():
        import time as _time
        has_data = False
        bytes_sent = 0
        t0 = _time.monotonic()
        first_byte_at = None
        try:
            async for chunk in tts.speak(
                text=cleaned_text,
                emotion=body.emotion,
                language=body.language or default_language,
                engine_name=body.engine,
                voice_profile=session_voice_profile,
            ):
                if chunk.audio_data:
                    if first_byte_at is None:
                        first_byte_at = _time.monotonic() - t0
                    has_data = True
                    bytes_sent += len(chunk.audio_data)
                    yield chunk.audio_data
        except RuntimeError as e:
            logger.error(f"TTS speak error: {e}")

        total_dt = _time.monotonic() - t0
        if not has_data:
            logger.warning(
                f"TTS produced no audio for text='{cleaned_text[:50]}...' "
                f"engine={current_provider} elapsed={total_dt:.2f}s"
            )
        else:
            logger.info(
                "speak: done engine=%s chars=%d bytes=%d total=%.2fs first_byte=%.2fs",
                current_provider, len(cleaned_text), bytes_sent, total_dt,
                first_byte_at if first_byte_at is not None else -1.0,
            )

    # speak() 내부에서 health check + fallback 처리하므로 별도 pre-flight 불필요

    return StreamingResponse(
        audio_generator(),
        media_type=content_type,
        headers={
            "Transfer-Encoding": "chunked",
            "Cache-Control": "no-cache",
            "X-TTS-Engine": current_provider,
        },
    )


@router.post("/agents/{session_id}/speak/stream")
async def speak_stream(session_id: str, body: SpeakRequest):
    """Sentence-streaming TTS — NDJSON envelope.

    Each line is a complete JSON object:

    * ``{"seq": N, "text": str, "format": "wav", "sample_rate": int,
      "audio_b64": str}`` — one fully-rendered sentence
    * ``{"seq": N, "text": str, "error": str}`` — per-sentence failure
      (stream continues)
    * ``{"done": true, "total": int, "elapsed_seconds": float}`` — terminator

    Whether to actually stream sentence-by-sentence is governed by
    ``tts_general.streaming_mode``:

    * ``off``    — return a single ``seq=0`` frame containing the whole
                   utterance (lowest TOTAL latency; no per-sentence
                   model setup overhead).
    * ``auto``   — stream only when text length ≥ ``streaming_min_chars``.
    * ``always`` — always sentence-by-sentence (lowest first-byte
                   latency).

    Engines that don't natively support sentence streaming
    transparently emit a single ``seq=0`` frame regardless of mode —
    no client-side branching needed.
    """
    import base64
    import time

    cleaned_text = sanitize_tts_text(body.text)
    if not cleaned_text:
        return JSONResponse(
            status_code=204, content={"detail": "No speakable text after sanitization"}
        )

    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()

    # Per-session voice profile lookup (same as /speak).
    session_voice_profile = None
    try:
        from service.claude_manager.session_store import get_session_store
        session = get_session_store().get(session_id)
        if session:
            session_voice_profile = session.get("tts_voice_profile")
    except Exception as e:
        logger.debug(f"Failed to look up session voice profile: {e}")

    default_language = "ko"
    current_provider = "edge_tts"
    streaming_mode = "off"
    streaming_min_chars = 80
    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

        general = get_config_manager().load_config(TTSGeneralConfig)
        default_language = general.default_language
        current_provider = general.provider
        streaming_mode = (general.streaming_mode or "off").lower()
        streaming_min_chars = int(general.streaming_min_chars or 80)
    except Exception:
        pass

    # Decide whether to actually stream sentence-by-sentence or batch
    # the whole utterance. Single-shot is faster end-to-end on
    # Pascal-class GPUs because there's no per-sentence model setup
    # overhead — we keep this as the default.
    use_sentence_stream = False
    if streaming_mode == "always":
        use_sentence_stream = True
    elif streaming_mode == "auto":
        use_sentence_stream = len(cleaned_text) >= streaming_min_chars

    logger.info(
        "speak/stream: session=%s engine=%s chars=%d mode=%s -> sentence_stream=%s",
        session_id, body.engine or current_provider, len(cleaned_text),
        streaming_mode, use_sentence_stream,
    )

    async def ndjson_generator():
        emitted = 0
        t0 = time.monotonic()
        first_emit_at = None
        try:
            if use_sentence_stream:
                async for chunk in tts.speak_sentences(
                    text=cleaned_text,
                    emotion=body.emotion,
                    language=body.language or default_language,
                    engine_name=body.engine,
                    voice_profile=session_voice_profile,
                ):
                    if chunk.is_final and not chunk.audio_data and chunk.error is None:
                        continue
                    if chunk.error is not None:
                        frame = {
                            "seq": chunk.seq,
                            "text": chunk.text,
                            "error": chunk.error,
                        }
                    else:
                        frame = {
                            "seq": chunk.seq,
                            "text": chunk.text,
                            "format": chunk.audio_format,
                            "sample_rate": chunk.sample_rate,
                            "audio_b64": base64.b64encode(chunk.audio_data).decode("ascii"),
                        }
                        emitted += 1
                        if first_emit_at is None:
                            first_emit_at = time.monotonic() - t0
                            logger.info(
                                "speak/stream: first sentence emitted at %.2fs",
                                first_emit_at,
                            )
                    yield (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
            else:
                # Single-shot path — collect the whole utterance via
                # legacy ``speak`` and emit it as one ``seq=0`` frame.
                # Same wire format, so the client doesn't care.
                engine = tts.get_engine(body.engine)
                if engine is None:
                    raise RuntimeError("No TTS engine available")
                from service.vtuber.tts.base import (
                    AudioFormat as _AF, TTSRequest as _TR,
                )
                req = _TR(
                    text=cleaned_text,
                    emotion=body.emotion,
                    language=(body.language or default_language) or "ko",
                    audio_format=_AF.WAV,
                    voice_profile=session_voice_profile,
                )
                req = await engine.apply_emotion(req)
                audio = await engine.synthesize(req)
                first_emit_at = time.monotonic() - t0
                emitted = 1
                logger.info(
                    "speak/stream: single-shot synthesis done in %.2fs "
                    "(%d audio bytes)", first_emit_at, len(audio),
                )
                frame = {
                    "seq": 0,
                    "text": cleaned_text,
                    "format": req.audio_format.value,
                    "sample_rate": req.sample_rate,
                    "audio_b64": base64.b64encode(audio).decode("ascii"),
                }
                yield (json.dumps(frame, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception as e:
            logger.exception("speak_stream generator failed: %r", e)
            err_frame = {"seq": -1, "error": f"{type(e).__name__}: {e}"}
            yield (json.dumps(err_frame) + "\n").encode("utf-8")

        total_dt = time.monotonic() - t0
        logger.info(
            "speak/stream: done emitted=%d total=%.2fs first_emit=%.2fs",
            emitted, total_dt, first_emit_at if first_emit_at is not None else -1.0,
        )
        terminator = {
            "done": True,
            "total": emitted,
            "elapsed_seconds": round(total_dt, 3),
            "first_emit_seconds": round(first_emit_at, 3) if first_emit_at is not None else None,
            "mode": "sentence" if use_sentence_stream else "single",
        }
        yield (json.dumps(terminator) + "\n").encode("utf-8")

    return StreamingResponse(
        ndjson_generator(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-TTS-Engine": current_provider,
            "X-TTS-Streaming": "sentence-ndjson" if use_sentence_stream else "single-ndjson",
            "X-TTS-Streaming-Mode": streaming_mode,
        },
    )


# ==================== Per-Session Voice Profile ====================

class AssignProfileRequest(BaseModel):
    """Request body to assign a voice profile to a session"""
    profile_name: str


@router.get("/agents/{session_id}/profile")
async def get_session_profile(session_id: str):
    """Get the voice profile assigned to a session."""
    from service.claude_manager.session_store import get_session_store

    session = get_session_store().get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": session_id,
        "tts_voice_profile": session.get("tts_voice_profile"),
    }


@router.put("/agents/{session_id}/profile")
async def assign_session_profile(session_id: str, body: AssignProfileRequest, auth: dict = Depends(require_auth)):
    """Assign a voice profile to a VTuber session.

    Stores the profile name in the session's extra_data JSON blob.
    """
    from service.claude_manager.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate profile exists
    profile_dir = VOICES_DIR / body.profile_name
    if not profile_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Voice profile '{body.profile_name}' not found")

    store.update(session_id, {"tts_voice_profile": body.profile_name})
    logger.info(f"Assigned voice profile '{body.profile_name}' to session {session_id}")

    return {"success": True, "session_id": session_id, "tts_voice_profile": body.profile_name}


@router.delete("/agents/{session_id}/profile")
async def unassign_session_profile(session_id: str, auth: dict = Depends(require_auth)):
    from service.claude_manager.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    store.update(session_id, {"tts_voice_profile": ""})
    logger.info(f"Unassigned voice profile from session {session_id}")

    return {"success": True, "session_id": session_id}


@router.get("/voices")
async def list_voices(language: Optional[str] = None):
    """List available voices from all healthy engines"""
    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()
    voices = await tts.get_all_voices(language)

    # Convert VoiceInfo dataclasses to dicts
    result = {}
    for engine_name, voice_list in voices.items():
        result[engine_name] = [
            {
                "id": v.id,
                "name": v.name,
                "language": v.language,
                "gender": v.gender,
                "engine": v.engine,
                "preview_text": v.preview_text,
            }
            for v in voice_list
        ]
    return result


@router.get("/voices/{engine}/{voice_id}/preview")
async def preview_voice(
    engine: str,
    voice_id: str,
    text: str = "안녕하세요, 반갑습니다.",
):
    """Preview a specific voice with sample text"""
    from service.vtuber.tts.tts_service import get_tts_service
    from service.vtuber.tts.base import TTSRequest

    tts = get_tts_service()
    engine_instance = tts.get_engine(engine)
    if not engine_instance:
        raise HTTPException(status_code=404, detail=f"Engine '{engine}' not found")

    request = TTSRequest(text=text, emotion="neutral")
    try:
        audio_data = await engine_instance.synthesize(request)
    except Exception as e:
        logger.error(f"Voice preview failed: {e}")
        raise HTTPException(status_code=500, detail="Voice preview failed")

    return StreamingResponse(
        iter([audio_data]),
        media_type="audio/mpeg",
    )


@router.get("/status")
async def get_status():
    """Get health status of all TTS engines"""
    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()
    return await tts.get_status()


@router.get("/engines")
async def list_engines():
    """List registered TTS engines and the current default"""
    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()

    default_provider = "edge_tts"
    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

        general = get_config_manager().load_config(TTSGeneralConfig)
        default_provider = general.provider
    except Exception:
        pass

    return {
        "engines": list(tts._engines.keys()),
        "default": default_provider,
    }


@router.get("/cache/stats")
async def get_cache_stats():
    """Get TTS audio cache statistics"""
    from service.vtuber.tts.cache import get_tts_cache

    return get_tts_cache().stats()


@router.delete("/cache")
async def clear_cache(auth: dict = Depends(require_auth)):
    """Clear the TTS audio cache"""
    from service.vtuber.tts.cache import get_tts_cache

    get_tts_cache().clear()
    return {"success": True, "message": "TTS cache cleared"}


# ==================== Voice Profile Management ====================

VOICES_DIR = Path(__file__).parent.parent / "static" / "voices"

# Built-in template profiles — auto-created if directory exists but profile.json is missing.
_BUILTIN_PROFILES = {
    "paimon_ko": {
        "name": "paimon_ko",
        "display_name": "파이몬 (한국어)",
        "language": "ko",
        "is_template": True,
        "prompt_text": "으음~ 나쁘지 않은데? 너도 먹어봐~ 우리 같이 먹자!",
        "prompt_lang": "ko",
        "emotion_refs": {
            "neutral": {
                "file": "ref_neutral.wav",
                "prompt_text": "으음~ 나쁘지 않은데? 너도 먹어봐~ 우리 같이 먹자!",
                "prompt_lang": "ko",
            },
            "joy": {
                "file": "ref_joy.wav",
                "prompt_text": "우와아——! 이건 세상에서 제일 맛있는 요리야! 이히힛, 역시 네가 최고야!",
                "prompt_lang": "ko",
            },
        },
    },
    "ruan_mei": {
        "name": "ruan_mei",
        "display_name": "완매 (한국어)",
        "language": "ko",
        "is_template": True,
        "prompt_text": "먹어 볼래? 이건 새로 절인 매화로 만든 디저트야. 이거 사려고 줄을 한참이나 섰다고",
        "prompt_lang": "ko",
        "emotion_refs": {
            "neutral": {
                "file": "ref_neutral.wav",
                "prompt_text": "먹어 볼래? 이건 새로 절인 매화로 만든 디저트야. 이거 사려고 줄을 한참이나 섰다고",
                "prompt_lang": "ko",
            },
            "joy": {
                "file": "ref_joy.wav",
                "prompt_text": "현대 음악은 내 취향이 아니지만, 전통극에는 푹 빠져들어. 현이 떨리는 순간, 시간이 과거로 흐르지",
                "prompt_lang": "ko",
            },
        },
    },
    "ellen_joe": {
        "name": "ellen_joe",
        "display_name": "엘렌 조 (한국어)",
        "language": "ko",
        "is_template": True,
        "prompt_text": "단거를 먹으면 체력이 보충되거든요, 하지만 몸무게가 쉽게 늘죠",
        "prompt_lang": "ko",
        "emotion_refs": {
            "neutral": {
                "file": "ref_neutral.wav",
                "prompt_text": "단거를 먹으면 체력이 보충되거든요, 하지만 몸무게가 쉽게 늘죠",
                "prompt_lang": "ko",
            },
            "anger": {
                "file": "ref_anger.wav",
                "prompt_text": "저기요, 소리내서 말하지 말아요. 왜 그런 눈으로 보는거죠? 어딜보는거에요",
                "prompt_lang": "ko",
            },
        },
    },
}


# Seed directory lives outside the Docker named-volume mount, so its files
# are always available from the image even when the volume already exists.
_BUILTIN_SOURCE_DIR = Path(__file__).parent.parent / "static" / "voices_seed"


def _ensure_builtin_profiles() -> None:
    """Auto-create builtin voice profile directories, audio files, and profile.json.

    On Docker named-volume deployments the volume may already exist from a
    previous image that did not include a new builtin preset.  This function
    copies the full preset directory from the *image source* (``static/voices/``)
    into the runtime ``VOICES_DIR`` so that newly added presets always appear.
    """
    for name, data in _BUILTIN_PROFILES.items():
        profile_dir = VOICES_DIR / name
        source_dir = _BUILTIN_SOURCE_DIR / name

        # --- directory ---
        if not profile_dir.is_dir():
            if source_dir.is_dir():
                try:
                    shutil.copytree(source_dir, profile_dir)
                    logger.info(f"Copied builtin voice directory: {name}")
                    continue  # copytree already includes profile.json
                except Exception as e:
                    logger.warning(f"Failed to copy builtin voice directory {name}: {e}")
                    continue
            else:
                # Source not available (shouldn't happen in production)
                continue

        # --- ref audio files ---
        emotion_refs = data.get("emotion_refs", {})
        for _emotion, ref in emotion_refs.items():
            ref_file = ref.get("file", "")
            if not ref_file:
                continue
            dest = profile_dir / ref_file
            src = source_dir / ref_file
            if not dest.exists() and src.exists():
                try:
                    shutil.copy2(src, dest)
                    logger.info(f"Copied missing ref audio {ref_file} for {name}")
                except Exception as e:
                    logger.warning(f"Failed to copy ref audio {ref_file} for {name}: {e}")

        # --- profile.json ---
        profile_json = profile_dir / "profile.json"
        if not profile_json.exists():
            try:
                _atomic_write_json(profile_json, data)
                logger.info(f"Auto-created profile.json for built-in profile: {name}")
            except Exception as e:
                logger.warning(f"Failed to auto-create profile.json for {name}: {e}")


def _is_template_profile(name: str) -> bool:
    """Check if a voice profile is marked as a template (read-only)."""
    profile_json = VOICES_DIR / name / "profile.json"
    if profile_json.exists():
        try:
            data = json.loads(profile_json.read_text(encoding="utf-8"))
            return bool(data.get("is_template", False))
        except Exception:
            pass
    return False


def _guard_template(name: str) -> None:
    """Raise 403 if the profile is a template."""
    if _is_template_profile(name):
        raise HTTPException(
            status_code=403,
            detail=f"Profile '{name}' is a built-in template and cannot be modified.",
        )


def _migrate_emotion_refs(data: dict) -> None:
    """Ensure each emotion_ref entry has prompt_text/prompt_lang fields.

    Legacy entries only had {"file": "...", "text": "..."}, so we back-fill
    from the profile-level prompt_text/prompt_lang as fallback.
    """
    emotion_refs = data.get("emotion_refs")
    if not isinstance(emotion_refs, dict):
        return
    fallback_text = data.get("prompt_text", "")
    fallback_lang = data.get("prompt_lang", "ko")
    for _emotion, ref in emotion_refs.items():
        if not isinstance(ref, dict):
            continue
        if "prompt_text" not in ref:
            # Migrate legacy "text" field → "prompt_text"
            ref["prompt_text"] = ref.pop("text", "") or fallback_text
        if "prompt_lang" not in ref:
            ref["prompt_lang"] = fallback_lang


class CreateProfileRequest(BaseModel):
    """Request body to create a voice profile"""
    name: str
    display_name: str
    language: str = "ko"
    prompt_text: str = ""
    prompt_lang: str = "ko"


class UpdateEmotionRefRequest(BaseModel):
    """Request body to update a single emotion ref's prompt"""
    prompt_text: Optional[str] = None
    prompt_lang: Optional[str] = None


class UpdateProfileRequest(BaseModel):
    """Request body to update a voice profile"""
    display_name: Optional[str] = None
    language: Optional[str] = None
    prompt_text: Optional[str] = None
    prompt_lang: Optional[str] = None
    gpt_sovits_settings: Optional[dict] = None


@router.get("/profiles")
async def list_profiles():
    """List all voice profiles"""
    _ensure_builtin_profiles()
    profiles = []
    if VOICES_DIR.exists():
        for profile_dir in sorted(VOICES_DIR.iterdir()):
            if not profile_dir.is_dir():
                continue
            profile_json = profile_dir / "profile.json"
            refs = {f.stem.replace("ref_", ""): True for f in profile_dir.glob("ref_*.wav")}
            if profile_json.exists():
                try:
                    data = json.loads(profile_json.read_text(encoding="utf-8"))
                    data["has_refs"] = refs
                    # Ensure emotion_refs have per-emotion prompt fields
                    _migrate_emotion_refs(data)
                    profiles.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read profile {profile_dir.name}: {e}")
            else:
                # Legacy directory without profile.json — auto-generate metadata
                profiles.append({
                    "name": profile_dir.name,
                    "display_name": profile_dir.name,
                    "language": "ko",
                    "prompt_text": "",
                    "prompt_lang": "ko",
                    "emotion_refs": {},
                    "has_refs": refs,
                })

    # Mark which profile is currently active in GPT-SoVITS config
    active_dir = ""
    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.gpt_sovits_config import GPTSoVITSConfig

        cfg = get_config_manager().load_config(GPTSoVITSConfig)
        active_dir = os.path.basename(cfg.ref_audio_dir.rstrip("/"))
    except Exception:
        pass

    for p in profiles:
        p["active"] = p.get("name") == active_dir

    return {"profiles": profiles}


@router.get("/profiles/{name}")
async def get_profile(name: str):
    """Get a specific voice profile"""
    profile_dir = VOICES_DIR / name
    if not profile_dir.exists() or not profile_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    _ensure_builtin_profiles()

    profile_json = profile_dir / "profile.json"
    if profile_json.exists():
        data = json.loads(profile_json.read_text(encoding="utf-8"))
    else:
        # Graceful fallback for directories without profile.json
        data = {
            "name": name,
            "display_name": name,
            "language": "ko",
            "prompt_text": "",
            "prompt_lang": "ko",
            "emotion_refs": {},
        }

    data["available_refs"] = [f.name for f in profile_dir.glob("ref_*.wav")]
    data["has_refs"] = {f.stem.replace("ref_", ""): True for f in profile_dir.glob("ref_*.wav")}
    _migrate_emotion_refs(data)
    return data


@router.post("/profiles")
async def create_profile(body: CreateProfileRequest, auth: dict = Depends(require_auth)):
    """Create a new voice profile directory with profile.json"""
    profile_dir = VOICES_DIR / body.name
    if profile_dir.exists():
        raise HTTPException(status_code=409, detail=f"Profile '{body.name}' already exists")

    profile_dir.mkdir(parents=True, exist_ok=True)

    profile_data = {
        "name": body.name,
        "display_name": body.display_name,
        "language": body.language,
        "prompt_text": body.prompt_text,
        "prompt_lang": body.prompt_lang,
        "emotion_refs": {},
        "gpt_sovits_settings": {
            "top_k": 5,
            "top_p": 1.0,
            "temperature": 1.0,
            "speed_factor": 1.0,
        },
    }
    _atomic_write_json(profile_dir / "profile.json", profile_data)
    return profile_data


@router.put("/profiles/{name}")
async def update_profile(name: str, body: UpdateProfileRequest, auth: dict = Depends(require_auth)):
    """Update an existing voice profile"""
    _guard_template(name)
    profile_dir = VOICES_DIR / name
    profile_json = profile_dir / "profile.json"
    if not profile_json.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    data = json.loads(profile_json.read_text(encoding="utf-8"))

    if body.display_name is not None:
        data["display_name"] = body.display_name
    if body.language is not None:
        data["language"] = body.language
    if body.prompt_text is not None:
        data["prompt_text"] = body.prompt_text
    if body.prompt_lang is not None:
        data["prompt_lang"] = body.prompt_lang
    if body.gpt_sovits_settings is not None:
        data["gpt_sovits_settings"] = body.gpt_sovits_settings

    _atomic_write_json(profile_json, data)
    return data


@router.post("/profiles/{name}/ref")
async def upload_reference_audio(
    name: str,
    emotion: str = Form(...),
    text: str = Form(""),
    lang: str = Form(""),
    file: UploadFile = File(...),
    auth: dict = Depends(require_auth),
):
    """Upload a reference audio file for a specific emotion"""
    _guard_template(name)
    profile_dir = VOICES_DIR / name
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    # Validate emotion
    valid_emotions = {"neutral", "joy", "anger", "sadness", "fear", "surprise", "disgust", "smirk"}
    if emotion not in valid_emotions:
        raise HTTPException(status_code=400, detail=f"Invalid emotion: {emotion}")

    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=400, detail="Only .wav files are accepted")

    # Save file
    ref_path = profile_dir / f"ref_{emotion}.wav"
    content = await file.read()
    ref_path.write_bytes(content)

    # Update profile.json emotion_refs with per-emotion prompt
    profile_json = profile_dir / "profile.json"
    if profile_json.exists():
        data = json.loads(profile_json.read_text(encoding="utf-8"))
        if "emotion_refs" not in data:
            data["emotion_refs"] = {}
        data["emotion_refs"][emotion] = {
            "file": f"ref_{emotion}.wav",
            "prompt_text": text or data["emotion_refs"].get(emotion, {}).get("prompt_text", ""),
            "prompt_lang": lang or data["emotion_refs"].get(emotion, {}).get("prompt_lang", data.get("prompt_lang", "ko")),
        }
        _atomic_write_json(profile_json, data)

    return {
        "success": True,
        "profile": name,
        "emotion": emotion,
        "file": f"ref_{emotion}.wav",
        "size": len(content),
    }


@router.delete("/profiles/{name}/ref/{emotion}")
async def delete_reference_audio(name: str, emotion: str, auth: dict = Depends(require_auth)):
    """Delete a reference audio file for a specific emotion"""
    _guard_template(name)
    # Validate name to prevent path traversal
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid profile name")

    profile_dir = VOICES_DIR / name
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    ref_path = profile_dir / f"ref_{emotion}.wav"
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail=f"Reference audio for '{emotion}' not found")

    ref_path.unlink()

    # Update profile.json
    profile_json = profile_dir / "profile.json"
    if profile_json.exists():
        data = json.loads(profile_json.read_text(encoding="utf-8"))
        if "emotion_refs" in data and emotion in data["emotion_refs"]:
            del data["emotion_refs"][emotion]
            _atomic_write_json(profile_json, data)

    return {"success": True, "profile": name, "emotion": emotion}


@router.get("/profiles/{name}/ref/{emotion}/audio")
async def get_reference_audio(name: str, emotion: str):
    """Stream a reference audio file for playback"""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid profile name")

    ref_path = VOICES_DIR / name / f"ref_{emotion}.wav"
    if not ref_path.exists():
        raise HTTPException(status_code=404, detail=f"Reference audio for '{emotion}' not found")

    return StreamingResponse(
        open(ref_path, "rb"),
        media_type="audio/wav",
        headers={"Content-Disposition": f'inline; filename="ref_{emotion}.wav"'},
    )


@router.put("/profiles/{name}/ref/{emotion}")
async def update_emotion_ref(name: str, emotion: str, body: UpdateEmotionRefRequest, auth: dict = Depends(require_auth)):
    """Update prompt_text / prompt_lang for a single emotion reference"""
    _guard_template(name)
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid profile name")

    profile_dir = VOICES_DIR / name
    profile_json = profile_dir / "profile.json"
    if not profile_json.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    data = json.loads(profile_json.read_text(encoding="utf-8"))
    if "emotion_refs" not in data:
        data["emotion_refs"] = {}
    if emotion not in data["emotion_refs"]:
        data["emotion_refs"][emotion] = {"file": f"ref_{emotion}.wav"}

    if body.prompt_text is not None:
        data["emotion_refs"][emotion]["prompt_text"] = body.prompt_text
    if body.prompt_lang is not None:
        data["emotion_refs"][emotion]["prompt_lang"] = body.prompt_lang

    _atomic_write_json(profile_json, data)
    return {"success": True, "profile": name, "emotion": emotion, "ref": data["emotion_refs"][emotion]}


@router.post("/profiles/{name}/activate")
async def activate_profile(name: str, auth: dict = Depends(require_auth)):
    """Set a voice profile as the active GPT-SoVITS voice"""
    # Validate name to prevent path traversal
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid profile name")

    profile_dir = VOICES_DIR / name
    if not profile_dir.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    try:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.gpt_sovits_config import GPTSoVITSConfig

        mgr = get_config_manager()
        cfg = mgr.load_config(GPTSoVITSConfig)

        # Update voice_profile (new) + legacy path fields for compatibility
        cfg.voice_profile = name
        cfg.ref_audio_dir = f"/app/static/voices/{name}"
        cfg.container_ref_dir = f"/workspace/GPT-SoVITS/references/{name}"

        # Update prompt from profile.json if available
        profile_json = profile_dir / "profile.json"
        if profile_json.exists():
            data = json.loads(profile_json.read_text(encoding="utf-8"))
            if data.get("prompt_text"):
                cfg.prompt_text = data["prompt_text"]
            if data.get("prompt_lang"):
                cfg.prompt_lang = data["prompt_lang"]

        mgr.save_config(cfg)
        logger.info(f"Activated voice profile: {name}")

        return {
            "success": True,
            "profile": name,
            "ref_audio_dir": cfg.ref_audio_dir,
            "container_ref_dir": cfg.container_ref_dir,
        }
    except Exception as e:
        logger.error(f"Failed to activate profile '{name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))
