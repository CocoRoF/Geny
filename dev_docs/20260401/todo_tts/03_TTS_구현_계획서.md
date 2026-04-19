# 03. TTS 구현 계획서

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **이전 문서**: [01_TTS_심층_분석_리포트.md](01_TTS_심층_분석_리포트.md) · [02_TTS_시스템_설계서.md](02_TTS_시스템_설계서.md)

---

## 1. 구현 단계 개요

| 단계 | 이름 | 범위 | 예상 | 핵심 결과물 |
|:----:|------|------|------|------------|
| **Phase 0** | 환경 준비 | 의존성, 패키지, Docker 기초 | 짧음 | 프로젝트 구조, 의존성 설치 |
| **Phase 1** | 엔진 코어 | 추상 베이스 + Edge TTS MVP | 중간 | TTSEngine ABC, EdgeTTSEngine, TTS API |
| **Phase 2** | Config 통합 | 계층적 TTS Config + UI 자동 렌더링 | 중간 | Config 기반 엔진 전환 |
| **Phase 3** | 클라우드 엔진 | OpenAI + ElevenLabs | 짧음~중간 | 2개 클라우드 엔진 |
| **Phase 4** | 오픈소스 엔진 | GPT-SoVITS + Fish Speech | 중간~김 | 2개 로컬 엔진 + Docker |
| **Phase 5** | 프론트엔드 | AudioManager + 립싱크 | 중간 | 오디오 재생 + 입모양 동기화 |
| **Phase 6** | 감정 연동 | EmotionExtractor → TTS 감정 | 짧음 | 감정 기반 음성 변조 |
| **Phase 7** | 고도화 | 캐시, 보이스 프로필, 확장 엔진 | 중간 | 프로덕션 품질 |

---

## 2. Phase 0: 환경 준비

### 목표
TTS 코드 작성을 위한 디렉토리 구조 생성 및 의존성 설치

### 작업 목록

#### 0-1. 디렉토리 구조 생성

```
backend/service/vtuber/tts/
├── __init__.py
├── base.py                     # TTSEngine ABC, TTSRequest, TTSChunk, VoiceInfo
├── tts_service.py              # TTSService (엔진 레지스트리 + 라우팅)
└── engines/
    ├── __init__.py
    └── (엔진 파일은 Phase 1~4에서 추가)

backend/service/config/sub_config/tts/
├── __init__.py
├── tts_general_config.py       # TTSGeneralConfig (Phase 2)
├── edge_tts_config.py          # EdgeTTSConfig (Phase 2)
├── openai_tts_config.py        # OpenAITTSConfig (Phase 3)
├── elevenlabs_config.py        # ElevenLabsConfig (Phase 3)
├── gpt_sovits_config.py        # GPTSoVITSConfig (Phase 4)
└── fish_speech_config.py       # FishSpeechConfig (Phase 4)

backend/controller/
└── tts_controller.py           # TTS API 엔드포인트 (Phase 1)

backend/static/voices/
└── (보이스 프로필 디렉토리 — Phase 4)

backend/cache/tts/
└── (오디오 캐시 디렉토리 — Phase 7)
```

#### 0-2. Python 의존성 추가

```txt
# requirements.txt에 추가
edge-tts>=6.1                   # Edge TTS (무료)
httpx>=0.27                     # 비동기 HTTP 클라이언트 (이미 있을 수 있음)
```

#### 0-3. 프론트엔드 의존성 확인

```
기존 의존성으로 충분 (추가 패키지 불필요):
- Web Audio API (브라우저 내장)
- MediaSource API (브라우저 내장)
- fetch streaming (브라우저 내장)
```

### 완료 기준
- [ ] 디렉토리 + `__init__.py` 파일 생성 완료
- [ ] `pip install edge-tts httpx` 정상 설치
- [ ] 기존 테스트 깨지지 않음

---

## 3. Phase 1: 엔진 코어 + Edge TTS MVP

### 목표
TTSEngine 추상 인터페이스 정의 → Edge TTS 엔진 구현 → `/api/tts/agents/{id}/speak` API → 브라우저에서 음성 재생 확인

### 작업 목록

#### 1-1. TTSEngine 추상 베이스 (`base.py`)

```python
# 구현할 클래스/데이터클래스:
- AudioFormat (Enum): MP3, WAV, OGG, PCM
- TTSRequest (dataclass): text, emotion, language, speed, pitch_shift, audio_format, sample_rate
- TTSChunk (dataclass): audio_data, is_final, chunk_index, word_boundary, viseme_data
- VoiceInfo (dataclass): id, name, language, gender, engine, preview_text
- TTSEngine (ABC): synthesize_stream, synthesize, get_voices, health_check, apply_emotion
```

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.2

#### 1-2. EdgeTTSEngine 구현 (`engines/edge_tts_engine.py`)

- `edge-tts` 라이브러리의 `Communicate` 클래스 사용
- 스트리밍 청크 생성 (`Communicate.stream()`)
- 언어별 기본 보이스 매핑 (ko/ja/en)
- `health_check()`: edge-tts는 외부 서버 의존 → 간단한 연결 테스트

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.3 Edge TTS Engine

#### 1-3. TTSService 기본 구현 (`tts_service.py`)

- 엔진 레지스트리 (register/get)
- `speak()` 메서드: 기본 라우팅 + 스트리밍
- 싱글턴 패턴 (`get_tts_service()`)
- 이 단계에서는 Config 미연동 → 하드코딩 기본값

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.4

#### 1-4. TTS Controller (`tts_controller.py`)

- `POST /api/tts/agents/{session_id}/speak` — StreamingResponse 반환
- `GET /api/tts/status` — 엔진 상태
- `GET /api/tts/engines` — 엔진 목록
- `main.py`에 라우터 등록

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.5

#### 1-5. 수동 테스트

```bash
# 백엔드 실행 후
curl -X POST http://localhost:8000/api/tts/agents/test/speak \
  -H "Content-Type: application/json" \
  -d '{"text": "안녕하세요, 테스트입니다.", "emotion": "neutral"}' \
  --output test_tts.mp3

# test_tts.mp3 재생하여 음성 확인
```

### 완료 기준
- [ ] `POST /api/tts/agents/{id}/speak` → MP3 오디오 스트리밍 반환
- [ ] 한국어, 일본어, 영어 각각 정상 합성
- [ ] `GET /api/tts/status` → `{"edge_tts": {"available": true}}`
- [ ] cURL로 받은 MP3 파일 재생 가능

---

## 4. Phase 2: Config 시스템 통합

### 목표
`@register_config` 기반 **계층적** TTS Config 구현 → 사이드바에 TTS 카테고리 생성 → General + Provider별 개별 설정 카드

### 작업 목록

#### 2-1. `sub_config/tts/` 디렉토리 생성

```
backend/service/config/sub_config/tts/
├── __init__.py
├── tts_general_config.py      # General: provider, 감정, 캐시, 오디오
└── edge_tts_config.py         # Edge TTS: 보이스 설정
```

#### 2-2. TTSGeneralConfig 클래스 생성

- `@register_config` 데코레이터 적용
- `get_config_name() → "tts_general"`, `get_category() → "tts"`
- 필드: `enabled`, `provider` (SELECT), `auto_speak`, `default_language`, 감정 매핑, 오디오, 캐시
- `get_fields_metadata()` — group별 ConfigField 정의

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.1

#### 2-3. EdgeTTSConfig 클래스 생성

- `get_config_name() → "tts_edge"`, `get_category() → "tts"`
- 필드: `voice_ko`, `voice_ja`, `voice_en` (각각 SELECT)

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.2

#### 2-4. config_controller.py에 TTS 카테고리 추가

```python
category_info = {
    ...
    "tts": {"name": "tts", "label": "TTS", "icon": "volume"},
}
```

#### 2-5. TTSService에 Config 연동

- `get_engine()`에서 `ConfigManager.load_config("tts_general").provider` 읽기
- `speak()`에서 `general.enabled`, `general.audio_format`, `general.sample_rate` 적용
- `apply_emotion()`에서 `general.emotion_speed_*`, `general.emotion_pitch_*` 적용
- 엔진에서 각자 Config 로드: `ConfigManager.load_config("tts_edge")` 등

#### 2-6. Config 자동 검색 동작 확인

- `_discover_configs()`가 `sub_config/tts/` 디렉토리 자동 탐색
- 백엔드 시작 시 `[Config] Registered: tts_general`, `[Config] Registered: tts_edge` 로그 확인

#### 2-7. Config UI 확인

- 프론트엔드에서 설정 탭 접속
- 사이드바에 **TTS (2)** 카테고리 생성 확인
- "General" 카드 + "Edge TTS" 카드 표시 확인
- 각 카드 클릭 → 개별 모달 → 필드 렌더링 확인
- 값 변경 → 저장 → API 실제 반영 확인

### 완료 기준
- [ ] 사이드바에 TTS 카테고리 표시 (카드 수 표시)
- [ ] `GET /api/config/tts_general` → General Config JSON 반환
- [ ] `GET /api/config/tts_edge` → Edge TTS Config JSON 반환
- [ ] `PUT /api/config/tts_general` → Provider 변경 성공
- [ ] Config UI에 TTS 카테고리 → 카드 목록 → 개별 모달 정상 동작
- [ ] Provider 변경 후 TTS 요청 시 변경된 엔진 사용

---

## 5. Phase 3: 클라우드 TTS 엔진

### 목표
OpenAI TTS + ElevenLabs 엔진 구현 + 각각의 개별 Config 카드 추가. Config 사이드바 TTS (4)로 증가.

### 작업 목록

#### 3-1. OpenAI TTS Config + Engine

- `sub_config/tts/openai_tts_config.py` → `tts_openai`, category `tts`
- 필드: `api_key` (PASSWORD), `model` (SELECT), `voice` (SELECT)
- `engines/openai_tts_engine.py` → `ConfigManager.load_config("tts_openai")` 사용

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.3, § 3.3

#### 3-2. ElevenLabs Config + Engine

- `sub_config/tts/elevenlabs_config.py` → `tts_elevenlabs`, category `tts`
- 필드: `api_key`, `voice_id`, `model_id`, `stability`, `similarity_boost`, `style`
- `engines/elevenlabs_engine.py` → `ConfigManager.load_config("tts_elevenlabs")` 사용

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.4, § 3.3

#### 3-3. TTSService 엔진 등록 업데이트

```python
_tts_service.register_engine(OpenAITTSEngine())
_tts_service.register_engine(ElevenLabsEngine())
```

#### 3-4. 통합 테스트

- General Config에서 provider를 `openai`로 변경 → TTS 요청 → OpenAI 음성 확인
- General Config에서 provider를 `elevenlabs`로 변경 → TTS 요청 → ElevenLabs 음성 확인
- OpenAI TTS 카드에서 API 키 미설정 시 적절한 에러 메시지 반환 확인
- 폴백: OpenAI API 키 잘못 → Edge TTS로 자동 전환 확인
- 사이드바 TTS (4) 표시 확인

### 완료 기준
- [ ] 사이드바 TTS 카테고리에 4개 카드 (General, Edge, OpenAI, ElevenLabs)
- [ ] OpenAI TTS로 한국어/영어 합성 정상
- [ ] ElevenLabs TTS로 합성 정상 + 감정별 voice_settings 차이 확인
- [ ] General에서 provider 변경만으로 엔진 즉시 전환
- [ ] 폴백 체인 정상 동작

---

## 6. Phase 4: 오픈소스 TTS 엔진 (GPT-SoVITS, Fish Speech)

### 목표
GPT-SoVITS 및 Fish Speech 엔진 구현 + 각각의 Config 카드 추가. Docker 서비스 추가. 감정별 보이스 프로필 관리. 사이드바 TTS (6).

### 작업 목록

#### 4-1. GPT-SoVITS Docker 서비스 추가

```yaml
# docker-compose.yml에 추가 (선택적 프로필)
services:
  gpt-sovits:
    image: breakstring/gpt-sovits:latest     # 또는 커스텀 빌드
    profiles: ["tts-local"]                   # 기본으로 뜨지 않음
    ports:
      - "9871:9871"
    volumes:
      - ./backend/static/voices:/app/references   # 보이스 데이터
      - gpt-sovits-models:/app/models             # SoVITS/GPT 모델
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    environment:
      - is_half=True
```

#### 4-2. GPT-SoVITS Config + Engine

- `sub_config/tts/gpt_sovits_config.py` → `tts_gpt_sovits`, category `tts`
- 필드: `enabled`, `api_url`, `ref_audio_dir`, `prompt_text`, `prompt_lang`, `top_k`, `top_p`, `temperature`, `speed`
- `engines/gpt_sovits_engine.py` → `ConfigManager.load_config("tts_gpt_sovits")` 사용
- httpx POST `{config.api_url}/tts` (API v2 형식)
- 감정별 레퍼런스 오디오 자동 선택 (`_get_emotion_ref()`)

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.5, § 3.3

#### 4-3. 보이스 프로필 관리

- `backend/static/voices/{profile_name}/` 구조 생성
- `profile.json` 스키마 정의
- 감정별 레퍼런스 오디오 파일 (`ref_neutral.wav`, `ref_joy.wav`, ...)
- `GET /api/tts/voices/gpt_sovits` → 프로필 목록 반환

**설계서 참조**: 02_TTS_시스템_설계서.md § 6. GPT-SoVITS 보이스 프로필 관리

#### 4-4. Fish Speech Docker 서비스 추가

```yaml
services:
  fish-speech:
    image: fishaudio/fish-speech:latest
    profiles: ["tts-local"]
    ports:
      - "8080:8080"
    volumes:
      - fish-speech-models:/app/models
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

#### 4-5. Fish Speech Config + Engine

- `sub_config/tts/fish_speech_config.py` → `tts_fish_speech`, category `tts`
- 필드: `enabled`, `api_url`, `reference_id`
- `engines/fish_speech_engine.py` → `ConfigManager.load_config("tts_fish_speech")` 사용
- OpenAI 호환 API (`/v1/audio/speech`)

**설계서 참조**: 02_TTS_시스템_설계서.md § 3.1.6, § 3.3

#### 4-6. Docker Compose 프로필 테스트

```bash
# 로컬 TTS 서비스 포함 기동
docker compose --profile tts-local up -d

# GPT-SoVITS 헬스 체크
curl http://localhost:9871/

# Fish Speech 헬스 체크
curl http://localhost:8080/v1/models
```

#### 4-7. 통합 테스트

- GPT-SoVITS로 한국어 합성 → 감정별 레퍼런스로 음색 변화 확인
- Fish Speech로 합성 → 음질 확인
- Docker 서비스 중지 시 Edge TTS 폴백 확인
- Config에서 엔진 전환 테스트

### 완료 기준
- [ ] 사이드바 TTS 카테고리에 6개 카드 (General, Edge, OpenAI, ElevenLabs, GPT-SoVITS, Fish Speech)
- [ ] GPT-SoVITS 컨테이너 정상 동작
- [ ] GPT-SoVITS 카드에서 설정 변경 → 즉시 반영
- [ ] `ref_joy.wav` ↔ `ref_sadness.wav` 감정에 따른 음색 차이 확인
- [ ] Fish Speech 카드에서 설정 변경 → 즉시 반영
- [ ] Fish Speech 컨테이너 정상 합성
- [ ] Docker 프로필 기반 선택적 기동
- [ ] 폴백 체인 정상 (오픈소스 서버 다운 → Edge TTS)

---

## 7. Phase 5: 프론트엔드 오디오 + 립싱크

### 목표
AudioManager로 TTS 오디오 재생 → Web Audio API 진폭 추출 → Live2D ParamMouthOpenY 립싱크

### 작업 목록

#### 5-1. AudioManager 구현 (`lib/audioManager.ts`)

- AudioContext 초기화
- StreamingResponse → Blob → Audio 재생
- Web Audio API 연결: MediaElementSource → AnalyserNode → GainNode → destination
- 진폭 콜백: `requestAnimationFrame` 루프에서 `getByteFrequencyData` → RMS 계산
- 볼륨 제어: GainNode.gain 조절
- stop/dispose 메서드

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.2

#### 5-2. LipSyncController 구현 (`lib/lipSync.ts`)

- 진폭 → ParamMouthOpenY 매핑
- 지수 이동 평균 스무딩 (smoothing factor 0.3)
- threshold 아래면 입 닫기
- `setModel()`: Live2D 모델 참조 연결
- `reset()`: 재생 종료 시 호출

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.3

#### 5-3. ttsApi 추가 (`lib/api.ts`)

```typescript
ttsApi.speak(sessionId, text, emotion, language?, engine?)
ttsApi.voices(language?)
ttsApi.preview(engine, voiceId, text?)
ttsApi.status()
ttsApi.engines()
```

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.1

#### 5-4. useVTuberStore TTS 상태 추가

```typescript
// 추가할 상태
ttsEnabled: boolean
ttsSpeaking: Record<string, boolean>
ttsVolume: number

// 추가할 액션
toggleTTS()
setTTSVolume(vol)
speakResponse(sessionId, text, emotion)
stopSpeaking(sessionId)
```

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.4

#### 5-5. Live2DCanvas 립싱크 연동

- `Live2DCanvas.tsx`에서 LipSyncController 인스턴스 생성
- 모델 로드 완료 시 `lipSync.setModel(model)` 호출
- AudioManager에 `lipSync.onAmplitude` 콜백 등록
- 기존 표정 시스템과 충돌 없이 공존 (ParamMouthOpenY만 TTS가 제어)

#### 5-6. AudioControls UI 컴포넌트

- TTS ON/OFF 토글 버튼
- 볼륨 슬라이더
- 현재 엔진 표시
- 재생 중 상태 표시 (펄스 애니메이션)

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.6

#### 5-7. VTuberChatPanel 통합

- SSE 메시지 수신 → ttsEnabled 확인 → speakResponse() 자동 호출
- 메시지별 수동 TTS 재생 버튼 (스피커 아이콘)
- 재생 중 시각 피드백

**설계서 참조**: 02_TTS_시스템_설계서.md § 4.5

### 완료 기준
- [ ] VTuber 응답 시 자동으로 음성 재생
- [ ] 음성 재생 중 Live2D 모델의 입이 자연스럽게 움직임
- [ ] TTS ON/OFF 토글 정상 동작
- [ ] 볼륨 슬라이더 동작
- [ ] 재생 종료 시 입이 자연스럽게 닫힘
- [ ] 메시지별 수동 재생 버튼 동작

---

## 8. Phase 6: 감정 연동 강화

### 목표
EmotionExtractor의 8가지 감정 → TTS 파라미터 매핑 완성. 엔진별 감정 표현 최적화.

### 작업 목록

#### 6-1. EmotionExtractor → TTS 파이프라인 통합

```python
# VTuber 응답 파이프라인에서
emotion_result = EmotionExtractor.extract(llm_response)
# emotion_result.primary_emotion → TTS에 전달

tts_service.speak(
    text=emotion_result.cleaned_text,
    emotion=emotion_result.primary_emotion,
)
```

#### 6-2. 엔진별 감정 파라미터 최적화

| 감정 | Edge TTS | OpenAI | ElevenLabs | GPT-SoVITS |
|------|----------|--------|------------|------------|
| joy | rate +10%, pitch +5% | speed 1.1 | stability↓, style↑ | ref_joy.wav |
| anger | rate +20%, pitch +2% | speed 1.15 | stability↑, style↑ | ref_anger.wav |
| sadness | rate -10%, pitch -5% | speed 0.9 | stability↑, style↓ | ref_sadness.wav |
| fear | rate +15%, pitch +8% | speed 1.1 | stability↓ | ref_fear.wav |
| surprise | rate +10%, pitch +10% | speed 1.05 | stability↓, style↑ | ref_surprise.wav |
| disgust | rate +5%, pitch -2% | speed 0.95 | stability↑ | ref_disgust.wav |
| smirk | rate +0%, pitch +3% | speed 1.0 | style↑ | ref_smirk.wav |
| neutral | 기본값 | 기본값 | 기본값 | ref_neutral.wav |

#### 6-3. Config에서 감정 매핑 커스터마이즈

- `ConfigManager.load_config("tts_general")` 의 emotion 매핑 필드 활용
- TTS 카테고리 → General 카드에서 감정별 속도/피치 조절 가능

#### 6-4. 감정 전환 테스트

- LLM에 감정적 응답 유도 → 각 감정별 TTS 출력 비교
- 감정 전환 시 부자연스러운 끊김 없는지 확인
- GPT-SoVITS 감정별 레퍼런스 음색 차이 확인

### 완료 기준
- [ ] 8가지 감정 각각 다른 TTS 파라미터 적용
- [ ] Edge TTS: 속도/피치 변화 체감
- [ ] ElevenLabs: voice_settings 차이 체감
- [ ] GPT-SoVITS: 레퍼런스별 음색 차이 체감
- [ ] Config에서 감정 매핑 수정 가능

---

## 9. Phase 7: 고도화 및 프로덕션 준비

### 목표
캐싱, 확장 엔진, 보이스 프로필 관리 UI, 비용 추적, 성능 최적화

### 작업 목록

#### 7-1. 오디오 캐시 시스템

- `text + emotion + engine + voice → SHA256 해시` 키 생성
- 파일 캐시: `backend/cache/tts/{hash}.mp3`
- 인메모리 인덱스: `_index.json`
- TTL 기반 만료 (기본 24시간)
- 최대 크기 초과 시 LRU 삭제
- Config에서 캐시 ON/OFF, 최대 크기 조절

**설계서 참조**: 02_TTS_시스템_설계서.md § 7. 오디오 캐시 설계

#### 7-2. 보이스 프로필 관리 API

```
GET  /api/tts/profiles              # 프로필 목록
GET  /api/tts/profiles/{name}       # 프로필 상세
POST /api/tts/profiles              # 프로필 생성
PUT  /api/tts/profiles/{name}       # 프로필 수정
POST /api/tts/profiles/{name}/ref   # 레퍼런스 오디오 업로드
```

#### 7-3. 확장 엔진 구현 (선택)

- Azure Speech: SSML 기반 세밀한 감정 제어 + Viseme 데이터
- Google Cloud TTS: Neural2 보이스
- NAVER CLOVA Voice: 한국어 특화

#### 7-4. 비용 추적

- 엔진별 문자 수 / API 호출 수 집계
- 월별 비용 추정 (엔진별 단가 기반)
- Config 화면에 비용 현황 표시

#### 7-5. 성능 최적화

- 동시 요청 제한 (semaphore)
- 긴 텍스트 → 문장 단위 분할 + 파이프라인 합성
- 첫 청크 지연 시간 측정 & 최적화
- WebSocket 방식 검토 (HTTP 스트리밍 → WS 전환 가능성)

#### 7-6. 보이스 프로필 관리 UI (프론트엔드)

- 프로필 목록 / 생성 / 삭제 화면
- 감정별 레퍼런스 오디오 업로드 UI
- 레퍼런스 미리듣기
- Live2D 모델 ↔ 보이스 프로필 매핑 관리

### 완료 기준
- [ ] 동일 문장 2회 요청 시 캐시 히트 확인
- [ ] 보이스 프로필 CRUD API 동작
- [ ] 프론트엔드에서 레퍼런스 오디오 업로드 가능
- [ ] 비용 추적 데이터 표시

---

## 10. 파일 생성 목록 (전체)

### 백엔드

| Phase | 파일 경로 | 설명 |
|:-----:|----------|------|
| 0 | `service/vtuber/tts/__init__.py` | 패키지 초기화 |
| 1 | `service/vtuber/tts/base.py` | TTSEngine ABC, 데이터클래스 |
| 1 | `service/vtuber/tts/tts_service.py` | TTSService 엔진 관리자 |
| 1 | `service/vtuber/tts/engines/__init__.py` | 엔진 패키지 |
| 1 | `service/vtuber/tts/engines/edge_tts_engine.py` | Edge TTS 엔진 |
| 1 | `controller/tts_controller.py` | TTS API 라우터 |
| 2 | `service/config/sub_config/tts/__init__.py` | TTS 카테고리 패키지 |
| 2 | `service/config/sub_config/tts/tts_general_config.py` | TTSGeneralConfig |
| 2 | `service/config/sub_config/tts/edge_tts_config.py` | EdgeTTSConfig |
| 3 | `service/config/sub_config/tts/openai_tts_config.py` | OpenAITTSConfig |
| 3 | `service/config/sub_config/tts/elevenlabs_config.py` | ElevenLabsConfig |
| 4 | `service/config/sub_config/tts/gpt_sovits_config.py` | GPTSoVITSConfig |
| 4 | `service/config/sub_config/tts/fish_speech_config.py` | FishSpeechConfig |
| 3 | `service/vtuber/tts/engines/openai_tts_engine.py` | OpenAI TTS 엔진 |
| 3 | `service/vtuber/tts/engines/elevenlabs_engine.py` | ElevenLabs 엔진 |
| 4 | `service/vtuber/tts/engines/gpt_sovits_engine.py` | GPT-SoVITS 엔진 |
| 4 | `service/vtuber/tts/engines/fish_speech_engine.py` | Fish Speech 엔진 |
| 4 | `static/voices/mao_pro/profile.json` | 예시 보이스 프로필 |
| 7 | `service/vtuber/tts/cache.py` | TTS 오디오 캐시 |
| 7 | `service/vtuber/tts/engines/azure_tts_engine.py` | Azure 엔진 (선택) |
| 7 | `service/vtuber/tts/engines/google_tts_engine.py` | Google 엔진 (선택) |
| 7 | `service/vtuber/tts/engines/clova_engine.py` | CLOVA 엔진 (선택) |

### 프론트엔드

| Phase | 파일 경로 | 설명 |
|:-----:|----------|------|
| 5 | `src/lib/audioManager.ts` | 오디오 재생 + Web Audio API |
| 5 | `src/lib/lipSync.ts` | 립싱크 컨트롤러 |
| 5 | `src/components/vtuber/AudioControls.tsx` | TTS 컨트롤 UI |

### 수정 파일

| Phase | 파일 경로 | 변경 내용 |
|:-----:|----------|----------|
| 0 | `requirements.txt` | edge-tts, httpx 추가 |
| 1 | `main.py` | TTS 라우터 등록 |
| 2 | `controller/config_controller.py` | TTS category_info 추가 |
| 4 | `docker-compose.yml` | GPT-SoVITS, Fish Speech 서비스 |
| 4 | `docker-compose.dev.yml` | 로컬 개발 TTS 설정 |
| 5 | `src/lib/api.ts` | ttsApi 추가 |
| 5 | `src/store/useVTuberStore.ts` | TTS 상태 추가 |
| 5 | `src/components/live2d/Live2DCanvas.tsx` | 립싱크 연동 |
| 5 | VTuberChatPanel 관련 컴포넌트 | TTS 트리거 통합 |

---

## 11. 의존성 관계

```
Phase 0 (환경 준비)
  │
  ├──→ Phase 1 (엔진 코어 + Edge TTS)
  │       │
  │       ├──→ Phase 2 (Config 통합)  ←── Config 시스템이 선행 조건
  │       │       │
  │       │       ├──→ Phase 3 (클라우드 엔진)
  │       │       │
  │       │       └──→ Phase 4 (오픈소스 엔진) ←── GPU Docker 환경 필요
  │       │
  │       └──→ Phase 5 (프론트엔드)  ←── Phase 1 API가 선행 조건
  │               │
  │               └──→ Phase 6 (감정 연동) ←── Phase 5 + Phase 2 필요
  │
  └──→ Phase 7 (고도화) ←── Phase 1~6 모두 완료 후
```

주의: **Phase 3과 Phase 4는 병렬 진행 가능** (둘 다 Phase 2에만 의존)

---

## 12. 테스트 전략

### 유닛 테스트

| 대상 | 테스트 범위 |
|------|------------|
| `TTSRequest` | 데이터 직렬화, 기본값 |
| `apply_emotion()` | 감정별 속도/피치 계산 |
| `make_cache_key()` | 동일 입력 → 동일 해시 |
| `_get_emotion_ref()` | 감정별 파일 경로 + 폴백 |
| `LipSyncController` | 진폭 → ParamMouthOpenY 매핑 |

### 통합 테스트

| 시나리오 | 검증 항목 |
|----------|----------|
| 엔진 전환 | Config 변경 → 다음 요청에서 새 엔진 사용 |
| 폴백 체인 | 선택 엔진 실패 → Edge TTS → 텍스트 |
| 감정 파이프라인 | EmotionExtractor → TTS → 음성 차이 |
| 오디오 캐시 | 첫 요청 합성 → 두 번째 요청 캐시 히트 |
| E2E | LLM 응답 → 감정 추출 → TTS → 오디오 재생 → 립싱크 |

### 수동 테스트 체크리스트

- [ ] Config 탭에서 엔진을 5번 연속 변경해도 앱이 안정적
- [ ] 긴 문장 (500자) TTS 합성 시 첫 소리 나오기까지 시간 측정
- [ ] GPT-SoVITS 서버를 중간에 꺼도 프론트엔드 오류 없음
- [ ] 동시에 여러 세션에서 TTS 요청 시 충돌 없음
- [ ] 음성 재생 중 새 메시지가 와도 큐잉 처리

---

## 13. 주의사항 및 리스크

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| GPT-SoVITS GPU 메모리 부족 | OOM 크래시 | Docker `mem_limit`, `is_half=True` 설정 |
| 레퍼런스 오디오 품질 | TTS 출력 품질 저하 | 레퍼런스 녹음 가이드 문서화 (5~10초, 깨끗한 단일 화자) |
| Edge TTS 서비스 불안정 | 무료 폴백 실패 | 2차 폴백 (다른 무료 TTS) 또는 로컬 Piper 경량 엔진 |
| 웹 오디오 정책 | 첫 재생 차단 | 사용자 인터랙션 후 AudioContext 초기화 |
| 동시 TTS 요청 | 서버 과부하 | Semaphore로 동시 합성 수 제한 |
| API 키 보안 | 유출 위험 | PASSWORD 타입 필드 + DB 암호화 저장 |

---

## 14. 용어 사전

| 용어 | 설명 |
|------|------|
| **TTSEngine** | TTS 엔진 추상 인터페이스. 모든 엔진이 이것을 구현 |
| **TTSService** | 엔진 레지스트리 + 라우팅 + 폴백을 담당하는 서비스 계층 |
| **TTS Config 계층** | `sub_config/tts/` 디렉토리 기반 계층적 설정. TTSGeneralConfig + 프로바이더별 Config 카드로 구성 |
| **TTSChunk** | 스트리밍 오디오의 한 조각 (bytes + 메타데이터) |
| **레퍼런스 오디오** | GPT-SoVITS가 음색을 복제할 때 참조하는 짧은 음성 샘플 |
| **보이스 프로필** | 감정별 레퍼런스 + 설정을 묶은 단위 (모델별 1개) |
| **AudioManager** | 프론트엔드 오디오 재생 + Web Audio API 관리 싱글턴 |
| **LipSyncController** | 오디오 진폭 → Live2D ParamMouthOpenY 매핑 담당 |
| **폴백 체인** | 선택 엔진 실패 → Edge TTS → 텍스트 순서의 에러 복구 |

---

*이 계획서에 따라 Phase 0부터 순차적으로 구현을 진행합니다.*
