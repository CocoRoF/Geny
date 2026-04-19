# 01. TTS/STT 현황 분석 리포트

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **목적**: VTuber 서비스에 TTS(Text-to-Speech) / STT(Speech-to-Text) 기능을 도입하기 위한 현황 분석

---

## 1. 현재 시스템 아키텍처 분석

### 1.1 VTuber 서비스 현황

현재 GenY VTuber 시스템은 **텍스트 기반 상호작용**만 지원한다.

```
[현재 데이터 흐름]

User (텍스트 입력)
  ↓ POST /api/chat/rooms/{roomId}/broadcast
Backend (LLM 처리)
  ↓ VTuber Classify → VTuber Respond (with [emotion] tag)
Emotion Extractor
  ↓ 감정 태그 파싱 → 표정/모션 매핑
Avatar State Manager
  ↓ SSE push
Frontend (Live2D 렌더링 + 텍스트 표시)
```

**핵심 한계점**:
- VTuber가 **음성으로 대답하지 못함** → 몰입감 부족
- 사용자가 **음성으로 대화할 수 없음** → 인터랙션 제한
- Live2D 아바타에 **립싱크(입 움직임)가 없음** → 부자연스러운 표현
- 감정은 표정/모션으로 표현되지만 **음성 톤에는 반영 불가**

### 1.2 현재 기술 스택

| 계층 | 기술 | 비고 |
|------|------|------|
| **Frontend** | Next.js 16, React 19, Pixi.js 7, Live2D Cubism 4 | WebGL 기반 렌더링 |
| **Backend** | FastAPI (Python), LangGraph | 비동기 처리, SSE 스트리밍 |
| **통신** | SSE (Server-Sent Events) | avatar_state, message, heartbeat |
| **상태관리** | Zustand | useVTuberStore, useMessengerStore |
| **DB** | PostgreSQL 16 | 세션, 설정, 로그 저장 |
| **배포** | Docker Compose | postgres + backend + frontend |

### 1.3 음성 관련 기존 코드 분석

현재 코드베이스에는 **TTS/STT 관련 코드가 전혀 없다**.

- `backend/service/vtuber/` — 감정 추출, 아바타 상태, 모델 관리만 존재
- `frontend/src/components/live2d/` — Live2D 렌더링, 채팅 패널만 존재
- `frontend/src/lib/api.ts` — 텍스트 기반 API만 정의
- `package.json` — 오디오 관련 라이브러리 없음

---

## 2. TTS (Text-to-Speech) 기술 분석

### 2.1 클라우드 TTS 서비스 비교

| 서비스 | 음질 | 한국어 | 일본어 | 감정 표현 | 스트리밍 | 비용 (100만 문자) | 보이스 클로닝 |
|--------|------|--------|--------|-----------|----------|-------------------|---------------|
| **ElevenLabs** | ★★★★★ | ✅ | ✅ | ✅ 우수 | ✅ WebSocket | ~$30 | ✅ 즉시 |
| **Google Cloud TTS** | ★★★★ | ✅ | ✅ | △ 제한적 | ✅ gRPC | ~$16 (WaveNet) | ✅ (Custom Voice) |
| **Azure Cognitive Speech** | ★★★★ | ✅ | ✅ | ✅ SSML | ✅ WebSocket | ~$16 | ✅ (Custom Neural) |
| **NAVER CLOVA Voice** | ★★★★ | ✅ 최고 | ✗ | △ | ✅ | ~$10 | ✗ |
| **Amazon Polly** | ★★★ | ✅ | ✅ | △ SSML | ✅ | ~$4 | ✗ |
| **OpenAI TTS** | ★★★★★ | ✅ | ✅ | ✅ 자연스러움 | ✅ | ~$15 | ✗ (프리셋만) |

### 2.2 오픈소스 / 셀프 호스트 TTS 비교

| 프레임워크 | 음질 | 한국어 | 실시간성 | VRAM 필요 | 감정 제어 | 보이스 클로닝 | 라이선스 |
|-----------|------|--------|----------|-----------|-----------|---------------|----------|
| **GPT-SoVITS** | ★★★★★ | ✅ | △ (~1s) | 4GB+ | ✅ | ✅ 5초 샘플 | MIT |
| **Fish Speech 1.5** | ★★★★★ | ✅ | ✅ (<0.5s) | 4GB+ | ✅ | ✅ 10초 샘플 | Apache 2.0 |
| **XTTS v2 (Coqui)** | ★★★★ | △ 약함 | △ (~1.5s) | 4GB+ | △ | ✅ 6초 샘플 | CPML |
| **StyleTTS 2** | ★★★★★ | △ | ✅ (<0.3s) | 2GB+ | ✅ 우수 | △ 파인튜닝 필요 | MIT |
| **VITS2** | ★★★★ | ✅ | ✅ (<0.2s) | 2GB+ | △ | △ 파인튜닝 필요 | Apache 2.0 |
| **Edge TTS** | ★★★★ | ✅ | ✅ | 0 (API) | △ | ✗ | 무료(비공식) |
| **Bark (Suno)** | ★★★★ | ✅ | ✗ (~5s) | 8GB+ | ✅ 자연스러움 | △ 프롬프트 | MIT |
| **Piper** | ★★★ | △ | ✅ (<0.1s) | CPU OK | ✗ | ✗ | MIT |

### 2.3 VTuber TTS 핵심 요구사항

1. **초저지연 (Low Latency)**
   - 목표: LLM 응답 생성과 동시에 음성 스트리밍 시작
   - 문장 단위가 아닌 **청크(chunk) 단위 스트리밍** 필요
   - 목표 지연: 첫 음성까지 < 500ms

2. **감정 연동 (Emotion-Aware)**
   - 현재 `[joy]`, `[anger]` 등 감정 태그가 이미 존재
   - TTS 음성에도 해당 감정을 반영해야 함
   - SSML 또는 감정 파라미터 지원 필수

3. **캐릭터 음성 일관성**
   - VTuber 캐릭터별 고유 목소리 유지
   - 보이스 클로닝 또는 파인튜닝으로 커스텀 보이스 생성
   - 모델 레지스트리에 음성 프로필 연결

4. **립싱크 데이터 생성**
   - 음성 → Viseme(입모양) 데이터 추출
   - Live2D 모델의 입 파라미터에 실시간 매핑
   - 방법: (a) TTS에서 타임스탬프 제공 (b) 오디오 진폭 분석 (c) Phoneme 기반

5. **다국어 지원**
   - 한국어 (1순위), 일본어, 영어
   - 코드 스위칭(언어 섞임) 처리

6. **비용 효율성**
   - 개발/테스트: 무료 또는 저비용
   - 프로덕션: 사용량 기반 과금 또는 셀프 호스팅

### 2.4 TTS 추천 전략 (하이브리드)

```
[1차 추천] 개발 및 데모 단계
├── Edge TTS (무료, 빠름, 한국어 우수)
└── OpenAI TTS API (고품질 백업)

[2차 추천] 프로덕션 단계
├── Fish Speech 1.5 (셀프호스팅, 보이스 클로닝, 빠른 추론)
├── ElevenLabs (클라우드 고품질, 감정 표현)
└── GPT-SoVITS (셀프호스팅, 보이스 클로닝, 감정 제어)

[3차 추천] 고급 커스터마이징
└── StyleTTS 2 + 커스텀 파인튜닝 (최고 감정 표현)
```

---

## 3. STT (Speech-to-Text) 기술 분석

### 3.1 클라우드 STT 서비스 비교

| 서비스 | 정확도 | 한국어 | 실시간 스트리밍 | 비용 (1시간) | 화자 분리 |
|--------|--------|--------|-----------------|-------------|-----------|
| **Google Cloud STT v2** | ★★★★★ | ✅ 우수 | ✅ gRPC | ~$1.44 | ✅ |
| **Azure Speech Services** | ★★★★★ | ✅ 우수 | ✅ WebSocket | ~$1.00 | ✅ |
| **OpenAI Whisper API** | ★★★★★ | ✅ 우수 | ✗ (배치만) | ~$0.36 | ✗ |
| **NAVER CLOVA Speech** | ★★★★★ | ✅ 최고 | ✅ WebSocket | ~$0.60 | ✅ |
| **Amazon Transcribe** | ★★★★ | ✅ | ✅ WebSocket | ~$1.44 | ✅ |
| **Deepgram** | ★★★★★ | ✅ | ✅ WebSocket | ~$0.60 | ✅ |

### 3.2 오픈소스 / 셀프 호스트 STT 비교

| 프레임워크 | 정확도 | 한국어 | 실시간 | VRAM 필요 | 라이선스 |
|-----------|--------|--------|--------|-----------|----------|
| **Whisper Large v3** | ★★★★★ | ✅ 우수 | △ (배치) | 10GB | MIT |
| **Faster Whisper** | ★★★★★ | ✅ 우수 | ✅ (VAD+청크) | 4-6GB | MIT |
| **Whisper.cpp** | ★★★★ | ✅ | ✅ (실시간) | CPU/2GB | MIT |
| **Distil-Whisper** | ★★★★ | ✅ 양호 | ✅ | 2-3GB | MIT |
| **Vosk** | ★★★ | ✅ | ✅ (경량) | CPU OK | Apache 2.0 |
| **SenseVoice (FunAudioLLM)** | ★★★★★ | ✅ 우수 | ✅ | 2-4GB | MIT |

### 3.3 VTuber STT 핵심 요구사항

1. **실시간 스트리밍 인식**
   - 브라우저 마이크 → WebSocket → 서버 STT
   - 중간 결과(Interim Results) 표시 → 최종 결과 확정
   - 목표 지연: < 300ms (중간 결과), < 1s (최종 결과)

2. **한국어 최적화**
   - 한국어 조사, 어미의 정확한 인식
   - 비표준 발화(구어체, 인터넷 용어) 처리
   - 숫자, 영어 혼용(코드 스위칭) 처리

3. **Voice Activity Detection (VAD)**
   - 사용자 발화 시작/종료 자동 감지
   - 침묵 구간 무시, 배경 소음 필터링
   - 브라우저 측 VAD로 불필요한 전송 방지

4. **브라우저 호환성**
   - Web Audio API + MediaRecorder 기반
   - Chrome, Edge, Firefox, Safari 지원
   - 모바일 브라우저 대응

5. **세션 컨텍스트 활용**
   - 이전 대화 맥락을 활용한 인식 개선
   - 커스텀 어휘(VTuber 이름, 고유 용어) 등록
   - 핫워드(wake word) 감지 가능성

### 3.4 STT 추천 전략 (하이브리드)

```
[1차 추천] 개발 및 데모 단계
├── Web Speech API (브라우저 내장, 무료, 한국어 지원)
└── Faster Whisper (로컬 백업, 고정확도)

[2차 추천] 프로덕션 단계
├── Deepgram (저비용, 실시간, WebSocket)
├── Google Cloud STT v2 (고품질, 스트리밍)
└── SenseVoice (셀프호스팅, 고품질)

[3차 추천] 완전 셀프호스트 (비용 0)
└── Faster Whisper + Silero VAD (실시간 파이프라인)
```

---

## 4. 립싱크 (Lip Sync) 기술 분석

### 4.1 립싱크 방식 비교

| 방식 | 정확도 | 구현 복잡도 | 실시간성 | 설명 |
|------|--------|-------------|----------|------|
| **오디오 진폭 기반** | ★★ | ★ 낮음 | ✅ 즉시 | 볼륨 → 입 열림 정도 매핑 |
| **Viseme 기반** | ★★★★ | ★★★ 중간 | ✅ | TTS에서 Viseme 타임스탬프 제공 |
| **Phoneme 기반** | ★★★★★ | ★★★★ 높음 | ✅ | 음소 분석 → 입모양 매핑 |
| **AI 기반 (Wav2Lip 등)** | ★★★★★ | ★★★★★ | △ 느림 | 비디오 기반, Live2D 부적합 |
| **rhubarb-lip-sync** | ★★★★ | ★★★ | △ | 오프라인 분석, 6개 입모양 |

### 4.2 Live2D 립싱크 구현 방법

Live2D Cubism SDK에서 입 움직임을 제어하는 핵심 파라미터:

```
ParamMouthOpenY  — 입 열림 정도 (0.0 ~ 1.0)
ParamMouthForm   — 입 모양 (웃음/일반) (-1.0 ~ 1.0)
```

**구현 전략**:

```
[Phase 1] 오디오 진폭 기반 (MVP)
├── TTS 오디오 스트림 → Web Audio AnalyserNode
├── 주기적으로 진폭(RMS) 계산
├── 진폭 → ParamMouthOpenY 매핑 (with smoothing)
└── 구현 난이도: 낮음, 효과: 기본적인 입 움직임

[Phase 2] Viseme 기반 (개선)
├── TTS 엔진에서 Viseme 이벤트 수신
├── Viseme → ParamMouthOpenY + ParamMouthForm 매핑
├── 타임스탬프 기반 동기화
└── 구현 난이도: 중간, 효과: 자연스러운 입 모양

[Phase 3] Phoneme 기반 (고급)
├── 음성에서 Phoneme 추출 (Montreal Forced Aligner 등)
├── Phoneme → Viseme → Live2D 파라미터
├── 한국어/일본어/영어 Phoneme 맵
└── 구현 난이도: 높음, 효과: 매우 자연스러운 립모션
```

---

## 5. 현재 아키텍처와의 통합 포인트 분석

### 5.1 TTS 통합 포인트

```
[기존 흐름]
vtuber_respond_node → "[joy] 안녕하세요!" → EmotionExtractor → AvatarState → SSE → Frontend

[TTS 추가 후 흐름]
vtuber_respond_node → "[joy] 안녕하세요!" → EmotionExtractor → AvatarState → SSE → Frontend
                                              ↓ (병렬)                                    ↓
                                         TTS Engine                              Audio Playback
                                              ↓                                       ↓
                                     Audio Stream (WebSocket/SSE)          Lip Sync Analysis
                                              ↓                                       ↓
                                         Frontend ←─────────────────── Live2D 입 파라미터 업데이트
```

**통합 필요 파일**:
| 파일 | 변경 사항 |
|------|-----------|
| `backend/service/vtuber/tts_service.py` | [신규] TTS 엔진 추상화 레이어 |
| `backend/controller/vtuber_controller.py` | TTS 스트리밍 엔드포인트 추가 |
| `backend/service/workflow/nodes/vtuber/vtuber_respond_node.py` | 응답 후 TTS 트리거 |
| `frontend/src/lib/api.ts` | TTS 오디오 스트리밍 API 추가 |
| `frontend/src/components/live2d/Live2DCanvas.tsx` | 립싱크 파라미터 연동 |
| `frontend/src/store/useVTuberStore.ts` | TTS 상태 (재생중/대기 등) 관리 |
| `model_registry.json` | 모델별 TTS 보이스 프로필 매핑 추가 |

### 5.2 STT 통합 포인트

```
[STT 흐름]
Browser Microphone
  ↓ getUserMedia()
Web Audio API + VAD
  ↓ 발화 감지 시
WebSocket 스트리밍 → Backend STT Service
  ↓ interim/final 결과
Frontend 텍스트 입력 → 기존 broadcast 흐름으로 합류
```

**통합 필요 파일**:
| 파일 | 변경 사항 |
|------|-----------|
| `backend/service/vtuber/stt_service.py` | [신규] STT 엔진 추상화 레이어 |
| `backend/controller/vtuber_controller.py` | WebSocket STT 엔드포인트 추가 |
| `frontend/src/lib/audioUtils.ts` | [신규] 마이크 캡처, VAD, 오디오 처리 |
| `frontend/src/components/live2d/VTuberChatPanel.tsx` | 마이크 버튼, 음성 입력 UI |
| `frontend/src/store/useVTuberStore.ts` | STT 상태 관리 (녹음중/처리중 등) |

### 5.3 감정 시스템과의 연동

현재 감정 시스템의 매핑을 TTS에도 확장:

```python
# 현재 emotion_extractor.py의 감정 → 표정 매핑
emotion_map = {
    "neutral": 0, "joy": 3, "anger": 2, "fear": 1,
    "sadness": 1, "surprise": 3, "disgust": 2, "smirk": 3
}

# 확장: 감정 → TTS 파라미터 매핑
tts_emotion_map = {
    "neutral": {"speed": 1.0, "pitch": 0, "style": "neutral"},
    "joy":     {"speed": 1.1, "pitch": +2, "style": "cheerful"},
    "anger":   {"speed": 1.2, "pitch": +1, "style": "angry"},
    "fear":    {"speed": 1.3, "pitch": +3, "style": "fearful"},
    "sadness": {"speed": 0.9, "pitch": -2, "style": "sad"},
    "surprise":{"speed": 1.2, "pitch": +4, "style": "excited"},
    "disgust": {"speed": 0.9, "pitch": -1, "style": "displeased"},
    "smirk":   {"speed": 1.0, "pitch": +1, "style": "playful"},
}
```

---

## 6. 인프라 영향도 분석

### 6.1 셀프 호스팅 시 리소스 요구사항

| 서비스 | CPU | RAM | VRAM | 스토리지 | 비고 |
|--------|-----|-----|------|----------|------|
| **TTS (Fish Speech)** | 4코어+ | 8GB+ | 4GB+ | 2GB | CUDA 필수 |
| **TTS (Edge TTS)** | 최소 | 최소 | 0 | 0 | API 호출만 |
| **STT (Faster Whisper)** | 4코어+ | 8GB+ | 4-6GB | 3GB | CUDA 권장 |
| **STT (Vosk)** | 2코어 | 2GB | 0 | 500MB | CPU OK |

### 6.2 Docker Compose 확장

```yaml
# 현재 서비스: postgres, backend, frontend
# 추가 필요 서비스:

services:
  tts-engine:        # TTS 추론 서버
    image: fish-speech:latest
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    ports:
      - "8001:8001"

  stt-engine:        # STT 추론 서버
    image: faster-whisper:latest
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    ports:
      - "8002:8002"
```

### 6.3 네트워크 대역폭

| 항목 | 데이터량 | 빈도 |
|------|----------|------|
| TTS 오디오 출력 | ~128kbps (MP3) / ~1.4Mbps (WAV) | 응답마다 |
| STT 오디오 입력 | ~256kbps (16kHz, 16bit, mono) | 발화 중 실시간 |
| Viseme 데이터 | ~1KB/s | TTS 재생 중 |

---

## 7. 위험 요소 및 제약 사항

### 7.1 기술적 위험

| 위험 | 심각도 | 완화 방안 |
|------|--------|-----------|
| TTS 지연으로 대화 흐름 끊김 | 🔴 높음 | 청크 스트리밍 + 프리버퍼링 |
| STT 오인식으로 잘못된 명령 실행 | 🟡 중간 | 확인 단계 추가, 수정 가능한 UI |
| GPU 메모리 부족 (TTS+STT 동시) | 🔴 높음 | 모델 크기 최적화, 순차 처리, GPU 공유 |
| Live2D 립싱크 동기화 어긋남 | 🟡 중간 | 타임스탬프 보정, 버퍼 관리 |
| 브라우저 오디오 권한 거부 | 🟡 중간 | 명확한 UX 안내, 텍스트 폴백 |
| 다중 사용자 동시 접속 시 부하 | 🔴 높음 | 큐잉 시스템, 인스턴스 스케일링 |

### 7.2 비즈니스 제약

| 제약 | 영향 | 대안 |
|------|------|------|
| GPU 서버 비용 | 클라우드 GPU 월 $100~500 | 경량 모델 / 클라우드 API 혼용 |
| 클라우드 API 비용 증가 | 사용량 비례 과금 | 캐싱, 짧은 응답 최적화 |
| 음성 저작권 (보이스 클로닝) | 법적 리스크 | 자체 제작 또는 라이선스 확인 |
| 개인정보 (음성 데이터) | GDPR/개인정보보호법 | 로컬 처리, 음성 데이터 미저장 |

---

## 8. 분석 결론

### 8.1 핵심 발견

1. **현재 시스템은 TTS/STT 통합을 위한 좋은 기반을 갖추고 있다**
   - SSE 기반 실시간 통신 파이프라인 존재
   - 감정 태그 시스템이 이미 동작 중
   - Live2D 모델에 입 파라미터(ParamMouthOpenY, ParamMouthForm) 내장

2. **TTS가 STT보다 우선순위가 높다**
   - VTuber의 핵심 가치는 "캐릭터가 말을 한다"는 것
   - 사용자 입력은 텍스트로도 가능하지만, VTuber 출력은 음성이 필수
   - TTS + 립싱크가 가장 큰 UX 향상을 가져옴

3. **하이브리드 전략이 최적**
   - 초기: Edge TTS (무료, 빠른 프로토타이핑)
   - 확장: Fish Speech / ElevenLabs (고품질, 커스터마이징)
   - STT는 Web Speech API로 시작 → Faster Whisper로 고도화

### 8.2 권장 우선순위

```
Phase 1 (MVP)     : TTS (Edge TTS) + 진폭 기반 립싱크
Phase 2 (개선)    : STT (Web Speech API) + 음성 대화 루프
Phase 3 (고도화)  : 커스텀 보이스 (Fish Speech) + Viseme 립싱크
Phase 4 (완성)    : 감정 TTS + 고급 립싱크 + 다국어 최적화
```

---

*다음 문서: [02_TTS_STT_시스템_설계서.md](02_TTS_STT_시스템_설계서.md)*
