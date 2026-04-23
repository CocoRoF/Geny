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
    TTSSentenceChunk,
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
    supports_sentence_stream = True

    # ── Internal: payload builder shared by /tts and /tts/stream ────
    def _build_payload(self, request: TTSRequest, config) -> tuple[dict, str]:
        """Return ``(payload, profile_name)`` for the upstream request.

        Pulled out of :meth:`synthesize_stream` so the sentence-streaming
        path can build the same body without duplicating the
        profile-resolution / mode-fallback logic.
        """
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
            payload["instruct"] = config.instruct.strip()

        return payload, profile

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

        config = get_config_manager().load_config(OmniVoiceConfig)

        if not config.enabled:
            raise ValueError("OmniVoice is not enabled")

        payload, profile = self._build_payload(request, config)

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

    async def synthesize_single_sentence(
        self, request: TTSRequest
    ) -> TTSSentenceChunk:
        """One already-segmented sentence → one wav clip, via ``/tts``.

        Used by the frontend-fed chunk pipeline (``/api/tts/agents/:sid
        /speak/chunks``) where the caller has already sliced the LLM
        output into sentence-sized pieces and we just need the audio
        for each. Sending the payload to ``/tts`` (single-shot)
        bypasses the upstream sentence splitter entirely, so one input
        chunk == one output clip — guaranteed.

        Multiple concurrent callers are safe: the httpx client pool
        supports up to 8 in-flight requests and the OmniVoice server
        gates actual GPU execution via its own semaphore.
        """
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

        config = get_config_manager().load_config(OmniVoiceConfig)
        if not config.enabled:
            raise ValueError("OmniVoice is not enabled")

        payload, profile = self._build_payload(request, config)
        api_url = config.api_url.rstrip("/")
        timeout = max(float(config.timeout_seconds or 0.0), 180.0)
        client = await _get_client(api_url, read_timeout=timeout)

        logger.info(
            "OmniVoice single-sentence: url=%s/tts mode=%s profile=%s lang=%s "
            "chars=%d emotion=%s",
            api_url, payload["mode"], profile, payload.get("language"),
            len(request.text or ""), request.emotion,
        )

        try:
            resp = await client.post(f"{api_url}/tts", json=payload)
            resp.raise_for_status()
            audio_data = resp.content
            sr = int(resp.headers.get("X-OmniVoice-Sample-Rate") or payload.get("sample_rate") or 24000)
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response is not None else ""
            logger.error("OmniVoice /tts error %s: %s", e.response.status_code, body)
            raise ValueError(f"OmniVoice /tts error {e.response.status_code}: {body}") from e
        except httpx.TimeoutException as e:
            logger.exception(
                "OmniVoice /tts timeout after %.1fs (type=%s)",
                timeout, type(e).__name__,
            )
            raise RuntimeError(
                f"OmniVoice /tts timed out after {timeout:.0f}s "
                f"(type={type(e).__name__})."
            ) from e

        return TTSSentenceChunk(
            seq=0,
            text=request.text,
            audio_data=audio_data or b"",
            sample_rate=sr,
            audio_format=str(payload.get("audio_format") or "wav"),
            is_final=True,
        )

    async def synthesize_sentence_stream(
        self, request: TTSRequest
    ) -> AsyncIterator[TTSSentenceChunk]:
        """Stream one fully-rendered sentence at a time via ``/tts/stream``.

        Wire format (NDJSON, one JSON object per line):

        * sentence frames: ``{"seq": N, "text": str, "format": "wav",
          "sample_rate": int, "audio_b64": str, ...}``
        * per-sentence error: ``{"seq": N, "error": str}``
        * terminator: ``{"done": true, "total": int, ...}``

        Each yielded :class:`TTSSentenceChunk` is independently playable
        — the client can hand each one to its audio queue immediately,
        which is the whole point of this code path. The terminator
        frame is converted into a final chunk with ``is_final=True``
        and an empty payload so callers have a deterministic end signal.
        """
        import base64

        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.omnivoice_config import OmniVoiceConfig

        config = get_config_manager().load_config(OmniVoiceConfig)
        if not config.enabled:
            raise ValueError("OmniVoice is not enabled")

        payload, profile = self._build_payload(request, config)

        # Inject sentence-splitter knobs from TTSGeneralConfig (so they
        # live in the same Settings card as ``streaming_mode``). The
        # upstream defaults take over if the load fails.
        try:
            from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig
            general = get_config_manager().load_config(TTSGeneralConfig)
            min_chars = int(getattr(general, "streaming_min_sentence_chars", 60) or 0)
            max_chars = int(getattr(general, "streaming_max_sentence_chars", 240) or 240)
            payload["min_sentence_chars"] = max(0, min(min_chars, 500))
            payload["max_sentence_chars"] = max(20, min(max_chars, 2000))
        except Exception as e:
            logger.debug("Could not load streaming chunk knobs from tts_general: %r", e)

        api_url = config.api_url.rstrip("/")
        # Sentence stream can take longer end-to-end than a single /tts
        # call (it synthesises N sentences sequentially). Use the same
        # 180s floor as the single-clip path; the TCP connection is
        # held open for the full duration.
        timeout = max(float(config.timeout_seconds or 0.0), 180.0)

        client = await _get_client(api_url, read_timeout=timeout)
        logger.info(
            "OmniVoice stream request: url=%s/tts/stream mode=%s profile=%s "
            "lang=%s timeout=%.1fs text_len=%d min_chars=%s max_chars=%s",
            api_url, payload["mode"], profile, payload.get("language"),
            timeout, len(request.text or ""),
            payload.get("min_sentence_chars"), payload.get("max_sentence_chars"),
        )

        sample_rate = int(payload.get("sample_rate") or 24000)
        audio_format_str = str(payload.get("audio_format") or "wav")
        last_seq = -1
        try:
            import time as _time
            t0 = _time.monotonic()
            first_byte_at: Optional[float] = None
            first_frame_at: Optional[float] = None
            async with client.stream(
                "POST", f"{api_url}/tts/stream", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if first_byte_at is None:
                        first_byte_at = _time.monotonic() - t0
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        frame = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("OmniVoice /tts/stream: skipping malformed frame: %r", line[:120])
                        continue

                    if frame.get("done"):
                        total_dt = _time.monotonic() - t0
                        logger.info(
                            "OmniVoice /tts/stream: done in %.2fs "
                            "(first_byte=%.2fs, first_frame=%.2fs, "
                            "last_seq=%d, upstream_elapsed=%s)",
                            total_dt,
                            first_byte_at if first_byte_at is not None else -1.0,
                            first_frame_at if first_frame_at is not None else -1.0,
                            last_seq, frame.get("elapsed_seconds"),
                        )
                        # Terminator frame — synthesise an empty final
                        # chunk so callers can release UI state.
                        yield TTSSentenceChunk(
                            seq=last_seq + 1,
                            text="",
                            audio_data=b"",
                            sample_rate=sample_rate,
                            audio_format=audio_format_str,
                            is_final=True,
                        )
                        return

                    seq = int(frame.get("seq", last_seq + 1))
                    if first_frame_at is None and frame.get("audio_b64"):
                        first_frame_at = _time.monotonic() - t0
                    last_seq = max(last_seq, seq)
                    text = str(frame.get("text") or "")
                    err = frame.get("error")
                    if err is not None:
                        logger.warning(
                            "OmniVoice /tts/stream: sentence %d failed upstream: %s",
                            seq, err,
                        )
                        yield TTSSentenceChunk(
                            seq=seq, text=text, audio_data=b"",
                            sample_rate=sample_rate,
                            audio_format=audio_format_str,
                            error=str(err),
                        )
                        continue

                    audio_b64 = frame.get("audio_b64") or ""
                    try:
                        audio_bytes = base64.b64decode(audio_b64) if audio_b64 else b""
                    except Exception:
                        logger.exception("OmniVoice /tts/stream: base64 decode failed for seq=%d", seq)
                        yield TTSSentenceChunk(
                            seq=seq, text=text, audio_data=b"",
                            sample_rate=sample_rate,
                            audio_format=audio_format_str,
                            error="base64_decode_failed",
                        )
                        continue

                    yield TTSSentenceChunk(
                        seq=seq,
                        text=text,
                        audio_data=audio_bytes,
                        sample_rate=int(frame.get("sample_rate") or sample_rate),
                        audio_format=str(frame.get("format") or audio_format_str),
                    )

            # Stream ended without an explicit terminator — emit one so
            # downstream consumers can finalise UI state.
            yield TTSSentenceChunk(
                seq=last_seq + 1, text="", audio_data=b"",
                sample_rate=sample_rate, audio_format=audio_format_str,
                is_final=True,
            )
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500] if e.response is not None else ""
            logger.error("OmniVoice /tts/stream API error %s: %s", e.response.status_code, body)
            raise ValueError(
                f"OmniVoice /tts/stream error {e.response.status_code}: {body}"
            ) from e
        except httpx.TimeoutException as e:
            logger.exception(
                "OmniVoice /tts/stream timeout after %.1fs (type=%s) url=%s",
                timeout, type(e).__name__, api_url,
            )
            raise RuntimeError(
                f"OmniVoice /tts/stream timed out after {timeout:.0f}s "
                f"(type={type(e).__name__})."
            ) from e
        except Exception as e:
            logger.exception(
                "OmniVoice /tts/stream error (type=%s repr=%r) url=%s",
                type(e).__name__, e, api_url,
            )
            raise

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
