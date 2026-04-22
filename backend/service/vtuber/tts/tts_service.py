"""
TTS Service — Engine registry, routing, and fallback management.

Manages all registered TTS engines, routes requests based on Config,
provides fallback chain when engines fail, and handles streaming synthesis.
"""

from logging import getLogger
from typing import AsyncIterator, Optional

from service.vtuber.tts.base import (
    AudioFormat,
    TTSChunk,
    TTSEngine,
    TTSRequest,
    VoiceInfo,
)

logger = getLogger(__name__)


class TTSService:
    """
    TTS engine registry + Config-based routing + fallback.

    Manages all TTS engine instances, selects the active engine
    from Config, and provides automatic fallback to Edge TTS.
    """

    def __init__(self):
        self._engines: dict[str, TTSEngine] = {}

    def register_engine(self, engine: TTSEngine) -> None:
        """Register a TTS engine instance"""
        self._engines[engine.engine_name] = engine
        logger.info(f"TTS engine registered: {engine.engine_name}")

    def get_engine(self, name: Optional[str] = None) -> Optional[TTSEngine]:
        """
        Get a TTS engine by name, or the default from Config.

        Falls back to edge_tts if the requested engine is not found.
        """
        if name is None:
            try:
                from service.config.manager import get_config_manager
                from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

                general = get_config_manager().load_config(TTSGeneralConfig)
                name = general.provider
            except Exception as e:
                logger.warning(f"Failed to load TTS general config: {e}")
                name = "edge_tts"

        engine = self._engines.get(name)
        if engine:
            return engine

        logger.warning(f"Engine '{name}' not found, falling back to edge_tts")
        return self._engines.get("edge_tts")

    async def speak(
        self,
        text: str,
        emotion: str = "neutral",
        language: str = "ko",
        engine_name: Optional[str] = None,
        voice_profile: Optional[str] = None,
    ) -> AsyncIterator[TTSChunk]:
        """
        Main TTS entry point — synthesize text to streaming audio.

        Reads Config for engine selection, audio format, and sample rate.
        Provides automatic fallback to Edge TTS on engine failure.
        """
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

        try:
            general = get_config_manager().load_config(TTSGeneralConfig)
        except Exception as e:
            logger.warning(f"Failed to load TTS general config: {e}")
            general = None

        # Check if TTS is enabled
        if general and not general.enabled:
            logger.info("TTS is disabled in config")
            return

        engine = self.get_engine(engine_name)
        if not engine:
            logger.error("No TTS engine available")
            raise RuntimeError("No TTS engine available")

        # Health check with fallback
        actual_engine_name = engine.engine_name
        if not await engine.health_check():
            logger.warning(f"{engine.engine_name} health check failed, trying fallback")
            engine = self._engines.get("edge_tts")
            if not engine or not await engine.health_check():
                logger.error(
                    f"All TTS engines unavailable "
                    f"(primary={actual_engine_name}, fallback=edge_tts)"
                )
                raise RuntimeError(
                    f"All TTS engines unavailable. "
                    f"Primary engine '{actual_engine_name}' health check failed. "
                    f"Check engine config (enabled, api_url, etc.)"
                )

        # Build request from Config
        audio_format = AudioFormat.MP3
        sample_rate = 24000
        if general:
            try:
                audio_format = AudioFormat(general.audio_format)
            except ValueError:
                pass
            sample_rate = general.sample_rate
            if not language:
                language = general.default_language

        request = TTSRequest(
            text=text,
            emotion=emotion,
            language=language or "ko",
            audio_format=audio_format,
            sample_rate=sample_rate,
            voice_profile=voice_profile,
        )

        # Apply emotion parameters
        request = await engine.apply_emotion(request)

        # Cache lookup — voice_profile을 포함하여 프로필별 캐시 분리
        from service.vtuber.tts.cache import get_tts_cache

        cache = get_tts_cache()
        voice_id = f"{engine.engine_name}:{voice_profile or 'default'}"
        cached = cache.get(text, emotion, engine.engine_name, voice_id)
        if cached:
            logger.debug(f"Cache hit for TTS: {text[:30]}...")
            yield TTSChunk(audio_data=cached, is_final=True, chunk_index=0)
            return

        # Stream synthesis with fallback + cache accumulation
        collected_chunks: list[bytes] = []
        try:
            async for chunk in engine.synthesize_stream(request):
                if chunk.audio_data:
                    collected_chunks.append(chunk.audio_data)
                yield chunk
        except Exception as e:
            logger.error(f"TTS synthesis failed ({engine.engine_name}): {e}")
            collected_chunks.clear()
            if engine.engine_name != "edge_tts":
                fallback = self._engines.get("edge_tts")
                if fallback:
                    logger.info("Retrying with edge_tts fallback")
                    try:
                        async for chunk in fallback.synthesize_stream(request):
                            if chunk.audio_data:
                                collected_chunks.append(chunk.audio_data)
                            yield chunk
                    except Exception as fallback_err:
                        logger.error(f"Edge TTS fallback also failed: {fallback_err}")
                        return

        # Store in cache
        if collected_chunks:
            full_audio = b"".join(collected_chunks)
            if full_audio:
                cache.put(
                    text, emotion, engine.engine_name, voice_id,
                    full_audio, audio_format.value,
                )

    async def get_all_voices(
        self, language: Optional[str] = None
    ) -> dict[str, list[VoiceInfo]]:
        """Get voices from all available engines"""
        result = {}
        for name, engine in self._engines.items():
            try:
                if await engine.health_check():
                    result[name] = await engine.get_voices(language)
            except Exception as e:
                logger.warning(f"Failed to get voices from {name}: {e}")
        return result

    async def get_status(self) -> dict:
        """Get health status of all registered engines"""
        status = {}
        for name, engine in self._engines.items():
            try:
                healthy = await engine.health_check()
                status[name] = {"available": healthy, "engine": name}
            except Exception:
                status[name] = {"available": False, "engine": name}
        return status


# Singleton
_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Get or create the global TTSService singleton"""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
        # Register all engines
        from service.vtuber.tts.engines.edge_tts_engine import EdgeTTSEngine
        from service.vtuber.tts.engines.openai_tts_engine import OpenAITTSEngine
        from service.vtuber.tts.engines.elevenlabs_engine import ElevenLabsEngine
        from service.vtuber.tts.engines.gpt_sovits_engine import GPTSoVITSEngine
        from service.vtuber.tts.engines.omnivoice_engine import OmniVoiceEngine

        _tts_service.register_engine(EdgeTTSEngine())
        _tts_service.register_engine(OpenAITTSEngine())
        _tts_service.register_engine(ElevenLabsEngine())
        _tts_service.register_engine(GPTSoVITSEngine())
        _tts_service.register_engine(OmniVoiceEngine())
    return _tts_service
