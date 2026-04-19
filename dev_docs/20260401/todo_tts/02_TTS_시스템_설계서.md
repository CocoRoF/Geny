# 02. TTS 시스템 설계서

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **범위**: TTS 전용 — 멀티 엔진 아키텍처, Config 기반 전환, 감정 연동, 립싱크

---

## 1. 설계 원칙

| 원칙 | 설명 |
|------|------|
| **엔진 추상화** | 모든 TTS 엔진을 동일 인터페이스 뒤에 숨긴다. 설정만 바꾸면 엔진이 교체된다 |
| **Config 드리븐** | `@register_config` 패턴을 활용하여 TTS 설정 UI가 자동 생성된다 |
| **감정 투명 전달** | EmotionExtractor → TTS Engine으로 감정이 자동 전달된다 |
| **스트리밍 우선** | 오디오는 항상 청크 스트리밍. 전체 생성 대기하지 않는다 |
| **Graceful Fallback** | 선택한 엔진 실패 시 Edge TTS로 자동 폴백. TTS 전체 실패 시 텍스트 표시 |
| **기존 코드 최소 침습** | VTuber 파이프라인의 핵심 로직은 건드리지 않고 TTS를 병렬로 붙인다 |

---

## 2. 전체 아키텍처

### 2.1 시스템 구조도

```
┌─────────────────────────────────────────────────────────────────────────┐
│                             Frontend (Next.js)                          │
│                                                                          │
│  ┌────────────┐  ┌───────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │ Live2D     │  │ VTuberChat    │  │ Audio       │  │ LipSync      │ │
│  │ Canvas     │  │ Panel         │  │ Manager     │  │ Controller   │ │
│  │ (기존)      │←─│ (기존+확장)   │──│ (신규)       │──│ (신규)        │ │
│  │ +립싱크 연동│  │ +TTS 트리거   │  │ 재생/큐잉    │  │ 진폭→입파라미터│ │
│  └─────┬──────┘  └──────┬────────┘  └──────┬──────┘  └──────┬───────┘ │
│        │               │                   │                 │         │
│  ┌─────┴───────────────┴───────────────────┴─────────────────┴───────┐ │
│  │                    useVTuberStore (Zustand) 확장                    │ │
│  │  기존: models, assignments, avatarStates, logs                     │ │
│  │  추가: ttsEnabled, ttsConfig, ttsSpeaking, ttsVolume              │ │
│  └─────────────────────────────┬─────────────────────────────────────┘ │
│                                │                                        │
│           SSE (avatar_state)   │   HTTP (TTS audio stream)             │
│  ┌─────────────────────────────┴────────────────────────────────┐      │
│  │                     api.ts (확장)                              │      │
│  │  기존: vtuberApi.* (7개)                                       │      │
│  │  추가: ttsApi.speak(), .voices(), .preview(), .status()       │      │
│  └──────────────────────────────────────────────────────────────┘      │
└───────────────────────────────────┬───────────────────────────────────┘
                                    │
                          ═════════╪═════════  Network
                                    │
┌───────────────────────────────────┴───────────────────────────────────┐
│                          Backend (FastAPI)                              │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      Controller Layer                             │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │  │
│  │  │ vtuber_      │  │ tts_         │  │ config_controller.py   │ │  │
│  │  │ controller   │  │ controller   │  │ (기존 — TTS 설정 자동  │ │  │
│  │  │ (기존)        │  │ (신규)        │  │  포함됨)               │ │  │
│  │  └──────┬───────┘  └──────┬───────┘  └────────────────────────┘ │  │
│  └─────────┼─────────────────┼─────────────────────────────────────┘  │
│            │                 │                                         │
│  ┌─────────┴─────────────────┴─────────────────────────────────────┐  │
│  │                       Service Layer                              │  │
│  │                                                                   │  │
│  │  ┌────────────────┐     ┌─────────────────────────────────────┐ │  │
│  │  │ EmotionExtract │     │          TTS Service                 │ │  │
│  │  │ or (기존)       │────→│                                     │ │  │
│  │  │ emotion="joy"  │     │  ┌─────────────────────────────┐   │ │  │
│  │  └────────────────┘     │  │    TTSEngine (Abstract)      │   │ │  │
│  │                          │  │                              │   │ │  │
│  │  ┌────────────────┐     │  │  synthesize_stream(req)      │   │ │  │
│  │  │ AvatarState    │     │  │  → AsyncIterator[TTSChunk]   │   │ │  │
│  │  │ Manager (기존)  │     │  └──────────────┬──────────────┘   │ │  │
│  │  └────────────────┘     │                  │                  │ │  │
│  │                          │    ┌─────────────┼─────────────┐   │ │  │
│  │                          │    │  Engine Registry           │   │ │  │
│  │  ┌────────────────┐     │    │                            │   │ │  │
│  │  │ sub_config/tts │────→│    │  ┌─────────┐ ┌─────────┐ │   │ │  │
│  │  │ (계층적 Config) │     │    │  │ EdgeTTS │ │ OpenAI  │ │   │ │  │
│  │  │                │     │    │  │ Engine  │ │ TTS     │ │   │ │  │
│  │  │ • General      │     │    │  └─────────┘ └─────────┘ │   │ │  │
│  │  │ • Edge TTS     │     │    │  ┌─────────┐ ┌─────────┐ │   │ │  │
│  │  │ • OpenAI       │     │    │  │ GPT-    │ │ Eleven  │ │   │ │  │
│  │  │ • ElevenLabs   │     │    │  │ SoVITS  │ │ Labs    │ │   │ │  │
│  │  │ • GPT-SoVITS   │     │    │  └─────────┘ └─────────┘ │   │ │  │
│  │  │ • Fish Speech  │     │    │  ┌─────────┐ ┌─────────┐ │   │ │  │
│  │  │   ...          │     │    │  │ Azure   │ │ Fish    │ │   │ │  │
│  │  └────────────────┘     │    │  │ Speech  │ │ Speech  │ │   │ │  │
│  │                          │    │  └─────────┘ └─────────┘ │   │ │  │
│  │                          │    │  ┌─────────┐ ┌─────────┐ │   │ │  │
│  │                          │    │  │ Azure   │ │ Fish    │ │   │ │  │
│  │                          │    │  │ Speech  │ │ Speech  │ │   │ │  │
│  │                          │    │  └─────────┘ └─────────┘ │   │ │  │
│  │                          │    │  ┌─────────┐ ┌─────────┐ │   │ │  │
│  │                          │    │  │ Google  │ │ CLOVA   │ │   │ │  │
│  │                          │    │  │ Cloud   │ │ Voice   │ │   │ │  │
│  │                          │    │  └─────────┘ └─────────┘ │   │ │  │
│  │                          │    └──────────────────────────┘   │ │  │
│  │                          └─────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌────────────────────────────── Optional ──────────────────────────┐  │
│  │  ┌─────────────────┐  ┌──────────────────┐                      │  │
│  │  │ GPT-SoVITS      │  │ Fish Speech      │  (Docker 서비스)     │  │
│  │  │ :9871            │  │ :8080            │                      │  │
│  │  └─────────────────┘  └──────────────────┘                      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 데이터 흐름 (전체)

```
[LLM 응답 생성]
  vtuber_respond_node → "[joy] 안녕하세요! 오늘 기분이 좋아요!"
      │
      ├──→ EmotionExtractor.extract()
      │      emotion = "joy"
      │      cleaned_text = "안녕하세요! 오늘 기분이 좋아요!"
      │      expression_index = 3
      │
      ├──→ AvatarStateManager.update_state()      ──→ SSE: avatar_state
      │      (표정 + 모션 업데이트)                        │
      │                                                    ↓
      └──→ 응답 메시지 저장 + SSE: message            Frontend에서:
             {text, emotion, tts_available: true}        1. 표정/모션 변경
                    │                                     2. 메시지 표시
                    ↓                                     3. TTS 요청 트리거
               Frontend에서:                                  │
               POST /api/tts/agents/{id}/speak              │
               {text: "안녕하세요!...", emotion: "joy"}       │
                    │                                         │
                    ↓                                         │
               TTS Service                                    │
               ├── Config에서 엔진 결정                      │
               ├── 감정 → 엔진별 파라미터 변환               │
               ├── 엔진.synthesize_stream()                  │
               └── HTTP chunked audio response               │
                    │                                         │
                    ↓                                         │
               Frontend AudioManager                          │
               ├── MediaSource/Audio 재생                     │
               ├── AnalyserNode → 진폭 추출        ←─────────┘
               └── LipSyncController
                    └── ParamMouthOpenY 실시간 업데이트
```

---

## 3. 백엔드 상세 설계

### 3.1 TTS Config 계층 구조 설계

기존 Config 시스템은 **디렉토리 기반 카테고리** 자동 검색을 사용한다:
- `sub_config/channels/` → 사이드바에 "Channels" 카테고리 (Discord, Slack, ...)
- `sub_config/general/` → 사이드바에 "General" 카테고리 (User, API, ...)

TTS도 동일한 패턴으로 **독립 카테고리**를 가진다:
- `sub_config/tts/` → 사이드바에 **"TTS"** 카테고리 생성
- 내부에 General + Provider별 개별 Config 파일

#### 디렉토리 구조

```
backend/service/config/sub_config/
├── channels/                          # 기존
│   ├── discord_config.py
│   ├── slack_config.py
│   └── ...
├── general/                           # 기존
│   ├── api_config.py
│   ├── user_config.py
│   └── ...
└── tts/                               # ★ 신규 TTS 카테고리
    ├── __init__.py
    ├── tts_general_config.py          # General — 공통 설정 + Provider 선택
    ├── edge_tts_config.py             # Edge TTS 개별 설정
    ├── openai_tts_config.py           # OpenAI TTS 개별 설정
    ├── elevenlabs_config.py           # ElevenLabs 개별 설정
    ├── gpt_sovits_config.py           # GPT-SoVITS 개별 설정
    ├── fish_speech_config.py          # Fish Speech 개별 설정
    ├── azure_tts_config.py            # Azure Speech 개별 설정 (Phase 7)
    ├── google_tts_config.py           # Google Cloud TTS 개별 설정 (Phase 7)
    └── clova_config.py                # NAVER CLOVA 개별 설정 (Phase 7)
```

#### 사이드바 결과

```
┌─── 설정 ──────────────────┐
│                            │
│  ┌──────────────────┬───┐ │
│  │ 전체             │20 │ │  ← 기존 12 + TTS 8
│  ├──────────────────┼───┤ │
│  │ Channels         │ 4 │ │
│  │ General          │ 8 │ │
│  │ TTS              │ 8 │ │  ← ★ 신규 카테고리
│  └──────────────────┴───┘ │
│                            │
└────────────────────────────┘
```

TTS 카테고리를 클릭하면 Provider별 Config **카드**가 나열됨:

```
┌─── TTS 카테고리 ─────────────────────────────────────────────────┐
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🔊  General (TTS 공통 설정)                       ✅ 활성화  │ │
│  │     Provider 선택, 언어, 감정 매핑, 캐시, 오디오 포맷        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🆓  Edge TTS                                      ✅ 사용중  │ │
│  │     무료 Microsoft Edge TTS 보이스 설정                      │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🤖  OpenAI TTS                                    ⬚ 미설정  │ │
│  │     OpenAI TTS API (tts-1, tts-1-hd)                         │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🎙️  ElevenLabs                                   ⬚ 미설정   │ │
│  │     고품질 음성 클로닝 + 감정 표현                            │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🔬  GPT-SoVITS                                   ⬚ 비활성  │ │
│  │     오픈소스 음성 복제 — 감정별 레퍼런스 오디오               │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ 🐟  Fish Speech                                   ⬚ 비활성  │ │
│  │     오픈소스 고속 음성 합성 (OpenAI 호환 API)                │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ...                                                               │
└────────────────────────────────────────────────────────────────────┘
```

각 카드를 클릭하면 해당 Provider의 **개별 설정 모달**이 열림.

#### config_controller.py 수정 필요

```python
# category_info에 tts 추가
category_info = {
    "general": {"name": "general", "label": "General", "icon": "settings"},
    "channels": {"name": "channels", "label": "Channels", "icon": "chat"},
    "tts": {"name": "tts", "label": "TTS", "icon": "volume"},          # ★ 추가
    "security": {"name": "security", "label": "Security", "icon": "shield"},
    "advanced": {"name": "advanced", "label": "Advanced", "icon": "code"},
}
```

---

### 3.1.1 TTS General Config

```python
# backend/service/config/sub_config/tts/tts_general_config.py

@register_config
@dataclass
class TTSGeneralConfig(BaseConfig):
    """TTS 공통 설정 — Provider 선택, 전역 ON/OFF, 감정, 캐시"""

    # ─── 기본 설정 ───
    enabled: bool = True
    provider: str = "edge_tts"             # 활성 Provider 선택
    auto_speak: bool = True                 # 응답 시 자동 TTS
    default_language: str = "ko"

    # ─── 감정 매핑 설정 (전 Provider 공통) ───
    emotion_speed_joy: float = 1.1
    emotion_speed_anger: float = 1.2
    emotion_speed_sadness: float = 0.9
    emotion_speed_fear: float = 1.3
    emotion_speed_surprise: float = 1.2
    emotion_pitch_joy: str = "+5%"
    emotion_pitch_anger: str = "+2%"
    emotion_pitch_sadness: str = "-5%"
    emotion_pitch_fear: str = "+8%"
    emotion_pitch_surprise: str = "+10%"

    # ─── 오디오 설정 (전 Provider 공통) ───
    audio_format: str = "mp3"
    sample_rate: int = 24000

    # ─── 캐시 설정 ───
    cache_enabled: bool = True
    cache_max_size_mb: int = 500
    cache_ttl_hours: int = 24

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_general"

    @classmethod
    def get_display_name(cls) -> str:
        return "General (TTS 공통 설정)"

    @classmethod
    def get_description(cls) -> str:
        return "Provider 선택, 언어, 감정 매핑, 오디오 포맷, 캐시"

    @classmethod
    def get_category(cls) -> str:
        return "tts"                        # ★ TTS 카테고리

    @classmethod
    def get_icon(cls) -> str:
        return "settings"                   # General 아이콘

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            # ─── 기본 그룹 ───
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="TTS 활성화",
                description="VTuber 음성 합성 기능 전체 ON/OFF",
                group="기본",
            ),
            ConfigField(
                name="provider",
                field_type=FieldType.SELECT,
                label="TTS Provider",
                description="사용할 TTS 엔진을 선택하세요. 각 Provider의 세부 설정은 개별 카드에서 합니다.",
                group="기본",
                options=[
                    {"value": "edge_tts", "label": "Edge TTS (무료)"},
                    {"value": "openai", "label": "OpenAI TTS"},
                    {"value": "elevenlabs", "label": "ElevenLabs"},
                    {"value": "gpt_sovits", "label": "GPT-SoVITS (오픈소스)"},
                    {"value": "fish_speech", "label": "Fish Speech (오픈소스)"},
                    {"value": "azure", "label": "Azure Speech"},
                    {"value": "google", "label": "Google Cloud TTS"},
                    {"value": "clova", "label": "NAVER CLOVA Voice"},
                ],
            ),
            ConfigField(
                name="auto_speak",
                field_type=FieldType.BOOLEAN,
                label="자동 음성 재생",
                description="VTuber 응답 시 자동으로 음성을 재생합니다",
                group="기본",
            ),
            ConfigField(
                name="default_language",
                field_type=FieldType.SELECT,
                label="기본 언어",
                group="기본",
                options=[
                    {"value": "ko", "label": "한국어"},
                    {"value": "ja", "label": "日本語"},
                    {"value": "en", "label": "English"},
                ],
            ),

            # ─── 감정 매핑 그룹 ───
            ConfigField(
                name="emotion_speed_joy",
                field_type=FieldType.NUMBER,
                label="기쁨 — 속도 배율",
                group="감정 매핑",
                min_value=0.5, max_value=2.0,
            ),
            ConfigField(
                name="emotion_pitch_joy",
                field_type=FieldType.STRING,
                label="기쁨 — 피치",
                group="감정 매핑",
                placeholder="+5%",
            ),
            # ... anger, sadness, fear, surprise 동일 패턴

            # ─── 오디오 그룹 ───
            ConfigField(
                name="audio_format",
                field_type=FieldType.SELECT,
                label="오디오 포맷",
                group="오디오",
                options=[
                    {"value": "mp3", "label": "MP3 (권장)"},
                    {"value": "wav", "label": "WAV (무손실)"},
                    {"value": "ogg", "label": "OGG"},
                ],
            ),
            ConfigField(
                name="sample_rate",
                field_type=FieldType.SELECT,
                label="샘플레이트",
                group="오디오",
                options=[
                    {"value": 24000, "label": "24kHz (기본)"},
                    {"value": 44100, "label": "44.1kHz"},
                    {"value": 48000, "label": "48kHz"},
                ],
            ),

            # ─── 캐시 그룹 ───
            ConfigField(
                name="cache_enabled",
                field_type=FieldType.BOOLEAN,
                label="오디오 캐시",
                description="동일 텍스트+감정의 TTS 결과를 캐시합니다",
                group="캐시",
            ),
            ConfigField(
                name="cache_max_size_mb",
                field_type=FieldType.NUMBER,
                label="최대 캐시 크기 (MB)",
                group="캐시",
                min_value=100, max_value=5000,
            ),
            ConfigField(
                name="cache_ttl_hours",
                field_type=FieldType.NUMBER,
                label="캐시 유효 시간 (시간)",
                group="캐시",
                min_value=1, max_value=168,
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {
                "display_name": "General (TTS 공통 설정)",
                "description": "Provider 선택, 언어, 감정 매핑, 오디오 포맷, 캐시",
            },
            "en": {
                "display_name": "General (TTS Settings)",
                "description": "Provider selection, language, emotion mapping, audio, cache",
            },
        }
```

---

### 3.1.2 Edge TTS Config

```python
# backend/service/config/sub_config/tts/edge_tts_config.py

@register_config
@dataclass
class EdgeTTSConfig(BaseConfig):
    """Edge TTS 설정 — 무료 Microsoft TTS"""

    voice_ko: str = "ko-KR-SunHiNeural"
    voice_ja: str = "ja-JP-NanamiNeural"
    voice_en: str = "en-US-JennyNeural"

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_edge"

    @classmethod
    def get_display_name(cls) -> str:
        return "Edge TTS"

    @classmethod
    def get_description(cls) -> str:
        return "무료 Microsoft Edge TTS — API 키 불필요, 빠른 응답"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_icon(cls) -> str:
        return "free"

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            ConfigField(
                name="voice_ko",
                field_type=FieldType.SELECT,
                label="한국어 보이스",
                group="보이스",
                options=[
                    {"value": "ko-KR-SunHiNeural", "label": "SunHi (여성)"},
                    {"value": "ko-KR-InJoonNeural", "label": "InJoon (남성)"},
                    {"value": "ko-KR-BongJinNeural", "label": "BongJin (남성)"},
                    {"value": "ko-KR-YuJinNeural", "label": "YuJin (여성)"},
                ],
            ),
            ConfigField(
                name="voice_ja",
                field_type=FieldType.SELECT,
                label="일본어 보이스",
                group="보이스",
                options=[
                    {"value": "ja-JP-NanamiNeural", "label": "Nanami (여성)"},
                    {"value": "ja-JP-KeitaNeural", "label": "Keita (남성)"},
                ],
            ),
            ConfigField(
                name="voice_en",
                field_type=FieldType.SELECT,
                label="영어 보이스",
                group="보이스",
                options=[
                    {"value": "en-US-JennyNeural", "label": "Jenny (여성)"},
                    {"value": "en-US-GuyNeural", "label": "Guy (남성)"},
                    {"value": "en-US-AriaNeural", "label": "Aria (여성)"},
                ],
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {"display_name": "Edge TTS", "description": "무료 Microsoft Edge TTS"},
            "en": {"display_name": "Edge TTS", "description": "Free Microsoft Edge TTS"},
        }
```

---

### 3.1.3 OpenAI TTS Config

```python
# backend/service/config/sub_config/tts/openai_tts_config.py

@register_config
@dataclass
class OpenAITTSConfig(BaseConfig):
    """OpenAI TTS 설정"""

    api_key: str = ""
    model: str = "tts-1"
    voice: str = "nova"

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_openai"

    @classmethod
    def get_display_name(cls) -> str:
        return "OpenAI TTS"

    @classmethod
    def get_description(cls) -> str:
        return "OpenAI TTS API — tts-1 (빠름), tts-1-hd (고품질)"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            ConfigField(
                name="api_key",
                field_type=FieldType.PASSWORD,
                label="API Key",
                group="인증",
                placeholder="sk-...",
                secure=True,
            ),
            ConfigField(
                name="model",
                field_type=FieldType.SELECT,
                label="모델",
                group="음성",
                options=[
                    {"value": "tts-1", "label": "tts-1 (빠름, 저비용)"},
                    {"value": "tts-1-hd", "label": "tts-1-hd (고품질)"},
                ],
            ),
            ConfigField(
                name="voice",
                field_type=FieldType.SELECT,
                label="보이스",
                group="음성",
                options=[
                    {"value": "alloy", "label": "Alloy"},
                    {"value": "ash", "label": "Ash"},
                    {"value": "coral", "label": "Coral"},
                    {"value": "echo", "label": "Echo"},
                    {"value": "fable", "label": "Fable"},
                    {"value": "nova", "label": "Nova"},
                    {"value": "onyx", "label": "Onyx"},
                    {"value": "sage", "label": "Sage"},
                    {"value": "shimmer", "label": "Shimmer"},
                ],
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {"display_name": "OpenAI TTS", "description": "OpenAI TTS API"},
            "en": {"display_name": "OpenAI TTS", "description": "OpenAI TTS API"},
        }
```

---

### 3.1.4 ElevenLabs Config

```python
# backend/service/config/sub_config/tts/elevenlabs_config.py

@register_config
@dataclass
class ElevenLabsConfig(BaseConfig):
    """ElevenLabs 설정"""

    api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_multilingual_v2"
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_elevenlabs"

    @classmethod
    def get_display_name(cls) -> str:
        return "ElevenLabs"

    @classmethod
    def get_description(cls) -> str:
        return "고품질 음성 클로닝 + 감정 표현 — 다국어 지원"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            ConfigField(
                name="api_key",
                field_type=FieldType.PASSWORD,
                label="API Key",
                group="인증",
                placeholder="xi-...",
                secure=True,
            ),
            ConfigField(
                name="voice_id",
                field_type=FieldType.STRING,
                label="Voice ID",
                description="ElevenLabs Voice Lab에서 생성한 보이스 ID",
                group="음성",
            ),
            ConfigField(
                name="model_id",
                field_type=FieldType.SELECT,
                label="모델",
                group="음성",
                options=[
                    {"value": "eleven_multilingual_v2", "label": "Multilingual v2 (다국어)"},
                    {"value": "eleven_turbo_v2_5", "label": "Turbo v2.5 (빠름)"},
                    {"value": "eleven_monolingual_v1", "label": "Monolingual v1 (영어)"},
                ],
            ),
            ConfigField(
                name="stability",
                field_type=FieldType.NUMBER,
                label="Stability",
                description="높을수록 안정적, 낮을수록 감정 표현 풍부",
                group="보이스 설정",
                min_value=0.0, max_value=1.0,
            ),
            ConfigField(
                name="similarity_boost",
                field_type=FieldType.NUMBER,
                label="Similarity Boost",
                group="보이스 설정",
                min_value=0.0, max_value=1.0,
            ),
            ConfigField(
                name="style",
                field_type=FieldType.NUMBER,
                label="Style Exaggeration",
                description="감정/스타일 과장 정도",
                group="보이스 설정",
                min_value=0.0, max_value=1.0,
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {"display_name": "ElevenLabs", "description": "고품질 음성 클로닝 + 감정 표현"},
            "en": {"display_name": "ElevenLabs", "description": "High-quality voice cloning + emotion"},
        }
```

---

### 3.1.5 GPT-SoVITS Config

```python
# backend/service/config/sub_config/tts/gpt_sovits_config.py

@register_config
@dataclass
class GPTSoVITSConfig(BaseConfig):
    """GPT-SoVITS 설정 — 오픈소스 음성 복제"""

    enabled: bool = False
    api_url: str = "http://localhost:9871"
    ref_audio_dir: str = ""
    prompt_text: str = ""
    prompt_lang: str = "ko"
    top_k: int = 5
    top_p: float = 1.0
    temperature: float = 1.0
    speed: float = 1.0

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_gpt_sovits"

    @classmethod
    def get_display_name(cls) -> str:
        return "GPT-SoVITS"

    @classmethod
    def get_description(cls) -> str:
        return "오픈소스 음성 복제 — 감정별 레퍼런스 오디오로 자연스러운 감정 표현"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="활성화",
                description="GPT-SoVITS Docker 서비스가 실행 중이어야 합니다",
                group="서버",
            ),
            ConfigField(
                name="api_url",
                field_type=FieldType.URL,
                label="API URL",
                description="GPT-SoVITS API v2 서버 주소",
                group="서버",
                placeholder="http://localhost:9871",
            ),
            ConfigField(
                name="ref_audio_dir",
                field_type=FieldType.STRING,
                label="레퍼런스 오디오 경로",
                description="감정별 레퍼런스 파일이 있는 디렉토리 (ref_joy.wav, ref_anger.wav, ...)",
                group="보이스",
                placeholder="/app/references/mao_pro/",
            ),
            ConfigField(
                name="prompt_text",
                field_type=FieldType.STRING,
                label="프롬프트 텍스트",
                description="레퍼런스 오디오에 해당하는 발화 텍스트",
                group="보이스",
            ),
            ConfigField(
                name="prompt_lang",
                field_type=FieldType.SELECT,
                label="프롬프트 언어",
                group="보이스",
                options=[
                    {"value": "ko", "label": "한국어"},
                    {"value": "ja", "label": "日本語"},
                    {"value": "en", "label": "English"},
                    {"value": "zh", "label": "中文"},
                ],
            ),
            ConfigField(
                name="top_k",
                field_type=FieldType.NUMBER,
                label="Top-K",
                group="생성 파라미터",
                min_value=1, max_value=50,
            ),
            ConfigField(
                name="top_p",
                field_type=FieldType.NUMBER,
                label="Top-P",
                group="생성 파라미터",
                min_value=0.0, max_value=1.0,
            ),
            ConfigField(
                name="temperature",
                field_type=FieldType.NUMBER,
                label="Temperature",
                group="생성 파라미터",
                min_value=0.1, max_value=2.0,
            ),
            ConfigField(
                name="speed",
                field_type=FieldType.NUMBER,
                label="발화 속도",
                group="생성 파라미터",
                min_value=0.5, max_value=2.0,
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {"display_name": "GPT-SoVITS", "description": "오픈소스 음성 복제 — 감정별 레퍼런스"},
            "en": {"display_name": "GPT-SoVITS", "description": "Open-source voice cloning — emotion references"},
        }
```

---

### 3.1.6 Fish Speech Config

```python
# backend/service/config/sub_config/tts/fish_speech_config.py

@register_config
@dataclass
class FishSpeechConfig(BaseConfig):
    """Fish Speech 설정 — 오픈소스 고속 TTS"""

    enabled: bool = False
    api_url: str = "http://localhost:8080"
    reference_id: str = ""

    @classmethod
    def get_config_name(cls) -> str:
        return "tts_fish_speech"

    @classmethod
    def get_display_name(cls) -> str:
        return "Fish Speech"

    @classmethod
    def get_description(cls) -> str:
        return "오픈소스 고속 음성 합성 — OpenAI 호환 API"

    @classmethod
    def get_category(cls) -> str:
        return "tts"

    @classmethod
    def get_fields_metadata(cls) -> list:
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="활성화",
                description="Fish Speech Docker 서비스가 실행 중이어야 합니다",
                group="서버",
            ),
            ConfigField(
                name="api_url",
                field_type=FieldType.URL,
                label="API URL",
                description="OpenAI 호환 API 서버 주소",
                group="서버",
                placeholder="http://localhost:8080",
            ),
            ConfigField(
                name="reference_id",
                field_type=FieldType.STRING,
                label="Reference Voice ID",
                description="등록된 레퍼런스 보이스 ID",
                group="보이스",
            ),
        ]

    @classmethod
    def get_i18n(cls) -> dict:
        return {
            "ko": {"display_name": "Fish Speech", "description": "오픈소스 고속 음성 합성"},
            "en": {"display_name": "Fish Speech", "description": "Open-source fast TTS"},
        }
```

---

### 3.1.7 Azure / Google / CLOVA Config (Phase 7 — 구조만)

```python
# 각각 동일한 패턴. get_category() -> "tts"
# backend/service/config/sub_config/tts/azure_tts_config.py    → "tts_azure"
# backend/service/config/sub_config/tts/google_tts_config.py   → "tts_google"
# backend/service/config/sub_config/tts/clova_config.py        → "tts_clova"
```

---

### 3.1.8 Config 간 참조 패턴

엔진 코드에서 Config를 읽을 때, **General + Provider별 Config을 각각** 로드:

```python
from service.config.manager import ConfigManager

# TTSService에서
general = ConfigManager.load_config("tts_general")    # Provider 선택, 감정, 캐시
edge    = ConfigManager.load_config("tts_edge")        # Edge TTS 보이스

# 예: GPT-SoVITS 엔진에서
general = ConfigManager.load_config("tts_general")     # 감정 속도/피치
sovits  = ConfigManager.load_config("tts_gpt_sovits")  # API URL, 레퍼런스 등
```

> **핵심**: 개별 Config 파일을 `sub_config/tts/` 디렉토리에 넣으면:
> - `_discover_configs()`가 자동 감지 → `@register_config`로 등록
> - `get_category() → "tts"` → 사이드바에 TTS 카테고리 생성
> - 각 Config가 **별도 카드**로 렌더링됨 (Discord, Slack처럼)
> - `GET /api/config/tts_general`, `GET /api/config/tts_edge`, ... 각각 독립 API
> - DB + JSON 파일에 개별 저장/로드

---

### 3.2 TTSEngine 추상 인터페이스

```python
# backend/service/vtuber/tts/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
from enum import Enum

class AudioFormat(Enum):
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    PCM = "pcm"

@dataclass
class TTSRequest:
    """TTS 합성 요청"""
    text: str                                  # 합성할 텍스트 (감정 태그 제거됨)
    emotion: str = "neutral"                   # EmotionExtractor가 추출한 감정
    language: str = "ko"                       # BCP-47 언어 코드
    speed: float = 1.0                         # 발화 속도 (감정에 따라 조절)
    pitch_shift: str = "+0%"                   # 피치 조절 (감정에 따라 조절)
    audio_format: AudioFormat = AudioFormat.MP3
    sample_rate: int = 24000

@dataclass
class TTSChunk:
    """오디오 스트리밍 청크"""
    audio_data: bytes                          # 오디오 바이너리 (부분)
    is_final: bool = False                     # 마지막 청크 여부
    chunk_index: int = 0                       # 청크 순번
    word_boundary: Optional[dict] = None       # WordBoundary 정보 (Edge TTS)
    viseme_data: Optional[list] = None         # Viseme 정보 (Azure)

@dataclass
class VoiceInfo:
    """보이스 정보"""
    id: str                                    # 엔진 내부 보이스 ID
    name: str                                  # 표시명
    language: str                              # 지원 언어
    gender: str                                # male / female
    engine: str                                # 소속 엔진명
    preview_text: str = "안녕하세요, 반갑습니다." # 미리듣기 텍스트

class TTSEngine(ABC):
    """TTS 엔진 추상 인터페이스 — 모든 엔진이 이것을 구현"""

    engine_name: str = "base"                  # 엔진 식별자

    @abstractmethod
    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        """텍스트 → 오디오 청크 스트림 (스트리밍 합성)"""

    @abstractmethod
    async def synthesize(self, request: TTSRequest) -> bytes:
        """텍스트 → 완전한 오디오 (배치 합성)"""

    @abstractmethod
    async def get_voices(self, language: Optional[str] = None) -> list[VoiceInfo]:
        """이 엔진에서 사용 가능한 보이스 목록"""

    @abstractmethod
    async def health_check(self) -> bool:
        """엔진 사용 가능 여부 확인"""

    async def apply_emotion(self, request: TTSRequest) -> TTSRequest:
        """감정에 따른 파라미터 조절 (엔진별 오버라이드 가능)"""
        general = ConfigManager.load_config("tts_general")  # ★ General Config 참조
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
        request.pitch_shift = emotion_pitches.get(request.emotion, "+0%")
        return request
```

### 3.3 엔진 구현체 설계

#### Edge TTS Engine

```python
# backend/service/vtuber/tts/engines/edge_tts_engine.py

class EdgeTTSEngine(TTSEngine):
    engine_name = "edge_tts"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        config = ConfigManager.load_config("tts_edge")     # ★ Edge 전용 Config
        voice = self._resolve_voice(request.language, config)
        request = await self.apply_emotion(request)

        communicate = edge_tts.Communicate(
            text=request.text,
            voice=voice,
            rate=self._speed_to_rate(request.speed),
            pitch=request.pitch_shift,
        )

        chunk_index = 0
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield TTSChunk(
                    audio_data=chunk["data"],
                    chunk_index=chunk_index,
                )
                chunk_index += 1
            elif chunk["type"] == "WordBoundary":
                yield TTSChunk(
                    audio_data=b"",
                    chunk_index=chunk_index,
                    word_boundary={
                        "text": chunk["text"],
                        "offset": chunk["offset"],
                        "duration": chunk["duration"],
                    },
                )
        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=chunk_index)

    def _resolve_voice(self, language: str, config) -> str:
        return {
            "ko": config.voice_ko,     # ★ EdgeTTSConfig 필드명
            "ja": config.voice_ja,
            "en": config.voice_en,
        }.get(language, config.voice_ko)
```

#### GPT-SoVITS Engine (핵심)

```python
# backend/service/vtuber/tts/engines/gpt_sovits_engine.py

class GPTSoVITSEngine(TTSEngine):
    engine_name = "gpt_sovits"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=60.0)

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        config = ConfigManager.load_config("tts_gpt_sovits")  # ★ GPT-SoVITS 전용 Config

        # 감정별 레퍼런스 오디오 선택 (핵심 감정 기능!)
        ref_audio_path = self._get_emotion_ref(request.emotion, config)

        payload = {
            "text": request.text,
            "text_lang": self._lang_to_sovits(request.language),
            "ref_audio_path": ref_audio_path,
            "prompt_text": config.prompt_text,
            "prompt_lang": config.prompt_lang,
            "top_k": config.top_k,
            "top_p": config.top_p,
            "temperature": config.temperature,
            "speed_factor": request.speed * config.speed,
            "media_type": request.audio_format.value,
            "streaming_mode": True,
            "parallel_infer": True,
            "repetition_penalty": 1.35,
        }

        chunk_index = 0
        try:
            async with self._client.stream(
                "POST", f"{config.api_url}/tts", json=payload
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(chunk_size=4096):
                    yield TTSChunk(audio_data=chunk, chunk_index=chunk_index)
                    chunk_index += 1
        except Exception as e:
            logger.error(f"GPT-SoVITS error: {e}")
            raise

        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=chunk_index)

    def _get_emotion_ref(self, emotion: str, config) -> str:
        """감정에 맞는 레퍼런스 오디오 경로 반환"""
        ref_dir = config.ref_audio_dir
        # 감정별 레퍼런스: ref_joy.wav, ref_anger.wav, ...
        emotion_file = f"ref_{emotion}.wav"
        full_path = os.path.join(ref_dir, emotion_file)

        if os.path.exists(full_path):
            return full_path
        # 폴백: neutral
        return os.path.join(ref_dir, "ref_neutral.wav")

    async def health_check(self) -> bool:
        try:
            config = ConfigManager.load_config("tts_gpt_sovits")
            resp = await self._client.get(f"{config.api_url}/")
            return resp.status_code == 200
        except:
            return False
```

#### OpenAI TTS Engine

```python
# backend/service/vtuber/tts/engines/openai_tts_engine.py

class OpenAITTSEngine(TTSEngine):
    engine_name = "openai"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        config = ConfigManager.load_config("tts_openai")  # ★ OpenAI 전용 Config

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.model,
                    "input": request.text,
                    "voice": config.voice,
                    "response_format": request.audio_format.value,
                    "speed": request.speed,
                },
            ) as resp:
                resp.raise_for_status()
                chunk_index = 0
                async for chunk in resp.aiter_bytes(4096):
                    yield TTSChunk(audio_data=chunk, chunk_index=chunk_index)
                    chunk_index += 1

        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=chunk_index)
```

#### ElevenLabs Engine

```python
# backend/service/vtuber/tts/engines/elevenlabs_engine.py

class ElevenLabsEngine(TTSEngine):
    engine_name = "elevenlabs"

    # 감정 → ElevenLabs voice_settings
    EMOTION_SETTINGS = {
        "neutral":  {"stability": 0.50, "similarity_boost": 0.75, "style": 0.00},
        "joy":      {"stability": 0.30, "similarity_boost": 0.75, "style": 0.80},
        "anger":    {"stability": 0.70, "similarity_boost": 0.85, "style": 0.60},
        "sadness":  {"stability": 0.60, "similarity_boost": 0.70, "style": 0.40},
        "fear":     {"stability": 0.40, "similarity_boost": 0.65, "style": 0.50},
        "surprise": {"stability": 0.20, "similarity_boost": 0.75, "style": 0.90},
        "disgust":  {"stability": 0.65, "similarity_boost": 0.80, "style": 0.30},
        "smirk":    {"stability": 0.45, "similarity_boost": 0.75, "style": 0.60},
    }

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        config = ConfigManager.load_config("tts_elevenlabs")  # ★ ElevenLabs 전용 Config
        voice_settings = self.EMOTION_SETTINGS.get(request.emotion, self.EMOTION_SETTINGS["neutral"])

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"https://api.elevenlabs.io/v1/text-to-speech/{config.voice_id}/stream",
                headers={"xi-api-key": config.api_key},
                json={
                    "text": request.text,
                    "model_id": config.model_id,
                    "voice_settings": voice_settings,
                },
            ) as resp:
                resp.raise_for_status()
                chunk_index = 0
                async for chunk in resp.aiter_bytes(4096):
                    yield TTSChunk(audio_data=chunk, chunk_index=chunk_index)
                    chunk_index += 1

        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=chunk_index)
```

#### Fish Speech Engine

```python
# backend/service/vtuber/tts/engines/fish_speech_engine.py

class FishSpeechEngine(TTSEngine):
    engine_name = "fish_speech"

    async def synthesize_stream(self, request: TTSRequest) -> AsyncIterator[TTSChunk]:
        config = ConfigManager.load_config("tts_fish_speech")  # ★ Fish Speech 전용 Config

        # Fish Speech는 OpenAI 호환 API → 동일 패턴
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{config.api_url}/v1/audio/speech",
                json={
                    "model": "fish-speech-1.5",
                    "input": request.text,
                    "voice": config.reference_id,
                    "response_format": request.audio_format.value,
                    "speed": request.speed,
                },
            ) as resp:
                resp.raise_for_status()
                chunk_index = 0
                async for chunk in resp.aiter_bytes(4096):
                    yield TTSChunk(audio_data=chunk, chunk_index=chunk_index)
                    chunk_index += 1

        yield TTSChunk(audio_data=b"", is_final=True, chunk_index=chunk_index)
```

### 3.4 TTS Service (엔진 관리자)

```python
# backend/service/vtuber/tts/tts_service.py

import hashlib, logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

class TTSService:
    """TTS 엔진 레지스트리 + Config 기반 라우팅 + 폴백 + 캐시"""

    def __init__(self):
        self._engines: dict[str, TTSEngine] = {}
        self._cache: dict[str, bytes] = {}    # hash → audio bytes (인메모리)

    def register_engine(self, engine: TTSEngine):
        """엔진 등록"""
        self._engines[engine.engine_name] = engine
        logger.info(f"TTS engine registered: {engine.engine_name}")

    def get_engine(self, name: Optional[str] = None) -> TTSEngine:
        """범용 Config에서 지정된 엔진 반환, 없으면 폴백"""
        if name is None:
            general = ConfigManager.load_config("tts_general")  # ★ General Config
            name = general.provider

        engine = self._engines.get(name)
        if engine:
            return engine

        # 폴백: edge_tts
        logger.warning(f"Engine '{name}' not found, falling back to edge_tts")
        return self._engines.get("edge_tts")

    async def speak(
        self,
        text: str,
        emotion: str = "neutral",
        language: str = "ko",
        engine_name: Optional[str] = None,
    ) -> AsyncIterator[TTSChunk]:
        """메인 TTS 엔트리포인트 — General Config 기반 엔진 선택 + 스트리밍"""

        general = ConfigManager.load_config("tts_general")  # ★ General Config
        if not general.enabled:
            return  # TTS 비활성화

        engine = self.get_engine(engine_name)
        if not engine:
            logger.error("No TTS engine available")
            return

        # 엔진 헬스 체크
        if not await engine.health_check():
            logger.warning(f"{engine.engine_name} health check failed, trying fallback")
            engine = self._engines.get("edge_tts")
            if not engine or not await engine.health_check():
                logger.error("All TTS engines unavailable")
                return

        request = TTSRequest(
            text=text,
            emotion=emotion,
            language=language,
            audio_format=AudioFormat(general.audio_format),    # ★ general
            sample_rate=general.sample_rate,                    # ★ general
        )

        # 감정 파라미터 적용
        request = await engine.apply_emotion(request)

        # 스트리밍 합성
        try:
            async for chunk in engine.synthesize_stream(request):
                yield chunk
        except Exception as e:
            logger.error(f"TTS synthesis failed ({engine.engine_name}): {e}")
            # 폴백 시도
            if engine.engine_name != "edge_tts":
                fallback = self._engines.get("edge_tts")
                if fallback:
                    logger.info("Retrying with edge_tts fallback")
                    async for chunk in fallback.synthesize_stream(request):
                        yield chunk

    async def get_all_voices(self, language: Optional[str] = None) -> dict[str, list[VoiceInfo]]:
        """모든 엔진의 보이스 목록"""
        result = {}
        for name, engine in self._engines.items():
            try:
                if await engine.health_check():
                    result[name] = await engine.get_voices(language)
            except:
                pass
        return result

    async def get_status(self) -> dict:
        """모든 엔진의 상태"""
        status = {}
        for name, engine in self._engines.items():
            try:
                healthy = await engine.health_check()
                status[name] = {"available": healthy, "engine": name}
            except:
                status[name] = {"available": False, "engine": name}
        return status

# 싱글턴
_tts_service: Optional[TTSService] = None

def get_tts_service() -> TTSService:
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
        # 기본 엔진 등록
        _tts_service.register_engine(EdgeTTSEngine())
        _tts_service.register_engine(OpenAITTSEngine())
        _tts_service.register_engine(ElevenLabsEngine())
        _tts_service.register_engine(GPTSoVITSEngine())
        _tts_service.register_engine(FishSpeechEngine())
        # Azure, Google, CLOVA 등 추가 가능
    return _tts_service
```

### 3.5 TTS Controller (API 엔드포인트)

```python
# backend/controller/tts_controller.py

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/tts", tags=["TTS"])

@router.post("/agents/{session_id}/speak")
async def speak(session_id: str, body: SpeakRequest):
    """
    텍스트를 음성으로 변환하여 오디오 스트리밍 반환

    - text: 합성할 텍스트
    - emotion: 감정 (neutral, joy, anger, sadness, fear, surprise, disgust, smirk)
    - language: 언어 코드 (ko, ja, en)
    - engine: 엔진 지정 (선택, 미지정 시 Config 기본값)
    """
    tts = get_tts_service()
    general = ConfigManager.load_config("tts_general")  # ★ General Config

    content_type = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
    }.get(general.audio_format, "audio/mpeg")

    async def audio_generator():
        async for chunk in tts.speak(
            text=body.text,
            emotion=body.emotion or "neutral",
            language=body.language or general.default_language,
            engine_name=body.engine,
        ):
            if chunk.audio_data:
                yield chunk.audio_data

    return StreamingResponse(
        audio_generator(),
        media_type=content_type,
        headers={
            "Transfer-Encoding": "chunked",
            "Cache-Control": "no-cache",
            "X-TTS-Engine": general.provider,
        },
    )

@router.get("/voices")
async def list_voices(language: str = None):
    """사용 가능한 보이스 목록 (엔진별)"""
    tts = get_tts_service()
    return await tts.get_all_voices(language)

@router.get("/voices/{engine}/{voice_id}/preview")
async def preview_voice(engine: str, voice_id: str, text: str = "안녕하세요, 반갑습니다."):
    """보이스 미리듣기"""
    tts = get_tts_service()
    engine_instance = tts.get_engine(engine)
    request = TTSRequest(text=text, emotion="neutral")
    audio_data = await engine_instance.synthesize(request)
    return StreamingResponse(
        iter([audio_data]),
        media_type="audio/mpeg",
    )

@router.get("/status")
async def get_status():
    """TTS 엔진 상태 확인"""
    tts = get_tts_service()
    return await tts.get_status()

@router.get("/engines")
async def list_engines():
    """등록된 TTS 엔진 목록"""
    tts = get_tts_service()
    return {
        "engines": list(tts._engines.keys()),
        "default": ConfigManager.load_config("tts_general").provider,
    }
```

---

## 4. 프론트엔드 상세 설계

### 4.1 API 확장 (`api.ts`)

```typescript
// frontend/src/lib/api.ts — ttsApi 추가

export const ttsApi = {
  /** TTS 오디오 스트리밍 요청 — Response는 ReadableStream */
  speak: async (
    sessionId: string,
    text: string,
    emotion: string = 'neutral',
    language?: string,
    engine?: string,
  ): Promise<Response> => {
    const backendUrl = getBackendUrl();
    return fetch(`${backendUrl}/api/tts/agents/${sessionId}/speak`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, emotion, language, engine }),
    });
  },

  /** 보이스 목록 */
  voices: (language?: string) =>
    apiCall<Record<string, VoiceInfo[]>>(
      `/api/tts/voices${language ? `?language=${language}` : ''}`
    ),

  /** 보이스 미리듣기 */
  preview: async (engine: string, voiceId: string, text?: string): Promise<Response> => {
    const backendUrl = getBackendUrl();
    const params = text ? `?text=${encodeURIComponent(text)}` : '';
    return fetch(`${backendUrl}/api/tts/voices/${engine}/${voiceId}/preview${params}`);
  },

  /** TTS 서비스 상태 */
  status: () => apiCall<Record<string, { available: boolean }>>('/api/tts/status'),

  /** 엔진 목록 */
  engines: () => apiCall<{ engines: string[]; default: string }>('/api/tts/engines'),
};
```

### 4.2 AudioManager 설계

```typescript
// frontend/src/lib/audioManager.ts

export class AudioManager {
  private audioContext: AudioContext | null = null;
  private currentAudio: HTMLAudioElement | null = null;
  private gainNode: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private sourceNode: MediaElementAudioSourceNode | null = null;
  private onAmplitudeChange: ((amplitude: number) => void) | null = null;
  private animFrameId: number | null = null;
  private _volume: number = 0.7;

  /**
   * AudioContext 초기화 (사용자 인터랙션 후 호출 필요)
   */
  async init(): Promise<void> {
    if (this.audioContext) return;
    this.audioContext = new AudioContext();
    this.gainNode = this.audioContext.createGain();
    this.gainNode.gain.value = this._volume;
    this.gainNode.connect(this.audioContext.destination);

    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.8;
  }

  /**
   * TTS 스트리밍 오디오 재생
   * Response body를 Blob으로 변환 → Audio 엘리먼트 재생
   */
  async playTTSResponse(
    response: Response,
    onStart?: () => void,
    onEnd?: () => void,
  ): Promise<void> {
    await this.init();
    this.stop(); // 이전 재생 중지

    if (!response.ok || !response.body) {
      throw new Error(`TTS response error: ${response.status}`);
    }

    // 스트리밍 바디 → Blob
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
    const blob = new Blob(chunks, { type: response.headers.get('content-type') || 'audio/mpeg' });
    const url = URL.createObjectURL(blob);

    // Audio 엘리먼트 생성 및 Web Audio API 연결
    const audio = new Audio(url);
    this.currentAudio = audio;

    if (this.audioContext && this.analyser && this.gainNode) {
      this.sourceNode = this.audioContext.createMediaElementSource(audio);
      this.sourceNode.connect(this.analyser);
      this.analyser.connect(this.gainNode);
      this.startAmplitudeTracking();
    }

    audio.onplay = () => onStart?.();
    audio.onended = () => {
      this.stopAmplitudeTracking();
      onEnd?.();
      URL.revokeObjectURL(url);
    };
    audio.onerror = () => {
      this.stopAmplitudeTracking();
      onEnd?.();
      URL.revokeObjectURL(url);
    };

    await audio.play();
  }

  /**
   * 진폭 추적 (립싱크용)
   */
  private startAmplitudeTracking(): void {
    if (!this.analyser) return;
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);

    const track = () => {
      this.analyser!.getByteFrequencyData(dataArray);

      // RMS 계산
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        sum += (dataArray[i] / 255) ** 2;
      }
      const rms = Math.sqrt(sum / dataArray.length);

      this.onAmplitudeChange?.(rms);
      this.animFrameId = requestAnimationFrame(track);
    };

    this.animFrameId = requestAnimationFrame(track);
  }

  private stopAmplitudeTracking(): void {
    if (this.animFrameId) {
      cancelAnimationFrame(this.animFrameId);
      this.animFrameId = null;
    }
    this.onAmplitudeChange?.(0); // 입 닫기
  }

  /** 립싱크 콜백 등록 */
  setAmplitudeCallback(cb: (amplitude: number) => void): void {
    this.onAmplitudeChange = cb;
  }

  /** 볼륨 설정 (0~1) */
  setVolume(vol: number): void {
    this._volume = Math.max(0, Math.min(1, vol));
    if (this.gainNode) {
      this.gainNode.gain.value = this._volume;
    }
  }

  /** 현재 재생 중지 */
  stop(): void {
    this.stopAmplitudeTracking();
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.src = '';
      this.currentAudio = null;
    }
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
  }

  /** 재생 중 여부 */
  get isPlaying(): boolean {
    return this.currentAudio !== null && !this.currentAudio.paused;
  }

  /** 정리 */
  dispose(): void {
    this.stop();
    this.audioContext?.close();
    this.audioContext = null;
  }
}

// 싱글턴
let _audioManager: AudioManager | null = null;
export function getAudioManager(): AudioManager {
  if (!_audioManager) {
    _audioManager = new AudioManager();
  }
  return _audioManager;
}
```

### 4.3 LipSync Controller 설계

```typescript
// frontend/src/lib/lipSync.ts

const SMOOTHING = 0.3;
const MOUTH_OPEN_SCALE = 1.8;
const THRESHOLD = 0.015;

export class LipSyncController {
  private model: any = null;  // Live2D model reference
  private smoothValue = 0;

  /** Live2D 모델 연결 */
  setModel(model: any): void {
    this.model = model;
  }

  /**
   * AudioManager에서 호출하는 콜백
   * amplitude: 0.0 ~ 1.0 (RMS)
   */
  onAmplitude(amplitude: number): void {
    // 지수 이동 평균 스무딩
    this.smoothValue = SMOOTHING * this.smoothValue + (1 - SMOOTHING) * amplitude;

    if (!this.model?.internalModel?.coreModel) return;

    const coreModel = this.model.internalModel.coreModel;
    const mouthOpen = this.smoothValue > THRESHOLD
      ? Math.min(this.smoothValue * MOUTH_OPEN_SCALE, 1.0)
      : 0;

    coreModel.setParameterValueById('ParamMouthOpenY', mouthOpen);
  }

  /** 리셋 (재생 종료 시) */
  reset(): void {
    this.smoothValue = 0;
    if (this.model?.internalModel?.coreModel) {
      this.model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', 0);
    }
  }
}
```

### 4.4 useVTuberStore 확장

```typescript
// useVTuberStore.ts에 추가할 TTS 상태 & 액션

// 추가 상태
ttsEnabled: boolean;                    // TTS ON/OFF
ttsSpeaking: Record<string, boolean>;   // 세션별 재생 상태
ttsVolume: number;                      // 0~1

// 추가 액션
toggleTTS: () => void;                  // TTS 토글
setTTSVolume: (vol: number) => void;    // 볼륨 설정
speakResponse: (                        // TTS 합성 + 재생
  sessionId: string,
  text: string,
  emotion: string,
) => Promise<void>;
stopSpeaking: (sessionId: string) => void; // 재생 중지
```

### 4.5 VTuberChatPanel 통합 설계

```
[메시지 수신 시 자동 TTS 트리거 흐름]

1. SSE message 이벤트 수신
     ↓
2. 스토어에 ttsEnabled 확인
     ↓ (ON이면)
3. ttsApi.speak(sessionId, text, emotion) 호출
     ↓
4. Response → AudioManager.playTTSResponse()
     ↓
5. AudioManager amplitude 콜백 → LipSyncController.onAmplitude()
     ↓
6. Live2DCanvas의 모델 ParamMouthOpenY 실시간 업데이트
     ↓
7. 재생 종료 → LipSyncController.reset()
```

### 4.6 AudioControls 컴포넌트 설계

```
┌─────────────────────────────────────────────────────────┐
│  🔊 TTS: ON     Volume: ████░░ 70%     Engine: Edge TTS │
│  [🔈 토글]       [━━━━━━━━○━━━━]        [▼ 엔진 선택]    │
└─────────────────────────────────────────────────────────┘

상태별 표시:
- TTS OFF:  🔇 TTS: OFF (회색)
- 대기 중:  🔊 TTS: ON (파란색)
- 재생 중:  🔊 재생 중... (녹색 + 펄스 애니메이션)
- 에러:    ⚠️ TTS 오류 (빨간색)
```

---

## 5. 설정(Config) 연동 상세

### 5.1 계층 구조 전체 맵

```
설정 사이드바                         설정 카드 목록
┌──────────────┐                    ┌──────────────────────────┐
│ 전체    (20) │                    │                          │
│ Channels (4) │                    │  [General 카드]          │ ← 클릭 → 모달
│ General  (8) │                    │  [Edge TTS 카드]         │ ← 클릭 → 모달
│ TTS      (8) │ ← 선택             │  [OpenAI TTS 카드]       │ ← 클릭 → 모달
│              │                    │  [ElevenLabs 카드]       │
└──────────────┘                    │  [GPT-SoVITS 카드]       │
                                    │  [Fish Speech 카드]      │
                                    │  [Azure Speech 카드]     │
                                    │  [Google Cloud TTS 카드] │
                                    └──────────────────────────┘

카드 클릭 시 열리는 모달:
┌── General (TTS 공통 설정) ────────────────────────────────┐
│                                                            │
│  ── 기본 ──                                               │
│  [✅] TTS 활성화                                          │
│  TTS Provider: [GPT-SoVITS (오픈소스) ▼]                  │
│  [✅] 자동 음성 재생                                      │
│  기본 언어: [한국어 ▼]                                     │
│                                                            │
│  ── 감정 매핑 ──                                          │
│  기쁨 — 속도 배율: [1.1]   기쁨 — 피치: [+5%]             │
│  분노 — 속도 배율: [1.2]   분노 — 피치: [+2%]             │
│  슬픔 — 속도 배율: [0.9]   슬픔 — 피치: [-5%]             │
│  ...                                                       │
│                                                            │
│  ── 오디오 ──                                             │
│  오디오 포맷: [MP3 (권장) ▼]                               │
│  샘플레이트: [24kHz (기본) ▼]                              │
│                                                            │
│  ── 캐시 ──                                               │
│  [✅] 오디오 캐시                                         │
│  최대 캐시 크기: [500] MB                                  │
│  캐시 유효 시간: [24] 시간                                  │
│                                                            │
│                                    [저장]  [초기화]        │
└────────────────────────────────────────────────────────────┘

카드 클릭 시 열리는 모달 (Provider 예시):
┌── GPT-SoVITS ─────────────────────────────────────────────┐
│                                                            │
│  ── 서버 ──                                               │
│  [☐] 활성화                                               │
│  API URL: [http://localhost:9871        ]                  │
│                                                            │
│  ── 보이스 ──                                             │
│  레퍼런스 오디오 경로: [/app/references/mao_pro/]          │
│  프롬프트 텍스트: [안녕하세요, 저는 마오입니다.]            │
│  프롬프트 언어: [한국어 ▼]                                 │
│                                                            │
│  ── 생성 파라미터 ──                                      │
│  Top-K: [5]                                                │
│  Top-P: [1.0]                                              │
│  Temperature: [1.0]                                        │
│  발화 속도: [1.0]                                          │
│                                                            │
│                                    [저장]  [초기화]        │
└────────────────────────────────────────────────────────────┘
```

### 5.2 설정 흐름 (계층적)

```
[사용자 시나리오: Provider를 GPT-SoVITS로 변경]

1. 설정 탭 → 사이드바에서 "TTS" 카테고리 클릭
     ↓
2. "GPT-SoVITS" 카드 클릭 → 모달 열림
     ↓ PUT /api/config/tts_gpt_sovits { "enabled": true, "api_url": "..." }
3. ConfigManager.update_config("tts_gpt_sovits")
     ├── DB 저장 (persistent_configs)
     ├── JSON 파일 백업 (variables/tts_gpt_sovits.json)
     └── 캐시 업데이트
     ↓
4. "General" 카드 클릭 → 모달 열림
     ↓ PUT /api/config/tts_general { "provider": "gpt_sovits" }
5. ConfigManager.update_config("tts_general")
     └── 다음 TTS 요청부터 GPT-SoVITS 엔진 사용!
```

```
[Config 읽기 흐름 — TTSService 내부]

tts_service.speak("안녕하세요", emotion="joy")
     │
     ├── general = ConfigManager.load_config("tts_general")
     │      general.provider → "gpt_sovits"
     │      general.enabled → True
     │      general.emotion_speed_joy → 1.1
     │
     └── sovits = ConfigManager.load_config("tts_gpt_sovits")
            sovits.api_url → "http://localhost:9871"
            sovits.ref_audio_dir → "/app/references/mao_pro/"
            sovits.temperature → 1.0
```

### 5.3 Config 이름 규칙

| Config Name | 카테고리 | 카드 표시명 | API 경로 |
|-------------|---------|-----------|---------|
| `tts_general` | tts | General (TTS 공통 설정) | `/api/config/tts_general` |
| `tts_edge` | tts | Edge TTS | `/api/config/tts_edge` |
| `tts_openai` | tts | OpenAI TTS | `/api/config/tts_openai` |
| `tts_elevenlabs` | tts | ElevenLabs | `/api/config/tts_elevenlabs` |
| `tts_gpt_sovits` | tts | GPT-SoVITS | `/api/config/tts_gpt_sovits` |
| `tts_fish_speech` | tts | Fish Speech | `/api/config/tts_fish_speech` |
| `tts_azure` | tts | Azure Speech | `/api/config/tts_azure` |
| `tts_google` | tts | Google Cloud TTS | `/api/config/tts_google` |
| `tts_clova` | tts | NAVER CLOVA | `/api/config/tts_clova` |

모두 `get_category() → "tts"` 반환 → 사이드바 TTS (8) 자동 집계

---

## 6. GPT-SoVITS 보이스 프로필 관리 설계

### 6.1 감정별 레퍼런스 디렉토리 구조

```
backend/static/voices/
├── mao_pro/
│   ├── ref_neutral.wav     # 평범한 톤 5~10초
│   ├── ref_joy.wav         # 밝고 활기찬 톤
│   ├── ref_anger.wav       # 화난 톤
│   ├── ref_sadness.wav     # 슬픈 톤
│   ├── ref_fear.wav        # 불안한 톤
│   ├── ref_surprise.wav    # 놀란 톤
│   ├── ref_disgust.wav     # 불쾌한 톤
│   ├── ref_smirk.wav       # 장난스러운 톤
│   └── profile.json        # 프로필 메타데이터
│
└── shizuku/
    ├── ref_neutral.wav
    ├── ref_joy.wav
    └── ...
```

### 6.2 profile.json 스키마

```json
{
  "name": "mao_pro",
  "display_name": "Mao Pro 보이스",
  "language": "ko",
  "prompt_text": "안녕하세요, 저는 마오입니다. 오늘도 좋은 하루 보내세요.",
  "prompt_lang": "ko",
  "emotion_refs": {
    "neutral": {"file": "ref_neutral.wav", "text": "안녕하세요, 저는 마오입니다."},
    "joy": {"file": "ref_joy.wav", "text": "와아~ 정말 좋아요! 너무 기뻐요!"},
    "anger": {"file": "ref_anger.wav", "text": "정말 화가 나요. 이건 아니에요."},
    "sadness": {"file": "ref_sadness.wav", "text": "슬프네요... 마음이 아파요."},
    "fear": {"file": "ref_fear.wav", "text": "무서워요... 어떡하죠?"},
    "surprise": {"file": "ref_surprise.wav", "text": "정말요?! 깜짝 놀랐어요!"},
    "disgust": {"file": "ref_disgust.wav", "text": "으... 그건 좀 별로예요."},
    "smirk": {"file": "ref_smirk.wav", "text": "후후~ 그렇게 생각하시나요?"}
  },
  "gpt_sovits_settings": {
    "top_k": 5,
    "top_p": 1.0,
    "temperature": 1.0,
    "speed_factor": 1.0
  }
}
```

---

## 7. 오디오 캐시 설계

### 7.1 캐시 키 생성

```python
import hashlib

def make_cache_key(text: str, emotion: str, engine: str, voice_id: str) -> str:
    """텍스트+감정+엔진+보이스 → 고유 해시"""
    raw = f"{text}|{emotion}|{engine}|{voice_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

### 7.2 캐시 저장소

```
backend/cache/tts/
├── a1b2c3d4e5f6g7h8.mp3   # 캐시된 오디오
├── ...
└── _index.json              # 캐시 인덱스 (key → {file, created, size, text_preview})
```

### 7.3 캐시 동작

```
요청 → Cache Hit?
  ├── Yes → 캐시된 오디오 스트리밍 반환 (즉시)
  └── No → TTS 엔진 합성 → 클라이언트 스트리밍 + 캐시 저장
```

---

## 8. 에러 처리 & 폴백 체인

```
[폴백 체인]

설정된 엔진 (예: GPT-SoVITS)
  │ 실패 (연결 불가 / 타임아웃 / 에러)
  ↓
Edge TTS (항상 등록된 무료 폴백)
  │ 실패 (네트워크 문제)
  ↓
텍스트만 반환 + "음성 합성 실패" 알림
  (Frontend는 정상 동작 유지)
```

```
[에러별 처리]

ConnectionError     → 즉시 폴백, "엔진 연결 불가" 로그
TimeoutError        → 5초 후 폴백, "응답 대기 시간 초과" 로그
HTTPStatusError     → 상태 코드 확인 후 폴백
AuthenticationError → API 키 설정 확인 안내
RateLimitError      → 잠시 후 재시도 또는 폴백
```

---

*다음 문서: [03_TTS_구현_계획서.md](03_TTS_구현_계획서.md)*
