"""
GPT-SoVITS TTS Engine — Open-source voice cloning with emotion references.

Connects to a locally running GPT-SoVITS API (v2) server.
Official image: xxxxrt666/gpt-sovits:latest — api_v2.py on port 9880.
Endpoint: POST /tts
Selects emotion-specific reference audio files for natural voice expression.
"""

import asyncio
import os
from logging import getLogger
from typing import AsyncIterator, Optional

import httpx

from service.vtuber.tts.base import (
    TTSChunk,
    TTSEngine,
    TTSRequest,
    VoiceInfo,
)

logger = getLogger(__name__)


# Module-level lock: GPT-SoVITS runs on a single GPU and cannot handle
# concurrent synthesis requests.  Serialise all calls so that overlapping
# VTuber sessions wait in line instead of getting 400/connection errors.
_synthesis_lock = asyncio.Lock()


class GPTSoVITSEngine(TTSEngine):
    """GPT-SoVITS engine with emotion-based reference audio selection"""

    engine_name = "gpt_sovits"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        """
        Stream audio from GPT-SoVITS API v2.

        api_v2.py 엔드포인트: POST /tts
        Payload (v2):
          - ref_audio_path: 레퍼런스 오디오 경로 (GPT-SoVITS 컨테이너 내)
          - prompt_text: 레퍼런스 오디오 발화 텍스트
          - prompt_lang: 레퍼런스 오디오 언어
          - text: 합성할 텍스트
          - text_lang: 합성 텍스트 언어
          - media_type: wav, ogg, aac, raw
        Response: wav 바이너리
        """
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.gpt_sovits_config import GPTSoVITSConfig

        config = get_config_manager().load_config(GPTSoVITSConfig)

        if not config.enabled:
            raise ValueError("GPT-SoVITS is not enabled")

        # Per-session voice_profile override (from TTSRequest)
        if request.voice_profile:
            ref_audio_dir = f"/app/static/voices/{request.voice_profile}"
            container_ref_dir = f"/workspace/GPT-SoVITS/references/{request.voice_profile}"
        else:
            # Resolve paths from voice_profile (or legacy direct paths)
            ref_audio_dir, container_ref_dir = self._resolve_profile_paths(config)

        # Select emotion-specific reference audio + per-emotion prompt
        ref_audio_path, per_prompt_text, per_prompt_lang = self._get_emotion_ref(
            request.emotion, config, ref_audio_dir, container_ref_dir,
        )
        if not ref_audio_path:
            logger.warning(
                "No reference audio found for GPT-SoVITS. "
                "Set voice_profile in config or upload reference audio."
            )

        # Map language code — v2 supports ko natively
        text_lang = self._lang_to_sovits(request.language)

        # Use per-emotion prompt if available, else fallback to config-level
        prompt_text = per_prompt_text or config.prompt_text or ""
        prompt_lang_raw = per_prompt_lang or config.prompt_lang or request.language
        prompt_lang = self._lang_to_sovits(prompt_lang_raw)

        # GPT-SoVITS v2 API payload — POST /tts
        payload = {
            "text": request.text,
            "text_lang": text_lang,
            "ref_audio_path": ref_audio_path,
            "prompt_text": prompt_text,
            "prompt_lang": prompt_lang,
            "media_type": "wav",
            "top_k": config.top_k,
            "top_p": config.top_p,
            "temperature": config.temperature,
            "speed_factor": config.speed,
            "streaming_mode": False,
        }

        api_url = config.api_url.rstrip("/")

        # Acquire lock — GPT-SoVITS is single-GPU, serialize requests
        async with _synthesis_lock:
            logger.info(
                f"GPT-SoVITS v2 request: url={api_url}/tts, "
                f"text_lang={text_lang}, prompt_lang={prompt_lang}, ref={ref_audio_path}"
            )

            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(f"{api_url}/tts", json=payload)
                    resp.raise_for_status()
                    audio_data = resp.content
            except httpx.HTTPStatusError as e:
                body = e.response.text[:500] if e.response else ""
                logger.error(f"GPT-SoVITS API error {e.response.status_code}: {body}")
                raise ValueError(f"GPT-SoVITS API error {e.response.status_code}: {body}")
            except Exception as e:
                logger.error(f"GPT-SoVITS synthesis error: {e}")
                raise

        if audio_data:
            yield TTSChunk(audio_data=audio_data, chunk_index=0)
        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=1)

    async def get_voices(self, language: Optional[str] = None) -> list[VoiceInfo]:
        """List available voice profiles from the references directory"""
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.tts.gpt_sovits_config import GPTSoVITSConfig

            config = get_config_manager().load_config(GPTSoVITSConfig)
            ref_audio_dir, _ = self._resolve_profile_paths(config)
            if not ref_audio_dir or not os.path.isdir(ref_audio_dir):
                return []

            # List reference audio files as "voices"
            voices = []
            for f in os.listdir(ref_audio_dir):
                if f.endswith(".wav") and f.startswith("ref_"):
                    emotion = f.replace("ref_", "").replace(".wav", "")
                    voices.append(
                        VoiceInfo(
                            id=f,
                            name=f"레퍼런스: {emotion}",
                            language="multilingual",
                            gender="unknown",
                            engine=self.engine_name,
                        )
                    )
            return voices
        except Exception as e:
            logger.warning(f"Failed to list GPT-SoVITS voices: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if GPT-SoVITS API v2 server is running (api_v2.py on port 9880).

        Uses httpx.AsyncClient (same pattern as OpenAI, ElevenLabs engines).
        GET /tts with minimal params — 400/422/500 all mean the server is alive.
        """
        try:
            from service.config.manager import get_config_manager
            from service.config.sub_config.tts.gpt_sovits_config import GPTSoVITSConfig

            config = get_config_manager().load_config(GPTSoVITSConfig)
            if not config.enabled:
                logger.debug("GPT-SoVITS is disabled in config")
                return False

            api_url = config.api_url.rstrip("/")

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{api_url}/tts",
                    params={
                        "text": "ping",
                        "text_lang": "ko",
                        "ref_audio_path": "",
                        "prompt_lang": "ko",
                        "prompt_text": "",
                    },
                )
                status_code = resp.status_code

            # 400/422/500 all mean the server is alive (param validation errors are expected)
            is_healthy = status_code in (200, 400, 422, 500)
            if is_healthy:
                logger.info(f"GPT-SoVITS health check OK: {api_url} → {status_code}")
            else:
                logger.warning(f"GPT-SoVITS health check failed: {api_url} → {status_code}")
            return is_healthy
        except Exception as e:
            logger.warning(f"GPT-SoVITS health check error: {type(e).__name__}: {e}")
            return False

    @staticmethod
    def _resolve_profile_paths(config) -> tuple[str, str]:
        """Derive ref_audio_dir and container_ref_dir from voice_profile.

        Falls back to legacy direct path fields for backward compatibility.
        """
        profile = getattr(config, "voice_profile", "") or ""
        if profile:
            return (
                f"/app/static/voices/{profile}",
                f"/workspace/GPT-SoVITS/references/{profile}",
            )
        # Legacy fallback
        return (
            getattr(config, "ref_audio_dir", "") or "",
            getattr(config, "container_ref_dir", "") or "",
        )

    def _get_emotion_ref(
        self, emotion: str, config, ref_dir: str, container_dir: str,
    ) -> tuple[str, str, str]:
        """Get (audio_path, prompt_text, prompt_lang) for a given emotion.

        Reads per-emotion prompt from profile.json.
        Falls back to neutral emotion, then to config-level prompt.
        """
        if not ref_dir:
            return ("", "", "")

        if not container_dir:
            container_dir = ref_dir

        # Try to load per-emotion prompts from profile.json
        profile_json_path = os.path.join(ref_dir, "profile.json")
        emotion_refs: dict = {}
        try:
            if os.path.exists(profile_json_path):
                import json
                with open(profile_json_path, "r", encoding="utf-8") as f:
                    profile_data = json.load(f)
                emotion_refs = profile_data.get("emotion_refs", {})
        except Exception as e:
            logger.warning(f"Failed to read profile.json: {e}")

        def _resolve(emo: str) -> tuple[str, str, str] | None:
            emotion_file = f"ref_{emo}.wav"
            full_path = os.path.join(ref_dir, emotion_file)
            if os.path.exists(full_path):
                ref_data = emotion_refs.get(emo, {})
                return (
                    os.path.join(container_dir, emotion_file),
                    ref_data.get("prompt_text", ""),
                    ref_data.get("prompt_lang", ""),
                )
            return None

        # Try requested emotion
        result = _resolve(emotion)
        if result:
            return result

        # Fallback to neutral
        result = _resolve("neutral")
        if result:
            logger.info(f"Emotion '{emotion}' not found, falling back to neutral")
            return result

        # Fallback to any registered emotion
        for fallback_emo in emotion_refs:
            result = _resolve(fallback_emo)
            if result:
                logger.info(
                    f"Emotion '{emotion}' and 'neutral' not found, "
                    f"falling back to '{fallback_emo}'"
                )
                return result

        # No local files found — send container path as-is
        container_path = os.path.join(container_dir, f"ref_{emotion}.wav")
        logger.warning(
            f"ref audio not found locally at {os.path.join(ref_dir, f'ref_{emotion}.wav')}, "
            f"sending container path as-is: {container_path}"
        )
        return (container_path, "", "")

    @staticmethod
    def _lang_to_sovits(language: str) -> str:
        """Map BCP-47 language code to GPT-SoVITS v2 language format.

        v2 supports: ko, en, zh, ja, all_zh, all_ja, auto, yue, all_yue.
        Korean is natively supported in v2 (unlike v1).
        """
        return {
            "ko": "ko",
            "ja": "all_ja",
            "en": "en",
            "zh": "all_zh",
        }.get(language, "auto")
