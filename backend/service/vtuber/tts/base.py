"""
TTS Engine abstract base and data classes.

Defines the TTSEngine ABC that all TTS engine implementations must follow,
along with shared data structures for TTS requests, responses, and voice metadata.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from logging import getLogger
from typing import AsyncIterator, Optional

logger = getLogger(__name__)


class AudioFormat(Enum):
    """Supported audio output formats"""
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    PCM = "pcm"


@dataclass
class TTSRequest:
    """TTS synthesis request parameters"""
    text: str
    emotion: str = "neutral"
    language: str = "ko"
    speed: float = 1.0
    pitch_shift: str = "+0Hz"
    audio_format: AudioFormat = AudioFormat.MP3
    sample_rate: int = 24000


@dataclass
class TTSChunk:
    """A chunk of streamed audio data"""
    audio_data: bytes
    is_final: bool = False
    chunk_index: int = 0
    word_boundary: Optional[dict] = None
    viseme_data: Optional[list] = None


@dataclass
class VoiceInfo:
    """Metadata for an available TTS voice"""
    id: str
    name: str
    language: str
    gender: str
    engine: str
    preview_text: str = "안녕하세요, 반갑습니다."


class TTSEngine(ABC):
    """
    Abstract TTS engine interface.

    All TTS engine implementations must inherit from this class
    and implement the required abstract methods.
    """

    engine_name: str = "base"

    @abstractmethod
    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        """Synthesize text to a stream of audio chunks"""
        ...

    async def synthesize(self, request: TTSRequest) -> bytes:
        """Synthesize text to complete audio bytes (batch mode)"""
        chunks = []
        async for chunk in self.synthesize_stream(request):
            if chunk.audio_data:
                chunks.append(chunk.audio_data)
        return b"".join(chunks)

    @abstractmethod
    async def get_voices(self, language: Optional[str] = None) -> list[VoiceInfo]:
        """List available voices for this engine"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if this engine is available and operational"""
        ...

    async def apply_emotion(self, request: TTSRequest) -> TTSRequest:
        """
        Adjust request parameters based on emotion.

        Uses General Config for emotion speed/pitch mapping.
        Individual engines can override for engine-specific behavior.
        """
        from service.config.manager import get_config_manager
        from service.config.sub_config.tts.tts_general_config import TTSGeneralConfig

        try:
            general = get_config_manager().load_config(TTSGeneralConfig)
            emotion_speeds = {
                "joy": general.emotion_speed_joy,
                "anger": general.emotion_speed_anger,
                "sadness": general.emotion_speed_sadness,
                "fear": general.emotion_speed_fear,
                "surprise": general.emotion_speed_surprise,
            }
            emotion_pitches = {
                "joy": general.emotion_pitch_joy,
                "anger": general.emotion_pitch_anger,
                "sadness": general.emotion_pitch_sadness,
                "fear": general.emotion_pitch_fear,
                "surprise": general.emotion_pitch_surprise,
            }
            request.speed *= emotion_speeds.get(request.emotion, 1.0)
            request.pitch_shift = emotion_pitches.get(request.emotion, "+0Hz")
        except Exception as e:
            logger.warning(f"Failed to load emotion config, using defaults: {e}")

        return request
