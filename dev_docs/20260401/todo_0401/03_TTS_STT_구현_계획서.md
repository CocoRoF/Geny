# 03. TTS/STT 구현 계획서

> **작성일**: 2026-04-01
> **대상 시스템**: GenY VTuber 서비스
> **목적**: TTS/STT 기능의 단계별 구현 로드맵 및 세부 작업 명세

---

## 1. 구현 로드맵 총괄

### 1.1 4단계 구현 전략

```
 Phase 1 (MVP)           Phase 2 (개선)          Phase 3 (고도화)        Phase 4 (완성)
 ─────────────           ──────────────          ────────────────        ──────────────
 Edge TTS 통합           STT 통합                커스텀 보이스           감정 음성 + 최적화
 진폭 기반 립싱크        Web Speech API          Fish Speech 연동       Viseme 립싱크
 기본 오디오 재생        마이크 입력 UI           보이스 클로닝           다국어 최적화
 설정 UI                 음성 대화 루프           엔진 교체 시스템       성능 튜닝
```

### 1.2 전체 일정 요약

| Phase | 기간 | 핵심 산출물 | 의존성 |
|-------|------|-------------|--------|
| **Phase 1** | 5~7일 | TTS 재생 + 립싱크 MVP | 없음 |
| **Phase 2** | 5~7일 | 음성 입력 + 대화 루프 | Phase 1 완료 |
| **Phase 3** | 7~10일 | 커스텀 보이스 + 엔진 추상화 | Phase 2 완료 |
| **Phase 4** | 5~7일 | 감정 TTS + 고급 립싱크 + 최적화 | Phase 3 완료 |

---

## 2. Phase 1: TTS MVP (Edge TTS + 립싱크)

### 2.1 목표
- VTuber가 응답을 **음성으로 말하는** 최소 기능 구현
- Live2D 아바타에 **기본 립싱크** (진폭 기반) 적용
- TTS **ON/OFF 토글** 및 기본 설정 UI

### 2.2 작업 목록

#### Task 1-1: 백엔드 TTS 기반 구조

**파일 생성**:
```
backend/service/vtuber/tts/
├── __init__.py
├── base.py              # TTSEngine ABC, TTSRequest, TTSChunk 데이터 클래스
├── edge_tts_engine.py   # Edge TTS 구현체
└── tts_service.py       # TTSService (엔진 관리, 요청 처리)
```

**세부 작업**:
- [ ] `base.py`: TTSEngine 추상 클래스 정의 (synthesize_stream, synthesize, list_voices, health_check)
- [ ] `base.py`: TTSRequest, TTSChunk, VoiceProfile, AudioFormat 데이터 클래스
- [ ] `edge_tts_engine.py`: edge-tts 라이브러리 활용 스트리밍 구현
- [ ] `edge_tts_engine.py`: 한/일/영 보이스 매핑 테이블
- [ ] `edge_tts_engine.py`: 속도/피치 파라미터 변환
- [ ] `tts_service.py`: 엔진 등록/선택/폴백 로직
- [ ] `tts_service.py`: 세션별 보이스 프로필 관리

**의존성 추가** (`requirements.txt`):
```
edge-tts>=6.1.0
```

#### Task 1-2: TTS API 엔드포인트

**파일 생성**:
```
backend/controller/tts_controller.py
```

**세부 작업**:
- [ ] `POST /api/tts/agents/{session_id}/speak` — 텍스트 → 오디오 스트리밍 응답
  - Content-Type: `audio/mpeg`
  - Transfer-Encoding: chunked
  - Request body: `{ text, emotion?, language? }`
- [ ] `GET /api/tts/voices` — 보이스 목록
- [ ] `GET /api/tts/voices/{voice_id}/preview` — 미리듣기 (짧은 샘플 문장)
- [ ] `PUT /api/tts/agents/{session_id}/voice` — 보이스 할당
- [ ] `GET /api/tts/agents/{session_id}/voice` — 할당된 보이스 조회
- [ ] `GET /api/tts/status` — TTS 서비스 상태
- [ ] `main.py`에 TTS 라우터 등록

#### Task 1-3: VTuber 응답 파이프라인 TTS 연동

**파일 수정**:
```
backend/service/workflow/nodes/vtuber/vtuber_respond_node.py
backend/controller/chat_controller.py
```

**세부 작업**:
- [ ] `vtuber_respond_node.py`: 응답 생성 후 TTS 트리거 이벤트 발행
- [ ] `chat_controller.py`: broadcast 처리 시 TTS 합성 스케줄링
- [ ] 응답 SSE 이벤트에 `tts_available: true` 플래그 추가
- [ ] 클라이언트가 별도 요청으로 TTS 오디오를 가져오는 방식 (Lazy TTS)

**Lazy TTS 전략 설명**:
```
[Why Lazy?]
LLM 응답이 완성된 후 TTS 합성을 시작하면 지연이 커짐
→ 대신 프론트엔드가 응답 텍스트를 받은 후 즉시 TTS API 호출
→ 스트리밍으로 첫 청크를 빠르게 받아 재생 시작

순서:
1. SSE: message 이벤트 수신 (텍스트 + emotion)
2. Frontend: TTS 활성화 상태면 → POST /api/tts/agents/{id}/speak
3. Backend: edge-tts 스트리밍 합성 → chunked response
4. Frontend: MediaSource API로 수신 즉시 재생 시작
```

#### Task 1-4: 프론트엔드 오디오 재생

**파일 생성**:
```
frontend/src/lib/audioManager.ts
frontend/src/lib/lipSync.ts
```

**세부 작업**:
- [ ] `audioManager.ts`: AudioManager 클래스
  - AudioContext 초기화 (사용자 인터랙션 후)
  - TTS 스트리밍 오디오 재생 (MediaSource API 또는 Audio 엘리먼트)
  - 볼륨 제어
  - 재생 대기열 관리 (여러 응답 순차 재생)
  - 재생 상태 콜백 (시작/종료/에러)
- [ ] `lipSync.ts`: LipSyncController 클래스
  - AnalyserNode 기반 진폭 추출
  - RMS → ParamMouthOpenY 매핑 (지수 이동 평균 스무딩)
  - Live2D 모델 파라미터 직접 제어
  - 시작/중지/정리 메서드

#### Task 1-5: 프론트엔드 TTS UI

**파일 수정**:
```
frontend/src/store/useVTuberStore.ts
frontend/src/components/live2d/VTuberChatPanel.tsx
frontend/src/components/tabs/VTuberTab.tsx
frontend/src/lib/api.ts
```

**파일 생성**:
```
frontend/src/components/live2d/AudioControls.tsx
```

**세부 작업**:
- [ ] `useVTuberStore.ts` 확장:
  - `ttsEnabled: boolean` 상태 추가
  - `ttsSpeaking: Record<string, boolean>` 상태 추가
  - `ttsVolume: number` (0~1) 상태 추가
  - `toggleTTS()`, `speakResponse()` 액션 추가
- [ ] `api.ts` 확장:
  - `ttsApi.speak(sessionId, text, emotion)` → fetch + ReadableStream
  - `ttsApi.listVoices()`, `ttsApi.previewVoice(voiceId)`
  - `ttsApi.assignVoice(sessionId, voiceId)`
- [ ] `AudioControls.tsx` 컴포넌트:
  - TTS ON/OFF 토글 버튼 (🔊/🔇)
  - 볼륨 슬라이더
  - 현재 재생 상태 표시
- [ ] `VTuberChatPanel.tsx` 수정:
  - 에이전트 응답 수신 시 자동 TTS 호출
  - 메시지별 "다시 듣기" 버튼 (🔊)
  - TTS 재생 중 시각적 표시
- [ ] `VTuberTab.tsx` 수정:
  - AudioControls 컴포넌트 배치 (하단 바)
  - Live2DCanvas에 LipSyncController 연결

#### Task 1-6: Live2D 모델 립싱크 연결

**파일 수정**:
```
frontend/src/components/live2d/Live2DCanvas.tsx
```

**세부 작업**:
- [ ] Live2D 모델 로드 후 LipSyncController 인스턴스 생성
- [ ] 오디오 재생 시 AnalyserNode 연결
- [ ] 모델의 `ParamMouthOpenY` 파라미터 실시간 업데이트
- [ ] 오디오 종료 시 입 파라미터 0으로 리셋 (with ease-out)
- [ ] 기존 표정/모션 애니메이션과 립싱크 동시 동작 확인

#### Task 1-7: TTS 설정 연동

**파일 수정**:
```
backend/service/config_manager.py (또는 해당 설정 파일)
```

**세부 작업**:
- [ ] TTS 설정 스키마 추가 (enabled, default_engine, default_voice 등)
- [ ] 설정 API로 TTS 설정 조회/변경 가능
- [ ] 모델 레지스트리에 보이스 프로필 필드 추가 (선택적)
- [ ] 프론트엔드 설정 UI에서 TTS 옵션 표시

### 2.3 Phase 1 테스트 계획

| 테스트 항목 | 기대 결과 | 방법 |
|-------------|-----------|------|
| TTS 기본 합성 | 한국어 텍스트 → MP3 오디오 반환 | curl POST /api/tts/.../speak |
| 스트리밍 재생 | 오디오가 끊김 없이 재생됨 | 브라우저에서 VTuber 탭 테스트 |
| 립싱크 동작 | 음성 재생 시 입이 열리고 닫힘 | 시각적 확인 |
| 감정별 음성 | joy/anger/sadness 등 다른 톤 | 각 감정 태그로 테스트 |
| ON/OFF 토글 | TTS 끄면 음성 안 나옴 | UI 토글 테스트 |
| 에러 폴백 | TTS 실패 시 텍스트만 표시 | 네트워크 차단 테스트 |

### 2.4 Phase 1 완료 기준

- [x] VTuber 응답이 음성으로 재생됨
- [x] 음성 재생 중 Live2D 입이 움직임
- [x] TTS ON/OFF 토글 동작
- [x] 감정에 따라 음성 톤/속도 차이 있음
- [x] 볼륨 조절 가능
- [x] TTS 실패 시 텍스트 폴백

---

## 3. Phase 2: STT 통합 (음성 입력)

### 3.1 목표
- 사용자가 **마이크로 말하면** VTuber에게 전달
- 실시간 **음성 인식 결과 표시**
- 완전한 **음성 대화 루프** 구현

### 3.2 작업 목록

#### Task 2-1: 브라우저 Web Speech API 통합 (Client-side STT)

**파일 생성**:
```
frontend/src/lib/speechRecognition.ts
```

**세부 작업**:
- [ ] `speechRecognition.ts`: Web Speech API 래퍼 클래스
  - `SpeechRecognition` / `webkitSpeechRecognition` 호환
  - 중간 결과(interim) 옵션
  - 언어 설정 (한/일/영)
  - 시작/정지/재시작 제어
  - 결과 콜백 (text, isFinal, confidence)
  - 에러 핸들링 (no-speech, audio-capture, not-allowed)
  - 자동 재시작 옵션 (연속 인식 모드)

**장점**:
- 무료, API 키 불필요
- 서버 부하 없음 (클라이언트 처리)
- Chrome/Edge에서 우수한 한국어 인식

**단점**:
- 브라우저 의존적 (Firefox/Safari 제한적)
- 커스터마이징 한계

#### Task 2-2: 백엔드 STT 기반 구조 (서버 사이드 옵션)

**파일 생성**:
```
backend/service/vtuber/stt/
├── __init__.py
├── base.py              # STTEngine ABC, STTResult, STTConfig
└── stt_service.py       # STTService (엔진 관리)
```

**파일 생성**:
```
backend/controller/stt_controller.py
```

**세부 작업**:
- [ ] `base.py`: STTEngine 추상 클래스 (transcribe_stream, transcribe, health_check)
- [ ] `base.py`: STTResult, STTConfig 데이터 클래스
- [ ] `stt_service.py`: 엔진 등록/선택 로직
- [ ] `stt_controller.py`: WebSocket 엔드포인트 (`/api/stt/agents/{id}/listen`)
- [ ] `stt_controller.py`: 배치 전사 엔드포인트 (`POST /api/stt/transcribe`)
- [ ] `main.py`에 STT 라우터 등록

> **Note**: Phase 2에서는 클라이언트 Web Speech API를 주로 사용하고, 서버 사이드 STT는 구조만 준비. Phase 3에서 Faster Whisper 등 구현체 추가.

#### Task 2-3: 마이크 입력 UI

**파일 생성**:
```
frontend/src/components/live2d/MicButton.tsx
```

**파일 수정**:
```
frontend/src/components/live2d/VTuberChatPanel.tsx
frontend/src/store/useVTuberStore.ts
```

**세부 작업**:
- [ ] `MicButton.tsx` 컴포넌트:
  - 3가지 동작 모드: PTT (Push-to-Talk), 토글, VAD 자동
  - 상태별 아이콘/색상 (대기: 회색, 녹음중: 빨강, 처리중: 주황)
  - PTT: mousedown/touchstart로 시작, mouseup/touchend로 종료
  - 토글: 클릭으로 시작/종료
  - 권한 요청 처리 (첫 사용 시)
  - 접근성: 키보드 단축키 (Space 등)
- [ ] `VTuberChatPanel.tsx` 수정:
  - 입력 필드 옆에 마이크 버튼 배치
  - 중간 인식 결과를 입력 필드에 실시간 표시
  - 최종 결과 확정 시 자동 전송 옵션
  - STT 결과 편집 가능 (전송 전)
- [ ] `useVTuberStore.ts` 확장:
  - `sttEnabled`, `sttListening`, `sttInterimText` 상태
  - `startListening()`, `stopListening()` 액션
  - `sttMode: 'ptt' | 'toggle' | 'vad'` 설정

#### Task 2-4: 음성 대화 루프 구현

**파일 수정**:
```
frontend/src/components/live2d/VTuberChatPanel.tsx
frontend/src/lib/audioManager.ts
```

**세부 작업**:
- [ ] 음성 대화 플로우 구현:
  ```
  마이크 입력 → STT → 텍스트 → broadcast → LLM → 응답 → TTS → 스피커
  ```
- [ ] 에코 방지 (Echo Cancellation):
  - TTS 재생 중 마이크 자동 뮤트
  - 또는 `echoCancellation: true` (getUserMedia 옵션)
  - TTS 재생 종료 후 마이크 자동 재활성화 (VAD 모드)
- [ ] 턴 관리:
  - 사용자 발화 감지 → VTuber "듣기" 모드
  - STT 종료 → VTuber "생각 중" 모드
  - LLM 응답 → VTuber "말하기" 모드
  - TTS 재생 종료 → VTuber "대기" 모드
- [ ] 인터럽트 지원:
  - TTS 재생 중 사용자가 말하면 TTS 즉시 중단
  - 새 사용자 입력 처리

#### Task 2-5: STT 설정 UI

**파일 생성**:
```
frontend/src/components/live2d/STTControls.tsx
```

**세부 작업**:
- [ ] STT 활성화/비활성화 토글
- [ ] 입력 모드 선택 (PTT/토글/VAD)
- [ ] 언어 선택 (한국어/일본어/영어)
- [ ] 자동 전송 ON/OFF
- [ ] 마이크 입력 수준 미터 (시각적 피드백)
- [ ] AudioControls에 STT 컨트롤 통합

### 3.3 Phase 2 테스트 계획

| 테스트 항목 | 기대 결과 |
|-------------|-----------|
| 마이크 권한 요청 | 브라우저 권한 팝업 → 허용 후 사용 가능 |
| 한국어 음성 인식 | "안녕하세요"를 정확히 인식 |
| 중간 결과 표시 | 말하는 중 실시간으로 텍스트 업데이트 |
| 음성 대화 루프 | 말하기 → 인식 → 응답 → TTS → 반복 |
| 에코 방지 | TTS 재생 중 마이크가 비활성화 |
| 인터럽트 | TTS 재생 중 말하면 즉시 중단 |

### 3.4 Phase 2 완료 기준

- [x] 사용자가 마이크로 VTuber에게 말할 수 있음
- [x] 중간 인식 결과가 실시간 표시됨
- [x] 완전한 음성 대화 루프 동작
- [x] 에코 방지 정상 동작
- [x] PTT, 토글 모드 지원
- [x] 마이크 권한 거부 시 텍스트 폴백

---

## 4. Phase 3: 커스텀 보이스 & 엔진 추상화

### 4.1 목표
- **VTuber 캐릭터별 고유 목소리** 생성
- **TTS 엔진 핫스왑** (설정으로 교체 가능)
- **서버 사이드 STT** 옵션 추가 (Faster Whisper)

### 4.2 작업 목록

#### Task 3-1: Fish Speech 엔진 통합

**파일 생성**:
```
backend/service/vtuber/tts/fish_speech_engine.py
```

**Docker 설정**:
```
docker-compose.yml 에 tts-engine 서비스 추가
```

**세부 작업**:
- [ ] Fish Speech Docker 이미지 구성
- [ ] HTTP API 기반 스트리밍 합성 구현
- [ ] 보이스 레퍼런스 오디오 관리 (업로드/선택)
- [ ] 감정 파라미터 전달
- [ ] 언어 자동 감지 / 명시적 지정
- [ ] 헬스 체크 구현
- [ ] GPU 리소스 관리 (동시 요청 제한)

#### Task 3-2: ElevenLabs / OpenAI TTS 엔진 통합

**파일 생성**:
```
backend/service/vtuber/tts/elevenlabs_engine.py
backend/service/vtuber/tts/openai_tts_engine.py
```

**세부 작업**:
- [ ] ElevenLabs Streaming API 연동
- [ ] 감정 → voice_settings 매핑 (stability, similarity_boost, style)
- [ ] OpenAI TTS API 연동 (tts-1, tts-1-hd)
- [ ] 음성 프리셋 선택 (alloy, echo, fable, onyx, nova, shimmer)
- [ ] API 키 관리 (설정 시스템 연동)
- [ ] Rate limiting 구현

#### Task 3-3: 보이스 클로닝 / 커스텀 보이스 관리

**파일 생성**:
```
backend/service/vtuber/tts/voice_manager.py
backend/controller/voice_controller.py
```

**세부 작업**:
- [ ] 레퍼런스 오디오 업로드 API
- [ ] 보이스 프로필 CRUD
- [ ] 모델 레지스트리와 보이스 프로필 연결
- [ ] 보이스 미리듣기 생성/캐싱
- [ ] 프론트엔드 보이스 관리 UI (VoiceSelector 컴포넌트)

```
보이스 프로필 구조:
{
  "id": "mao_voice_v1",
  "name": "Mao 보이스",
  "engine": "fish_speech",
  "reference_audio": "/static/voices/mao_pro/reference_01.wav",
  "language": "ko",
  "settings": {
    "speed": 1.0,
    "pitch": 0,
    "emotion_styles": { ... }
  },
  "linked_model": "mao_pro"
}
```

#### Task 3-4: TTS 엔진 팩토리 & 설정 시스템

**파일 수정**:
```
backend/service/vtuber/tts/tts_service.py
```

**세부 작업**:
- [ ] 엔진 팩토리 패턴 구현 (설정 기반 자동 로딩)
- [ ] 설정 변경 시 실시간 엔진 교체 (hot-swap)
- [ ] 엔진별 헬스 체크 → 자동 폴백
- [ ] 엔진 우선순위 설정
- [ ] 캐시 레이어 추가 (동일 텍스트+감정 → 캐시된 오디오)
- [ ] 비용 트래킹 (클라우드 API 사용량 기록)

#### Task 3-5: 서버 사이드 STT (Faster Whisper)

**파일 생성**:
```
backend/service/vtuber/stt/faster_whisper_engine.py
```

**Docker 설정**:
```
docker-compose.yml 에 stt-engine 서비스 추가 (또는 backend에 내장)
```

**세부 작업**:
- [ ] Faster Whisper 모델 로딩 (large-v3 / distil-large-v3)
- [ ] Silero VAD 통합 (음성 구간 감지)
- [ ] 오디오 버퍼링 + VAD 기반 세그먼트 분할
- [ ] WebSocket 스트리밍 전사 구현
- [ ] GPU/CPU 모드 자동 감지
- [ ] 동시 요청 관리 (세마포어)

#### Task 3-6: TTS 오디오 캐시 시스템

**파일 생성**:
```
backend/service/vtuber/tts/audio_cache.py
```

**세부 작업**:
- [ ] 파일 시스템 기반 캐시 (hash(text + emotion + voice) → audio file)
- [ ] LRU 캐시 정책 (최대 크기 설정)
- [ ] TTL (Time-to-Live) 적용
- [ ] 캐시 통계 API (히트율, 크기)
- [ ] 수동 캐시 클리어 기능

### 4.3 Phase 3 완료 기준

- [x] VTuber별 고유 목소리 할당 가능
- [x] TTS 엔진을 설정으로 변경 가능 (Edge/Fish Speech/ElevenLabs/OpenAI)
- [x] 보이스 레퍼런스 업로드 및 클로닝
- [x] 서버 사이드 STT 동작 (Faster Whisper)
- [x] TTS 오디오 캐시 동작

---

## 5. Phase 4: 감정 음성 + 고급 립싱크 + 최적화

### 5.1 목표
- **감정에 따라 음성 톤/스타일이 확연히 변화**
- **Viseme 기반 고급 립싱크**로 자연스러운 입 모양
- **성능 최적화** 및 프로덕션 준비

### 5.2 작업 목록

#### Task 4-1: 감정 TTS 고도화

**세부 작업**:
- [ ] 감정별 TTS 파라미터 프로파일 세밀화
  ```
  joy:     속도 +10%, 피치 +5%, 밝은 톤
  anger:   속도 +20%, 피치 +2%, 강한 톤, 거친 호흡
  sadness: 속도 -10%, 피치 -5%, 낮고 느린 톤
  fear:    속도 +30%, 피치 +8%, 떨리는 톤
  surprise: 속도 +20%, 피치 +10%, 높은 시작
  ```
- [ ] ElevenLabs/Fish Speech의 감정 임베딩 활용
- [ ] 감정 전환 시 자연스러운 블렌딩 (이전 감정 → 현재 감정)
- [ ] 감정별 레퍼런스 오디오 세트 (보이스 클로닝 엔진용)

#### Task 4-2: Viseme 기반 고급 립싱크

**파일 수정/생성**:
```
frontend/src/lib/lipSync.ts (확장)
frontend/src/lib/visemeMap.ts (신규)
```

**세부 작업**:
- [ ] Viseme 맵 정의 (Azure 호환 15개 Viseme):
  ```typescript
  const VISEME_MAP: Record<number, { mouthOpenY: number, mouthForm: number }> = {
    0:  { mouthOpenY: 0.0, mouthForm: 0.0 },  // sil (silence)
    1:  { mouthOpenY: 0.4, mouthForm: 0.2 },  // æ, ə, ʌ
    2:  { mouthOpenY: 1.0, mouthForm: 0.0 },  // aa (아)
    3:  { mouthOpenY: 0.6, mouthForm: -0.3 }, // ao (오)
    4:  { mouthOpenY: 0.3, mouthForm: 0.5 },  // ey (에이)
    5:  { mouthOpenY: 0.2, mouthForm: 0.7 },  // er
    6:  { mouthOpenY: 0.3, mouthForm: 0.6 },  // ih (이)
    7:  { mouthOpenY: 0.5, mouthForm: -0.5 }, // uw (우)
    // ... 한국어/일본어 특수 Viseme 추가
  };
  ```
- [ ] TTS 엔진에서 Viseme 이벤트 수신 (지원하는 엔진만)
- [ ] Viseme → Live2D 파라미터 매핑 + 보간(interpolation)
- [ ] 타임스탬프 동기화 (오디오 재생 위치와 Viseme 일치)
- [ ] 진폭 기반 립싱크와의 하이브리드 (Viseme 미지원 시 폴백)

#### Task 4-3: 성능 최적화

**세부 작업**:
- [ ] TTS 지연 최적화:
  - 문장 분할 → 첫 문장 즉시 합성 시작
  - 이전 문장 재생 중 다음 문장 프리펩치
  - 자주 사용하는 문구 프리캐시
- [ ] STT 지연 최적화:
  - 클라이언트 VAD로 불필요한 데이터 전송 차단
  - 청크 크기 최적화 (100ms → 200ms 가능성)
  - 연결 풀링
- [ ] 메모리 최적화:
  - 오디오 버퍼 순환 사용
  - 미사용 AudioContext 정리
  - WebSocket 연결 효율화
- [ ] 동시성 최적화:
  - TTS 요청 큐잉 (동시 합성 제한)
  - GPU 메모리 관리 (TTS/STT 시분할)

#### Task 4-4: 다국어 최적화

**세부 작업**:
- [ ] 언어 자동 감지:
  - LLM 응답의 주 언어 감지
  - 해당 언어에 맞는 보이스 자동 선택
- [ ] 코드 스위칭 처리:
  - "오늘 meeting이 있어" → 한국어 보이스로 영어 부분도 자연스럽게
  - 필요시 언어별 청크 분할 합성
- [ ] 보이스별 언어 지원 매트릭스 관리

#### Task 4-5: 프로덕션 준비

**세부 작업**:
- [ ] 모니터링:
  - TTS 합성 지연 메트릭 (P50, P95, P99)
  - STT 인식 정확도 메트릭
  - 오디오 스트리밍 에러율
  - 엔진별 사용량 / 비용 대시보드
- [ ] 로깅:
  - TTS/STT 요청/응답 로그 (오디오 데이터 제외)
  - 에러 로그 (에러 유형, 빈도, 폴백 성공률)
- [ ] Rate Limiting:
  - 세션당 TTS 호출 제한
  - 글로벌 동시 TTS 합성 제한
  - 클라우드 API 비용 상한 설정
- [ ] 문서:
  - API 문서 (OpenAPI/Swagger)
  - 설정 가이드
  - 트러블슈팅 가이드

---

## 6. 파일 구조 최종 형태

### 6.1 백엔드

```
backend/service/vtuber/
├── __init__.py
├── avatar_state_manager.py     (기존)
├── delegation.py               (기존)
├── emotion_extractor.py        (기존)
├── live2d_model_manager.py     (기존)
├── thinking_trigger.py         (기존)
├── tts/                        (Phase 1~3 신규)
│   ├── __init__.py
│   ├── base.py                 # TTSEngine ABC, 데이터 클래스
│   ├── tts_service.py          # 메인 TTS 서비스 (엔진 관리)
│   ├── edge_tts_engine.py      # Phase 1: Edge TTS
│   ├── fish_speech_engine.py   # Phase 3: Fish Speech
│   ├── elevenlabs_engine.py    # Phase 3: ElevenLabs
│   ├── openai_tts_engine.py    # Phase 3: OpenAI TTS
│   ├── voice_manager.py        # Phase 3: 보이스 프로필 관리
│   └── audio_cache.py          # Phase 3: 오디오 캐시
└── stt/                        (Phase 2~3 신규)
    ├── __init__.py
    ├── base.py                 # STTEngine ABC, 데이터 클래스
    ├── stt_service.py          # 메인 STT 서비스
    └── faster_whisper_engine.py # Phase 3: Faster Whisper

backend/controller/
├── ...                         (기존)
├── tts_controller.py           (Phase 1 신규)
├── stt_controller.py           (Phase 2 신규)
└── voice_controller.py         (Phase 3 신규)
```

### 6.2 프론트엔드

```
frontend/src/
├── lib/
│   ├── ...                     (기존)
│   ├── audioManager.ts         (Phase 1 신규)
│   ├── lipSync.ts              (Phase 1 신규)
│   ├── speechRecognition.ts    (Phase 2 신규)
│   └── visemeMap.ts            (Phase 4 신규)
├── components/live2d/
│   ├── ...                     (기존)
│   ├── AudioControls.tsx       (Phase 1 신규)
│   ├── MicButton.tsx           (Phase 2 신규)
│   ├── VoiceSelector.tsx       (Phase 3 신규)
│   └── LipSyncDebug.tsx        (Phase 4 신규, 개발용)
├── store/
│   └── useVTuberStore.ts       (기존, Phase 1~2 확장)
└── public/
    └── audio-processor.js      (Phase 2 신규, AudioWorklet)
```

---

## 7. 의존성 목록

### 7.1 백엔드 Python 패키지

| 패키지 | Phase | 용도 |
|--------|-------|------|
| `edge-tts>=6.1.0` | 1 | Edge TTS 엔진 |
| `httpx>=0.27.0` | 3 | Fish Speech/ElevenLabs API 호출 |
| `faster-whisper>=1.0.0` | 3 | 서버 사이드 STT |
| `silero-vad>=5.1` | 3 | Voice Activity Detection |
| `openai>=1.30.0` | 3 | OpenAI TTS API (이미 존재할 수 있음) |

### 7.2 프론트엔드 npm 패키지

| 패키지 | Phase | 용도 |
|--------|-------|------|
| (없음 - 브라우저 내장 API 사용) | 1-2 | Web Audio API, MediaSource API |

> **Note**: TTS/STT의 프론트엔드 구현은 모두 **브라우저 내장 API**를 사용하므로 추가 npm 패키지가 필요 없음.

---

## 8. Docker Compose 확장 계획

### 8.1 Phase 1~2 (변경 없음)

Edge TTS와 Web Speech API는 외부 서비스이므로 인프라 변경 불필요.

### 8.2 Phase 3 (GPU 서비스 추가)

```yaml
# docker-compose.prod.yml 확장

services:
  # ... 기존 서비스

  tts-engine:
    image: fishaudio/fish-speech:latest
    container_name: geny-tts
    restart: unless-stopped
    ports:
      - "8001:8001"
    volumes:
      - tts-models:/app/models
      - tts-voices:/app/voices
    environment:
      - DEVICE=cuda
      - MAX_CONCURRENT=2
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  stt-engine:
    image: fedirz/faster-whisper-server:latest
    container_name: geny-stt
    restart: unless-stopped
    ports:
      - "8002:8002"
    volumes:
      - stt-models:/app/models
    environment:
      - MODEL_SIZE=large-v3
      - DEVICE=cuda
      - COMPUTE_TYPE=float16
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  tts-models:
  tts-voices:
  stt-models:
```

---

## 9. 위험 관리 계획

### 9.1 기술적 위험 & 완화

| 위험 | 발생 확률 | 영향도 | 완화 방안 | 담당 Phase |
|------|-----------|--------|-----------|-----------|
| Edge TTS 서비스 중단/변경 | 중 | 높음 | OpenAI TTS 폴백 준비 | Phase 1 |
| 브라우저 오디오 정책 변경 | 낮 | 중 | 사용자 인터랙션 후 AudioContext 생성 | Phase 1 |
| Web Speech API 브라우저 미지원 | 중 | 중 | Faster Whisper 서버 폴백 | Phase 2 |
| GPU 메모리 부족 | 높 | 높음 | 경량 모델, 순차 처리, 메모리 모니터링 | Phase 3 |
| 보이스 클로닝 품질 불만족 | 중 | 중 | 여러 엔진 테스트, 레퍼런스 오디오 최적화 가이드 | Phase 3 |
| 립싱크 동기화 어긋남 | 중 | 중 | 타임스탬프 보정, 진폭 폴백 | Phase 4 |
| 동시 접속 시 성능 저하 | 높 | 높음 | 큐잉, 캐시, 인스턴스 스케일링 | Phase 4 |

### 9.2 Phase별 롤백 계획

```
Phase 1 실패 시: TTS 코드 비활성화, 기존 텍스트 기반으로 동작
Phase 2 실패 시: STT 코드 비활성화, 텍스트 입력으로 동작
Phase 3 실패 시: Edge TTS + Web Speech API로 유지
Phase 4 실패 시: Phase 3 상태로 유지, 진폭 립싱크 사용
```

---

## 10. 성공 지표 (KPIs)

| 지표 | 목표값 | 측정 방법 |
|------|--------|-----------|
| TTS 첫 오디오 지연 | < 500ms | 스트리밍 응답 첫 바이트 시간 |
| TTS 자연스러움 | MOS >= 3.5/5 | 사용자 평가 |
| STT 인식 정확도 (한국어) | >= 90% WER | Whisper baseline 대비 |
| 립싱크 동기화 정확도 | 오프셋 < 100ms | 시각적 검증 |
| 음성 대화 루프 지연 | < 3초 (전체) | 발화 종료~TTS 재생 시작 |
| 시스템 안정성 | 99.5% 가용성 | 에러율 모니터링 |
| 사용자 만족도 | >= 4.0/5 | 설문 조사 |

---

## 부록 A: 빠른 시작 체크리스트

### Phase 1 시작 전 확인

- [ ] Python 3.11+ 환경 준비
- [ ] `pip install edge-tts` 설치 확인
- [ ] 브라우저에서 Web Audio API 지원 확인
- [ ] Live2D 모델의 `ParamMouthOpenY` 파라미터 존재 확인
- [ ] SSE 통신 정상 동작 확인 (기존 avatar_state)

### Edge TTS 빠른 테스트

```bash
# 터미널에서 Edge TTS 테스트
edge-tts --voice ko-KR-SunHiNeural --text "안녕하세요, 저는 GenY 브이튜버입니다." --write-media test.mp3
# test.mp3 재생하여 음질 확인
```

### Phase 1 첫 번째 커밋 목표

```
feat(tts): Edge TTS 기반 VTuber 음성 합성 MVP

- TTSEngine 추상 인터페이스 정의
- Edge TTS 엔진 구현 (한/일/영)
- POST /api/tts/agents/{id}/speak 엔드포인트
- 프론트엔드 오디오 재생 (AudioManager)
- 진폭 기반 립싱크 (LipSyncController)
- TTS ON/OFF 토글 UI
```

---

*이 문서는 전체 구현의 로드맵입니다. 각 Phase의 세부 구현은 진행하면서 추가 설계 문서가 필요할 수 있습니다.*
