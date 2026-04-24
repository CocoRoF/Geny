# VTuber Live2D 렌더링 기능 이식 세부 계획서

> 작성일: 2026-03-29
> 프로젝트: Geny (멀티 에이전트 자율 시스템)
> 이식 대상: Open-LLM-VTuber → Geny (Live2D 캐릭터 렌더링, 음성 제외)
> 참조: 01_VTuber_렌더링_시스템_분석_리포트.md, 02_Geny_구조_및_이식_가능성_리포트.md

---

## 목차

1. [이식 목표 및 범위](#1-이식-목표-및-범위)
2. [전체 아키텍처 설계](#2-전체-아키텍처-설계)
3. [Phase 1: 기반 인프라 구축](#3-phase-1-기반-인프라-구축)
4. [Phase 2: 백엔드 감정 엔진](#4-phase-2-백엔드-감정-엔진)
5. [Phase 3: 프론트엔드 Live2D 렌더러](#5-phase-3-프론트엔드-live2d-렌더러)
6. [Phase 4: LiveTab (세션 탭) 구현](#6-phase-4-livetab-세션-탭-구현)
7. [Phase 5: ChatTab 통합](#7-phase-5-chattab-통합)
8. [Phase 6: 설정 및 관리 UI](#8-phase-6-설정-및-관리-ui)
9. [Phase 7: 테스트 및 최적화](#9-phase-7-테스트-및-최적화)
10. [파일 목록 및 변경 사항 총괄](#10-파일-목록-및-변경-사항-총괄)
11. [의존성 및 라이선스](#11-의존성-및-라이선스)
12. [리스크 및 대응 계획](#12-리스크-및-대응-계획)

---

## 1. 이식 목표 및 범위

### 1.1 목표

Geny의 AI 에이전트에 **Live2D VTuber 캐릭터**를 부여하여, 에이전트의 실행 상태와 감정을 시각적으로 표현합니다.

```
현재: 에이전트 → 3D 미니 캐릭터 (무표정, 단순 걷기)
목표: 에이전트 → Live2D 캐릭터 (표정, 감정, 눈 깜빡임, 물리 효과, 인터랙션)
```

### 1.2 범위 (In-Scope)

| # | 기능 | 우선순위 |
|---|------|---------|
| 1 | Live2D 모델 로딩 및 렌더링 | P0 |
| 2 | 표정/감정 표현 시스템 (emotionMap 기반) | P0 |
| 3 | 유휴 애니메이션 (Idle, 눈 깜빡임) | P0 |
| 4 | 에이전트 실행 상태 → 표정 자동 매핑 | P0 |
| 5 | 물리 시뮬레이션 (머리카락, 의상) | P1 |
| 6 | 터치 인터랙션 (HitArea 반응) | P1 |
| 7 | 모델 전환 (런타임 캐릭터 변경) | P1 |
| 8 | 다중 모델 관리 및 설정 UI | P2 |
| 9 | 세션 **Live** 탭 (독립 탭으로 Live2D 렌더링) | P0 |
| 10 | ChatTab 채팅 중 Live2D 아바타 표시 | P2 |

### 1.3 범위 외 (Out-of-Scope)

- ❌ TTS (Text-to-Speech) 음성 합성
- ❌ 립싱크 (오디오 기반 입 움직임)
- ❌ ASR (Automatic Speech Recognition) 음성 인식
- ❌ 실시간 페이스 트래킹

---

## 2. 전체 아키텍처 설계

### 2.1 목표 아키텍처

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Frontend (Next.js)                             │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │  세션 탭 바: 명령 | 그래프 | 스토리지 | 도구 | 로그 | 💠 Live │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌─────────────────┐  ┌──────────────────────────┐  ┌─────────────┐  │
│  │  PlaygroundTab   │  │  LiveTab (신규 세션 탭)   │  │  ChatTab    │  │
│  │  3D 도시 씬     │  │  ┌────────────────────┐  │  │  채팅방     │  │
│  │  ┌──────────┐   │  │  │  Live2D Canvas      │  │  │ ┌─────────┐│  │
│  │  │ 미니 3D  │   │  │  │  (Pixi.js + Cubism) │  │  │ │미니 L2D ││  │
│  │  │ 아바타   │   │  │  │  전체 크기 렌더링   │  │  │ │옆 아바타││  │
│  │  │ (기존유지)│   │  │  │  표정/감정/물리     │  │  │ └─────────┘│  │
│  │  └──────────┘   │  │  └────────────────────┘  │  │             │  │
│  └─────────────────┘  └──────────────────────────┘  └─────────────┘  │
│                                                                         │
│  ┌─── Zustand Stores ───────────────────────────────────────────────┐  │
│  │  useAppStore        useVTuberStore (신규)     useMessengerStore   │  │
│  │  sessions[]         live2dModels[]             rooms[]            │  │
│  │  selectedSession    avatarStates{}             messages[]         │  │
│  │                     emotionMaps{}              agentProgress[]    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌─── SSE 이벤트 리스너 ────────────────────────────────────────────┐  │
│  │  기존: log, status, result, message, agent_progress              │  │
│  │  신규: avatar_state { session_id, emotion, expression_idx, ... } │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                         │
└──────────────────────────┬──────────────────────────────────────────────┘
                           │ REST API + SSE
                           │
┌──────────────────────────┼──────────────────────────────────────────────┐
│                          │  Backend (FastAPI)                           │
│                          │                                              │
│  ┌─── 기존 서비스 ──────┴─────────────────────────────────┐           │
│  │  Agent Session (LangGraph)                               │           │
│  │  ├─ memory_inject → relevance_gate → adaptive_classify  │           │
│  │  ├─ guard_direct → direct_answer → post_model           │           │
│  │  └─ ⭐ emit_avatar_state (신규 노드)                    │           │
│  │                                                          │           │
│  │  Session Logger                                          │           │
│  │  └─ ⭐ AVATAR 로그 레벨 (신규)                          │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                         │
│  ┌─── 신규 서비스 ─────────────────────────────────────────┐           │
│  │                                                          │           │
│  │  VTuber Service (신규)                                   │           │
│  │  ├─ Live2dModelManager    (모델 관리)                    │           │
│  │  ├─ EmotionExtractor      (감정 추출)                    │           │
│  │  └─ AvatarStateManager    (상태 관리 + SSE 발행)        │           │
│  │                                                          │           │
│  │  VTuber Controller (신규)                                │           │
│  │  ├─ GET  /api/vtuber/models          모델 목록          │           │
│  │  ├─ GET  /api/vtuber/models/{name}   모델 상세          │           │
│  │  ├─ POST /api/vtuber/models          모델 등록          │           │
│  │  ├─ PUT  /api/vtuber/agents/{id}/model  모델 할당       │           │
│  │  ├─ GET  /api/vtuber/agents/{id}/state  현재 상태       │           │
│  │  ├─ POST /api/vtuber/agents/{id}/interact  터치 반응    │           │
│  │  └─ GET  /api/vtuber/agents/{id}/events   SSE 스트림    │           │
│  │                                                          │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                         │
│  ┌─── 정적 파일 서빙 ─────────────────────────────────────┐           │
│  │  /static/live2d-models/{name}/runtime/...               │           │
│  │  /static/avatars/{name}.png                              │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 데이터 흐름 (감정 표현)

```
[에이전트 실행 시작]
    ↓
LangGraph 노드 실행
    ↓
post_model 노드 (LLM 응답 파싱)
    ↓
emit_avatar_state 노드 (신규)
    ├─ 응답 텍스트 분석
    ├─ 감정 키워드 추출: "[joy]" → 3
    ├─ 에이전트 상태 분석: executing → "concentrating"
    └─ SSE 이벤트 발행: avatar_state
    ↓
SSE → 프론트엔드
    ↓
useVTuberStore 상태 업데이트
    ↓
Live2D 컴포넌트 리렌더링
    ├─ 표정 전환 (exp3.json 적용)
    ├─ 모션 변경 (idle → gesture)
    └─ 파라미터 블렌딩 (부드러운 전환)
```

### 2.3 SSE 이벤트 프로토콜

#### 기존 이벤트 (변경 없음)
```
event: log          { timestamp, level, message, metadata }
event: status       { state, progress }
event: result       { success, output, cost_usd }
event: heartbeat    { timestamp }
event: done         (종료)
```

#### 신규 이벤트
```
event: avatar_state
data: {
  "session_id": "abc123",
  "emotion": "joy",                    // 감정 이름
  "expression_index": 3,               // 표정 인덱스
  "motion_group": "Idle",             // 모션 그룹
  "motion_index": 0,                   // 모션 인덱스
  "intensity": 1.0,                    // 표정 강도 (0.0~1.0)
  "transition_ms": 300,                // 전환 시간 (ms)
  "trigger": "agent_output",           // 트리거 원인
  "timestamp": "2026-03-29T..."
}
```

---

## 3. Phase 1: 기반 인프라 구축

### 3.1 목표
모델 파일 서빙, 기본 설정 파일, 의존성 설정

### 3.2 작업 목록

#### 3.2.1 Live2D 모델 디렉토리 생성

```
geny/backend/static/
└── live2d-models/
    ├── model_registry.json            ← 모델 레지스트리 (model_dict.json 역할)
    └── mao_pro/                       ← Open-LLM-VTuber에서 복사
        └── runtime/
            ├── mao_pro.model3.json
            ├── mao_pro.moc3
            ├── mao_pro.physics3.json
            ├── mao_pro.pose3.json
            ├── mao_pro.cdi3.json
            ├── mao_pro.4096/
            │   └── texture_00.png
            ├── expressions/
            │   ├── exp_01.exp3.json ~ exp_08.exp3.json
            └── motions/
                └── mtn_01.motion3.json ~ ...
```

#### 3.2.2 model_registry.json 작성

```json
{
  "models": [
    {
      "name": "mao_pro",
      "display_name": "Mao Pro",
      "description": "기본 VTuber 캐릭터",
      "url": "/static/live2d-models/mao_pro/runtime/mao_pro.model3.json",
      "thumbnail": "/static/live2d-models/mao_pro/thumbnail.png",
      "kScale": 0.5,
      "initialXshift": 0,
      "initialYshift": 0,
      "idleMotionGroupName": "Idle",
      "emotionMap": {
        "neutral": 0,
        "anger": 2,
        "disgust": 2,
        "fear": 1,
        "joy": 3,
        "smirk": 3,
        "sadness": 1,
        "surprise": 3
      },
      "tapMotions": {
        "HitAreaHead": { "": 1 },
        "HitAreaBody": { "": 1 }
      }
    }
  ],
  "default_model": "mao_pro",
  "agent_model_assignments": {}
}
```

#### 3.2.3 백엔드 정적 파일 마운트

**파일:** `backend/main.py` 수정

```python
# 기존 정적 파일 마운트 이후에 추가
from fastapi.staticfiles import StaticFiles

# Live2D 모델 정적 파일 서빙
app.mount(
    "/static/live2d-models",
    StaticFiles(directory="static/live2d-models"),
    name="live2d-models"
)
```

#### 3.2.4 Nginx 라우팅 추가

**파일:** `nginx/nginx.conf` 수정

```nginx
# Live2D 모델 파일 서빙 (캐싱 포함)
location /static/live2d-models/ {
    proxy_pass http://backend:8000;
    proxy_cache_valid 200 1d;            # 1일 캐시
    add_header Cache-Control "public, max-age=86400";
    add_header Access-Control-Allow-Origin *;
}
```

#### 3.2.5 프론트엔드 의존성 추가

**파일:** `frontend/package.json` 수정

```json
{
  "dependencies": {
    "pixi.js": "^7.3.3",
    "pixi-live2d-display": "^0.4.0",
    "@pixi/utils": "^7.3.3"
  }
}
```

> **참고:** `pixi-live2d-display`은 Cubism SDK를 래핑한 MIT 라이선스 라이브러리로, Live2D 모델을 Pixi.js에서 쉽게 렌더링할 수 있게 합니다.

#### 3.2.6 Cubism SDK 코어 파일 설치

```
frontend/public/lib/
└── live2d/
    └── live2dcubismcore.min.js        ← Live2D 공식 SDK 코어
```

**파일:** `frontend/src/app/layout.tsx` 수정

```tsx
<Script src="/lib/live2d/live2dcubismcore.min.js" strategy="beforeInteractive" />
```

### 3.3 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `backend/static/live2d-models/` | 신규 | 모델 파일 디렉토리 |
| `backend/static/live2d-models/model_registry.json` | 신규 | 모델 레지스트리 |
| `backend/main.py` | 수정 | 정적 파일 마운트 추가 |
| `nginx/nginx.conf` | 수정 | Live2D 라우팅 추가 |
| `frontend/package.json` | 수정 | pixi.js 의존성 추가 |
| `frontend/public/lib/live2d/` | 신규 | Cubism SDK 코어 |
| `frontend/src/app/layout.tsx` | 수정 | SDK 스크립트 로드 |

---

## 4. Phase 2: 백엔드 감정 엔진

### 4.1 목표
에이전트 출력에서 감정을 추출하고 SSE로 발행하는 백엔드 파이프라인 구축

### 4.2 작업 목록

#### 4.2.1 VTuber 서비스 모듈 생성

**파일:** `backend/service/vtuber/__init__.py`

```python
from .live2d_model_manager import Live2dModelManager
from .emotion_extractor import EmotionExtractor
from .avatar_state_manager import AvatarStateManager
```

#### 4.2.2 Live2D 모델 매니저

**파일:** `backend/service/vtuber/live2d_model_manager.py`

```python
import json
import os
from typing import Dict, List, Optional
from dataclasses import dataclass, field

@dataclass
class Live2dModelInfo:
    name: str
    display_name: str
    description: str
    url: str
    thumbnail: str
    kScale: float = 0.5
    initialXshift: float = 0
    initialYshift: float = 0
    idleMotionGroupName: str = "Idle"
    emotionMap: Dict[str, int] = field(default_factory=dict)
    tapMotions: Dict[str, Dict[str, int]] = field(default_factory=dict)

class Live2dModelManager:
    """Live2D 모델 레지스트리 관리"""

    def __init__(self, models_dir: str = "static/live2d-models"):
        self.models_dir = models_dir
        self.registry_path = os.path.join(models_dir, "model_registry.json")
        self.models: Dict[str, Live2dModelInfo] = {}
        self.agent_assignments: Dict[str, str] = {}  # session_id → model_name
        self._load_registry()

    def _load_registry(self):
        """레지스트리 파일에서 모델 정보 로드"""
        if os.path.exists(self.registry_path):
            with open(self.registry_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for model_data in data.get("models", []):
                model = Live2dModelInfo(**model_data)
                self.models[model.name] = model
            self.agent_assignments = data.get("agent_model_assignments", {})

    def get_model(self, name: str) -> Optional[Live2dModelInfo]:
        """모델 정보 반환"""
        return self.models.get(name)

    def list_models(self) -> List[Live2dModelInfo]:
        """모든 등록된 모델 목록"""
        return list(self.models.values())

    def assign_model_to_agent(self, session_id: str, model_name: str):
        """에이전트에 Live2D 모델 할당"""
        if model_name not in self.models:
            raise ValueError(f"Model not found: {model_name}")
        self.agent_assignments[session_id] = model_name
        self._save_registry()

    def get_agent_model(self, session_id: str) -> Optional[Live2dModelInfo]:
        """에이전트에 할당된 모델 반환"""
        model_name = self.agent_assignments.get(session_id)
        return self.models.get(model_name) if model_name else None

    def get_emotion_map(self, model_name: str) -> Dict[str, int]:
        """모델의 감정 매핑 반환"""
        model = self.models.get(model_name)
        return model.emotionMap if model else {}

    def get_emo_str(self, model_name: str) -> str:
        """감정 키 문자열 반환 (LLM 프롬프트용)"""
        emo_map = self.get_emotion_map(model_name)
        return ", ".join(f"[{key}]" for key in emo_map.keys())

    def _save_registry(self):
        """레지스트리 파일 저장"""
        data = {
            "models": [vars(m) for m in self.models.values()],
            "agent_model_assignments": self.agent_assignments
        }
        with open(self.registry_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
```

#### 4.2.3 감정 추출기

**파일:** `backend/service/vtuber/emotion_extractor.py`

```python
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

@dataclass
class EmotionResult:
    """감정 추출 결과"""
    emotions: List[str]              # 추출된 감정 이름 ["joy", "surprise"]
    expression_indices: List[int]    # 표정 인덱스 [3, 3]
    cleaned_text: str                # 감정 태그 제거된 텍스트
    primary_emotion: str             # 주요 감정 (마지막)
    primary_index: int               # 주요 표정 인덱스

class EmotionExtractor:
    """LLM 출력에서 감정 키워드를 추출하는 엔진

    Open-LLM-VTuber의 Live2dModel.extract_emotion() 로직을 이식.
    """

    def __init__(self, emotion_map: Dict[str, int]):
        self.emotion_map = emotion_map
        self._compile_patterns()

    def _compile_patterns(self):
        """감정 키워드 패턴 컴파일"""
        if not self.emotion_map:
            self._pattern = None
            return
        escaped_keys = [re.escape(key) for key in self.emotion_map.keys()]
        self._pattern = re.compile(
            r'\[(' + '|'.join(escaped_keys) + r')\]',
            re.IGNORECASE
        )

    def extract(self, text: str) -> EmotionResult:
        """텍스트에서 감정 추출

        입력: "[joy] 안녕하세요! [surprise] 반가워요!"
        출력: EmotionResult(
            emotions=["joy", "surprise"],
            expression_indices=[3, 3],
            cleaned_text="안녕하세요! 반가워요!",
            primary_emotion="surprise",
            primary_index=3
        )
        """
        if not self._pattern:
            return EmotionResult(
                emotions=[], expression_indices=[],
                cleaned_text=text, primary_emotion="neutral", primary_index=0
            )

        # 감정 키워드 추출
        matches = self._pattern.findall(text)
        emotions = [m.lower() for m in matches]
        indices = [self.emotion_map.get(e, 0) for e in emotions]

        # 텍스트 정리
        cleaned = self._pattern.sub('', text).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)  # 중복 공백 제거

        # 주요 감정 (마지막 감정이 현재 상태)
        primary_emotion = emotions[-1] if emotions else "neutral"
        primary_index = indices[-1] if indices else 0

        return EmotionResult(
            emotions=emotions,
            expression_indices=indices,
            cleaned_text=cleaned,
            primary_emotion=primary_emotion,
            primary_index=primary_index
        )

    def update_emotion_map(self, new_map: Dict[str, int]):
        """감정 매핑 업데이트"""
        self.emotion_map = new_map
        self._compile_patterns()

class AgentStateEmotionMapper:
    """에이전트 실행 상태를 감정으로 자동 매핑

    LLM 출력에 감정 태그가 없을 때 에이전트 상태 기반으로 감정을 추론.
    """

    STATE_EMOTION_MAP = {
        "idle": "neutral",
        "thinking": "neutral",         # 생각 중 (기본)
        "executing": "neutral",        # 실행 중
        "tool_calling": "surprise",    # 도구 호출 시
        "success": "joy",              # 성공
        "error": "fear",               # 에러 발생
        "waiting": "neutral",          # 대기 중
        "speaking": "joy",             # 발화 중
    }

    @classmethod
    def map_state_to_emotion(cls, agent_state: str) -> str:
        """에이전트 상태 → 감정 이름"""
        return cls.STATE_EMOTION_MAP.get(agent_state, "neutral")

    @classmethod
    def resolve_emotion(
        cls,
        extracted_emotion: Optional[str],
        agent_state: str,
        emotion_map: Dict[str, int]
    ) -> Tuple[str, int]:
        """
        감정 태그 추출 결과와 에이전트 상태를 결합하여 최종 감정 결정

        우선순위: 감정 태그 > 에이전트 상태 매핑
        """
        if extracted_emotion and extracted_emotion in emotion_map:
            return extracted_emotion, emotion_map[extracted_emotion]

        state_emotion = cls.map_state_to_emotion(agent_state)
        index = emotion_map.get(state_emotion, 0)
        return state_emotion, index
```

#### 4.2.4 아바타 상태 매니저

**파일:** `backend/service/vtuber/avatar_state_manager.py`

```python
import asyncio
from datetime import datetime
from typing import Dict, Optional, Callable, Awaitable
from dataclasses import dataclass, asdict

@dataclass
class AvatarState:
    """아바타의 현재 표현 상태"""
    session_id: str
    emotion: str = "neutral"
    expression_index: int = 0
    motion_group: str = "Idle"
    motion_index: int = 0
    intensity: float = 1.0
    transition_ms: int = 300
    trigger: str = "system"            # system, agent_output, user_interact, state_change
    timestamp: str = ""

    def to_sse_data(self) -> dict:
        """SSE 이벤트 데이터로 변환"""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
        return asdict(self)

class AvatarStateManager:
    """에이전트별 아바타 상태 관리 및 SSE 발행"""

    def __init__(self):
        self._states: Dict[str, AvatarState] = {}
        self._subscribers: Dict[str, list] = {}  # session_id → [callback, ...]

    def get_state(self, session_id: str) -> AvatarState:
        """현재 아바타 상태 반환"""
        if session_id not in self._states:
            self._states[session_id] = AvatarState(session_id=session_id)
        return self._states[session_id]

    async def update_state(
        self,
        session_id: str,
        emotion: Optional[str] = None,
        expression_index: Optional[int] = None,
        motion_group: Optional[str] = None,
        motion_index: Optional[int] = None,
        intensity: float = 1.0,
        transition_ms: int = 300,
        trigger: str = "system"
    ):
        """아바타 상태 업데이트 및 구독자 알림"""
        state = self.get_state(session_id)

        if emotion is not None:
            state.emotion = emotion
        if expression_index is not None:
            state.expression_index = expression_index
        if motion_group is not None:
            state.motion_group = motion_group
        if motion_index is not None:
            state.motion_index = motion_index
        state.intensity = intensity
        state.transition_ms = transition_ms
        state.trigger = trigger
        state.timestamp = datetime.utcnow().isoformat()

        # 구독자에게 알림
        await self._notify_subscribers(session_id, state)

    def subscribe(self, session_id: str, callback: Callable):
        """SSE 구독 등록"""
        if session_id not in self._subscribers:
            self._subscribers[session_id] = []
        self._subscribers[session_id].append(callback)

    def unsubscribe(self, session_id: str, callback: Callable):
        """SSE 구독 해제"""
        if session_id in self._subscribers:
            self._subscribers[session_id] = [
                cb for cb in self._subscribers[session_id] if cb != callback
            ]

    async def _notify_subscribers(self, session_id: str, state: AvatarState):
        """구독자에게 상태 변경 알림"""
        callbacks = self._subscribers.get(session_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(state)
                else:
                    callback(state)
            except Exception as e:
                pass  # 개별 구독자 에러 격리

    def cleanup_session(self, session_id: str):
        """세션 정리"""
        self._states.pop(session_id, None)
        self._subscribers.pop(session_id, None)
```

#### 4.2.5 VTuber 컨트롤러

**파일:** `backend/controller/vtuber_controller.py`

```python
import asyncio
import json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/vtuber", tags=["vtuber"])

# --- Request/Response Models ---

class ModelAssignRequest(BaseModel):
    model_name: str

class InteractRequest(BaseModel):
    hit_area: str               # "HitAreaHead", "HitAreaBody"
    x: Optional[float] = None
    y: Optional[float] = None

class EmotionOverrideRequest(BaseModel):
    emotion: str
    intensity: float = 1.0
    transition_ms: int = 300

# --- 모델 관리 엔드포인트 ---

@router.get("/models")
async def list_models(request: Request):
    """등록된 Live2D 모델 목록"""
    manager = request.app.state.live2d_model_manager
    models = manager.list_models()
    return {"models": [vars(m) for m in models]}

@router.get("/models/{name}")
async def get_model(name: str, request: Request):
    """특정 모델 상세 정보"""
    manager = request.app.state.live2d_model_manager
    model = manager.get_model(name)
    if not model:
        raise HTTPException(404, f"Model not found: {name}")
    return vars(model)

# --- 에이전트-모델 할당 ---

@router.put("/agents/{session_id}/model")
async def assign_model(session_id: str, req: ModelAssignRequest, request: Request):
    """에이전트에 Live2D 모델 할당"""
    manager = request.app.state.live2d_model_manager
    try:
        manager.assign_model_to_agent(session_id, req.model_name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "session_id": session_id, "model_name": req.model_name}

@router.get("/agents/{session_id}/model")
async def get_agent_model(session_id: str, request: Request):
    """에이전트에 할당된 모델 정보"""
    manager = request.app.state.live2d_model_manager
    model = manager.get_agent_model(session_id)
    if not model:
        return {"session_id": session_id, "model": None}
    return {"session_id": session_id, "model": vars(model)}

# --- 아바타 상태 ---

@router.get("/agents/{session_id}/state")
async def get_avatar_state(session_id: str, request: Request):
    """에이전트 아바타 현재 상태"""
    state_manager = request.app.state.avatar_state_manager
    state = state_manager.get_state(session_id)
    return state.to_sse_data()

# --- SSE 스트림 ---

@router.get("/agents/{session_id}/events")
async def avatar_events(session_id: str, request: Request):
    """에이전트 아바타 상태 SSE 스트림"""
    state_manager = request.app.state.avatar_state_manager

    async def event_generator():
        queue = asyncio.Queue()

        async def on_state_change(state):
            await queue.put(state)

        state_manager.subscribe(session_id, on_state_change)

        try:
            # 초기 상태 전송
            current = state_manager.get_state(session_id)
            yield f"event: avatar_state\ndata: {json.dumps(current.to_sse_data())}\n\n"

            while True:
                try:
                    state = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"event: avatar_state\ndata: {json.dumps(state.to_sse_data())}\n\n"
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {{}}\n\n"
        finally:
            state_manager.unsubscribe(session_id, on_state_change)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# --- 인터랙션 ---

@router.post("/agents/{session_id}/interact")
async def interact_with_avatar(
    session_id: str, req: InteractRequest, request: Request
):
    """아바타 터치 인터랙션"""
    model_manager = request.app.state.live2d_model_manager
    state_manager = request.app.state.avatar_state_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        raise HTTPException(404, "No model assigned to this agent")

    # tapMotions에서 모션 찾기
    tap_motions = model.tapMotions.get(req.hit_area, {})
    if tap_motions:
        motion_index = list(tap_motions.values())[0]
        await state_manager.update_state(
            session_id=session_id,
            motion_group="TapBody" if "Body" in req.hit_area else "TapHead",
            motion_index=motion_index,
            trigger="user_interact"
        )

    return {"status": "ok", "hit_area": req.hit_area}

# --- 감정 수동 오버라이드 ---

@router.post("/agents/{session_id}/emotion")
async def override_emotion(
    session_id: str, req: EmotionOverrideRequest, request: Request
):
    """수동 감정 오버라이드 (디버깅/데모용)"""
    model_manager = request.app.state.live2d_model_manager
    state_manager = request.app.state.avatar_state_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        raise HTTPException(404, "No model assigned to this agent")

    emotion_map = model.emotionMap
    expression_index = emotion_map.get(req.emotion, 0)

    await state_manager.update_state(
        session_id=session_id,
        emotion=req.emotion,
        expression_index=expression_index,
        intensity=req.intensity,
        transition_ms=req.transition_ms,
        trigger="manual_override"
    )

    return {"status": "ok", "emotion": req.emotion, "expression_index": expression_index}
```

#### 4.2.6 기존 SSE 스트림에 avatar_state 통합

**파일:** `backend/controller/agent_controller.py` 수정

기존 execute/events SSE 스트림에 avatar_state 이벤트를 통합하여, 에이전트 실행 중 자동으로 표정 이벤트를 발생시킵니다.

```python
# 기존 SSE 이벤트 발행 로직에 추가
async def _emit_avatar_state_from_log(log_entry, session_id, app_state):
    """로그 엔트리에서 에이전트 상태를 분석하여 avatar_state 발행"""
    state_manager = app_state.avatar_state_manager
    model_manager = app_state.live2d_model_manager

    model = model_manager.get_agent_model(session_id)
    if not model:
        return

    emotion_extractor = EmotionExtractor(model.emotionMap)

    # 로그 레벨에 따른 감정 매핑
    level = log_entry.get("level", "")
    message = log_entry.get("message", "")

    if level == "RESPONSE":
        # LLM 응답에서 감정 추출 시도
        result = emotion_extractor.extract(message)
        if result.emotions:
            await state_manager.update_state(
                session_id=session_id,
                emotion=result.primary_emotion,
                expression_index=result.primary_index,
                trigger="agent_output"
            )
    elif level == "TOOL":
        await state_manager.update_state(
            session_id=session_id,
            emotion="surprise",
            expression_index=model.emotionMap.get("surprise", 0),
            trigger="state_change"
        )
    elif level == "GRAPH" and "error" in message.lower():
        await state_manager.update_state(
            session_id=session_id,
            emotion="fear",
            expression_index=model.emotionMap.get("fear", 0),
            trigger="state_change"
        )
```

#### 4.2.7 main.py Lifespan에 VTuber 서비스 초기화 추가

**파일:** `backend/main.py` 수정

```python
# Step 11: VTuber Service 초기화
from service.vtuber import Live2dModelManager, AvatarStateManager

live2d_model_manager = Live2dModelManager("static/live2d-models")
avatar_state_manager = AvatarStateManager()
app.state.live2d_model_manager = live2d_model_manager
app.state.avatar_state_manager = avatar_state_manager
logger.info(f"[Step 11] VTuber Service initialized ({len(live2d_model_manager.models)} models)")

# 라우터 등록
from controller.vtuber_controller import router as vtuber_router
app.include_router(vtuber_router)
```

### 4.3 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `backend/service/vtuber/__init__.py` | 신규 | VTuber 서비스 패키지 |
| `backend/service/vtuber/live2d_model_manager.py` | 신규 | 모델 관리자 |
| `backend/service/vtuber/emotion_extractor.py` | 신규 | 감정 추출기 |
| `backend/service/vtuber/avatar_state_manager.py` | 신규 | 상태 관리자 |
| `backend/controller/vtuber_controller.py` | 신규 | REST + SSE API |
| `backend/controller/agent_controller.py` | 수정 | avatar_state 통합 |
| `backend/main.py` | 수정 | 서비스 초기화 + 라우터 |

---

## 5. Phase 3: 프론트엔드 Live2D 렌더러

### 5.1 목표
Live2D 모델을 로딩/렌더링하고 표정/모션을 제어하는 프론트엔드 컴포넌트

### 5.2 작업 목록

#### 5.2.1 VTuber 상태 관리 (Zustand Store)

**파일:** `frontend/src/store/useVTuberStore.ts` (신규)

```typescript
import { create } from 'zustand';

export interface Live2dModelInfo {
  name: string;
  display_name: string;
  description: string;
  url: string;
  thumbnail: string;
  kScale: number;
  initialXshift: number;
  initialYshift: number;
  idleMotionGroupName: string;
  emotionMap: Record<string, number>;
  tapMotions: Record<string, Record<string, number>>;
}

export interface AvatarState {
  session_id: string;
  emotion: string;
  expression_index: number;
  motion_group: string;
  motion_index: number;
  intensity: number;
  transition_ms: number;
  trigger: string;
  timestamp: string;
}

interface VTuberStore {
  // 모델 관리
  availableModels: Live2dModelInfo[];
  agentModelMap: Record<string, string>;  // session_id → model_name

  // 아바타 상태
  avatarStates: Record<string, AvatarState>;  // session_id → state

  // 표시 설정
  activeAvatarSessionId: string | null;
  showVTuberPanel: boolean;
  panelSize: 'small' | 'medium' | 'large' | 'fullscreen';

  // Actions
  fetchModels: () => Promise<void>;
  assignModel: (sessionId: string, modelName: string) => Promise<void>;
  updateAvatarState: (sessionId: string, state: Partial<AvatarState>) => void;
  setActiveAvatar: (sessionId: string | null) => void;
  toggleVTuberPanel: () => void;
  setPanelSize: (size: 'small' | 'medium' | 'large' | 'fullscreen') => void;
  subscribeToAvatarEvents: (sessionId: string) => () => void;
}

export const useVTuberStore = create<VTuberStore>((set, get) => ({
  availableModels: [],
  agentModelMap: {},
  avatarStates: {},
  activeAvatarSessionId: null,
  showVTuberPanel: false,
  panelSize: 'medium',

  fetchModels: async () => {
    const res = await fetch(`${getBackendUrl()}/api/vtuber/models`);
    const data = await res.json();
    set({ availableModels: data.models });
  },

  assignModel: async (sessionId, modelName) => {
    await fetch(`${getBackendUrl()}/api/vtuber/agents/${sessionId}/model`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName })
    });
    set(state => ({
      agentModelMap: { ...state.agentModelMap, [sessionId]: modelName }
    }));
  },

  updateAvatarState: (sessionId, newState) => {
    set(state => ({
      avatarStates: {
        ...state.avatarStates,
        [sessionId]: {
          ...state.avatarStates[sessionId],
          ...newState,
          session_id: sessionId
        } as AvatarState
      }
    }));
  },

  setActiveAvatar: (sessionId) => {
    set({
      activeAvatarSessionId: sessionId,
      showVTuberPanel: sessionId !== null
    });
  },

  toggleVTuberPanel: () => {
    set(state => ({ showVTuberPanel: !state.showVTuberPanel }));
  },

  setPanelSize: (size) => {
    set({ panelSize: size });
  },

  subscribeToAvatarEvents: (sessionId) => {
    const url = `${getBackendUrl()}/api/vtuber/agents/${sessionId}/events`;
    const source = new EventSource(url);

    source.addEventListener('avatar_state', (e) => {
      const state = JSON.parse(e.data) as AvatarState;
      get().updateAvatarState(sessionId, state);
    });

    source.addEventListener('heartbeat', () => {});

    // cleanup 함수 반환
    return () => source.close();
  }
}));
```

#### 5.2.2 Live2D 렌더링 컴포넌트

**파일:** `frontend/src/components/live2d/Live2DCanvas.tsx` (신규)

```typescript
'use client';

import React, { useRef, useEffect, useCallback, useState } from 'react';
import { Live2dModelInfo, AvatarState } from '@/store/useVTuberStore';

// PixiJS + pixi-live2d-display 타입 (dynamic import)
type PixiApp = any;
type Live2DModel = any;

interface Live2DCanvasProps {
  modelInfo: Live2dModelInfo;
  avatarState: AvatarState;
  width?: number;
  height?: number;
  onHitAreaTap?: (hitArea: string) => void;
  className?: string;
}

export default function Live2DCanvas({
  modelInfo,
  avatarState,
  width = 800,
  height = 600,
  onHitAreaTap,
  className = ''
}: Live2DCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const appRef = useRef<PixiApp | null>(null);
  const modelRef = useRef<Live2DModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pixi.js + Live2D 초기화 (dynamic import)
  useEffect(() => {
    let mounted = true;

    async function initLive2D() {
      try {
        // Dynamic imports (SSR 방지)
        const PIXI = await import('pixi.js');
        const { Live2DModel: L2DModel } = await import('pixi-live2d-display');

        if (!mounted || !canvasRef.current) return;

        // Pixi Application 생성
        const app = new PIXI.Application({
          view: canvasRef.current,
          width,
          height,
          backgroundAlpha: 0,        // 투명 배경
          antialias: true,
          resolution: window.devicePixelRatio || 1,
          autoDensity: true
        });
        appRef.current = app;

        // Live2D 모델 로드
        const modelUrl = modelInfo.url;
        const model = await L2DModel.from(modelUrl);

        if (!mounted) {
          model.destroy();
          return;
        }

        modelRef.current = model;

        // 모델 위치/크기 설정
        model.scale.set(modelInfo.kScale);
        model.x = width / 2 + modelInfo.initialXshift;
        model.y = height;
        model.anchor.set(0.5, 1);

        // 유휴 모션 시작
        if (modelInfo.idleMotionGroupName) {
          model.internalModel.motionManager.startMotion(
            modelInfo.idleMotionGroupName,
            0
          );
        }

        // 눈 깜빡임 활성화
        model.internalModel.eyeBlink?.setEnable(true);

        // HitArea 클릭 이벤트
        model.on('hit', (hitAreas: string[]) => {
          if (onHitAreaTap && hitAreas.length > 0) {
            onHitAreaTap(hitAreas[0]);
          }
        });

        app.stage.addChild(model);
        setLoading(false);

      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load Live2D model');
          setLoading(false);
        }
      }
    }

    initLive2D();

    return () => {
      mounted = false;
      if (modelRef.current) {
        modelRef.current.destroy();
        modelRef.current = null;
      }
      if (appRef.current) {
        appRef.current.destroy(true);
        appRef.current = null;
      }
    };
  }, [modelInfo.url, width, height]);

  // 표정 상태 업데이트
  useEffect(() => {
    const model = modelRef.current;
    if (!model) return;

    const { expression_index, transition_ms } = avatarState;

    // 표정 적용
    try {
      const expressions = model.internalModel.settings.expressions;
      if (expressions && expressions[expression_index]) {
        model.expression(expression_index);
      }
    } catch (e) {
      // 표정 인덱스가 범위 밖일 때 무시
    }
  }, [avatarState.expression_index, avatarState.timestamp]);

  // 모션 상태 업데이트
  useEffect(() => {
    const model = modelRef.current;
    if (!model) return;

    const { motion_group, motion_index, trigger } = avatarState;

    if (trigger === 'user_interact' || trigger === 'state_change') {
      try {
        model.motion(motion_group, motion_index);
      } catch (e) {
        // 모션 그룹이 없을 때 무시
      }
    }
  }, [avatarState.motion_group, avatarState.motion_index, avatarState.timestamp]);

  return (
    <div className={`relative ${className}`}>
      <canvas
        ref={canvasRef}
        style={{ width, height }}
        className="pointer-events-auto"
      />

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/20 rounded-lg">
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-white/80">Loading Live2D...</span>
          </div>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-red-500/10 rounded-lg">
          <span className="text-sm text-red-400">{error}</span>
        </div>
      )}
    </div>
  );
}
```

#### 5.2.3 VTuber 패널 컴포넌트

**파일:** `frontend/src/components/live2d/VTuberPanel.tsx` (신규)

```typescript
'use client';

import React, { useEffect } from 'react';
import dynamic from 'next/dynamic';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useAppStore } from '@/store/useAppStore';
import { X, Maximize2, Minimize2, ChevronDown } from 'lucide-react';

// SSR 방지 - Live2D는 클라이언트에서만 렌더링
const Live2DCanvas = dynamic(() => import('./Live2DCanvas'), {
  ssr: false,
  loading: () => <div className="w-full h-full bg-gray-900/50 animate-pulse" />
});

const PANEL_SIZES = {
  small: { width: 300, height: 400 },
  medium: { width: 500, height: 600 },
  large: { width: 700, height: 800 },
  fullscreen: { width: 0, height: 0 }  // CSS로 처리
};

export default function VTuberPanel() {
  const {
    availableModels,
    avatarStates,
    activeAvatarSessionId,
    showVTuberPanel,
    panelSize,
    agentModelMap,
    setActiveAvatar,
    toggleVTuberPanel,
    setPanelSize,
    subscribeToAvatarEvents,
    fetchModels
  } = useVTuberStore();

  const sessions = useAppStore(s => s.sessions);

  // 모델 목록 로드
  useEffect(() => {
    fetchModels();
  }, []);

  // 활성 아바타 SSE 구독
  useEffect(() => {
    if (!activeAvatarSessionId) return;
    const unsub = subscribeToAvatarEvents(activeAvatarSessionId);
    return unsub;
  }, [activeAvatarSessionId]);

  if (!showVTuberPanel || !activeAvatarSessionId) return null;

  const modelName = agentModelMap[activeAvatarSessionId];
  const modelInfo = availableModels.find(m => m.name === modelName);
  const avatarState = avatarStates[activeAvatarSessionId];
  const session = sessions.find(s => s.session_id === activeAvatarSessionId);

  if (!modelInfo || !avatarState) return null;

  const size = PANEL_SIZES[panelSize];
  const isFullscreen = panelSize === 'fullscreen';

  const handleHitAreaTap = async (hitArea: string) => {
    await fetch(
      `${getBackendUrl()}/api/vtuber/agents/${activeAvatarSessionId}/interact`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hit_area: hitArea })
      }
    );
  };

  return (
    <div
      className={`
        ${isFullscreen ? 'fixed inset-0 z-50' : 'absolute bottom-4 right-4 z-40'}
        bg-gray-900/90 rounded-xl shadow-2xl border border-gray-700/50
        backdrop-blur-sm overflow-hidden
        transition-all duration-300
      `}
      style={isFullscreen ? {} : { width: size.width, height: size.height }}
    >
      {/* 헤더 바 */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800/80 border-b border-gray-700/50">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-sm font-medium text-white/90">
            {session?.name || 'VTuber'} — {modelInfo.display_name}
          </span>
        </div>

        <div className="flex items-center gap-1">
          {/* 감정 표시 */}
          <span className="text-xs px-2 py-0.5 rounded bg-blue-500/20 text-blue-300">
            {avatarState.emotion}
          </span>

          {/* 크기 조절 */}
          <button
            onClick={() => setPanelSize(isFullscreen ? 'medium' : 'fullscreen')}
            className="p-1 hover:bg-gray-700 rounded"
          >
            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          </button>

          {/* 닫기 */}
          <button
            onClick={toggleVTuberPanel}
            className="p-1 hover:bg-gray-700 rounded"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Live2D Canvas */}
      <Live2DCanvas
        modelInfo={modelInfo}
        avatarState={avatarState}
        width={isFullscreen ? window.innerWidth : size.width}
        height={isFullscreen ? window.innerHeight - 40 : size.height - 40}
        onHitAreaTap={handleHitAreaTap}
      />
    </div>
  );
}
```

#### 5.2.4 VTuber API 클라이언트

**파일:** `frontend/src/lib/api.ts` 수정 (추가)

```typescript
// 기존 api.ts에 vtuberApi 추가

export const vtuberApi = {
  listModels: () => apiCall<{ models: Live2dModelInfo[] }>(
    `${getBackendUrl()}/api/vtuber/models`
  ),

  getModel: (name: string) => apiCall<Live2dModelInfo>(
    `${getBackendUrl()}/api/vtuber/models/${name}`
  ),

  assignModel: (sessionId: string, modelName: string) => apiCall<{ status: string }>(
    `${getBackendUrl()}/api/vtuber/agents/${sessionId}/model`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_name: modelName })
    }
  ),

  getAgentModel: (sessionId: string) => apiCall<{ session_id: string; model: any }>(
    `${getBackendUrl()}/api/vtuber/agents/${sessionId}/model`
  ),

  getAvatarState: (sessionId: string) => apiCall<AvatarState>(
    `${getBackendUrl()}/api/vtuber/agents/${sessionId}/state`
  ),

  interactWithAvatar: (sessionId: string, hitArea: string) => apiCall<{ status: string }>(
    `${getBackendUrl()}/api/vtuber/agents/${sessionId}/interact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hit_area: hitArea })
    }
  ),

  overrideEmotion: (sessionId: string, emotion: string, intensity?: number) => apiCall<any>(
    `${getBackendUrl()}/api/vtuber/agents/${sessionId}/emotion`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ emotion, intensity: intensity ?? 1.0 })
    }
  ),

  subscribeToAvatarEvents: (
    sessionId: string,
    onState: (state: AvatarState) => void
  ): (() => void) => {
    const url = `${getBackendUrl()}/api/vtuber/agents/${sessionId}/events`;
    const source = new EventSource(url);

    source.addEventListener('avatar_state', (e: MessageEvent) => {
      onState(JSON.parse(e.data));
    });

    return () => source.close();
  }
};
```

#### 5.2.5 타입 정의 추가

**파일:** `frontend/src/types/index.ts` 수정 (추가)

```typescript
// VTuber 관련 타입 추가

export interface Live2dModelInfo {
  name: string;
  display_name: string;
  description: string;
  url: string;
  thumbnail: string;
  kScale: number;
  initialXshift: number;
  initialYshift: number;
  idleMotionGroupName: string;
  emotionMap: Record<string, number>;
  tapMotions: Record<string, Record<string, number>>;
}

export interface AvatarState {
  session_id: string;
  emotion: string;
  expression_index: number;
  motion_group: string;
  motion_index: number;
  intensity: number;
  transition_ms: number;
  trigger: string;
  timestamp: string;
}

export interface VTuberConfig {
  enabled: boolean;
  default_model: string;
  auto_assign: boolean;
  panel_position: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left';
  panel_size: 'small' | 'medium' | 'large';
}
```

### 5.3 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `frontend/src/store/useVTuberStore.ts` | 신규 | VTuber Zustand 스토어 |
| `frontend/src/components/live2d/Live2DCanvas.tsx` | 신규 | Live2D 렌더링 컴포넌트 |
| `frontend/src/components/live2d/VTuberPanel.tsx` | 신규 | VTuber 패널 UI |
| `frontend/src/lib/api.ts` | 수정 | vtuberApi 추가 |
| `frontend/src/types/index.ts` | 수정 | VTuber 타입 추가 |

---

## 6. Phase 4: LiveTab (세션 탭) 구현

### 6.1 목표
세션 선택 시 상단 세션 탭 바에 **Live** 버튼을 추가하여, 클릭 시 독립된 Live2D 렌더링 화면을 표시합니다.
**기존 PlaygroundTab(3D 도시)은 일절 수정하지 않으며, 완전히 새로운 독립 탭으로 구현합니다.**

> 세션 탭 바: `명령 | 그래프 | 스토리지 | 도구 | 로그 | 💠 Live`

### 6.2 작업 목록

#### 6.2.1 LiveTab 컴포넌트 (신규)

**파일:** `frontend/src/components/tabs/LiveTab.tsx` (신규)

세션 전용 Live2D 렌더링 탭입니다. 세션에 할당된 Live2D 모델을 전체 영역에 렌더링하고, 감정 상태 표시/모델 전환/감정 테스터를 포함합니다.

```typescript
'use client';

import React, { useEffect, useMemo } from 'react';
import dynamic from 'next/dynamic';
import { useVTuberStore } from '@/store/useVTuberStore';
import { useAppStore } from '@/store/useAppStore';
import { Sparkles, RefreshCw } from 'lucide-react';

const Live2DCanvas = dynamic(() => import('../live2d/Live2DCanvas'), {
  ssr: false,
  loading: () => <div className="w-full h-full bg-gray-900/50 animate-pulse" />
});

const EmotionTester = dynamic(() => import('../live2d/EmotionTester'), { ssr: false });

export default function LiveTab() {
  const selectedSessionId = useAppStore(s => s.selectedSessionId);
  const sessions = useAppStore(s => s.sessions);

  const {
    availableModels,
    agentModelMap,
    avatarStates,
    subscribeToAvatarEvents,
    fetchModels,
    assignModel
  } = useVTuberStore();

  const session = useMemo(
    () => sessions.find(s => s.session_id === selectedSessionId),
    [sessions, selectedSessionId]
  );

  const modelName = selectedSessionId ? agentModelMap[selectedSessionId] : null;
  const modelInfo = availableModels.find(m => m.name === modelName);
  const avatarState = selectedSessionId ? avatarStates[selectedSessionId] : null;

  // 모델 목록 로드
  useEffect(() => { fetchModels(); }, []);

  // SSE 구독
  useEffect(() => {
    if (!selectedSessionId) return;
    const unsub = subscribeToAvatarEvents(selectedSessionId);
    return unsub;
  }, [selectedSessionId]);

  // 모델이 할당되지 않은 상태 → 모델 선택 UI
  if (!modelInfo || !selectedSessionId) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-6 text-gray-400">
        <Sparkles size={48} className="text-purple-400" />
        <h2 className="text-lg font-semibold text-white">Live2D 아바타</h2>
        <p className="text-sm">이 세션에 Live2D 모델을 할당하세요</p>

        <div className="grid grid-cols-2 gap-4 mt-4">
          {availableModels.map(model => (
            <button
              key={model.name}
              onClick={() => assignModel(selectedSessionId, model.name)}
              className="flex flex-col items-center gap-2 p-4 rounded-xl
                         bg-gray-800 hover:bg-gray-700 border border-gray-700
                         hover:border-purple-500 transition-all"
            >
              {model.thumbnail && (
                <img src={model.thumbnail} alt={model.display_name}
                     className="w-24 h-24 object-cover rounded-lg" />
              )}
              <span className="text-sm font-medium text-white">{model.display_name}</span>
              <span className="text-xs text-gray-500">{model.description}</span>
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-gray-950">
      {/* 상단 상태 바 */}
      <div className="flex items-center justify-between px-4 py-2 bg-gray-900/80 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
          <span className="text-sm font-medium text-white/90">
            {session?.name || 'Session'} — {modelInfo.display_name}
          </span>
        </div>
        {avatarState && (
          <span className="text-xs px-2 py-0.5 rounded bg-purple-500/20 text-purple-300">
            {avatarState.emotion} (idx: {avatarState.expression_index})
          </span>
        )}
      </div>

      {/* Live2D 캔버스 (전체 영역) */}
      <div className="flex-1 relative">
        {avatarState && (
          <Live2DCanvas
            modelInfo={modelInfo}
            avatarState={avatarState}
            width={800}
            height={600}
            onHitAreaTap={async (hitArea) => {
              await fetch(
                `${getBackendUrl()}/api/vtuber/agents/${selectedSessionId}/interact`,
                {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ hit_area: hitArea })
                }
              );
            }}
            className="w-full h-full"
          />
        )}
      </div>

      {/* 하단 감정 테스터 (개발/디버깅용) */}
      {selectedSessionId && (
        <div className="border-t border-gray-800">
          <EmotionTester sessionId={selectedSessionId} />
        </div>
      )}
    </div>
  );
}
```

#### 6.2.2 세션 탭 바에 Live 탭 등록

**파일:** `frontend/src/components/TabNavigation.tsx` 수정

세션 선택 시 표시되는 **세션 전용 탭 목록**에 `Live` 탭을 추가합니다.

```typescript
// 세션 탭 목록에 추가 (기존 명령, 그래프, 스토리지, 도구, 로그 옆)
const SESSION_TABS = [
  { id: 'command', label: '명령', icon: <Terminal size={16} /> },
  { id: 'graph',   label: '그래프', icon: <GitBranch size={16} /> },
  { id: 'storage', label: '스토리지', icon: <Database size={16} /> },
  { id: 'tools',   label: '도구', icon: <Wrench size={16} /> },
  { id: 'logs',    label: '로그', icon: <FileText size={16} /> },
  // ⭐ 신규: Live2D 아바타 탭
  { id: 'live',    label: 'Live', icon: <Sparkles size={16} /> },
];
```

#### 6.2.3 세션 탭 라우팅에서 LiveTab 렌더링

세션 탭 콘텐츠 렌더링 로직에서 `live` 탭 선택 시 `LiveTab` 컴포넌트를 렌더링합니다.

```typescript
// 세션 탭 콘텐츠 렌더링
switch (activeSessionTab) {
  case 'command': return <CommandTab />;
  case 'graph':   return <GraphTab />;
  case 'storage': return <StorageTab />;
  case 'tools':   return <ToolTab />;
  case 'logs':    return <LogTab />;
  case 'live':    return <LiveTab />;  // ⭐ 신규
}
```

### 6.3 핵심 설계 원칙

1. **완전 독립**: PlaygroundTab(3D 도시)과 LiveTab(Live2D)은 서로 의존하지 않음
2. **기존 코드 무수정**: 3D 시스템(avatarSystem.ts, PlaygroundTab.tsx)에 변경 없음
3. **세션 스코프**: Live 탭은 세션 선택 시에만 표시되며, 선택된 세션의 아바타를 렌더링
4. **점진적 활성화**: 모델이 할당되지 않은 세션은 모델 선택 UI를 먼저 표시

### 6.4 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `frontend/src/components/tabs/LiveTab.tsx` | 신규 | Live2D 세션 탭 (독립) |
| `frontend/src/components/TabNavigation.tsx` | 수정 | 세션 탭에 Live 추가 |

---

## 7. Phase 5: ChatTab 통합

### 7.1 목표
채팅방에서 에이전트 메시지 옆에 미니 Live2D 아바타 표시

### 7.2 작업 목록

#### 7.2.1 미니 아바타 컴포넌트

**파일:** `frontend/src/components/live2d/MiniAvatar.tsx` (신규)

```typescript
'use client';

import React from 'react';
import dynamic from 'next/dynamic';
import { useVTuberStore } from '@/store/useVTuberStore';

const Live2DCanvas = dynamic(() => import('./Live2DCanvas'), { ssr: false });

interface MiniAvatarProps {
  sessionId: string;
  size?: number;       // 64, 96, 128
  className?: string;
}

export default function MiniAvatar({ sessionId, size = 96, className = '' }: MiniAvatarProps) {
  const { availableModels, agentModelMap, avatarStates } = useVTuberStore();

  const modelName = agentModelMap[sessionId];
  const modelInfo = availableModels.find(m => m.name === modelName);
  const avatarState = avatarStates[sessionId];

  if (!modelInfo || !avatarState) {
    return (
      <div
        className={`rounded-full bg-gray-700 ${className}`}
        style={{ width: size, height: size }}
      />
    );
  }

  return (
    <div
      className={`rounded-lg overflow-hidden ${className}`}
      style={{ width: size, height: size }}
    >
      <Live2DCanvas
        modelInfo={modelInfo}
        avatarState={avatarState}
        width={size}
        height={size}
      />
    </div>
  );
}
```

#### 7.2.2 ChatTab 메시지 아바타 통합

**파일:** `frontend/src/components/tabs/ChatTab.tsx` 수정

```typescript
// 에이전트 메시지 렌더링에 MiniAvatar 추가
function AgentMessage({ message }: { message: ChatRoomMessage }) {
  const modelAssigned = useVTuberStore(s => !!s.agentModelMap[message.session_id]);

  return (
    <div className="flex items-start gap-3">
      {/* 기존 아바타 또는 Live2D 미니 아바타 */}
      {modelAssigned ? (
        <MiniAvatar sessionId={message.session_id} size={48} />
      ) : (
        <div className="w-12 h-12 rounded-full bg-gray-600" /> /* 기존 */
      )}

      <div className="flex-1">
        <span className="font-medium">{message.role_name}</span>
        <p>{message.content}</p>
      </div>
    </div>
  );
}
```

### 7.3 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `frontend/src/components/live2d/MiniAvatar.tsx` | 신규 | 미니 아바타 |
| `frontend/src/components/tabs/ChatTab.tsx` | 수정 | 미니 아바타 통합 |

---

## 8. Phase 6: 설정 및 관리 UI

### 8.1 목표
VTuber 모델 관리, 에이전트-모델 할당, 설정 UI

### 8.2 작업 목록

#### 8.2.1 VTuber 설정 탭

**파일:** `frontend/src/components/tabs/VTuberTab.tsx` (신규)

**기능:**
1. 등록된 Live2D 모델 목록 (썸네일 + 정보)
2. 에이전트-모델 할당 UI (드래그 앤 드롭 or 선택)
3. Live2D 모델 미리보기 (전체 크기)
4. 감정 테스트 UI (감정 버튼 클릭 → 표정 변경 미리보기)
5. 모델 설정 편집 (emotionMap, kScale, 포지션 조정)

```typescript
export default function VTuberTab() {
  return (
    <div className="flex h-full">
      {/* 좌측: 모델 목록 + 에이전트 할당 */}
      <div className="w-1/3 border-r">
        <ModelList />
        <AgentModelAssignment />
      </div>

      {/* 우측: 미리보기 + 설정 */}
      <div className="flex-1">
        <ModelPreview />
        <EmotionTester />
      </div>
    </div>
  );
}
```

#### 8.2.2 메인 탭에 VTuber 관리 탭 추가

**파일:** `frontend/src/components/TabNavigation.tsx` 수정

```typescript
// 메인 탭 목록에 VTuber 관리탭 추가 (모델 관리/할당 설정용)
// 참고: 세션 탭의 'Live' 버튼은 Phase 4에서 이미 추가됨 (렌더링용)
{ id: 'vtuber', label: 'VTuber', icon: <Sparkles size={16} /> }
```

#### 8.2.3 감정 테스트 컴포넌트

**파일:** `frontend/src/components/live2d/EmotionTester.tsx` (신규)

```typescript
// 감정 버튼을 나열하고 클릭 시 Live2D 표정 변경
// 개발/디버깅에 매우 유용
export default function EmotionTester({ sessionId }: { sessionId: string }) {
  const emotions = ['neutral', 'joy', 'anger', 'sadness', 'surprise', 'fear', 'disgust', 'smirk'];

  return (
    <div className="flex flex-wrap gap-2 p-4">
      {emotions.map(emotion => (
        <button
          key={emotion}
          onClick={() => vtuberApi.overrideEmotion(sessionId, emotion)}
          className="px-3 py-1 rounded bg-gray-700 hover:bg-gray-600 text-sm"
        >
          {emotion}
        </button>
      ))}
    </div>
  );
}
```

### 8.3 산출물

| 파일 | 상태 | 설명 |
|------|------|------|
| `frontend/src/components/tabs/VTuberTab.tsx` | 신규 | VTuber 관리 탭 |
| `frontend/src/components/TabNavigation.tsx` | 수정 | 탭 추가 |
| `frontend/src/components/live2d/EmotionTester.tsx` | 신규 | 감정 테스터 |

---

## 9. Phase 7: 테스트 및 최적화

### 9.1 백엔드 테스트

#### 9.1.1 감정 추출 유닛 테스트

```python
# backend/tests/test_emotion_extractor.py
def test_extract_single_emotion():
    extractor = EmotionExtractor({"joy": 3, "neutral": 0})
    result = extractor.extract("[joy] Hello!")
    assert result.primary_emotion == "joy"
    assert result.primary_index == 3
    assert result.cleaned_text == "Hello!"

def test_extract_multiple_emotions():
    extractor = EmotionExtractor({"joy": 3, "surprise": 3, "neutral": 0})
    result = extractor.extract("[joy] Hi [surprise] there!")
    assert result.emotions == ["joy", "surprise"]
    assert result.expression_indices == [3, 3]

def test_no_emotions():
    extractor = EmotionExtractor({"joy": 3})
    result = extractor.extract("Just plain text")
    assert result.emotions == []
    assert result.primary_emotion == "neutral"
```

#### 9.1.2 API 통합 테스트

```python
# backend/tests/test_vtuber_api.py
async def test_list_models():
    response = await client.get("/api/vtuber/models")
    assert response.status_code == 200
    assert "models" in response.json()

async def test_assign_model():
    response = await client.put(
        "/api/vtuber/agents/test-session/model",
        json={"model_name": "mao_pro"}
    )
    assert response.status_code == 200

async def test_avatar_state_sse():
    # SSE 연결 테스트
    async with client.stream("GET", "/api/vtuber/agents/test-session/events") as response:
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                data = json.loads(line[5:])
                assert "session_id" in data
                break
```

### 9.2 프론트엔드 테스트

```typescript
// 수동 테스트 체크리스트
// □ Live2D 모델 로딩 (mao_pro)
// □ 표정 전환 (neutral → joy → anger → sadness)
// □ 유휴 모션 재생
// □ 눈 깜빡임 자동
// □ 물리 시뮬레이션 (마우스 이동 시)
// □ HitArea 클릭 반응
// □ SSE 이벤트 수신 → 표정 실시간 변경
// □ 패널 크기 조절 (small/medium/large/fullscreen)
// □ 3D Playground에서 클릭 → 패널 팝업
// □ ChatTab 미니 아바타 표시
// □ VTuber 탭에서 모델 관리
```

### 9.3 성능 최적화

| 최적화 항목 | 방법 | 예상 효과 |
|-----------|------|----------|
| 모델 캐싱 | IndexedDB에 .moc3, 텍스처 캐시 | 2회 로드부터 1초 이하 |
| 렌더링 최적화 | 비활성 아바타 requestAnimationFrame 중지 | GPU 50% 절약 |
| 텍스처 압축 | 4096→2048 또는 WebP 변환 | 메모리 75% 절약 |
| SSE 디바운싱 | 같은 감정 중복 이벤트 무시 | 네트워크 절약 |
| Lazy loading | VTuber 탭 진입 시에만 Pixi.js 로드 | 초기 번들 크기 절감 |

---

## 10. 파일 목록 및 변경 사항 총괄

### 10.1 신규 생성 파일

| # | 파일 경로 | 설명 | Phase |
|---|----------|------|-------|
| 1 | `backend/static/live2d-models/model_registry.json` | 모델 레지스트리 | 1 |
| 2 | `backend/static/live2d-models/mao_pro/` (복사) | 기본 Live2D 모델 | 1 |
| 3 | `frontend/public/lib/live2d/live2dcubismcore.min.js` | Cubism SDK 코어 | 1 |
| 4 | `backend/service/vtuber/__init__.py` | 서비스 패키지 | 2 |
| 5 | `backend/service/vtuber/live2d_model_manager.py` | 모델 관리자 | 2 |
| 6 | `backend/service/vtuber/emotion_extractor.py` | 감정 추출기 | 2 |
| 7 | `backend/service/vtuber/avatar_state_manager.py` | 상태 관리자 | 2 |
| 8 | `backend/controller/vtuber_controller.py` | VTuber API | 2 |
| 9 | `frontend/src/store/useVTuberStore.ts` | Zustand 스토어 | 3 |
| 10 | `frontend/src/components/live2d/Live2DCanvas.tsx` | 렌더링 컴포넌트 | 3 |
| 11 | `frontend/src/components/live2d/VTuberPanel.tsx` | VTuber 패널 UI (ChatTab용 등) | 3 |
| 11-1 | `frontend/src/components/tabs/LiveTab.tsx` | 세션 Live 탭 (독립 Live2D 렌더링) | 4 |
| 12 | `frontend/src/components/live2d/MiniAvatar.tsx` | 미니 아바타 | 5 |
| 13 | `frontend/src/components/tabs/VTuberTab.tsx` | VTuber 관리 탭 | 6 |
| 14 | `frontend/src/components/live2d/EmotionTester.tsx` | 감정 테스터 | 6 |
| 15 | `backend/tests/test_emotion_extractor.py` | 유닛 테스트 | 7 |
| 16 | `backend/tests/test_vtuber_api.py` | API 테스트 | 7 |

### 10.2 수정 파일

| # | 파일 경로 | 변경 내용 | Phase |
|---|----------|----------|-------|
| 1 | `backend/main.py` | 정적 파일 마운트 + VTuber 서비스 초기화 + 라우터 | 1, 2 |
| 2 | `nginx/nginx.conf` | `/static/live2d-models/` 라우팅 추가 | 1 |
| 3 | `frontend/package.json` | pixi.js, pixi-live2d-display 의존성 | 1 |
| 4 | `frontend/src/app/layout.tsx` | Cubism SDK 스크립트 로드 | 1 |
| 5 | `backend/controller/agent_controller.py` | avatar_state SSE 이벤트 통합 | 2 |
| 6 | `frontend/src/lib/api.ts` | vtuberApi 추가 | 3 |
| 7 | `frontend/src/types/index.ts` | VTuber 타입 추가 | 3 |
| 8 | `frontend/src/components/TabNavigation.tsx` | 세션 탭에 Live 추가 + 메인 탭에 VTuber 관리 | 4, 6 |
| 9 | `frontend/src/components/tabs/ChatTab.tsx` | MiniAvatar 통합 | 5 |
| ~~10~~ | ~~`frontend/src/components/TabNavigation.tsx`~~ | ~~(8번에 통합)~~ | — |

### 10.3 복사 파일 (Open-LLM-VTuber → Geny)

| # | 원본 | 대상 | 비고 |
|---|------|------|------|
| 1 | `Open-LLM-VTuber/live2d-models/mao_pro/` | `geny/backend/static/live2d-models/mao_pro/` | 전체 디렉토리 |
| 2 | `Open-LLM-VTuber/model_dict.json` | 참조하여 `model_registry.json` 작성 | 구조 변환 |

---

## 11. 의존성 및 라이선스

### 11.1 새로 추가되는 의존성

| 패키지 | 버전 | 라이선스 | 용도 |
|--------|------|---------|------|
| pixi.js | ^7.3.3 | MIT | 2D WebGL 렌더링 |
| pixi-live2d-display | ^0.4.0 | MIT | Live2D 모델 렌더링 래퍼 |
| @pixi/utils | ^7.3.3 | MIT | Pixi.js 유틸리티 |
| live2dcubismcore.min.js | 4.x | Live2D OSS License | Cubism SDK 코어 |

### 11.2 라이선스 주의사항

**Live2D Cubism SDK:**
- **개인/교육 목적**: 무료 (Live2D Open Software License)
- **상용 목적**: Live2D Cubism Editor 라이선스 필요
- **오픈소스 프로젝트**: Live2D OSS License 준수 시 사용 가능
- **Geny 적용**: OSS 프로젝트로 배포 시 라이선스 고지 필요

**Live2D 모델 (mao_pro):**
- 모델별 개별 라이선스 확인 필요
- 프로젝트 배포 시 모델 저작권 고지 필수

---

## 12. 리스크 및 대응 계획

### 12.1 기술적 리스크

| # | 리스크 | 발생 확률 | 영향도 | 대응 방안 |
|---|--------|---------|--------|----------|
| 1 | Cubism SDK + Next.js SSR 충돌 | 높음 | 중 | `dynamic import` + `ssr: false`로 해결 |
| 2 | Pixi.js + Three.js Canvas 충돌 | 중 | 중 | 별도 DOM 요소에 분리 렌더링 |
| 3 | 다중 Live2D 모델 성능 저하 | 중 | 고 | 포커스 모드 (1개만 렌더링) |
| 4 | model3.json 로딩 CORS 에러 | 높음 | 저 | nginx CORS 헤더 + 정적 파일 서빙 |
| 5 | 표정 전환 시 깜빡임/끊김 | 중 | 중 | transition_ms + 블렌딩 로직 |
| 6 | 모바일 성능 부족 | 높음 | 중 | 모바일에서 정적 이미지 fallback |

### 12.2 프로젝트 리스크

| # | 리스크 | 대응 방안 |
|---|--------|----------|
| 1 | Cubism SDK 라이선스 변경 | 대안: Live2D 대신 VRM/MMD 모델 지원 |
| 2 | pixi-live2d-display 유지보수 중단 | 대안: 직접 Cubism SDK 연동 |
| 3 | 모델 부족 (기본 1개) | 무료 Live2D 모델 수집 or 자체 제작 |

### 12.3 Phase별 실행 우선순위

```
Phase 1 (기반 인프라)     → 필수, 즉시 실행
Phase 2 (백엔드 감정 엔진)  → 필수, Phase 1 완료 후
Phase 3 (Live2D 렌더러)    → 필수, Phase 1 완료 후 (Phase 2와 병렬 가능)
Phase 4 (LiveTab 구현)     → 핵심, Phase 2+3 완료 후 (PlaygroundTab 무수정)
Phase 5 (Chat 통합)        → 선택, Phase 3 완료 후
Phase 6 (설정 UI)          → 선택, Phase 4 완료 후
Phase 7 (테스트/최적화)     → 필수, 전체 완료 후
```

```
Timeline:
────────────────────────────────────────────────────────────────────
Phase 1: ████████                    기반 인프라
Phase 2:         ████████████        백엔드 감정 엔진 (병렬 ↓)
Phase 3:         ████████████        Live2D 렌더러   (병렬 ↑)
Phase 4:                     ████████ LiveTab 구현 (독립)
Phase 5:                             ████████ Chat 통합
Phase 6:                                     ████████ 설정 UI
Phase 7:                                             ████████ 테스트
────────────────────────────────────────────────────────────────────
```

---

## 부록 A: 에이전트 감정 프롬프트 템플릿

에이전트가 감정 태그를 응답에 포함하도록 유도하는 시스템 프롬프트 템플릿:

```
[VTuber Expression Instructions]
당신의 응답에 감정 태그를 포함하세요.
사용 가능한 감정: {emo_keys}

규칙:
1. 문장 시작 또는 감정이 변하는 지점에 태그를 삽입하세요
2. 하나의 응답에 1~3개의 감정 태그를 사용하세요
3. 의미 없이 과도하게 사용하지 마세요

예시:
- "[joy] 안녕하세요! 만나서 반갑습니다!"
- "[neutral] 검색 결과를 알려드리겠습니다. [surprise] 흥미로운 결과가 나왔네요!"
- "[sadness] 죄송합니다, 해당 정보를 찾을 수 없습니다."
```

## 부록 B: Live2D 모델 추가 가이드

새 모델을 추가하는 절차:

```
1. Live2D 모델 파일 준비
   └── model_name/runtime/ 에 model3.json + 관련 파일

2. backend/static/live2d-models/ 에 모델 디렉토리 복사

3. model_registry.json에 모델 정보 추가
   {
     "name": "new_model",
     "display_name": "New Character",
     "url": "/static/live2d-models/new_model/runtime/new_model.model3.json",
     "emotionMap": { ... },
     ...
   }

4. 썸네일 이미지 생성 (선택)
   └── static/live2d-models/new_model/thumbnail.png

5. 서버 재시작 (model_registry.json 리로드)

6. 프론트엔드에서 모델 목록 새로고침
```

## 부록 C: 감정 매핑 커스터마이징

에이전트 실행 상태별 커스텀 감정 매핑 설정:

```json
{
  "state_emotion_overrides": {
    "developer": {
      "thinking": "neutral",
      "tool_calling": "smirk",
      "success": "joy",
      "error": "anger"
    },
    "researcher": {
      "thinking": "surprise",
      "tool_calling": "neutral",
      "success": "joy",
      "error": "sadness"
    }
  }
}
```

---

*End of Report*

> 이 문서는 Geny 프로젝트에 Open-LLM-VTuber의 Live2D 렌더링 기능을 이식하기 위한 완전한 세부 계획서입니다.
> 7개 Phase로 구분된 단계별 실행 계획과 16개 신규 파일, 10개 수정 파일의 구체적인 코드 구조를 포함합니다.
