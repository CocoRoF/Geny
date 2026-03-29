# Open-LLM-VTuber 렌더링 시스템 심층 분석 리포트

> 분석 일자: 2026-03-29
> 대상: Open-LLM-VTuber 프로젝트 (VTuber 캐릭터 렌더링 시스템)
> 목적: Geny 프로젝트로의 이식을 위한 기술 분석
> 범위: Live2D 렌더링, 표정/감정 시스템, 애니메이션, 통신 프로토콜 (음성 TTS 제외)

---

## 1. 아키텍처 개요

### 1.1 전체 구조

Open-LLM-VTuber는 **백엔드-프론트엔드 실시간 통신 아키텍처**로, WebSocket 프로토콜을 기반으로 합니다.

```
┌─────────────────────────────────────┐
│     Frontend (Web Application)      │
│  ┌──────────────────────────────┐   │
│  │  Live2D Cubism SDK + Pixi.js│   │
│  │  - 모델 로딩 & 렌더링       │   │
│  │  - 표정/감정 표현           │   │
│  │  - 립싱크 애니메이션        │   │
│  │  - 유휴/제스처 모션         │   │
│  └────────┬─────────────────────┘   │
│           │ WebSocket                │
└───────────┼─────────────────────────┘
            │
┌───────────┼─────────────────────────┐
│  Backend  │ (Python FastAPI)        │
│  ┌────────┴─────────────────────┐   │
│  │  WebSocket Handler           │   │
│  │  ├─ Live2D Model Manager     │   │
│  │  ├─ Expression Extractor     │   │
│  │  ├─ Agent (LLM Backend)      │   │
│  │  └─ TTS Manager (립싱크용)   │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

### 1.2 핵심 설계 원칙

1. **백엔드 주도 표정 제어**: LLM이 생성한 텍스트에서 감정 태그를 추출하여 프론트엔드로 전달
2. **SDK 독립적 백엔드**: 백엔드는 Live2D SDK에 의존하지 않고, 표정 인덱스만 전달
3. **실시간 스트리밍**: 문장 단위로 표정/오디오를 스트리밍하여 자연스러운 반응 구현
4. **순서 보장 전송**: 병렬 처리되더라도 프론트엔드에는 올바른 순서로 전달

---

## 2. Live2D 모델 시스템

### 2.1 모델 파일 구조

```
live2d-models/
└── mao_pro/
    └── runtime/
        ├── mao_pro.model3.json        ← 핵심 설정 파일 (프론트엔드 진입점)
        ├── mao_pro.moc3               ← Cubism 모델 바이너리 데이터
        ├── mao_pro.physics3.json      ← 물리 파라미터 (머리카락 흔들림 등)
        ├── mao_pro.pose3.json         ← 포즈 정의
        ├── mao_pro.cdi3.json          ← 디스플레이 정보
        ├── mao_pro.4096/
        │   └── texture_00.png         ← 모델 텍스처 (4096x4096)
        ├── expressions/
        │   ├── exp_01.exp3.json       ← 표정 0: neutral
        │   ├── exp_02.exp3.json       ← 표정 1: fear/sadness
        │   ├── exp_03.exp3.json       ← 표정 2: anger/disgust
        │   ├── exp_04.exp3.json       ← 표정 3: joy/smirk/surprise
        │   ├── exp_05.exp3.json
        │   ├── exp_06.exp3.json
        │   ├── exp_07.exp3.json
        │   └── exp_08.exp3.json       ← 총 8개 표정
        └── motions/
            ├── mtn_01.motion3.json    ← Idle 모션
            └── ...                    ← 추가 모션 파일들
```

### 2.2 model3.json 핵심 구조

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "mao_pro.moc3",
    "Textures": ["mao_pro.4096/texture_00.png"],
    "Physics": "mao_pro.physics3.json",
    "Pose": "mao_pro.pose3.json",
    "DisplayInfo": "mao_pro.cdi3.json",
    "Expressions": [
      { "Name": "exp_01", "File": "expressions/exp_01.exp3.json" },
      { "Name": "exp_02", "File": "expressions/exp_02.exp3.json" }
      // ... 총 8개
    ],
    "Motions": {
      "Idle": [
        { "File": "motions/mtn_01.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }
      ],
      "TapBody": [
        { "File": "motions/mtn_02.motion3.json", "FadeInTime": 0.5, "FadeOutTime": 0.5 }
      ]
    }
  },
  "Groups": [
    { "Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"] },
    { "Target": "Parameter", "Name": "LipSync", "Ids": ["ParamA"] }
  ],
  "HitAreas": [
    { "Id": "HitAreaHead", "Name": "Head" },
    { "Id": "HitAreaBody", "Name": "Body" }
  ]
}
```

### 2.3 모델 레지스트리 (model_dict.json)

```json
{
  "name": "mao_pro",
  "description": "",
  "url": "/live2d-models/mao_pro/runtime/mao_pro.model3.json",
  "kScale": 0.5,                    // 렌더링 스케일
  "initialXshift": 0,               // 초기 X 위치
  "initialYshift": 0,               // 초기 Y 위치
  "kXOffset": 1150,                  // X 오프셋
  "idleMotionGroupName": "Idle",     // 기본 유휴 모션 그룹
  "emotionMap": {                    // 감정 → 표정 인덱스 매핑
    "neutral": 0,
    "anger": 2,
    "disgust": 2,
    "fear": 1,
    "joy": 3,
    "smirk": 3,
    "sadness": 1,
    "surprise": 3
  },
  "tapMotions": {                    // 클릭 영역별 반응 모션
    "HitAreaHead": { "": 1 },
    "HitAreaBody": { "": 1 }
  }
}
```

**핵심 포인트:**
- `emotionMap`은 감정 이름을 표정 파일 인덱스로 매핑
- 하나의 표정 인덱스에 여러 감정이 매핑될 수 있음 (joy, smirk, surprise → 3)
- `idleMotionGroupName`으로 유휴 상태 애니메이션 지정
- `tapMotions`으로 사용자 클릭 인터랙션 지원

---

## 3. 백엔드 표정/감정 제어 시스템

### 3.1 핵심 클래스: Live2dModel

**파일:** `src/open_llm_vtuber/live2d_model.py`

```python
class Live2dModel:
    def __init__(self, live2d_model_name: str, model_dict_path: str = "model_dict.json"):
        # model_dict.json에서 모델 정보 로드
        # emotionMap으로부터 감정 문자열(emo_str) 생성
        # 예: "[neutral], [anger], [disgust], [fear], [joy], [smirk], [sadness], [surprise]"

    def extract_emotion(self, str_to_check: str) -> list[int]:
        """
        텍스트에서 감정 키워드를 추출하여 표정 인덱스 리스트 반환

        예시:
        입력: "[joy] 안녕하세요! [surprise] 반가워요!"
        출력: [3, 3]  (joy→3, surprise→3)
        """

    def remove_emotion_keywords(self, target_str: str) -> str:
        """
        텍스트에서 감정 태그 제거

        예시:
        입력: "[joy] 안녕하세요! [surprise] 반가워요!"
        출력: "안녕하세요! 반가워요!"
        """

    def set_model(self, live2d_model_name: str):
        """모델 변경 - 런타임 핫스왑 지원"""
```

### 3.2 감정 추출 파이프라인

전체 파이프라인은 데코레이터 패턴으로 구현됩니다:

**파일:** `src/open_llm_vtuber/agent/transformers.py`

```
LLM 토큰 스트림
    ↓
@sentence_divider()        → 토큰 → 문장 분할
    ↓
@actions_extractor()       → 문장에서 감정 태그 추출, Actions 생성
    ↓
@display_processor()       → 디스플레이 텍스트 처리 (<think> 태그 등)
    ↓
@tts_filter()              → TTS용 텍스트 필터링
    ↓
SentenceOutput {
    display_text: DisplayText,
    tts_text: str,
    actions: Actions
}
```

### 3.3 데이터 타입 정의

**파일:** `src/open_llm_vtuber/agent/output_types.py`

```python
@dataclass
class Actions:
    expressions: Optional[List[str] | List[int]] = None  # 표정 인덱스 리스트
    pictures: Optional[List[str]] = None                  # 이미지 (미사용)
    sounds: Optional[List[str]] = None                    # 사운드 (미사용)

@dataclass
class DisplayText:
    text: str                       # 표시할 텍스트
    name: Optional[str] = None      # 캐릭터 이름
    avatar: Optional[str] = None    # 아바타 이미지 경로

@dataclass
class SentenceOutput:
    display_text: DisplayText       # UI 표시용
    tts_text: str                   # TTS 입력용
    actions: Actions                # 표정/액션 정보
```

### 3.4 표현 프롬프트 시스템

LLM에게 감정 태그를 사용하도록 지시하는 시스템 프롬프트가 존재합니다:

```python
# service_context.py에서 시스템 프롬프트 구성
def construct_system_prompt(self):
    """
    템플릿의 [<insert_emomap_keys>]를 실제 감정 키 목록으로 치환
    예: "[neutral], [anger], [fear], [joy], [sadness], [surprise]"
    """
    prompt = persona_prompt + live2d_expression_prompt
    prompt = prompt.replace("[<insert_emomap_keys>]", self.live2d_model.emo_str)
```

이 프롬프트는 LLM이 응답에 `[joy]`, `[sadness]` 같은 감정 태그를 삽입하도록 유도합니다.

---

## 4. WebSocket 통신 프로토콜

### 4.1 연결 수명 주기

```
1. 프론트엔드 → ws://host:port/client-ws 연결
2. 백엔드 → "set-model-and-conf" 메시지 전송 (모델 정보 + 설정)
3. 백엔드 → "control: start-mic" 전송 (마이크 시작)
4. 양방향 메시지 교환 시작
5. 연결 종료 시 컨텍스트 정리
```

### 4.2 서버→클라이언트 메시지 (렌더링 관련)

#### 초기 설정 메시지
```json
{
  "type": "set-model-and-conf",
  "model_info": {
    "name": "mao_pro",
    "url": "/live2d-models/mao_pro/runtime/mao_pro.model3.json",
    "kScale": 0.5,
    "emotionMap": { "neutral": 0, "joy": 3, ... },
    "idleMotionGroupName": "Idle",
    "tapMotions": { "HitAreaHead": {"": 1} }
  },
  "conf_name": "Mao Pro",
  "conf_uid": "mao_pro_001",
  "client_uid": "unique-client-id"
}
```

#### 오디오+표정 메시지 (핵심 렌더링 시그널)
```json
{
  "type": "audio",
  "audio": "base64-encoded-wav-audio",
  "volumes": [0.2, 0.5, 0.8, 0.6, 0.3, ...],
  "slice_length": 20,
  "display_text": {
    "text": "안녕하세요! 반가워요!",
    "name": "Mao",
    "avatar": "mao.png"
  },
  "actions": {
    "expressions": [3, 3],
    "pictures": null,
    "sounds": null
  },
  "forwarded": false
}
```

#### 제어 메시지
```json
{ "type": "control", "text": "start-mic" }
{ "type": "control", "text": "conversation-chain-start" }
{ "type": "full-text", "text": "상태 텍스트" }
{ "type": "backend-synth-complete" }
{ "type": "force-new-message" }
```

### 4.3 클라이언트→서버 메시지

| 타입 | 페이로드 | 용도 |
|------|----------|------|
| `text-input` | `{text: "사용자 메시지"}` | 텍스트 입력 |
| `mic-audio-data` | `{audio: [float32...]}` | 오디오 청크 |
| `mic-audio-end` | `{}` | 오디오 입력 종료 |
| `interrupt-signal` | `{heard_response: "부분 텍스트"}` | 대화 중단 |
| `fetch-configs` | `{}` | 캐릭터 목록 요청 |
| `switch-config` | `{config_uid: "char_id"}` | 캐릭터 전환 |
| `frontend-playback-complete` | `{}` | 재생 완료 알림 |

### 4.4 핵심 포인트 - 표정 데이터 흐름

```
LLM 응답: "[joy] 안녕하세요! [surprise] 놀랍네요!"
    ↓
actions_extractor: expressions = [3, 3]
    ↓
display_text.text = "안녕하세요! 놀랍네요!" (태그 제거)
    ↓
WebSocket 전송: { type: "audio", actions: { expressions: [3, 3] }, ... }
    ↓
프론트엔드: model.setExpression(expressions[0])  // exp_04.exp3.json 적용
```

---

## 5. 프론트엔드 렌더링 시스템

### 5.1 프론트엔드 아키텍처 (Git 서브모듈 - 외부 저장소)

프론트엔드는 별도 저장소로 관리되어 이 워크스페이스에 포함되어 있지 않지만, 백엔드 코드와 프로토콜에서 요구사항을 완전히 파악할 수 있습니다:

**기술 스택 (추정):**
- **Pixi.js** - 2D WebGL 렌더링 엔진
- **Cubism SDK for Web** - Live2D 애니메이션 엔진
- **Web Audio API** - 오디오 재생 + 립싱크
- **WebSocket API** - 백엔드 실시간 통신

### 5.2 프론트엔드가 구현해야 하는 기능

1. **모델 로딩**: `model3.json` → `.moc3` + 텍스처 + 물리 + 표정 + 모션 로드
2. **표정 적용**: 표정 인덱스를 받아 해당 `.exp3.json` 파일의 파라미터 적용
3. **유휴 모션**: `idleMotionGroupName`에 해당하는 모션 루프 재생
4. **립싱크**: `volumes` 배열을 `slice_length` (20ms) 간격으로 `ParamA` 적용
5. **눈 깜빡임**: `EyeBlink` 그룹의 파라미터 자동 애니메이션
6. **물리 시뮬레이션**: 머리카락, 옷 등의 물리 효과
7. **터치 인터랙션**: `HitArea` 감지 → `tapMotions` 재생
8. **모델 전환**: `set-model-and-conf` 메시지 수신 시 모델 교체

### 5.3 립싱크 볼륨 분석 시스템

**파일:** `src/open_llm_vtuber/utils/stream_audio.py`

```python
def prepare_audio_payload(audio_path, display_text, actions):
    """
    오디오 파일 → WebSocket 전송용 페이로드 생성
    """
    audio = AudioSegment.from_file(audio_path)
    audio_base64 = base64.b64encode(audio.export(format="wav").read()).decode()
    volumes = _get_volume_by_chunks(audio, chunk_length_ms=20)

    return {
        "type": "audio",
        "audio": audio_base64,
        "volumes": volumes,          # 정규화된 볼륨 배열
        "slice_length": 20,          # 20ms 간격
        "display_text": display_text,
        "actions": actions
    }

def _get_volume_by_chunks(audio, chunk_length_ms=20):
    """
    오디오를 20ms 청크로 분할하고 각 청크의 RMS 볼륨 계산
    0.0 ~ 1.0으로 정규화
    """
    chunks = make_chunks(audio, chunk_length_ms)
    volumes = [chunk.rms for chunk in chunks]
    max_vol = max(volumes) if volumes else 1
    return [v / max_vol for v in volumes]  # 정규화
```

**프론트엔드 립싱크 구현:**
```
프레임마다:
1. 현재 오디오 재생 위치(ms) 확인
2. chunk_index = floor(현재_위치 / slice_length)
3. volume = volumes[chunk_index]
4. ParamA (입 파라미터) = volume * 최대_입_벌림
5. Live2D 모델 업데이트
```

---

## 6. 캐릭터 설정 시스템

### 6.1 캐릭터 설정 구조

**파일:** `config_templates/conf.default.yaml`

```yaml
character_config:
  conf_name: "Mao Pro"                    # 표시 이름
  conf_uid: "mao_pro_001"                 # 고유 ID
  live2d_model_name: "mao_pro"            # model_dict.json 참조 키
  character_name: "Mao"                   # AI 캐릭터 이름
  avatar: "mao.png"                       # 아바타 이미지 (UI 표시용)
  persona_prompt: |                       # 성격 프롬프트
    You are Mao, a confident AI assistant.
    Use [joy] for happy moments, [neutral] for default.

system_config:
  tool_prompts:
    live2d_expression_prompt: 'live2d_expression_prompt'  # 감정 태그 사용법 프롬프트
```

### 6.2 캐릭터 전환 메커니즘

```python
# service_context.py
async def handle_config_switch(self, new_config):
    """서버 재시작 없이 캐릭터 핫스왑"""
    self.live2d_model.set_model(new_config.live2d_model_name)
    self.system_prompt = self.construct_system_prompt()
    # agent, tts, asr 등 재초기화
```

### 6.3 다중 캐릭터 관리

```
characters/
├── en_nuke_debate.yaml      # 영어 토론 캐릭터
├── en_unhelpful_ai.yaml     # 비협조적 AI 캐릭터
├── zh_米粒.yaml              # 중국어 캐릭터
└── zh_翻译腔.yaml            # 번역체 캐릭터
```

각 캐릭터 파일은 기본 설정을 오버라이드하는 구조입니다.

---

## 7. 서비스 컨텍스트와 의존성 주입

### 7.1 ServiceContext

**파일:** `src/open_llm_vtuber/service_context.py`

```python
class ServiceContext:
    """클라이언트별 서비스 인스턴스 관리"""

    # 핵심 속성
    live2d_model: Live2dModel          # 모델 관리자
    agent_engine: AgentInterface       # LLM 에이전트
    system_prompt: str                 # 시스템 프롬프트 (감정 프롬프트 포함)
    client_uid: str                    # 클라이언트 식별자

    def construct_system_prompt(self):
        """
        페르소나 + 감정 프롬프트 결합
        [<insert_emomap_keys>]를 실제 감정 키로 치환
        """

    def load_from_config(self, config):
        """설정에서 모든 엔진 초기화"""
        self.init_live2d()
        self.init_agent()
        # ...

    def handle_config_switch(self, config):
        """런타임 캐릭터 전환"""
```

### 7.2 클라이언트별 컨텍스트 분리

```
클라이언트 A 연결 → ServiceContext A (Live2dModel A, Agent A)
클라이언트 B 연결 → ServiceContext B (Live2dModel B, Agent B)
```

각 클라이언트는 독립적인 캐릭터, 대화 기록, 표정 상태를 유지합니다.

---

## 8. 대화 처리 파이프라인 (Conversation Pipeline)

### 8.1 전체 처리 흐름

**파일:** `src/open_llm_vtuber/conversations/single_conversation.py`

```
사용자 입력 (텍스트 or 음성)
    ↓
[1] 입력 처리 (ASR 변환 or 텍스트 그대로)
    ↓
[2] BatchInput 생성 {text, images}
    ↓
[3] Agent.chat(batch_input) → 스트림 SentenceOutput
    ↓
[4] 표정 추출 파이프라인 (transformers)
    │  ├─ sentence_divider: 토큰 → 문장
    │  ├─ actions_extractor: 감정 태그 → Actions
    │  ├─ display_processor: <think> 태그 처리
    │  └─ tts_filter: TTS 텍스트 정리
    ↓
[5] TTS 생성 (병렬, 순서 보장)
    ↓
[6] 볼륨 분석 (20ms 청크 RMS)
    ↓
[7] 페이로드 조립
    │  { type:"audio", audio, volumes, display_text, actions }
    ↓
[8] WebSocket 순차 전송 (시퀀스 번호 기반)
    ↓
[9] 프론트엔드 렌더링
    │  ├─ 표정 변경 (expressions → exp.json 적용)
    │  ├─ 오디오 재생
    │  └─ 립싱크 (volumes → ParamA)
    ↓
[10] frontend-playback-complete → 다음 문장
```

### 8.2 TTS 매니저의 순서 보장

**파일:** `src/open_llm_vtuber/conversations/tts_manager.py`

```python
class TTSTaskManager:
    """
    병렬 TTS 생성 + 순차 전송

    문장 1 (TTS 생성 800ms) ─────────→ [전송 1]
    문장 2 (TTS 생성 300ms) ──→ [대기] → [전송 2]
    문장 3 (TTS 생성 500ms) ───→ [대기] → [전송 3]
    """
    async def speak(self, tts_text, display_text, actions, ...):
        # 시퀀스 번호 할당
        # TTS 비동기 생성 시작
        # 페이로드 큐에 추가
        # 순서대로 전송
```

---

## 9. WebSocket 핸들러 상세

### 9.1 연결 관리

**파일:** `src/open_llm_vtuber/websocket_handler.py`

```python
class WebSocketHandler:
    client_connections: Dict[str, WebSocket]       # 활성 연결
    client_contexts: Dict[str, ServiceContext]      # 클라이언트별 컨텍스트
    current_conversation_tasks: Dict[str, Task]    # 진행 중인 대화

    async def handle_new_connection(self, websocket, client_uid):
        """
        1. 기존 컨텍스트 로드 or 새 컨텍스트 생성
        2. set-model-and-conf 메시지 전송
        3. 마이크 시작 시그널 전송
        4. 메시지 루프 시작
        """

    async def _route_message(self, websocket, client_uid, data):
        """메시지 타입별 라우팅"""
        match data.get("type"):
            case "text-input": self._handle_conversation_trigger(...)
            case "mic-audio-end": self._handle_conversation_trigger(...)
            case "fetch-configs": self._handle_fetch_configs(...)
            case "switch-config": self._handle_config_switch(...)
            case "interrupt-signal": self._handle_interrupt(...)
            case "frontend-playback-complete": ...
```

### 9.2 중단 처리 (Interrupt)

```python
async def _handle_interrupt(self, client_uid, data):
    """사용자가 AI 응답 도중 중단할 때"""
    # 현재 대화 태스크 취소
    # TTS 큐 클리어
    # 프론트엔드에 중단 확인 전송
```

---

## 10. 서버 구성 및 정적 파일 서빙

### 10.1 FastAPI 서버

**파일:** `src/open_llm_vtuber/server.py`

```python
class WebSocketServer:
    def __init__(self):
        self.app = FastAPI()

        # CORS 설정
        self.app.add_middleware(CORSMiddleware, allow_origins=["*"])

        # 정적 파일 마운트
        self.app.mount("/live2d-models", CORSStaticFiles(directory="live2d-models"))
        self.app.mount("/avatars", AvatarStaticFiles(directory="avatars"))
        self.app.mount("/bg", CORSStaticFiles(directory="backgrounds"))
        self.app.mount("/cache", CORSStaticFiles(directory="cache"))
```

### 10.2 라우트 정의

**파일:** `src/open_llm_vtuber/routes.py`

| 엔드포인트 | 타입 | 용도 |
|-----------|------|------|
| `/client-ws` | WebSocket | 메인 클라이언트 연결 |
| `/tts-ws` | WebSocket | TTS 생성 (별도) |
| `/asr` | POST | 음성 인식 |
| `/live2d-models/info` | GET | 사용 가능한 모델 목록 + 아바타 |
| `/web-tool` | GET | 웹 도구 UI |
| `/proxy-ws` | WebSocket | 프록시 모드 (선택) |

---

## 11. 핵심 의존성 정리

### 11.1 백엔드 (렌더링 관련)

| 라이브러리 | 역할 | 이식 필요 |
|-----------|------|----------|
| FastAPI | WebSocket 서버 | ✅ 적용 (Geny에 이미 존재) |
| pydub | 오디오 볼륨 분석 (립싱크) | ⚠️ 음성 제외 시 불필요 |
| Pydantic | 설정 검증 | ✅ Geny에 이미 존재 |
| loguru | 로깅 | ❌ 불필요 |

### 11.2 프론트엔드 (렌더링 핵심)

| 라이브러리 | 역할 | 이식 필요 |
|-----------|------|----------|
| Pixi.js | 2D WebGL 렌더링 | ✅ 필수 |
| Cubism SDK for Web | Live2D 모델 렌더링 | ✅ 필수 |
| Web Audio API | 립싱크 재생 | ⚠️ 음성 제외 시 대체 방안 필요 |

---

## 12. 분석 결론 및 핵심 이식 대상

### 12.1 이식 핵심 컴포넌트 (음성 제외)

| 우선순위 | 컴포넌트 | 설명 |
|---------|---------|------|
| P0 | Live2D 모델 렌더링 | Pixi.js + Cubism SDK로 모델 로딩/렌더링 |
| P0 | 표정/감정 시스템 | emotionMap + 감정 추출 + 프론트엔드 표정 적용 |
| P0 | 유휴 애니메이션 | Idle 모션 루프 재생 + 눈 깜빡임 |
| P1 | 물리 시뮬레이션 | 머리카락/의상 물리 효과 |
| P1 | 터치 인터랙션 | HitArea 감지 → 반응 모션 |
| P1 | 모델 전환 | 런타임 캐릭터/모델 변경 |
| P2 | 다중 표정 블렌딩 | 여러 표정 동시 적용 + 전환 |
| P2 | 모션 시스템 | 제스처, 특수 모션 |

### 12.2 백엔드 이식 대상

| 컴포넌트 | 원본 파일 | 이식 대상 |
|---------|----------|----------|
| Live2dModel 클래스 | `live2d_model.py` | 감정 추출 로직 |
| Actions 데이터 타입 | `output_types.py` | SSE 이벤트 타입 |
| 감정 추출 파이프라인 | `transformers.py` | LangGraph 노드 |
| model_dict.json | 프로젝트 루트 | 백엔드 설정 |
| 캐릭터 설정 | `characters/*.yaml` | 에이전트 설정 확장 |

### 12.3 프론트엔드 이식 대상

| 컴포넌트 | 구현 내용 | 통합 위치 |
|---------|----------|----------|
| Live2D 렌더링 엔진 | Pixi.js + Cubism SDK 초기화 | 새 컴포넌트 |
| 표정 애니메이터 | 표정 전환 + 블렌딩 | Live2D 컴포넌트 내 |
| 유휴 모션 | 루프 재생 시스템 | Live2D 컴포넌트 내 |
| 눈 깜빡임 | 자동 파라미터 애니메이션 | Live2D 컴포넌트 내 |
| 물리 시뮬레이션 | physics3.json 적용 | Live2D 렌더러 내 |
| 이벤트 리스너 | SSE 기반 표정 업데이트 | Geny SSE 시스템 |

---

## 13. 아키텍처 다이어그램 (이식 관점)

```
┌─────────────────────────────────── Open-LLM-VTuber ────────────────────────────────────┐
│                                                                                         │
│  ┌─── 이식 대상 (백엔드) ─────────────────┐   ┌─── 이식 대상 (프론트엔드) ───────────┐ │
│  │                                         │   │                                       │ │
│  │  Live2dModel                            │   │  Live2D 렌더링 엔진                   │ │
│  │  ├─ emotionMap 관리                     │   │  ├─ Pixi.js + Cubism SDK              │ │
│  │  ├─ extract_emotion()                   │   │  ├─ model3.json 로더                  │ │
│  │  └─ remove_emotion_keywords()           │   │  ├─ 표정 적용기                       │ │
│  │                                         │   │  ├─ 유휴 모션 재생기                  │ │
│  │  Actions 데이터 모델                    │   │  ├─ 눈 깜빡임 자동화                  │ │
│  │  ├─ expressions: List[int]              │   │  ├─ 물리 시뮬레이션                   │ │
│  │  └─ 확장 가능 구조                      │   │  └─ 터치 인터랙션                     │ │
│  │                                         │   │                                       │ │
│  │  감정 추출 파이프라인                   │   │  모델 관리                             │ │
│  │  ├─ LLM 출력 → 감정 태그 파싱          │   │  ├─ model_dict.json 참조              │ │
│  │  ├─ emotionMap 매핑                     │   │  ├─ 런타임 모델 전환                  │ │
│  │  └─ 텍스트 정리                         │   │  └─ 복수 모델 캐싱                    │ │
│  │                                         │   │                                       │ │
│  │  캐릭터 설정 시스템                     │   │  통신                                 │ │
│  │  ├─ model_dict.json                     │   │  ├─ SSE 이벤트 리스너                 │ │
│  │  └─ 캐릭터별 감정 프롬프트              │   │  └─ 표정/상태 업데이트 핸들러         │ │
│  │                                         │   │                                       │ │
│  └─────────────────────────────────────────┘   └───────────────────────────────────────┘ │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

*End of Report*
