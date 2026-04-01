"""
TTS Controller

REST API endpoints for Text-to-Speech:
- POST /api/tts/agents/{session_id}/speak — Stream audio synthesis
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
from logging import getLogger
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

logger = getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


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
    """
    from service.vtuber.tts.tts_service import get_tts_service

    tts = get_tts_service()

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
        has_data = False
        try:
            async for chunk in tts.speak(
                text=body.text,
                emotion=body.emotion,
                language=body.language or default_language,
                engine_name=body.engine,
            ):
                if chunk.audio_data:
                    has_data = True
                    yield chunk.audio_data
        except RuntimeError as e:
            logger.error(f"TTS speak error: {e}")
            # 제너레이터 안에서 HTTP 응답을 바꿀 수 없으므로 에러 로그만 남김
            # 아래에서 has_data 체크로 처리

        if not has_data:
            logger.warning(
                f"TTS produced no audio for text='{body.text[:50]}...' "
                f"engine={current_provider}"
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
async def clear_cache():
    """Clear the TTS audio cache"""
    from service.vtuber.tts.cache import get_tts_cache

    get_tts_cache().clear()
    return {"success": True, "message": "TTS cache cleared"}


# ==================== Voice Profile Management ====================

VOICES_DIR = Path(__file__).parent.parent / "static" / "voices"


class CreateProfileRequest(BaseModel):
    """Request body to create a voice profile"""
    name: str
    display_name: str
    language: str = "ko"
    prompt_text: str = ""
    prompt_lang: str = "ko"


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
    profiles = []
    if VOICES_DIR.exists():
        for profile_dir in sorted(VOICES_DIR.iterdir()):
            if not profile_dir.is_dir():
                continue
            profile_json = profile_dir / "profile.json"
            if profile_json.exists():
                try:
                    data = json.loads(profile_json.read_text(encoding="utf-8"))
                    data["has_refs"] = {
                        f.stem.replace("ref_", ""): True
                        for f in profile_dir.glob("ref_*.wav")
                    }
                    profiles.append(data)
                except Exception as e:
                    logger.warning(f"Failed to read profile {profile_dir.name}: {e}")
    return {"profiles": profiles}


@router.get("/profiles/{name}")
async def get_profile(name: str):
    """Get a specific voice profile"""
    profile_dir = VOICES_DIR / name
    if not profile_dir.exists() or not profile_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    profile_json = profile_dir / "profile.json"
    if not profile_json.exists():
        raise HTTPException(status_code=404, detail=f"Profile '{name}' has no profile.json")

    data = json.loads(profile_json.read_text(encoding="utf-8"))
    data["available_refs"] = [f.name for f in profile_dir.glob("ref_*.wav")]
    return data


@router.post("/profiles")
async def create_profile(body: CreateProfileRequest):
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
    (profile_dir / "profile.json").write_text(
        json.dumps(profile_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return profile_data


@router.put("/profiles/{name}")
async def update_profile(name: str, body: UpdateProfileRequest):
    """Update an existing voice profile"""
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

    profile_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return data


@router.post("/profiles/{name}/ref")
async def upload_reference_audio(
    name: str,
    emotion: str = Form(...),
    text: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a reference audio file for a specific emotion"""
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

    # Update profile.json emotion_refs
    profile_json = profile_dir / "profile.json"
    if profile_json.exists():
        data = json.loads(profile_json.read_text(encoding="utf-8"))
        if "emotion_refs" not in data:
            data["emotion_refs"] = {}
        data["emotion_refs"][emotion] = {
            "file": f"ref_{emotion}.wav",
            "text": text,
        }
        profile_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "success": True,
        "profile": name,
        "emotion": emotion,
        "file": f"ref_{emotion}.wav",
        "size": len(content),
    }
