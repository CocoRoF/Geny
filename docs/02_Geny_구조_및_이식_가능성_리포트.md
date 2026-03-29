# Geny 프로젝트 구조 및 VTuber 이식 가능성 분석 리포트

> 분석 일자: 2026-03-29
> 대상: Geny 프로젝트 (멀티 에이전트 자율 시스템)
> 목적: Open-LLM-VTuber Live2D 렌더링 기능 이식을 위한 구조 분석 및 가능성 평가
> 범위: 백엔드/프론트엔드 전체 아키텍처, 통신 메커니즘, 통합 지점 식별

---

## 1. Geny 프로젝트 개요

### 1.1 프로젝트 정체성

Geny는 **멀티 에이전트 자율 시스템**으로, 다수의 AI 에이전트(Claude Code 세션)를 병렬로 관리하며 실시간 모니터링과 협업을 가능하게 합니다.

**핵심 기능:**
- 에이전트 세션 생성/관리/모니터링
- 채팅방 기반 멀티 에이전트 브로드캐스트
- LangGraph 기반 워크플로우 실행 엔진
- 3D 도시 시각화 (에이전트 = 도시 시민)
- 벡터 검색 기반 메모리 시스템
- MCP(Model Context Protocol) 도구 통합

### 1.2 기술 스택

| 계층 | 기술 | 버전 |
|------|------|------|
| 백엔드 프레임워크 | FastAPI | ≥0.115 |
| AI 오케스트레이션 | LangGraph + LangChain | ≥1.0 |
| 데이터베이스 | PostgreSQL | 16-alpine |
| 벡터 검색 | FAISS | ≥1.9 |
| 프론트엔드 프레임워크 | Next.js | 16.1.6 |
| 3D 렌더링 | Three.js + React Three Fiber | 0.183 / 9.5 |
| 상태 관리 | Zustand | 5.0.11 |
| 스타일링 | TailwindCSS | 4.0 |
| 워크플로우 UI | @xyflow/react | 12.10 |
| 컨테이너 | Docker Compose | - |

---

## 2. 백엔드 아키텍처 상세

### 2.1 애플리케이션 초기화 (Lifespan)

```python
# main.py - 10단계 초기화 시퀀스
async with lifespan(app):
    Step 1:  Database Init         (PostgreSQL + 마이그레이션)
    Step 2:  Config Manager        (DB + JSON 듀얼 스토리지)
    Step 3:  Session & Chat Store  (세션/채팅 영속성)
    Step 4:  Session Logging       (구조화된 로그)
    Step 5:  Tool Loader           (빌트인 + 커스텀 Python)
    Step 6:  MCP Loader            (외부 MCP 서버)
    Step 7:  Tool Presets          (도구 프리셋 템플릿)
    Step 8:  Workflow Engine       (노드 등록)
    Step 9:  Shared Folder Manager (공유 폴더)
    Step 10: Session Idle Monitor  (유휴 세션 감시)
```

### 2.2 API 엔드포인트 구조

```
/api/
├── agents/                           # 에이전트 세션 관리
│   ├── GET    /                      # 세션 목록
│   ├── POST   /                      # 세션 생성
│   ├── GET    /{id}                  # 세션 상세
│   ├── DELETE /{id}                  # 소프트 삭제
│   ├── POST   /{id}/execute          # 단일 실행
│   ├── POST   /{id}/execute/start    # 실행 시작 (SSE 스트리밍)
│   ├── GET    /{id}/execute/events   # SSE 이벤트 스트림 ⭐
│   ├── GET    /{id}/state            # LangGraph 상태
│   ├── GET    /{id}/graph            # 그래프 구조
│   └── memory/                       # 메모리 관리
│       ├── GET    /                  # 메모리 엔트리
│       ├── POST   /search            # 벡터 검색
│       └── GET    /graph             # 메모리 관계 그래프
├── chat/                             # 채팅 & 메시징
│   ├── rooms/                        # 채팅방 CRUD
│   │   ├── GET/POST /
│   │   ├── GET/PUT/DELETE /{id}
│   │   ├── POST /{id}/broadcast      # 브로드캐스트 ⭐
│   │   ├── GET  /{id}/events         # 방 SSE 이벤트 ⭐
│   │   └── GET  /{id}/subscribe      # 구독 (재연결 지원)
│   ├── direct/{session_id}           # DM 전송
│   └── inbox/{session_id}            # 수신함
├── workflows/                        # 워크플로우 관리
├── tools/                            # 도구 카탈로그
├── tool-presets/                     # 도구 프리셋
├── config/                           # 설정 관리
├── internal/tools/execute            # 도구 직접 실행
└── /health                           # 헬스체크
```

### 2.3 서비스 레이어

```
service/
├── langgraph/
│   └── agent_session.py              # LangGraph 기반 에이전트 세션
│       ├── ClaudeProcess             # CLI 서브프로세스
│       ├── ClaudeCLIChatModel        # LangChain 어댑터
│       ├── CompiledStateGraph        # LangGraph 워크플로우
│       │   ├─ memory_inject
│       │   ├─ relevance_gate
│       │   ├─ adaptive_classify
│       │   ├─ guard_direct
│       │   ├─ direct_answer
│       │   └─ post_model
│       └── SessionMemoryManager      # LTM + STM + 벡터
│
├── chat/
│   └── conversation_store.py         # 채팅방 + 메시지 저장소
│
├── workflow/
│   └── workflow_executor.py          # 20가지 노드 타입 워크플로우 엔진
│
└── logging/
    └── session_logger.py             # 3계층 로깅 (DB + 파일 + 메모리)
```

### 2.4 통신 메커니즘: SSE (Server-Sent Events)

Geny는 **WebSocket이 아닌 SSE**를 실시간 통신에 사용합니다:

```
┌── SSE 패턴 1: 명령 실행 스트리밍 ──────────────────┐
│                                                      │
│  POST /execute/start → { status: "started" }        │
│  GET  /execute/events → EventSource                 │
│       event: log       { timestamp, level, message } │
│       event: status    { state, progress }           │
│       event: result    { success, output, cost_usd } │
│       event: heartbeat { timestamp }                 │
│       event: done      (연결 종료)                   │
│                                                      │
│  폴링 간격: 150ms                                    │
│  재연결: 최대 20회, 3초 간격                         │
└──────────────────────────────────────────────────────┘

┌── SSE 패턴 2: 채팅방 구독 ─────────────────────────┐
│                                                      │
│  GET /rooms/{id}/events → EventSource               │
│       event: message         (새 메시지)             │
│       event: broadcast_status (진행 상태)            │
│       event: agent_progress  (에이전트 실행 상황)    │
│       event: broadcast_done  (브로드캐스트 완료)     │
│                                                      │
│  커서 기반 페이지네이션 (lastMessageId)              │
│  자동 재연결 지원                                    │
└──────────────────────────────────────────────────────┘
```

### 2.5 Nginx 구성

```nginx
# SSE 최적화 설정
proxy_buffering    off;      # SSE 버퍼링 비활성화
proxy_cache        off;      # 캐싱 비활성화
proxy_read_timeout 86400s;   # 24시간 타임아웃
gzip               off;      # 압축 비활성화 (SSE 호환)
chunked_transfer_encoding on; # 청크 인코딩 활성화

# 라우팅
/api/*          → FastAPI 백엔드 (8000)
/health         → 백엔드 헬스체크
/static/assets/* → 백엔드 정적 파일
/               → Next.js 프론트엔드 (3000)
```

---

## 3. 프론트엔드 아키텍처 상세

### 3.1 디렉토리 구조

```
frontend/src/
├── app/                        # Next.js App Router
│   ├── page.tsx               # 메인 대시보드
│   ├── layout.tsx             # 루트 레이아웃
│   ├── messenger/             # 채팅 페이지
│   └── wiki/                  # 문서 페이지
│
├── components/
│   ├── Sidebar.tsx            # 세션 목록 + 네비게이션
│   ├── Header.tsx             # 상단 바
│   ├── tabs/                  # 13개 탭 UI
│   │   ├── MainTab.tsx        # 대시보드 개요
│   │   ├── CommandTab.tsx     # 명령 실행 (SSE 스트리밍) ⭐
│   │   ├── PlaygroundTab.tsx  # 3D 도시 시각화 ⭐⭐⭐
│   │   ├── ChatTab.tsx        # 채팅방 관리 ⭐
│   │   ├── LogsTab.tsx        # 로그 뷰어
│   │   ├── MemoryTab.tsx      # 메모리 브라우저
│   │   ├── WorkflowTab.tsx    # 워크플로우 에디터
│   │   ├── GraphTab.tsx       # 그래프 시각화
│   │   └── SettingsTab.tsx    # 설정 UI
│   ├── messenger/             # 채팅 컴포넌트
│   └── graphEditor/           # 워크플로우 그래프 에디터
│
├── lib/                       # 유틸리티
│   ├── api.ts                # REST + SSE API 클라이언트 ⭐
│   ├── avatarSystem.ts       # 아바타 애니메이션 시스템 ⭐⭐
│   ├── assetLoader.ts        # 3D 모델 로더 ⭐
│   ├── cityLayout.ts         # 도시 그리드 레이아웃
│   └── i18n/                 # 국제화
│
├── store/                     # Zustand 상태 관리
│   ├── useAppStore.ts        # 글로벌 앱 상태
│   ├── useMessengerStore.ts  # 채팅 상태
│   └── useWorkflowStore.ts   # 워크플로우 상태
│
└── types/
    ├── index.ts              # 전체 타입 정의
    └── workflow.ts           # 워크플로우 타입
```

### 3.2 현재 3D 시각화 시스템 (PlaygroundTab)

**현재 구현:**

```typescript
// PlaygroundTab.tsx - 3D 도시 렌더링
<Canvas>
  <CameraController />          // 마우스/터치 카메라 제어
  <ambientLight />              // 환경 조명
  <directionalLight castShadow /> // 그림자 포함 주 조명

  {/* 도시 레이아웃 */}
  <Roads />                     // 도로 GLB 모델
  <Buildings />                 // 건물 GLB 모델
  <Nature />                    // 나무, 풀, 바위
  <Platform />                  // 지면

  {/* 에이전트 아바타 */}
  <AvatarSystem>
    {sessions.map(s => <Avatar3D key={s.id} session={s} />)}
  </AvatarSystem>
</Canvas>
```

### 3.3 현재 아바타 시스템 (avatarSystem.ts)

```
AvatarSystem
├── Pathfinder (A* 알고리즘)
│   └── 8방향 이동, 대각선 비용 √2
│
├── 캐릭터 모델
│   └── 12개 Kenney 미니 캐릭터 (GLB)
│       ├── character-female-a ~ f
│       └── character-male-a ~ f
│
├── 뼈대 애니메이션 (Bone Animation)
│   ├── torso: 미세한 상하 운동 (0.03~0.1 rad)
│   ├── head: 좌우/상하 시선 이동 (0.04~0.15 rad)
│   ├── arms: 팔 흔들기 (0.08~0.9 rad)
│   └── legs: 걷기 동작 (0.02~0.8 rad)
│
├── 애니메이션 상태
│   ├── idle: 미세 움직임 (2.0 rad/s)
│   ├── walk: 걷기 (6.0 rad/s)
│   ├── run: 달리기 (12.0 rad/s)
│   └── thinking: 생각 중 (3.0 rad/s)
│
└── 방랑 AI
    ├── 랜덤 목적지 (최대 6유닛)
    ├── 유휴 타이머 (3~10초)
    └── A* 경로 탐색
```

### 3.4 SSE API 클라이언트 (api.ts)

```typescript
// 명령 실행 SSE 스트리밍
agentApi.executeStream(sessionId, request, (eventType, eventData) => {
  switch(eventType) {
    case 'log':    handleLogEntry(eventData);     // 실행 로그
    case 'status': handleStatus(eventData);       // 상태 변경
    case 'result': handleResult(eventData);       // 실행 결과
    case 'done':   cleanup();                     // 완료
  }
});

// 채팅방 구독
chatApi.subscribeToRoom(roomId, lastMsgId, (type, data) => {
  // message, broadcast_status, agent_progress, broadcast_done
});
```

### 3.5 상태 관리 (Zustand)

```typescript
// useAppStore.ts - 글로벌 상태
{
  sessions: SessionInfo[],              // 모든 에이전트 세션
  selectedSessionId: string | null,     // 선택된 세션
  activeTab: string,                    // 현재 탭
  sessionDataCache: {                   // 세션별 캐시
    [id]: { input, output, status, logEntries }
  },
  healthStatus: 'connecting' | 'connected' | 'disconnected'
}

// useMessengerStore.ts - 채팅 상태
{
  rooms: ChatRoom[],
  activeRoomId: string | null,
  messages: ChatRoomMessage[],
  broadcastStatus: BroadcastStatus | null,
  agentProgress: AgentProgressState[] | null   // 에이전트별 진행상황
}
```

---

## 4. 현재 에이전트 아바타 표현 분석

### 4.1 현재 상태

| 기능 | 현재 상태 | Live2D 이식 후 |
|------|----------|---------------|
| 캐릭터 렌더링 | 3D GLB 미니 캐릭터 | 2D Live2D 모델 |
| 표정 | ❌ 없음 | ✅ 8+ 표정 |
| 감정 표현 | ❌ 없음 | ✅ emotionMap 기반 |
| 유휴 애니메이션 | ✅ 뼈대 기반 sine wave | ✅ Live2D Idle 모션 |
| 걷기 | ✅ A* + 뼈대 애니메이션 | ⚠️ 대체 방안 필요 |
| 눈 깜빡임 | ❌ 없음 | ✅ 자동 |
| 물리 효과 | ❌ 없음 | ✅ 머리카락/의상 |
| 립싱크 | ❌ 없음 | ⚠️ 음성 제외 시 텍스트 동기화 |
| 터치 반응 | ❌ 없음 | ✅ HitArea 인터랙션 |

### 4.2 에이전트 상태와 표정의 연결 가능성

현재 Geny의 에이전트 상태 전이:

```
에이전트 생성 → idle
    ↓
명령 실행 시작 → thinking/executing
    ↓
도구 호출 → tool_using (도구명 표시)
    ↓
결과 반환 → completed/failed
    ↓
유휴 상태 → idle (방랑 시작)
```

**Live2D 표정 매핑 가능성:**

| 에이전트 상태 | 현재 표현 | Live2D 매핑 |
|-------------|----------|-------------|
| idle | 미세 움직임 | neutral + Idle 모션 |
| thinking | 생각 모션 | 생각 표정 + 시선 이동 |
| executing | 걷기/달리기 | 집중 표정 |
| tool_using | - | 호기심/집중 표정 |
| success | - | joy/smirk 표정 |
| error | - | fear/sadness 표정 |
| speaking (새로) | - | 말하기 모션 + 립싱크 |

---

## 5. 이식 가능성 평가

### 5.1 통신 아키텍처 호환성

```
┌── Open-LLM-VTuber ──┐        ┌── Geny ─────────────┐
│                      │        │                      │
│  WebSocket 기반      │   →    │  SSE 기반            │
│  양방향 실시간       │        │  단방향 서버→클라이언트│
│  /client-ws          │        │  /execute/events     │
│                      │        │  /rooms/{id}/events   │
└──────────────────────┘        └──────────────────────┘
```

**평가:**
- ✅ **SSE로 충분**: Live2D 표정 제어는 서버→클라이언트 단방향이므로 SSE 적합
- ✅ **이벤트 타입 확장 용이**: 기존 SSE 이벤트에 `avatar_state` 타입 추가 가능
- ✅ **기존 인프라 재사용**: Nginx SSE 설정, 프론트엔드 EventSource 클라이언트 재사용
- ⚠️ **사용자 인터랙션**: 클릭/터치는 REST API로 처리 가능 (POST /avatar/interact)

### 5.2 프론트엔드 렌더링 호환성

```
┌── Open-LLM-VTuber ──┐        ┌── Geny ─────────────┐
│                      │        │                      │
│  Pixi.js (2D)       │   →    │  Three.js (3D)       │
│  Cubism SDK          │        │  React Three Fiber   │
│  Canvas 2D           │        │  WebGL Canvas 3D     │
│                      │        │                      │
│  단일 캐릭터         │        │  다중 캐릭터 (도시)  │
│  전체 화면           │        │  미니 캐릭터 + 환경  │
└──────────────────────┘        └──────────────────────┘
```

**평가:**
- ⚠️ **렌더링 엔진 차이**: Pixi.js(2D) vs Three.js(3D) - 공존 가능
- ✅ **독립 Canvas 가능**: Live2D를 별도 Canvas로 렌더링하고 3D 씬과 분리/통합
- ✅ **pixi-live2d-display**: Three.js 위에 Pixi.js 오버레이 또는 별도 패널
- ⭐ **하이브리드 접근**: 3D 도시에서 아바타 클릭 시 Live2D 패널 팝업

### 5.3 상태 관리 호환성

```
┌── Open-LLM-VTuber ──┐        ┌── Geny ─────────────┐
│                      │        │                      │
│  per-client context  │   →    │  Zustand store       │
│  WebSocket state     │        │  useAppStore         │
│  서버 주도           │        │  useMessengerStore   │
└──────────────────────┘        └──────────────────────┘
```

**평가:**
- ✅ **Zustand 확장 용이**: `useVTuberStore` 추가로 Live2D 상태 관리
- ✅ **세션별 상태 분리**: 기존 `sessionDataCache` 패턴 활용
- ✅ **SSE 이벤트 핸들러**: 기존 패턴으로 avatar_state 이벤트 처리

### 5.4 백엔드 서비스 호환성

```
┌── Open-LLM-VTuber ──┐        ┌── Geny ─────────────┐
│                      │        │                      │
│  Live2dModel 클래스  │   →    │  Tool 시스템         │
│  감정 추출 파이프라인│        │  LangGraph 노드      │
│  ServiceContext      │        │  Agent Session       │
│  캐릭터 YAML 파일    │        │  Config Manager      │
└──────────────────────┘        └──────────────────────┘
```

**평가:**
- ✅ **Tool 시스템으로 통합**: 감정 추출을 빌트인 도구로 구현
- ✅ **LangGraph 노드 추가**: `emit_avatar_state` 노드로 표정 이벤트 발생
- ✅ **Config Manager 확장**: 캐릭터/모델 설정을 기존 config 시스템에 통합
- ✅ **세션 로거 활용**: 표정 변경 이벤트를 기존 로깅 시스템에 기록

---

## 6. 핵심 통합 지점 식별

### 6.1 백엔드 통합 지점

| # | 통합 지점 | 위치 | 방법 |
|---|----------|------|------|
| 1 | **모델 관리 API** | `controller/` 신규 | 모델 목록/정보/업로드 REST 엔드포인트 |
| 2 | **표정 이벤트** | `session_logger.py` | 새 로그 레벨 `AVATAR` 추가 |
| 3 | **감정 추출 노드** | `service/workflow/nodes/` | LangGraph 노드로 감정 추출 |
| 4 | **캐릭터 설정** | `config_controller.py` | 기존 config 시스템에 VTuber 설정 추가 |
| 5 | **모델 파일 서빙** | `main.py` + nginx | 정적 파일 마운트 + 프록시 |
| 6 | **SSE 이벤트 확장** | `agent_controller.py` | avatar_state 이벤트 타입 추가 |

### 6.2 프론트엔드 통합 지점

| # | 통합 지점 | 위치 | 방법 |
|---|----------|------|------|
| 1 | **Live2D 컴포넌트** | `components/live2d/` 신규 | Pixi.js + Cubism SDK |
| 2 | **VTuber 스토어** | `store/useVTuberStore.ts` | 모델/표정 상태 관리 |
| 3 | **Playground 통합** | `tabs/PlaygroundTab.tsx` | 아바타 클릭 → Live2D 패널 |
| 4 | **Chat 통합** | `tabs/ChatTab.tsx` | 메시지 옆 Live2D 미니 아바타 |
| 5 | **SSE 리스너** | `lib/api.ts` | avatar_state 이벤트 핸들러 |
| 6 | **모델 API** | `lib/api.ts` | 모델 관리 API 클라이언트 |
| 7 | **타입 정의** | `types/index.ts` | VTuber 관련 타입 추가 |

### 6.3 인프라 통합 지점

| # | 통합 지점 | 위치 | 방법 |
|---|----------|------|------|
| 1 | **정적 파일** | `nginx.conf` | `/live2d-models/` 라우트 추가 |
| 2 | **Docker** | `docker-compose.yml` | 볼륨 마운트 (모델 파일) |
| 3 | **패키지** | `package.json` | pixi.js, pixi-live2d-display 추가 |

---

## 7. 기술적 도전과 해결 방안

### 7.1 도전 1: 2D Live2D + 3D Three.js 공존

**문제:** Live2D는 2D(Pixi.js), Geny는 3D(Three.js) → 같은 씬에 둘 수 없음

**해결 방안:**

```
방안 A: 분리 레이어 (⭐ 권장)
┌─────────────────────────────┐
│  3D 도시 씬 (Three.js)     │ ← 배경
├─────────────────────────────┤
│  Live2D 오버레이 (Pixi.js) │ ← 전경 (패널/팝업)
└─────────────────────────────┘

방안 B: 독립 뷰
┌──────────────┬──────────────┐
│  3D 도시     │  Live2D      │
│  (좌측)      │  (우측)      │
└──────────────┴──────────────┘

방안 C: 탭 전환
[Playground 3D] [VTuber 2D] ← 별도 탭
```

### 7.2 도전 2: 다중 에이전트 × 다중 Live2D

**문제:** 에이전트가 여러 개일 때 각각 Live2D 모델을 갖는 게 성능에 부담

**해결 방안:**
- **포커스 모드**: 선택된 에이전트 1개만 Live2D 렌더링
- **미니 아바타**: 채팅방에서 작은 Live2D (512×512)
- **LOD(Level of Detail)**: 활성 = Live2D, 비활성 = 정적 이미지

### 7.3 도전 3: SSE vs WebSocket (립싱크 없이)

**문제:** 음성 제외 시 실시간 립싱크 불필요, 하지만 표정 변경은 실시간 필요

**해결 방안:**
- SSE의 `agent_progress` 이벤트에 `emotion` 필드 추가
- 에이전트 실행 중 상태 변화 시 즉시 SSE 이벤트 발생
- 150ms 폴링으로 충분한 반응 속도 확보 (사람 눈은 ~100ms 변화 감지)

### 7.4 도전 4: Cubism SDK 라이선스

**문제:** Live2D Cubism SDK는 상용 라이선스 필요 (특정 조건)

**해결 방안:**
- 개인/교육 목적: 무료 사용 가능
- 오픈소스: `pixi-live2d-display` (MIT 라이선스) 활용
- Cubism Web Framework: Live2D 공식 SDK (자체 라이선스)

---

## 8. 성능 및 확장성 평가

### 8.1 프론트엔드 성능 영향

| 항목 | 현재 | Live2D 추가 후 | 영향 |
|------|------|---------------|------|
| Canvas 수 | 1 (Three.js) | 2 (Three.js + Pixi.js) | 低 |
| GPU 부하 | 중 (3D 씬) | 중~고 (3D + 2D) | 중 |
| 메모리 | ~150MB | +50~100MB (모델) | 중 |
| FPS | 60 | 55~60 | 低 |
| 네트워크 | SSE 스트림 | +표정 이벤트 (~1KB/EA) | 低 |

### 8.2 백엔드 성능 영향

| 항목 | 현재 | Live2D 추가 후 | 영향 |
|------|------|---------------|------|
| API 엔드포인트 | ~40 | +5~10 | 低 |
| SSE 이벤트 | 로그/상태 | +avatar_state | 低 |
| 정적 파일 | 3D GLB | +Live2D 모델 (~5MB/개) | 低 |
| 처리 부하 | LLM + 도구 | +감정 추출 (경량) | 低 |

### 8.3 데이터 사이즈 예상

| 리소스 | 크기 | 개수 | 총 크기 |
|--------|------|------|---------|
| Live2D 모델 (.moc3) | ~2MB | 5개 | ~10MB |
| 텍스처 (.png) | ~2MB | 5개 | ~10MB |
| 표정 (.exp3.json) | ~1KB | 40개 (8×5) | ~40KB |
| 모션 (.motion3.json) | ~5KB | 25개 (5×5) | ~125KB |
| **합계** | | | **~20MB** |

---

## 9. 이식 가능성 종합 평가

### 9.1 평가 매트릭스

| 평가 항목 | 점수 (5점) | 비고 |
|----------|-----------|------|
| 아키텍처 호환성 | ⭐⭐⭐⭐ | SSE로 충분, 구조적 유사성 높음 |
| 프론트엔드 통합 | ⭐⭐⭐⭐ | 별도 Canvas 분리로 깔끔한 통합 |
| 백엔드 통합 | ⭐⭐⭐⭐⭐ | Tool/LangGraph 시스템에 자연스러운 통합 |
| 성능 영향 | ⭐⭐⭐⭐ | 경량 추가, 기존 성능 거의 영향 없음 |
| 구현 복잡도 | ⭐⭐⭐ | Cubism SDK 학습 곡선, 2D+3D 공존 처리 |
| 유지보수성 | ⭐⭐⭐⭐ | 모듈화된 컴포넌트 설계 가능 |
| 확장 가능성 | ⭐⭐⭐⭐⭐ | 음성/립싱크/멀티모달 확장 용이 |

### 9.2 최종 평가

**이식 가능성: 매우 높음 (95%)**

**근거:**
1. Geny의 SSE 기반 실시간 통신이 Live2D 표정 제어에 적합
2. LangGraph 노드 시스템이 감정 추출 파이프라인에 자연스럽게 통합
3. 프론트엔드의 컴포넌트 기반 구조가 Live2D 모듈 추가에 용이
4. 기존 3D 시스템과 2D Live2D의 분리 설계가 가능
5. 음성 제외로 가장 복잡한 립싱크 문제가 제거됨

**주요 리스크:**
- Cubism SDK 라이선스 확인 필요
- 다중 Live2D 모델 동시 렌더링 시 성능 테스트 필요
- 2D+3D 혼합 UX 설계 검증 필요

---

*End of Report*
