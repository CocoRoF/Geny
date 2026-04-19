# 02. TTS/STT 시스템 설계서

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **목적**: TTS/STT 통합을 위한 상세 시스템 아키텍처 설계

---

## 1. 전체 아키텍처 설계

### 1.1 목표 아키텍처 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Next.js)                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ Live2D   │ │  Chat    │ │  Audio   │ │  Lip Sync       │   │
│  │ Canvas   │ │  Panel   │ │  Manager │ │  Controller     │   │
│  └─────┬────┘ └────┬─────┘ └────┬─────┘ └────────┬─────────┘   │
│        │           │            │                 │              │
│  ┌─────┴───────────┴────────────┴─────────────────┴──────┐      │
│  │              VTuber Store (Zustand)                     │      │
│  │  models | assignments | avatarStates | ttsState | sttState │  │
│  └───────────────────────┬────────────────────────────────┘      │
│                          │                                        │
│  ┌───────────────────────┴────────────────────────────────┐      │
│  │              Communication Layer                        │      │
│  │  SSE (avatar/chat) | WebSocket (STT) | Fetch (TTS)    │      │
│  └────────────────────────────────────────────────────────┘      │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                    ═══════════╪═══════════  Network
                               │
┌──────────────────────────────┴────────────────────────────────────┐
│                       Backend (FastAPI)                            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐  │
│  │ VTuber         │  │ TTS            │  │ STT                │  │
│  │ Controller     │  │ Controller     │  │ Controller         │  │
│  │ (기존)          │  │ (신규)          │  │ (신규)              │  │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────────┘  │
│          │                   │                    │               │
│  ┌───────┴───────────────────┴────────────────────┴───────────┐  │
│  │                    Service Layer                             │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐  │  │
│  │  │ Emotion      │ │ TTS Service  │ │ STT Service        │  │  │
│  │  │ Extractor    │ │ (추상화)      │ │ (추상화)            │  │  │
│  │  │ (기존)        │ │              │ │                    │  │  │
│  │  └──────┬───────┘ └──────┬───────┘ └────────┬───────────┘  │  │
│  │         │                │                   │              │  │
│  │  ┌──────┴────────────────┴───────────────────┴──────────┐  │  │
│  │  │              Engine Abstraction Layer                  │  │  │
│  │  │  ┌─────────┐ ┌─────────┐ ┌──────────┐ ┌──────────┐ │  │  │
│  │  │  │ EdgeTTS │ │ Fish    │ │ Eleven   │ │ OpenAI   │ │  │  │
│  │  │  │ Engine  │ │ Speech  │ │ Labs     │ │ TTS      │ │  │  │
│  │  │  └─────────┘ └─────────┘ └──────────┘ └──────────┘ │  │  │
│  │  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐    │  │  │
│  │  │  │ WebSpeech│ │ Faster   │ │ Google Cloud STT │    │  │  │
│  │  │  │ (client) │ │ Whisper  │ │                  │    │  │  │
│  │  │  └──────────┘ └──────────┘ └──────────────────┘    │  │  │
│  │  └────────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Audio Cache (Redis / FileSystem)             │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 핵심 설계 원칙

1. **추상화 (Abstraction)**: TTS/STT 엔진은 인터페이스 뒤에 숨기고, 설정으로 교체 가능
2. **스트리밍 우선 (Streaming-First)**: 모든 오디오는 청크 단위로 스트리밍 처리
3. **점진적 향상 (Progressive Enhancement)**: 오디오 없이도 동작, 오디오는 부가적 기능
4. **기존 감정 시스템 활용**: EmotionExtractor의 결과를 TTS 파라미터에 직접 매핑
5. **Fail-Graceful**: TTS/STT 실패 시 텍스트 폴백으로 자연스럽게 전환

---

## 2. TTS 시스템 상세 설계

### 2.1 TTS 서비스 추상화 계층

```python
# backend/service/vtuber/tts/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional
from enum import Enum

class AudioFormat(Enum):
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    PCM = "pcm"

@dataclass
class TTSRequest:
    text: str
    voice_id: str                      # 캐릭터별 보이스 ID
    emotion: str = "neutral"           # 감정 태그
    language: str = "ko"               # BCP-47 언어 코드
    speed: float = 1.0                 # 발화 속도
    pitch: float = 0.0                 # 피치 조절
    format: AudioFormat = AudioFormat.MP3
    sample_rate: int = 24000

@dataclass
class TTSChunk:
    audio_data: bytes                  # 오디오 바이너리
    is_final: bool = False             # 마지막 청크 여부
    duration_ms: Optional[int] = None  # 청크 재생 시간
    viseme: Optional[str] = None       # Viseme 정보 (지원 시)
    timestamp_ms: Optional[int] = None # 타임스탬프

@dataclass
class VoiceProfile:
    voice_id: str
    name: str
    language: str
    gender: str
    preview_url: Optional[str] = None
    emotion_styles: dict = None        # 감정별 스타일 파라미터

class TTSEngine(ABC):
    """TTS 엔진 추상 인터페이스"""

    @abstractmethod
    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        """텍스트를 오디오 청크 스트림으로 변환"""

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> bytes:
        """텍스트를 완전한 오디오 바이너리로 변환"""

    @abstractmethod
    async def list_voices(self, language: Optional[str] = None) -> list[VoiceProfile]:
        """사용 가능한 보이스 목록"""

    @abstractmethod
    async def health_check(self) -> bool:
        """엔진 상태 확인"""
```

### 2.2 TTS 엔진 구현체

#### 2.2.1 Edge TTS 엔진 (Phase 1 - MVP)

```python
# backend/service/vtuber/tts/edge_tts_engine.py

import edge_tts

class EdgeTTSEngine(TTSEngine):
    """Microsoft Edge TTS - 무료, 빠름, 한국어 우수"""

    # 감정별 보이스 매핑 (한국어)
    VOICE_MAP = {
        "ko": {
            "female": "ko-KR-SunHiNeural",
            "male": "ko-KR-InJoonNeural",
        },
        "ja": {
            "female": "ja-JP-NanamiNeural",
            "male": "ja-JP-KeitaNeural",
        },
        "en": {
            "female": "en-US-JennyNeural",
            "male": "en-US-GuyNeural",
        }
    }

    # 감정 → SSML 스타일 매핑
    EMOTION_SSML = {
        "joy":      '<mstts:express-as style="cheerful">',
        "anger":    '<mstts:express-as style="angry">',
        "sadness":  '<mstts:express-as style="sad">',
        "fear":     '<mstts:express-as style="terrified">',
        "surprise": '<mstts:express-as style="excited">',
        "neutral":  '',  # 기본 스타일
    }

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        voice = self._resolve_voice(request.voice_id, request.language)
        communicate = edge_tts.Communicate(
            text=request.text,
            voice=voice,
            rate=self._speed_to_rate(request.speed),
            pitch=self._pitch_to_str(request.pitch),
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield TTSChunk(
                    audio_data=chunk["data"],
                    is_final=False,
                )
            elif chunk["type"] == "WordBoundary":
                # Viseme/타이밍 정보로 활용 가능
                pass
        yield TTSChunk(audio_data=b"", is_final=True)
```

#### 2.2.2 Fish Speech 엔진 (Phase 3 - 고급)

```python
# backend/service/vtuber/tts/fish_speech_engine.py

import httpx

class FishSpeechEngine(TTSEngine):
    """Fish Speech 1.5 - 셀프호스팅, 보이스 클로닝, 감정 표현"""

    def __init__(self, base_url: str = "http://tts-engine:8001"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        payload = {
            "text": request.text,
            "reference_id": request.voice_id,  # 사전 등록된 보이스
            "emotion": request.emotion,
            "language": request.language,
            "speed": request.speed,
            "format": request.format.value,
            "streaming": True,
        }
        async with self.client.stream("POST", f"{self.base_url}/v1/tts", json=payload) as resp:
            async for chunk in resp.aiter_bytes(chunk_size=4096):
                yield TTSChunk(audio_data=chunk, is_final=False)
        yield TTSChunk(audio_data=b"", is_final=True)
```

#### 2.2.3 ElevenLabs 엔진 (클라우드 고품질)

```python
# backend/service/vtuber/tts/elevenlabs_engine.py

class ElevenLabsEngine(TTSEngine):
    """ElevenLabs - 최고 품질, WebSocket 스트리밍, 감정 표현 우수"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.elevenlabs.io/v1"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        url = f"{self.base_url}/text-to-speech/{request.voice_id}/stream"
        headers = {"xi-api-key": self.api_key}
        payload = {
            "text": request.text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": self._emotion_to_settings(request.emotion),
        }
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield TTSChunk(audio_data=chunk, is_final=False)
        yield TTSChunk(audio_data=b"", is_final=True)

    def _emotion_to_settings(self, emotion: str) -> dict:
        settings = {
            "neutral":  {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0},
            "joy":      {"stability": 0.3, "similarity_boost": 0.75, "style": 0.8},
            "anger":    {"stability": 0.7, "similarity_boost": 0.80, "style": 0.6},
            "sadness":  {"stability": 0.6, "similarity_boost": 0.70, "style": 0.4},
            "surprise": {"stability": 0.2, "similarity_boost": 0.75, "style": 0.9},
            "fear":     {"stability": 0.4, "similarity_boost": 0.70, "style": 0.5},
        }
        return settings.get(emotion, settings["neutral"])
```

### 2.3 TTS 서비스 매니저

```python
# backend/service/vtuber/tts/tts_service.py

class TTSService:
    """TTS 엔진 관리 및 요청 처리"""

    def __init__(self, config_manager):
        self.config = config_manager
        self.engines: dict[str, TTSEngine] = {}
        self.default_engine: str = "edge_tts"
        self.voice_cache = {}  # 음성 캐시 (중복 합성 방지)

    async def initialize(self):
        """설정에 따른 엔진 초기화"""
        tts_config = await self.config.get("tts")

        # 항상 Edge TTS는 폴백으로 등록
        self.engines["edge_tts"] = EdgeTTSEngine()

        if tts_config.get("fish_speech_enabled"):
            self.engines["fish_speech"] = FishSpeechEngine(
                base_url=tts_config["fish_speech_url"]
            )

        if tts_config.get("elevenlabs_api_key"):
            self.engines["elevenlabs"] = ElevenLabsEngine(
                api_key=tts_config["elevenlabs_api_key"]
            )

        self.default_engine = tts_config.get("default_engine", "edge_tts")

    async def synthesize_for_vtuber(
        self,
        session_id: str,
        text: str,
        emotion: str = "neutral",
        engine_name: Optional[str] = None,
    ) -> AsyncIterator[TTSChunk]:
        """VTuber 세션에 대한 TTS 합성 (스트리밍)"""

        # 1. 세션의 보이스 프로필 조회
        voice_profile = await self._get_session_voice(session_id)

        # 2. 감정 → TTS 파라미터 변환
        tts_params = self._emotion_to_params(emotion, voice_profile)

        # 3. 요청 생성
        request = TTSRequest(
            text=text,
            voice_id=voice_profile.voice_id,
            emotion=emotion,
            language=voice_profile.language,
            speed=tts_params["speed"],
            pitch=tts_params["pitch"],
        )

        # 4. 엔진 선택 및 합성
        engine = self.engines.get(engine_name or self.default_engine)
        if not engine or not await engine.health_check():
            engine = self.engines["edge_tts"]  # 폴백

        async for chunk in engine.synthesize_stream(request):
            yield chunk
```

### 2.4 TTS API 엔드포인트 설계

```python
# backend/controller/tts_controller.py

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/tts", tags=["TTS"])

@router.post("/agents/{session_id}/speak")
async def speak(session_id: str, body: SpeakRequest):
    """텍스트를 음성으로 변환하여 스트리밍 반환"""
    # -> StreamingResponse(media_type="audio/mpeg")

@router.post("/agents/{session_id}/speak/stream")
async def speak_stream(session_id: str, body: SpeakRequest):
    """청크 단위 오디오 스트리밍 (SSE 기반)"""
    # -> EventSourceResponse with base64-encoded audio chunks

@router.get("/voices")
async def list_voices(language: Optional[str] = None):
    """사용 가능한 보이스 목록"""

@router.get("/voices/{voice_id}/preview")
async def preview_voice(voice_id: str, text: str = "안녕하세요"):
    """보이스 미리듣기"""

@router.get("/engines")
async def list_engines():
    """사용 가능한 TTS 엔진 목록 및 상태"""

@router.put("/agents/{session_id}/voice")
async def assign_voice(session_id: str, body: AssignVoiceRequest):
    """세션에 보이스 프로필 할당"""

@router.get("/agents/{session_id}/voice")
async def get_voice(session_id: str):
    """세션에 할당된 보이스 프로필 조회"""
```

### 2.5 TTS 오디오 스트리밍 프로토콜

```
[방식 A: HTTP Chunked Transfer (권장 - MVP)]

Client                              Server
  │                                    │
  │  POST /api/tts/agents/{id}/speak   │
  │  { text, emotion }                 │
  │ ──────────────────────────────────→│
  │                                    │ TTSEngine.synthesize_stream()
  │  HTTP 200                          │
  │  Content-Type: audio/mpeg          │
  │  Transfer-Encoding: chunked        │
  │ ←──────────────────────────────────│
  │  [audio chunk 1] ←────────────────│
  │  [audio chunk 2] ←────────────────│
  │  [audio chunk 3] ←────────────────│
  │  [0 - end]       ←────────────────│
  │                                    │

[방식 B: SSE + Base64 (메타데이터 포함)]

Client                              Server
  │                                    │
  │  POST /api/tts/agents/{id}/speak/stream
  │ ──────────────────────────────────→│
  │                                    │
  │  event: audio_chunk                │
  │  data: { chunk: "base64...",       │
  │          index: 0,                 │
  │          duration_ms: 250,         │
  │          viseme: "aa" }            │
  │ ←──────────────────────────────────│
  │                                    │
  │  event: audio_chunk                │
  │  data: { chunk: "base64...", ... } │
  │ ←──────────────────────────────────│
  │                                    │
  │  event: audio_done                 │
  │  data: { total_duration_ms: 3500 } │
  │ ←──────────────────────────────────│
```

---

## 3. STT 시스템 상세 설계

### 3.1 STT 서비스 추상화 계층

```python
# backend/service/vtuber/stt/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Optional

@dataclass
class STTResult:
    text: str                          # 인식된 텍스트
    is_final: bool                     # 최종 결과 여부
    confidence: float = 0.0            # 신뢰도 (0.0~1.0)
    language: Optional[str] = None     # 감지된 언어
    alternatives: list[str] = None     # 대안 결과

@dataclass
class STTConfig:
    language: str = "ko-KR"            # BCP-47 언어 코드
    sample_rate: int = 16000           # 샘플링 레이트
    encoding: str = "pcm_s16le"        # 오디오 인코딩
    interim_results: bool = True       # 중간 결과 반환 여부
    vad_enabled: bool = True           # Voice Activity Detection
    custom_vocabulary: list[str] = None # 커스텀 어휘

class STTEngine(ABC):
    """STT 엔진 추상 인터페이스"""

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        config: STTConfig,
    ) -> AsyncIterator[STTResult]:
        """오디오 스트림 → 텍스트 스트림 (실시간)"""

    @abstractmethod
    async def transcribe(self, audio_data: bytes, config: STTConfig) -> STTResult:
        """완전한 오디오 → 텍스트 (배치)"""

    @abstractmethod
    async def health_check(self) -> bool:
        """엔진 상태 확인"""
```

### 3.2 STT 엔진 구현체

#### 3.2.1 Faster Whisper 엔진 (셀프호스팅)

```python
# backend/service/vtuber/stt/faster_whisper_engine.py

class FasterWhisperEngine(STTEngine):
    """Faster Whisper - 셀프호스팅, 고정확도, VAD 내장"""

    def __init__(self, model_size: str = "large-v3", device: str = "cuda"):
        self.model_size = model_size
        self.device = device
        self.model = None

    async def initialize(self):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type="float16",
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        config: STTConfig,
    ) -> AsyncIterator[STTResult]:
        """VAD 기반 실시간 전사"""
        buffer = AudioBuffer(sample_rate=config.sample_rate)
        vad = SileroVAD()  # Voice Activity Detection

        async for audio_chunk in audio_stream:
            buffer.append(audio_chunk)

            # VAD로 발화 구간 감지
            if vad.is_speech(audio_chunk):
                buffer.mark_speech()
            elif buffer.has_speech and buffer.silence_duration > 0.5:
                # 발화 종료 → 전사
                speech_audio = buffer.get_speech_segment()
                segments, _ = self.model.transcribe(
                    speech_audio,
                    language=config.language[:2],
                    beam_size=5,
                    vad_filter=True,
                )
                for segment in segments:
                    yield STTResult(
                        text=segment.text.strip(),
                        is_final=True,
                        confidence=segment.avg_logprob,
                        language=config.language,
                    )
                buffer.reset()
```

#### 3.2.2 Google Cloud STT 엔진 (클라우드)

```python
# backend/service/vtuber/stt/google_stt_engine.py

class GoogleSTTEngine(STTEngine):
    """Google Cloud Speech-to-Text v2 - 실시간 스트리밍, 고정확도"""

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        config: STTConfig,
    ) -> AsyncIterator[STTResult]:
        from google.cloud import speech_v2

        client = speech_v2.SpeechAsyncClient()
        streaming_config = speech_v2.StreamingRecognitionConfig(
            config=speech_v2.RecognitionConfig(
                explicit_decoding_config=speech_v2.ExplicitDecodingConfig(
                    encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                    sample_rate_hertz=config.sample_rate,
                    audio_channel_count=1,
                ),
                language_codes=[config.language],
                model="long",
            ),
            streaming_features=speech_v2.StreamingRecognitionFeatures(
                interim_results=config.interim_results,
            ),
        )

        async def request_generator():
            yield speech_v2.StreamingRecognizeRequest(
                streaming_config=streaming_config,
            )
            async for chunk in audio_stream:
                yield speech_v2.StreamingRecognizeRequest(audio=chunk)

        responses = await client.streaming_recognize(
            requests=request_generator()
        )
        async for response in responses:
            for result in response.results:
                yield STTResult(
                    text=result.alternatives[0].transcript,
                    is_final=result.is_final,
                    confidence=result.alternatives[0].confidence,
                )
```

### 3.3 STT WebSocket 엔드포인트 설계

```python
# backend/controller/stt_controller.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(prefix="/api/stt", tags=["STT"])

@router.websocket("/agents/{session_id}/listen")
async def listen_websocket(websocket: WebSocket, session_id: str):
    """실시간 음성 인식 WebSocket"""
    await websocket.accept()

    stt_service = get_stt_service()
    config = STTConfig(
        language="ko-KR",
        sample_rate=16000,
        interim_results=True,
        vad_enabled=True,
    )

    try:
        async def audio_generator():
            while True:
                data = await websocket.receive_bytes()
                if data == b"END":
                    break
                yield data

        async for result in stt_service.transcribe_stream(audio_generator(), config):
            await websocket.send_json({
                "type": "transcript",
                "text": result.text,
                "is_final": result.is_final,
                "confidence": result.confidence,
            })

            # 최종 결과가 나오면 채팅으로 자동 전송 (선택적)
            if result.is_final and result.text.strip():
                await websocket.send_json({
                    "type": "final_transcript",
                    "text": result.text,
                })

    except WebSocketDisconnect:
        pass

@router.get("/engines")
async def list_stt_engines():
    """사용 가능한 STT 엔진 목록"""

@router.post("/transcribe")
async def transcribe_file(file: UploadFile):
    """오디오 파일 전사 (배치)"""
```

### 3.4 STT WebSocket 프로토콜

```
[클라이언트 → 서버]

1. WebSocket 연결: ws://backend/api/stt/agents/{session_id}/listen

2. 설정 메시지 (JSON):
   {
     "type": "config",
     "language": "ko-KR",
     "sample_rate": 16000,
     "interim_results": true,
     "auto_send": true          // 최종 결과 자동 채팅 전송
   }

3. 오디오 데이터 (Binary):
   [PCM 16bit, 16kHz, mono audio bytes]
   → 100ms 간격으로 전송 (1600 samples = 3200 bytes)

4. 종료:
   b"END"

[서버 → 클라이언트]

1. 중간 결과:
   {
     "type": "transcript",
     "text": "안녕하",
     "is_final": false,
     "confidence": 0.0
   }

2. 최종 결과:
   {
     "type": "final_transcript",
     "text": "안녕하세요",
     "is_final": true,
     "confidence": 0.95
   }

3. 오류:
   {
     "type": "error",
     "message": "STT engine unavailable"
   }

4. VAD 이벤트:
   {
     "type": "vad",
     "is_speech": true
   }
```

---

## 4. 립싱크 시스템 설계

### 4.1 립싱크 파이프라인

```
[Phase 1: 진폭 기반 립싱크 (MVP)]

TTS Audio Stream
      ↓
Frontend AudioContext.createAnalyser()
      ↓
requestAnimationFrame loop:
  ├── getByteFrequencyData() → 주파수 데이터
  ├── RMS 계산 → 0.0~1.0 진폭값
  ├── Smoothing (exponential moving average)
  └── Live2D model.internalModel.coreModel
        .setParameterValueById("ParamMouthOpenY", smooth_amplitude)
```

```
[Phase 2: Viseme 기반 립싱크 (개선)]

TTS Engine (Azure/ElevenLabs)
      ↓
Viseme Events: { viseme_id, audio_offset_ms }
      ↓
Frontend Viseme Queue:
  ├── Time-synchronized playback
  ├── Viseme → Live2D parameter mapping:
  │    ├── "sil" (silence)    → MouthOpenY: 0.0, MouthForm: 0.0
  │    ├── "aa"  (아)          → MouthOpenY: 1.0, MouthForm: 0.0
  │    ├── "ee"  (이)          → MouthOpenY: 0.3, MouthForm: 0.5
  │    ├── "oo"  (우)          → MouthOpenY: 0.6, MouthForm: -0.5
  │    ├── "oh"  (오)          → MouthOpenY: 0.7, MouthForm: -0.3
  │    └── ... (총 15~22개 Viseme)
  └── Interpolation between visemes (예: 80ms transition)
```

### 4.2 프론트엔드 립싱크 컨트롤러

```typescript
// frontend/src/lib/lipSync.ts

export class LipSyncController {
  private analyser: AnalyserNode | null = null;
  private dataArray: Uint8Array | null = null;
  private smoothValue = 0;
  private animationId: number | null = null;
  private model: any; // Live2D model reference

  // 설정
  private readonly SMOOTHING = 0.3;           // 스무딩 팩터 (0=즉시, 1=변화없음)
  private readonly THRESHOLD = 0.01;          // 최소 진폭 임계값
  private readonly MOUTH_OPEN_SCALE = 1.5;    // 입 열림 스케일

  constructor(private audioContext: AudioContext) {}

  /**
   * 오디오 소스를 립싱크에 연결
   */
  connectSource(source: MediaElementAudioSourceNode | AudioBufferSourceNode) {
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.8;

    source.connect(this.analyser);
    this.analyser.connect(this.audioContext.destination);

    this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    this.startAnimation();
  }

  /**
   * Live2D 모델 연결
   */
  setModel(model: any) {
    this.model = model;
  }

  /**
   * 애니메이션 루프 - 오디오 분석 → 입 파라미터 업데이트
   */
  private startAnimation() {
    const animate = () => {
      if (!this.analyser || !this.dataArray) return;

      this.analyser.getByteFrequencyData(this.dataArray);

      // RMS (Root Mean Square) 계산
      let sum = 0;
      for (let i = 0; i < this.dataArray.length; i++) {
        sum += (this.dataArray[i] / 255) ** 2;
      }
      const rms = Math.sqrt(sum / this.dataArray.length);

      // 지수 이동 평균으로 스무딩
      this.smoothValue = this.SMOOTHING * this.smoothValue + (1 - this.SMOOTHING) * rms;

      // Live2D 파라미터 업데이트
      if (this.model?.internalModel?.coreModel) {
        const mouthOpen = Math.min(
          this.smoothValue * this.MOUTH_OPEN_SCALE,
          1.0
        );
        const coreModel = this.model.internalModel.coreModel;
        coreModel.setParameterValueById("ParamMouthOpenY", mouthOpen > this.THRESHOLD ? mouthOpen : 0);
      }

      this.animationId = requestAnimationFrame(animate);
    };

    this.animationId = requestAnimationFrame(animate);
  }

  /**
   * 정리
   */
  disconnect() {
    if (this.animationId) cancelAnimationFrame(this.animationId);
    this.analyser?.disconnect();
    this.smoothValue = 0;
  }
}
```

---

## 5. 프론트엔드 오디오 매니저 설계

### 5.1 AudioManager 클래스

```typescript
// frontend/src/lib/audioManager.ts

export class AudioManager {
  private audioContext: AudioContext | null = null;
  private lipSync: LipSyncController | null = null;
  private currentAudio: HTMLAudioElement | null = null;
  private audioQueue: AudioQueueItem[] = [];
  private isPlaying = false;

  // STT 관련
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private sttWebSocket: WebSocket | null = null;

  /**
   * TTS 오디오 재생 (스트리밍)
   */
  async playTTSStream(sessionId: string, text: string, emotion: string): Promise<void> {
    await this.ensureAudioContext();

    const response = await fetch(`/api/tts/agents/${sessionId}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, emotion }),
    });

    if (!response.ok || !response.body) throw new Error('TTS request failed');

    // MediaSource API로 스트리밍 재생
    const mediaSource = new MediaSource();
    const audio = new Audio();
    audio.src = URL.createObjectURL(mediaSource);

    mediaSource.addEventListener('sourceopen', async () => {
      const sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
      const reader = response.body!.getReader();

      // 오디오 스트림 → SourceBuffer에 추가
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          mediaSource.endOfStream();
          break;
        }
        await this.appendBuffer(sourceBuffer, value);
      }
    });

    // 립싱크 연결
    const source = this.audioContext!.createMediaElementSource(audio);
    this.lipSync?.connectSource(source);

    await audio.play();
    this.currentAudio = audio;
  }

  /**
   * STT 시작 - 마이크 캡처 + WebSocket 스트리밍
   */
  async startSTT(
    sessionId: string,
    onTranscript: (text: string, isFinal: boolean) => void,
  ): Promise<void> {
    // 마이크 권한 요청
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        sampleRate: 16000,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      }
    });

    // WebSocket 연결
    const backendUrl = getBackendUrl().replace('http', 'ws');
    this.sttWebSocket = new WebSocket(
      `${backendUrl}/api/stt/agents/${sessionId}/listen`
    );

    this.sttWebSocket.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'transcript' || data.type === 'final_transcript') {
        onTranscript(data.text, data.is_final);
      }
    };

    // AudioWorklet으로 PCM 데이터 추출 및 전송
    await this.audioContext!.audioWorklet.addModule('/audio-processor.js');
    const source = this.audioContext!.createMediaStreamSource(this.mediaStream);
    const processor = new AudioWorkletNode(this.audioContext!, 'pcm-processor');

    processor.port.onmessage = (event) => {
      if (this.sttWebSocket?.readyState === WebSocket.OPEN) {
        this.sttWebSocket.send(event.data); // PCM bytes
      }
    };

    source.connect(processor);
  }

  /**
   * STT 중지
   */
  stopSTT(): void {
    this.mediaStream?.getTracks().forEach(t => t.stop());
    this.sttWebSocket?.send(new Uint8Array([69, 78, 68])); // "END"
    this.sttWebSocket?.close();
    this.mediaStream = null;
    this.sttWebSocket = null;
  }

  /**
   * TTS 재생 중지
   */
  stopTTS(): void {
    this.currentAudio?.pause();
    this.currentAudio = null;
    this.lipSync?.disconnect();
  }
}
```

### 5.2 VTuber Store 확장

```typescript
// useVTuberStore.ts 확장

interface VTuberState {
  // ... 기존 상태

  // TTS 상태
  ttsEnabled: boolean;                   // TTS 활성화 여부
  ttsEngine: string;                     // 현재 TTS 엔진
  ttsVoices: Record<string, VoiceProfile>; // 세션별 보이스
  ttsSpeaking: Record<string, boolean>;  // 세션별 재생 상태

  // STT 상태
  sttEnabled: boolean;                   // STT 활성화 여부
  sttListening: boolean;                 // 녹음 중 여부
  sttInterimText: string;               // 중간 인식 결과

  // 액션
  toggleTTS(): void;
  toggleSTT(): void;
  setVoice(sessionId: string, voice: VoiceProfile): Promise<void>;
  speakResponse(sessionId: string, text: string, emotion: string): Promise<void>;
  startListening(sessionId: string): Promise<void>;
  stopListening(): void;
}
```

---

## 6. 통합 데이터 흐름 설계

### 6.1 전체 대화 루프 (음성 대화)

```
┌─────────────────────────────── 음성 대화 루프 ───────────────────────────────┐
│                                                                               │
│  [1] 사용자 음성 입력                                                          │
│  Browser Mic → AudioWorklet → WebSocket → STT Engine → 텍스트                 │
│                                                                               │
│  [2] 텍스트 처리 (기존 흐름)                                                    │
│  텍스트 → POST /broadcast → VTuber Classify → VTuber Respond                  │
│                                                                               │
│  [3] LLM 응답 + 감정                                                          │
│  "[joy] 안녕하세요! 오늘 기분이 좋아요!"                                         │
│       ↓                                                                       │
│  EmotionExtractor: emotion="joy", text="안녕하세요! 오늘 기분이 좋아요!"        │
│                                                                               │
│  [4] 병렬 처리                                                                │
│  ┌─────────────────────┐  ┌─────────────────────┐                            │
│  │ Avatar State Update │  │ TTS Synthesis       │                            │
│  │ expression = joy    │  │ text + emotion=joy  │                            │
│  │ motion = TapBody    │  │ voice = mao_pro_v1  │                            │
│  │       ↓             │  │       ↓             │                            │
│  │ SSE → Frontend      │  │ Audio Stream →      │                            │
│  │ → 표정/모션 변경     │  │ Frontend            │                            │
│  └─────────────────────┘  └──────────┬──────────┘                            │
│                                      ↓                                        │
│  [5] 프론트엔드 동기화                                                         │
│  ┌──────────────────────────────────────────────────────────────┐            │
│  │  Live2D Canvas                                               │            │
│  │  ├── 표정: joy (expression_index: 3) ← AvatarState SSE      │            │
│  │  ├── 모션: TapBody ← AvatarState SSE                        │            │
│  │  ├── 립싱크: ParamMouthOpenY ← AudioAnalyser (실시간)        │            │
│  │  └── 오디오: 스피커 출력 ← TTS Audio Stream                  │            │
│  └──────────────────────────────────────────────────────────────┘            │
│                                                                               │
│  [6] 사용자 응답 대기 → [1]로 반복                                             │
└───────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 메시지 처리 시퀀스 다이어그램

```
User        Frontend       Backend         LLM         TTS Engine
 │              │              │              │              │
 │ 🎤 음성입력   │              │              │              │
 │─────────────→│              │              │              │
 │              │ WS: audio    │              │              │
 │              │─────────────→│              │              │
 │              │              │ STT 처리      │              │
 │              │ WS: "안녕"   │              │              │
 │              │←─────────────│              │              │
 │              │              │              │              │
 │              │ POST broadcast("안녕")      │              │
 │              │─────────────→│              │              │
 │              │   200 OK     │              │              │
 │              │←─────────────│              │              │
 │              │              │ classify     │              │
 │              │              │─────────────→│              │
 │              │              │ "[joy] 안녕!" │              │
 │              │              │←─────────────│              │
 │              │              │              │              │
 │              │              │── emotion_extract ──┐       │
 │              │              │                     │       │
 │              │ SSE: avatar  │◄── avatar update ───┘       │
 │              │←─────────────│                             │
 │              │ 표정 변경 ✨  │                             │
 │              │              │                             │
 │              │              │── TTS: "안녕!" + joy ──────→│
 │              │              │                             │
 │              │ audio stream │◄────── audio chunks ────────│
 │              │←─────────────│                             │
 │ 🔊 음성 출력 │              │                             │
 │ 👄 립싱크    │              │                             │
 │←────────────│              │                             │
```

---

## 7. 설정 시스템 설계

### 7.1 TTS/STT 설정 스키마

```json
{
  "tts": {
    "enabled": true,
    "default_engine": "edge_tts",
    "auto_speak": true,
    "engines": {
      "edge_tts": {
        "enabled": true,
        "default_voice_ko": "ko-KR-SunHiNeural",
        "default_voice_ja": "ja-JP-NanamiNeural",
        "default_voice_en": "en-US-JennyNeural"
      },
      "fish_speech": {
        "enabled": false,
        "url": "http://tts-engine:8001",
        "default_reference_id": "mao_voice_v1"
      },
      "elevenlabs": {
        "enabled": false,
        "api_key": "",
        "default_voice_id": ""
      },
      "openai_tts": {
        "enabled": false,
        "api_key": "",
        "model": "tts-1",
        "voice": "nova"
      }
    },
    "emotion_mapping": {
      "joy":      { "speed": 1.1, "pitch": "+5%",  "style": "cheerful" },
      "anger":    { "speed": 1.2, "pitch": "+2%",  "style": "angry" },
      "sadness":  { "speed": 0.9, "pitch": "-5%",  "style": "sad" },
      "fear":     { "speed": 1.3, "pitch": "+8%",  "style": "fearful" },
      "surprise": { "speed": 1.2, "pitch": "+10%", "style": "excited" },
      "neutral":  { "speed": 1.0, "pitch": "+0%",  "style": "default" }
    },
    "cache": {
      "enabled": true,
      "max_size_mb": 500,
      "ttl_hours": 24
    }
  },
  "stt": {
    "enabled": true,
    "default_engine": "web_speech_api",
    "engines": {
      "web_speech_api": {
        "enabled": true,
        "language": "ko-KR"
      },
      "faster_whisper": {
        "enabled": false,
        "url": "http://stt-engine:8002",
        "model_size": "large-v3",
        "language": "ko"
      },
      "google_cloud_stt": {
        "enabled": false,
        "credentials_path": "",
        "language": "ko-KR"
      }
    },
    "vad": {
      "enabled": true,
      "threshold": 0.5,
      "silence_duration_ms": 500,
      "min_speech_duration_ms": 250
    },
    "auto_send": false,
    "custom_vocabulary": []
  },
  "lip_sync": {
    "enabled": true,
    "method": "amplitude",
    "smoothing": 0.3,
    "mouth_open_scale": 1.5,
    "threshold": 0.01
  }
}
```

### 7.2 모델 레지스트리 확장

```json
{
  "models": [
    {
      "name": "mao_pro",
      "display_name": "Mao Pro",
      "url": "/static/live2d-models/mao_pro/runtime/mao_pro.model3.json",
      "kScale": 0.5,
      "emotionMap": { "neutral": 0, "joy": 3, "anger": 2, ... },
      "tapMotions": { ... },

      "voice": {
        "edge_tts": {
          "voice_id": "ko-KR-SunHiNeural",
          "speed": 1.0,
          "pitch": "+0%"
        },
        "fish_speech": {
          "reference_id": "mao_voice_v1",
          "reference_audio": "/static/voices/mao_pro/reference.wav"
        },
        "elevenlabs": {
          "voice_id": "EXAVITQu4vr4xnSDxMaL"
        }
      },

      "lipSync": {
        "paramMouthOpenY": "ParamMouthOpenY",
        "paramMouthForm": "ParamMouthForm",
        "mouthOpenScale": 1.5,
        "smoothing": 0.3
      }
    }
  ]
}
```

---

## 8. 프론트엔드 UI 설계

### 8.1 VTuber Tab UI 확장

```
┌──────────────────────────────────────────────────────────────┐
│  VTuber Tab                                         [설정 ⚙️] │
├────────────────────────────┬─────────────────────────────────┤
│                            │                                 │
│                            │  💬 Chat Panel                  │
│    🎭 Live2D Canvas       │  ┌─────────────────────────┐    │
│                            │  │ 🤖 Mao: 안녕하세요!     │    │
│    ┌─────────────────┐    │  │    [🔊 다시 듣기]        │    │
│    │                 │    │  │                          │    │
│    │   Live2D Model  │    │  │ 👤 You: 오늘 뭐해?      │    │
│    │   + Lip Sync    │    │  │                          │    │
│    │                 │    │  │ 🤖 Mao: [joy] 코딩하고   │    │
│    │                 │    │  │    있어요~ 🔊              │    │
│    └─────────────────┘    │  │                          │    │
│                            │  └─────────────────────────┘    │
│    ┌──────────────────┐   │                                 │
│    │ 😊 Joy  😠 Anger │   │  ┌─────────────────────────┐    │
│    │ 😢 Sad  😮 Surp  │   │  │ 메시지 입력...     [🎤] [📤]│ │
│    └──────────────────┘   │  │ (음성 인식 중: "안녕...")  │    │
│                            │  └─────────────────────────┘    │
├────────────────────────────┴─────────────────────────────────┤
│  🔊 TTS: ON [Edge TTS ▼]  | 🎤 STT: OFF  | 👄 Lip Sync: ON │
│  Voice: SunHi [미리듣기 ▶]  | Volume: ████░░ 70%              │
└──────────────────────────────────────────────────────────────┘
```

### 8.2 새로운 UI 컴포넌트

| 컴포넌트 | 위치 | 기능 |
|----------|------|------|
| `AudioControls.tsx` | `components/live2d/` | TTS/STT 토글, 볼륨, 엔진 선택 |
| `MicButton.tsx` | `components/live2d/` | 마이크 버튼 (PTT/연속/VAD 모드) |
| `VoiceSelector.tsx` | `components/live2d/` | 보이스 프로필 선택 UI |
| `LipSyncDebug.tsx` | `components/live2d/` | 립싱크 디버그 시각화 (개발용) |
| `TTSSettingsModal.tsx` | `components/modals/` | TTS 상세 설정 모달 |
| `STTSettingsModal.tsx` | `components/modals/` | STT 상세 설정 모달 |

### 8.3 마이크 버튼 인터랙션

```
[모드 1: Push-to-Talk (PTT)]
버튼 누르고 있는 동안만 녹음
→ 직관적, 오인식 방지
→ 모바일/데스크탑 모두 지원

[모드 2: 토글]
클릭으로 녹음 시작/중지
→ 긴 발화에 적합
→ VAD로 자동 종료 가능

[모드 3: VAD 자동]
자동으로 발화 감지
→ 핸즈프리 대화
→ 오인식 가능성 있음
→ TTS 재생 중에는 자동 중지 (에코 방지)
```

---

## 9. 보안 및 개인정보 설계

### 9.1 보안 고려사항

| 항목 | 위험 | 대책 |
|------|------|------|
| API 키 노출 | TTS/STT API 키가 클라이언트에 노출 | 모든 API 호출은 백엔드 프록시 경유 |
| 음성 데이터 유출 | 마이크 데이터가 가로채어질 수 있음 | WSS(WebSocket Secure) 사용 |
| 음성 데이터 저장 | 사용자 음성이 서버에 남을 수 있음 | 인메모리 처리, 전사 후 즉시 폐기 |
| API 남용 | TTS/STT 무한 호출로 과금 폭증 | Rate limiting, 세션당 이용 제한 |
| XSS via STT | 인식된 텍스트에 스크립트 삽입 | 출력 이스케이핑, 입력 검증 |

### 9.2 개인정보 처리 방침

```
1. 음성 데이터는 STT 처리 후 즉시 폐기 (서버에 저장하지 않음)
2. TTS 결과 오디오는 캐시 목적으로만 임시 저장 (TTL 적용)
3. 텍스트 전사 결과만 채팅 기록으로 저장
4. 마이크 접근은 사용자 명시적 허용 필요
5. 클라우드 STT/TTS 사용 시 해당 서비스의 개인정보 정책 고지
```

---

## 10. 에러 처리 및 폴백 설계

### 10.1 에러 시나리오별 폴백

```
[TTS 에러]
Primary Engine 실패
  ↓ 자동 폴백
Edge TTS (항상 사용 가능)
  ↓ 실패 시
텍스트만 표시 + "음성 변환 실패" 알림

[STT 에러]
WebSocket 연결 실패
  ↓ 재연결 시도 (3회)
  ↓ 실패 시
Web Speech API 폴백 (브라우저 내장)
  ↓ 미지원 시
텍스트 입력으로 자동 전환

[립싱크 에러]
AudioContext 생성 실패
  ↓
립싱크 비활성화 (표정/모션만 표시)
  ↓
사용자에게 비침습적 알림
```

### 10.2 상태 모니터링

```typescript
// TTS/STT 상태 모니터링
interface AudioServiceStatus {
  tts: {
    engine: string;
    status: 'ready' | 'speaking' | 'error' | 'disabled';
    lastError?: string;
    latency_ms?: number;
  };
  stt: {
    engine: string;
    status: 'ready' | 'listening' | 'processing' | 'error' | 'disabled';
    lastError?: string;
  };
  lipSync: {
    status: 'active' | 'inactive' | 'error';
    method: 'amplitude' | 'viseme';
    currentAmplitude?: number;
  };
}
```

---

*다음 문서: [03_TTS_STT_구현_계획서.md](03_TTS_STT_구현_계획서.md)*
