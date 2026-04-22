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


# ── Persistent HTTP client pool ──────────────────────────────────────
# Re-use a single ``httpx.AsyncClient`` per upstream URL across all
# requests. Per-call client construction was costing one TCP handshake
# and TLS / HTTP-2 negotiation per synthesis — measurable overhead on
# short utterances. ``Limits`` keeps a small idle pool warm so the
# next request lands on a hot connection.
#
# We also intentionally drop the module-level ``asyncio.Lock`` that
# previously serialised every adapter call. The geny-omnivoice service
# already serialises GPU access via its own ``asyncio.Semaphore``
# (``OMNIVOICE_MAX_CONCURRENCY``), so the adapter lock was pure
# duplicate work — and worse, it artificially blocked a *second*
# adapter caller from even sending the HTTP request, defeating any
# pipelining we add at the model layer in later phases.
_clients_lock = asyncio.Lock()
_clients: dict[tuple[str, float], httpx.AsyncClient] = {}


async def _get_client(api_url: str, read_timeout: float) -> httpx.AsyncClient:
    """Return a process-wide persistent client keyed by (url, timeout)."""
    key = (api_url.rstrip("/"), float(read_timeout))
    client = _clients.get(key)
    if client is not None and not client.is_closed:
        return client
    async with _clients_lock:
        client = _clients.get(key)
        if client is not None and not client.is_closed:
            return client
        timeout = httpx.Timeout(
            connect=10.0,
            read=read_timeout,
            write=30.0,
            pool=10.0,
        )
        limits = httpx.Limits(
            max_keepalive_connections=4,
            max_connections=8,
            keepalive_expiry=30.0,
        )
        client = httpx.AsyncClient(timeout=timeout, limits=limits)
        _clients[key] = client
        return client


async def aclose_clients() -> None:
    """Best-effort shutdown hook for graceful FastAPI lifespan exit."""
    async with _clients_lock:
        for client in list(_clients.values()):
            try:
                await client.aclose()
            except Exception:  # pragma: no cover - best effort
                logger.debug("failed closing httpx client", exc_info=True)
        _clients.clear()


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
        # First-time CUDA inference on Pascal GPUs (e.g. GTX 1070) can
        # easily exceed the legacy 60s default. Honour Config but raise the
        # implicit floor so the very first request after model load does
        # not get cut off mid-generation.
        timeout = max(float(config.timeout_seconds or 0.0), 180.0)

        # Use the persistent client pool — see ``_get_client`` for the
        # rationale. The upstream omnivoice service serialises GPU work
        # itself, so we deliberately do *not* wrap the request in a
        # local lock; that would only block adapter callers from
        # queueing on the upstream semaphore.
        client = await _get_client(api_url, read_timeout=timeout)
        logger.info(
            "OmniVoice request: url=%s/tts mode=%s profile=%s lang=%s timeout=%.1fs text_len=%d",
            api_url, payload["mode"], profile, payload.get("language"),
            timeout, len(request.text or ""),
        )
        try:
            resp = await client.post(f"{api_url}/tts", json=payload)
            resp.raise_for_status()
            audio_data = resp.content
        except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response is not None else ""
                logger.error("OmniVoice API error %s: %s", e.response.status_code, body)
                raise ValueError(
                    f"OmniVoice API error {e.response.status_code}: {body}"
                ) from e
        except httpx.TimeoutException as e:
            # ReadTimeout/ConnectTimeout/WriteTimeout: str(e) is often
            # empty; surface the type explicitly so ops can see it.
            logger.exception(
                "OmniVoice timeout after %.1fs (type=%s repr=%r) url=%s payload_keys=%s",
                timeout, type(e).__name__, e, api_url, list(payload.keys()),
            )
            raise RuntimeError(
                f"OmniVoice request timed out after {timeout:.0f}s "
                f"(type={type(e).__name__}). Increase Config.timeout_seconds "
                f"or check GPU load on the omnivoice service."
            ) from e
        except Exception as e:
            # Always log the type/repr + full traceback. ``str(e)`` is
            # frequently empty for httpx / asyncio cancellation errors.
            logger.exception(
                "OmniVoice synthesis error (type=%s repr=%r) url=%s",
                type(e).__name__, e, api_url,
            )
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
            client = await _get_client(api_url, read_timeout=5.0)
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
            client = await _get_client(api_url, read_timeout=5.0)
            resp = await client.get(f"{api_url}/health")
            if resp.status_code != 200:
                logger.warning(
                    "OmniVoice health check non-200: %s", resp.status_code
                )
                return False
            body = resp.json()
            # New servers expose ``phase`` (loading / warming / ok / error);
            # we only treat ``ok`` as ready so callers can fall back during
            # the warmup window. Older servers only expose ``status`` —
            # honour that as a fallback for backward compatibility.
            phase = body.get("phase")
            if phase is not None:
                return phase == "ok"
            return body.get("status") == "ok"
        except Exception as e:
            logger.warning("OmniVoice health check error: %s: %s", type(e).__name__, e)
            return False
