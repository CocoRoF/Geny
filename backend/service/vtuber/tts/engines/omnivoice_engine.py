"""
OmniVoice TTS Engine — Geny adapter for the in-cluster ``geny-omnivoice`` service.

Connects to the FastAPI server defined under ``Geny/omnivoice/server/`` via HTTP.
Supports voice cloning (``mode=clone``), voice design (``mode=design``),
and auto voice (``mode=auto``).

Compatible with the same ``static/voices/<profile>/profile.json`` layout
used by ``GPTSoVITSEngine`` so existing voice profiles work unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
from logging import getLogger
from typing import AsyncIterator, Optional

import httpx

from service.vtuber.tts.base import (
    AudioFormat,
    TTSChunk,
    TTSEngine,
    TTSRequest,
    VoiceInfo,
)

logger = getLogger(__name__)


# ── Concurrency guard ────────────────────────────────────────────────
# Defense-in-depth: the geny-omnivoice service already gates GPU access
# with its own asyncio.Semaphore (OMNIVOICE_MAX_CONCURRENCY), but we keep
# a module-level lock here too, mirroring the GPTSoVITSEngine pattern.
_synthesis_lock = asyncio.Lock()


# ── Voice-profile filesystem layout (shared with GPT-SoVITS) ─────────
# Backend path:   /app/static/voices/<profile>/...
# omnivoice path: /voices/<profile>/...   (read-only bind from same source)
_BACKEND_VOICES_ROOT = "/app/static/voices"
_OMNIVOICE_VOICES_ROOT = "/voices"


def _container_ref_path(profile: str, file: str) -> str:
    return f"{_OMNIVOICE_VOICES_ROOT}/{profile}/{file}"


def _backend_profile_dir(profile: str) -> str:
    return f"{_BACKEND_VOICES_ROOT}/{profile}"


def _read_profile_json(profile: str) -> dict:
    path = os.path.join(_backend_profile_dir(profile), "profile.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception:  # pragma: no cover - defensive
        logger.warning("Failed to parse profile.json for %s", profile, exc_info=True)
        return {}


def _resolve_emotion_ref(profile: str, emotion: str) -> tuple[Optional[str], str, str]:
    """Return (container_ref_path, prompt_text, prompt_lang) for ``emotion``.

    Falls back to ``neutral``, then to any registered emotion, then to a
    naive ``ref_<emotion>.wav`` filename.
    """
    if not profile:
        return (None, "", "")

    profile_dir = _backend_profile_dir(profile)
    data = _read_profile_json(profile)
    emotion_refs = data.get("emotion_refs", {}) if isinstance(data, dict) else {}

    def _try(emo: str) -> tuple[Optional[str], str, str] | None:
        meta = emotion_refs.get(emo) if isinstance(emotion_refs, dict) else None
        if isinstance(meta, dict):
            file = meta.get("file") or f"ref_{emo}.wav"
            full_local = os.path.join(profile_dir, file)
            if os.path.isfile(full_local):
                return (
                    _container_ref_path(profile, file),
                    meta.get("prompt_text") or "",
                    meta.get("prompt_lang") or "",
                )
        # Filesystem fallback
        file = f"ref_{emo}.wav"
        if os.path.isfile(os.path.join(profile_dir, file)):
            return (_container_ref_path(profile, file), "", "")
        return None

    for candidate in (emotion, "neutral"):
        result = _try(candidate)
        if result is not None:
            return result

    if isinstance(emotion_refs, dict):
        for emo in emotion_refs:
            result = _try(emo)
            if result is not None:
                return result

    # Last resort: trust the convention.
    return (_container_ref_path(profile, f"ref_{emotion}.wav"), "", "")


class OmniVoiceEngine(TTSEngine):
    """OmniVoice engine — calls the in-cluster geny-omnivoice service."""

    engine_name = "omnivoice"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

        config = get_config_manager().load_config(OmniVoiceConfig)

        if not config.enabled:
            raise ValueError("OmniVoice is not enabled")

        # Per-session voice_profile override wins over Config.
        profile = request.voice_profile or config.voice_profile or ""
        mode = (config.mode or "clone").lower()

        payload: dict = {
            "text": request.text,
            "mode": mode,
            "language": (config.language or request.language or "") or None,
            "speed": float(config.speed) * float(request.speed or 1.0),
            "duration": float(config.duration_seconds) if config.duration_seconds > 0 else None,
            "num_step": int(config.num_step),
            "guidance_scale": float(config.guidance_scale),
            "denoise": bool(config.denoise),
            "audio_format": (config.audio_format or request.audio_format.value or "wav"),
            "sample_rate": int(request.sample_rate or 24000),
        }

        if mode in ("clone",) or (mode == "auto" and profile):
            ref_audio_path, prompt_text, _prompt_lang = _resolve_emotion_ref(
                profile, request.emotion or "neutral"
            )
            if ref_audio_path:
                payload["mode"] = "clone"
                payload["ref_audio_path"] = ref_audio_path
                if prompt_text:
                    payload["ref_text"] = prompt_text
                elif config.auto_asr:
                    payload["ref_text"] = None
            else:
                logger.warning(
                    "OmniVoice: no ref_audio resolved for profile=%s emotion=%s; "
                    "falling back to auto mode",
                    profile,
                    request.emotion,
                )
                payload["mode"] = "auto"

        if mode == "design":
            instruct = (config.instruct or "").strip()
            if not instruct:
                raise ValueError("OmniVoice mode=design requires Config.instruct to be set")
            payload["instruct"] = instruct
        elif config.instruct:
            # Optional design hint on top of clone/auto modes.
            payload["instruct"] = config.instruct.strip()

        api_url = config.api_url.rstrip("/")
        timeout = float(config.timeout_seconds or 60.0)

        async with _synthesis_lock:
            logger.info(
                "OmniVoice request: url=%s/tts mode=%s profile=%s lang=%s",
                api_url, payload["mode"], profile, payload.get("language"),
            )
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(f"{api_url}/tts", json=payload)
                    resp.raise_for_status()
                    audio_data = resp.content
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response is not None else ""
                logger.error("OmniVoice API error %s: %s", e.response.status_code, body)
                raise ValueError(
                    f"OmniVoice API error {e.response.status_code}: {body}"
                ) from e
            except Exception as e:
                logger.error("OmniVoice synthesis error: %s", e)
                raise

        if audio_data:
            yield TTSChunk(audio_data=audio_data, chunk_index=0)
        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=1)

    async def get_voices(self, language: Optional[str] = None) -> list[VoiceInfo]:
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

            config = get_config_manager().load_config(OmniVoiceConfig)
        except Exception:
            return []

        api_url = config.api_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{api_url}/voices")
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Failed to list OmniVoice voices: %s", e)
            return []

        out: list[VoiceInfo] = []
        for voice in data.get("voices", []):
            voice_lang = voice.get("language") or "multilingual"
            if language and not voice_lang.startswith(language):
                continue
            out.append(
                VoiceInfo(
                    id=voice.get("id", ""),
                    name=voice.get("name") or voice.get("id", ""),
                    language=voice_lang,
                    gender="unknown",
                    engine=self.engine_name,
                )
            )
        return out

    async def health_check(self) -> bool:
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

            config = get_config_manager().load_config(OmniVoiceConfig)
            if not config.enabled:
                logger.debug("OmniVoice is disabled in config")
                return False

            api_url = config.api_url.rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{api_url}/health")
                if resp.status_code != 200:
                    logger.warning(
                        "OmniVoice health check non-200: %s", resp.status_code
                    )
                    return False
                body = resp.json()
                # ``loading`` means the model is still warming up — treat as
                # not-yet-ready so the TTSService can fall back gracefully.
                return body.get("status") == "ok"
        except Exception as e:
            logger.warning("OmniVoice health check error: %s: %s", type(e).__name__, e)
            return False
