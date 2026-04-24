# Geny 이중 에이전트 아키텍처 계획서

> **작성일**: 2026-03-30
> **목표**: Geny를 VTuber Agent(외부 소통) + Sub-Worker(작업 수행)의 이중 구조로 고도화
> **상태**: 설계 단계

---

## 목차

1. [현재 시스템 분석](#1-현재-시스템-분석)
2. [목표 아키텍처](#2-목표-아키텍처)
3. [현재 구조와의 Gap 분석](#3-현재-구조와의-gap-분석)
4. [구현 가능성 검토](#4-구현-가능성-검토)
5. [세부 구현 계획](#5-세부-구현-계획)
6. [Phase별 실행 로드맵](#6-phase별-실행-로드맵)
7. [리스크 및 완화 전략](#7-리스크-및-완화-전략)

---

## 1. 현재 시스템 분석

### 1.1 세션 아키텍처 (현재)

현재 Geny의 **모든 세션은 동일한 AgentSession**으로 생성되며, 세션 간 구조적 차이가 없다.

```
┌─────────────────────────────────────────────┐
│              AgentSession (동일 타입)          │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Session A │  │ Session B │  │ Session C │  │
│  │ (Worker)  │  │(Developer)│  │(Researcher)│ │
│  └──────────┘  └──────────┘  └──────────┘  │
│         │            │             │         │
│         ▼            ▼             ▼         │
│    ┌──────────────────────────────────┐     │
│    │    동일한 execute_command() 경로    │     │
│    │    동일한 Workflow Graph 실행       │     │
│    │    동일한 Tool 접근 권한            │     │
│    └──────────────────────────────────┘     │
└─────────────────────────────────────────────┘
```

**핵심 파일 위치**:
- 세션 생성: `backend/service/executor/agent_session_manager.py` → `create_agent_session()` (L270+)
- 세션 모델: `backend/service/claude_manager/models.py` → `CreateSessionRequest` (L185+)
- 세션 실행: `backend/service/execution/agent_executor.py` → `execute_command()` (L317-371)
- 그래프 실행: `backend/service/executor/agent_session.py` → `invoke()` / `astream()`
- 세션 저장소: `backend/service/claude_manager/session_store.py` → PostgreSQL `sessions` 테이블

### 1.2 실행 흐름 (현재)

```
사용자 입력
    │
    ├─── [Command 탭] POST /api/agents/{id}/execute
    │         │
    ├─── [Chat 탭] POST /api/chat/rooms/{id}/broadcast
    │         │        (is_chat_message=True)
    │         │
    └─── [DM Tool] _trigger_dm_response()
              │
              ▼
     execute_command()  ← 모든 경로가 여기로 수렴
              │
              ▼
     agent.invoke(input_text, **invoke_kwargs)
              │
              ▼
     ┌── CompiledStateGraph ──┐
     │                         │
     │  memory_inject          │
     │  → relevance_gate       │
     │  → classify_difficulty  │
     │  → [EASY/MEDIUM/HARD]   │
     │  → ... 30개 노드 ...     │
     │  → final_answer         │
     │                         │
     └─────────────────────────┘
              │
              ▼
     record_execution() → 메모리 기록
     _emit_avatar_state() → VTuber 감정 상태
```

**근거 파일**:
- `execute_command()`: `backend/service/execution/agent_executor.py` L317-371
- 자율 그래프: `backend/service/executor/autonomous_graph.py` (30개 노드, 5개 라우터)
- 워크플로우 실행기: `backend/service/workflow/workflow_executor.py`
- 아바타 상태 전송: `backend/service/execution/agent_executor.py` L97-122

### 1.3 VTuber 서브시스템 (현재)

현재 VTuber는 **출력 표시 전용** 레이어로, 에이전트 실행 결과를 시각화하는 역할만 수행한다.

```
AgentSession 실행 완료
    │
    ▼
EmotionExtractor: 텍스트에서 감정 추출 ([joy], [sadness] 태그 파싱)
    │
    ▼
AvatarStateManager: SSE로 Live2D 상태 브로드캐스트
    │
    ▼
Frontend Live2D Canvas: 표정 변경, 모션 재생
```

**근거 파일**:
- 감정 추출: `backend/service/vtuber/emotion_extractor.py` (2단계: 텍스트 태그 + 상태 기반 폴백)
- 아바타 상태: `backend/service/vtuber/avatar_state_manager.py` (SSE 스트리밍)
- 모델 관리: `backend/service/vtuber/model_manager.py` (Live2D 모델 CRUD)
- VTuber API: `backend/controller/vtuber_controller.py` (REST endpoints)
- 프론트엔드: `frontend/src/components/tabs/VTuberTab.tsx`

**현재 VTuber의 한계**:
- ❌ 독립적인 대화 세션이 아님 (다른 세션의 출력을 시각화만 함)
- ❌ 자체적인 의사결정/대화 능력 없음
- ❌ 사용자와의 직접 대화 인터페이스 없음
- ❌ 생각하기(thinking) 트리거 없음
- ✅ 감정 표현 파이프라인 존재
- ✅ SSE 실시간 스트리밍 존재
- ✅ Live2D 렌더링 + 물리 시뮬레이션 존재

### 1.4 세션 간 통신 (현재)

이미 **3가지 통신 메커니즘**이 구현되어 있다:

| 메커니즘 | 파일 위치 | 동작 |
|---------|----------|------|
| **Chat Room Broadcast** | `backend/controller/chat_controller.py` L329+ | 방의 모든 에이전트에 병렬 실행 |
| **Direct Message (DM)** | `backend/tools/built_in/geny_tools.py` L655-722 | 1:1 메시지 + 자동 응답 트리거 |
| **Shared Folder** | `backend/controller/shared_folder_controller.py` | 파일 기반 비동기 교환 |

**DM 자동 트리거 로직** (가장 중요):
```python
# geny_tools.py L86-138
def _trigger_dm_response(target_session_id, sender_name, content, message_id):
    async def _deliver_and_respond():
        prompt = f"[SYSTEM] You received a DM from {sender_name}...\n{content}"
        result = await execute_command(session_id=target_session_id, prompt=prompt)
    asyncio.get_running_loop().create_task(_deliver_and_respond())
```

→ 이 패턴을 **VTuber → Sub-Worker 세션 위임(delegation)**에 재활용 가능

### 1.5 워크플로우 시스템 (현재)

4가지 빌트인 워크플로우 템플릿:

| 템플릿 | 파일 | 노드 수 | 용도 |
|--------|------|---------|------|
| Simple | `backend/workflows/template-simple.json` | 6 | 기본 Q&A |
| Autonomous | `backend/workflows/template-autonomous.json` | 28 | 난이도 분류 + 복원력 |
| Optimized | `backend/workflows/template-optimized-autonomous.json` | 9 | 비용 최적화 |
| Ultra-Light | `backend/workflows/template-ultra-light.json` | ~5 | 경량 |

**워크플로우 노드 유형** (22종):
- 모델 노드 6종 (`llm_call`, `classify`, `adaptive_classify`, `direct_answer`, `answer`, `review`)
- 로직 노드 5종 (`conditional_router`, `iteration_gate`, `check_progress`, `state_setter`, `relevance_gate`)
- 복원력 노드 2종 (`context_guard`, `post_model`)
- 작업 노드 7종 (`create_todos`, `execute_todo`, `batch_execute_todo`, `direct_tool`, `final_review`, `final_answer`, `final_synthesis`)
- 메모리 노드 2종 (`memory_inject`, `memory_reflect`)

**근거**: `backend/service/workflow/nodes/base.py` L413-610 (NodeRegistry)

---

## 2. 목표 아키텍처

### 2.1 이중 에이전트 구조

```
┌────────────────────────────────────────────────────────────────────┐
│                        Geny Dual-Agent System                       │
│                                                                     │
│  ┌─────────────────────────┐     ┌──────────────────────────────┐ │
│  │    VTuber Agent 🎭       │     │      Sub-Worker 🔧             │ │
│  │   (소통 & 일상 에이전트)    │     │   (작업 수행 에이전트)          │ │
│  │                          │     │                               │ │
│  │  • 사용자와 1차 대화       │     │  • 코드 작성/수정              │ │
│  │  • 감정 표현 + Live2D     │ ──► │  • 파일 시스템 조작            │ │
│  │  • 간단한 질문 즉시 해결    │ ◄── │  • 복잡한 분석/리서치          │ │
│  │  • 복잡한 작업 → Sub-Worker 위임  │     │  • 장시간 실행 태스크          │ │
│  │  • 진행상황 보고 수신       │     │  • 도구 사용 (MCP, 파일 등)    │ │
│  │  • 생각하기(Thinking)      │     │  • 결과를 VTuber에게 보고      │ │
│  │  • 메모리 기록/회상         │     │  • 메모리 기록/회상            │ │
│  │                          │     │                               │ │
│  │  워크플로우: VTuber-Light  │     │  워크플로우: Autonomous        │ │
│  │  모델: 경량 (Sonnet 등)    │     │  모델: 고성능 (Opus 등)        │ │
│  └─────────────────────────┘     └──────────────────────────────┘ │
│            │                                  │                     │
│            ▼                                  ▼                     │
│  ┌──────────────────────────────────────────────────────────┐     │
│  │              공유 메모리 레이어 (SessionMemoryManager)       │     │
│  │  • Long-Term Memory (MEMORY.md, daily/, topics/)          │     │
│  │  • Short-Term Memory (session.jsonl)                      │     │
│  │  • Vector Memory (FAISS)                                  │     │
│  └──────────────────────────────────────────────────────────┘     │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 VTuber Agent 역할 정의

**핵심 원칙**: VTuber Agent는 **"인격(Persona)"** 을 가진 소통 전문 에이전트

| 기능 | 설명 | 현재 존재 여부 |
|------|------|-------------|
| **일상 대화** | 사용자와 자연스러운 인사, 잡담, 감정 교류 | ❌ 새로 구축 |
| **간단 질문 응답** | 시간/날씨/간단한 지식 등 즉시 대답 | ❌ 새로 구축 |
| **작업 위임** | 복잡한 요청 → Sub-Worker에 DM으로 위임 | 🔶 DM 메커니즘 존재 |
| **진행상황 모니터링** | Sub-Worker 실행 상태 주기적 확인 | ❌ 새로 구축 |
| **결과 보고** | Sub-Worker 작업 완료 시 사용자에게 요약 보고 | ❌ 새로 구축 |
| **생각하기 (Thinking)** | 유휴 시간에 스스로 생각/계획/회상 | ❌ 새로 구축 |
| **감정 표현** | 대화 맥락에 맞는 Live2D 감정 변화 | ✅ 기존 시스템 활용 |
| **메모리 자동 기록** | 모든 대화 자동 기록 + 중요도 분류 | 🔶 기본 로직만 존재 |

### 2.3 Sub-Worker 역할 정의

**핵심 원칙**: Sub-Worker는 **현재 Command 탭의 로직과 100% 동일**

| 기능 | 설명 | 현재 존재 여부 |
|------|------|-------------|
| **코드 작성** | 파일 생성, 수정, 삭제 | ✅ 완벽 동작 |
| **도구 사용** | MCP, 파일 시스템, Git, Shell 등 | ✅ 완벽 동작 |
| **난이도 분류** | EASY/MEDIUM/HARD 자동 분류 후 경로 선택 | ✅ 완벽 동작 |
| **자율 실행** | TODO 분해 → 순차 실행 → 리뷰 | ✅ 완벽 동작 |
| **진행상황 보고** | 작업 완료 시 VTuber에게 결과 전달 | 🔶 DM 메커니즘 활용 |
| **결과 메모리 기록** | 실행 결과 자동 record_execution | ✅ 방금 수정 완료 |

### 2.4 통신 프로토콜

```
┌──────────┐                          ┌────────────┐
│  VTuber   │  ─── 작업 위임 (DM) ───►  │ Sub-Worker │
│  Agent    │  ◄── 결과 보고 (DM) ───   │            │
│           │  ◄── 진행상황 (DM) ───     │            │
└──────────┘                          └────────────┘
     ▲                                      ▲
     │                                      │
     └───── 공유 메모리 (같은 storage_path) ────┘
```

**통신 방식 1: DM 기반 위임** (기존 메커니즘 활용)
```
VTuber → geny_send_direct_message(target=sub_worker, content="코드 작성해줘...")
    → Sub-Worker 자동 트리거 → 실행 → 결과 DM으로 회신
```

**통신 방식 2: 공유 메모리** (새로 구축)
```
VTuber가 memory_write("task_request", ...)
Sub-Worker가 memory_read("task_request")
Sub-Worker가 memory_write("task_result", ...)
VTuber가 memory_read("task_result")
```

---

## 3. 현재 구조와의 Gap 분석

### 3.1 활용 가능한 기존 시스템 (그대로 사용)

| 시스템 | 파일 | 활용 방법 |
|--------|------|----------|
| `execute_command()` 통합 실행 | `agent_executor.py` L317-371 | Sub-Worker 실행 경로 그대로 사용 |
| DM 자동 트리거 | `geny_tools.py` L86-138 | VTuber↔Sub-Worker 위임 메커니즘 |
| Live2D + 감정 추출 | `service/vtuber/*` | VTuber Agent 시각적 표현 |
| SSE 스트리밍 | `chat_controller.py` L578+ | 실시간 상태 업데이트 |
| 워크플로우 시스템 | `workflow_executor.py` | 에이전트별 다른 그래프 할당 |
| 메모리 시스템 | `service/memory/manager.py` | 공유 메모리 레이어 |
| 세션 저장소 | `session_store.py` | DB 기반 세션 관리 |
| Tool Preset | `tool_preset_controller.py` | 에이전트별 도구 제한 |
| NodeRegistry (22종) | `workflow/nodes/base.py` | 워크플로우 노드 재사용 |

### 3.2 수정이 필요한 시스템

| 시스템 | 변경 내용 | 근거 |
|--------|----------|------|
| **SessionRole enum** | `VTUBER` 역할 추가 | `models.py` L21-26: 현재 WORKER/DEVELOPER/RESEARCHER/PLANNER만 존재 |
| **CreateSessionRequest** | `linked_session_id` 필드 추가 (VTuber↔Sub-Worker 연결) | `models.py` L185+: 현재 세션 간 연결 개념 없음 |
| **AgentSessionManager** | VTuber 세션 생성 시 Sub-Worker 세션 자동 생성 | `agent_session_manager.py` L270+: 현재 개별 생성만 가능 |
| **시스템 프롬프트 빌더** | VTuber 전용 프롬프트 구성 | `agent_session_manager.py` L196-261: 현재 role별 분기 없음 |
| **VTuber 워크플로우** | 경량 대화형 그래프 생성 | `workflows/` 디렉토리: 현재 작업 중심 템플릿만 존재 |

### 3.3 새로 구축이 필요한 시스템

| 시스템 | 설명 | 이유 |
|--------|------|------|
| **VTuber 전용 워크플로우 노드** | 작업 위임 판단, 진행상황 모니터링 노드 | 현재 노드 22종에 대화/위임 노드 없음 |
| **VTuber 대화 인터페이스** | 프론트엔드에서 VTuber와 직접 대화 | 현재 VTuber 탭은 표시 전용 |
| **Thinking 트리거 시스템** | 유휴 시간 자동 사고 + 이벤트 기반 트리거 | 현재 없음 |
| **작업 위임 프로토콜** | VTuber→Sub-Worker 구조화된 위임+보고 체계 | DM은 있으나 구조화되지 않음 |
| **VTuber 프롬프트** | 인격/페르소나 기반 시스템 프롬프트 | `backend/prompts/`에 VTuber 전용 없음 |
| **VTuber 탭 리디자인** | 대화 UI + Live2D 통합 화면 | 현재 분리됨 |

---

## 4. 구현 가능성 검토

### 4.1 검토 결과: ✅ 구현 가능

기존 시스템이 이미 **핵심 인프라를 모두 제공**하고 있어, 새로운 시스템을 처음부터 만들 필요가 없다.

| 필요 기능 | 기존 인프라 | 구현 난이도 |
|----------|-----------|-----------|
| VTuber 세션 실행 | `execute_command()` 동일 경로 | ⭐ 낮음 |
| VTuber↔Sub-Worker 통신 | DM `_trigger_dm_response()` | ⭐ 낮음 |
| VTuber 전용 그래프 | `WorkflowExecutor` + `NodeRegistry` | ⭐⭐ 중간 |
| 작업 위임 판단 | 새로운 워크플로우 노드 1개 | ⭐⭐ 중간 |
| Live2D + 대화 통합 UI | 기존 컴포넌트 조합 | ⭐⭐ 중간 |
| Thinking 트리거 | 새로운 타이머 기반 서비스 | ⭐⭐⭐ 높음 |
| 공유 메모리 | `SessionMemoryManager` 확장 | ⭐⭐ 중간 |

### 4.2 핵심 재사용 포인트

**1) DM 자동 트리거 = 작업 위임 메커니즘**

현재 `geny_tools.py` L86-138의 `_trigger_dm_response()`가 이미 "한 세션이 다른 세션에 메시지를 보내면 자동으로 해당 세션이 실행되는" 패턴을 구현하고 있다. VTuber→Sub-Worker 위임에 **그대로** 적용 가능.

**2) 워크플로우 시스템 = VTuber 전용 그래프**

`WorkflowExecutor`가 JSON 기반 워크플로우 정의를 `CompiledStateGraph`로 컴파일한다. VTuber 전용 경량 워크플로우를 JSON으로 정의하면 **기존 실행 엔진 그대로 사용 가능**.

**3) SessionRole = VTuber 역할 분리**

`SessionRole` enum에 `VTUBER`를 추가하면, 프롬프트 빌더(`_build_system_prompt()`)에서 자동으로 VTuber 전용 시스템 프롬프트를 로드할 수 있다.

---

## 5. 세부 구현 계획

### Phase 1: VTuber 기반 인프라 (Backend)

#### 1-1. SessionRole에 VTUBER 추가

**파일**: `backend/service/claude_manager/models.py` L21-26

```python
# 현재
class SessionRole(str, Enum):
    WORKER = "worker"
    DEVELOPER = "developer"
    RESEARCHER = "researcher"
    PLANNER = "planner"

# 변경 후
class SessionRole(str, Enum):
    WORKER = "worker"
    DEVELOPER = "developer"
    RESEARCHER = "researcher"
    PLANNER = "planner"
    VTUBER = "vtuber"           # NEW: 외부 소통 에이전트
```

#### 1-2. CreateSessionRequest에 linked_session_id 추가

**파일**: `backend/service/claude_manager/models.py` L185+

```python
class CreateSessionRequest(BaseModel):
    # ... 기존 필드 ...
    linked_session_id: Optional[str] = None   # NEW: 연결된 세션 (VTuber↔Sub-Worker 쌍)
    session_type: Optional[str] = None        # NEW: "vtuber" | "sub" (기본값: "sub")
```

#### 1-3. SessionStore 스키마 확장

**파일**: `backend/service/claude_manager/session_store.py`

세션 레코드에 `linked_session_id` 및 `session_type` 컬럼 추가.
PostgreSQL 마이그레이션 + JSON 폴백 모두 대응.

#### 1-4. AgentSessionManager: VTuber 쌍 세션 자동 생성 로직

**파일**: `backend/service/executor/agent_session_manager.py` L270+

```python
async def create_agent_session(self, request: CreateSessionRequest):
    # ... 기존 로직 ...

    # NEW: VTuber 세션 생성 시 Sub-Worker 세션 자동 생성
    if request.role == SessionRole.VTUBER:
        cli_request = CreateSessionRequest(
            session_name=f"{request.session_name}_sub",
            role=SessionRole.WORKER,
            model="claude-sonnet-4-20250514",   # Sub-Worker는 고성능 모델
            workflow_id="template-autonomous",   # 기존 자율 워크플로우
            linked_session_id=vtuber_session_id,
            session_type="sub",
            working_dir=request.working_dir,     # 동일 작업 디렉토리 공유
        )
        cli_session = await self.create_agent_session(cli_request)
        # VTuber 세션에 Sub-Worker 세션 ID 역링크
        await self._store.update(vtuber_session_id, linked_session_id=cli_session.session_id)
```

#### 1-5. VTuber 전용 시스템 프롬프트 생성

**새 파일**: `backend/prompts/vtuber.md`

VTuber 에이전트의 인격(Persona) 정의:
- 성격, 말투, 감정 표현 패턴
- 작업 위임 판단 기준 (간단한 건 직접, 복잡한 건 Sub-Worker에 위임)
- 진행상황 보고 수신 시 사용자에게 자연스럽게 전달하는 방법
- 생각하기(Thinking) 행동 패턴

**프롬프트 빌더 수정 위치**: `backend/service/executor/agent_session_manager.py` L196-261
```python
# _build_system_prompt() 내부
if request.role == SessionRole.VTUBER:
    # VTuber 전용 프롬프트 로드
    # 경량 모델 적합하도록 최적화
    # linked Sub-Worker 세션 ID를 컨텍스트에 주입
```

**프롬프트 빌더 핵심 수정**: `backend/service/prompt/builder.py`
- `PromptSection`에 VTuber 전용 섹션 추가 (persona, delegation_rules, thinking_triggers)

### Phase 2: VTuber 전용 워크플로우

#### 2-1. VTuber 경량 워크플로우 생성

**새 파일**: `backend/workflows/template-vtuber.json`

현재 autonomous 워크플로우 (28노드)와 달리, VTuber는 **경량 대화 중심**:

```
START
  → memory_inject (메모리 로드)
  → vtuber_classify (위임 판단: direct_response / delegate_to_sub_worker / thinking)
  ├─ [direct_response] → vtuber_respond (직접 응답) → END
  ├─ [delegate_to_sub_worker] → vtuber_delegate (Sub-Worker에 위임) → END
  └─ [thinking] → vtuber_think (자기 사고) → END
```

**약 7-9개 노드**로 구성된 경량 그래프.

#### 2-2. 새로운 워크플로우 노드: VTuberClassifyNode

**새 파일**: `backend/service/workflow/nodes/vtuber/vtuber_classify_node.py`

LLM을 사용하여 사용자 입력을 3가지로 분류:

```python
class VTuberClassifyNode(BaseNode):
    """VTuber 입력 분류 노드.

    판단 기준:
    1. direct_response: 인사, 잡담, 간단한 질문, 감정 교류
    2. delegate_to_sub_worker: 코드 작성, 파일 조작, 복잡한 분석, 장시간 작업
    3. thinking: 자발적 사고 트리거 (유휴 상태에서 호출)
    """
```

**등록 위치**: `backend/service/workflow/nodes/base.py` L572-610 (NodeRegistry)

#### 2-3. 새로운 워크플로우 노드: VTuberDelegateNode

**새 파일**: `backend/service/workflow/nodes/vtuber/vtuber_delegate_node.py`

Sub-Worker에게 작업을 위임하는 노드:

```python
class VTuberDelegateNode(BaseNode):
    """Sub-Worker에게 작업을 위임하고 사용자에게 안내 메시지 반환.

    1. linked_session_id로 Sub-Worker 식별
    2. 작업 내용을 구조화하여 DM으로 전송 (geny_send_direct_message 내부 호출)
    3. 사용자에게 "작업을 시작했어요! 완료되면 알려드릴게요~" 같은 응답 생성
    """
```

**재활용**: `geny_tools.py` L655-722의 `geny_send_direct_message` + L86-138의 `_trigger_dm_response()`

#### 2-4. 새로운 워크플로우 노드: VTuberRespondNode

**새 파일**: `backend/service/workflow/nodes/vtuber/vtuber_respond_node.py`

VTuber 인격에 맞는 직접 응답 생성:

```python
class VTuberRespondNode(BaseNode):
    """VTuber 인격으로 직접 응답.

    - 페르소나에 맞는 어투 유지
    - 감정 태그 자동 삽입 ([joy], [sadness] 등)
    - 메모리 컨텍스트를 가진 자연스러운 대화
    """
```

#### 2-5. 새로운 워크플로우 노드: VTuberThinkNode

**새 파일**: `backend/service/workflow/nodes/vtuber/vtuber_think_node.py`

유휴 시간에 자발적으로 사고하는 노드:

```python
class VTuberThinkNode(BaseNode):
    """VTuber 자발적 사고 노드.

    트리거 조건:
    - 유휴 시간이 N분 이상 경과
    - 특정 이벤트 발생 (Sub-Worker 작업 완료, 시간 기반 등)

    행동:
    - 과거 대화 회상 및 정리
    - 오늘 계획 점검
    - Sub-Worker 작업 상태 확인
    - 사용자에게 먼저 말 걸기 (옵션)
    """
```

### Phase 3: Thinking 트리거 시스템

#### 3-1. ThinkingTriggerService

**새 파일**: `backend/service/vtuber/thinking_trigger.py`

```python
class ThinkingTriggerService:
    """VTuber의 자발적 사고를 관리하는 서비스.

    트리거 유형:
    1. IDLE_TIMER: 마지막 대화 후 N분 경과 시 자동 실행
    2. SUB_WORKER_COMPLETE: Sub-Worker 작업 완료 시 결과 보고 트리거
    3. SCHEDULED: 특정 시간에 자동 실행 (아침 인사, 일정 확인 등)
    4. EVENT: 외부 이벤트 (메신저 메시지 수신 등)
    """

    async def start(self, vtuber_session_id: str):
        """세션에 대한 thinking 모니터링 시작"""

    async def stop(self, vtuber_session_id: str):
        """세션에 대한 thinking 모니터링 중지"""

    async def _on_idle_timeout(self, vtuber_session_id: str):
        """유휴 타임아웃 시 VTuber에게 thinking 트리거"""
        prompt = "[SYSTEM][THINKING_TRIGGER] idle_timeout"
        await execute_command(vtuber_session_id, prompt)

    async def _on_sub_worker_complete(self, vtuber_session_id: str, result: str):
        """Sub-Worker 작업 완료 시 VTuber에게 결과 전달"""
        prompt = f"[SYSTEM][SUB_WORKER_RESULT] {result}"
        await execute_command(vtuber_session_id, prompt)
```

#### 3-2. Sub-Worker 완료 → VTuber에 자동 보고 연결

**수정 파일**: `backend/service/execution/agent_executor.py` L317-371

`execute_command()` 완료 후, 해당 세션이 Sub-Worker 타입이고 linked VTuber 세션이 있으면:

```python
# execute_command() 완료 후 추가
if session_type == "sub" and linked_vtuber_id:
    await thinking_trigger.on_sub_worker_complete(linked_vtuber_id, result.output)
```

### Phase 4: 프론트엔드 통합

#### 4-1. VTuber 탭 리디자인

**수정 파일**: `frontend/src/components/tabs/VTuberTab.tsx`

현재 구조:
```
[모델 선택] [감정 테스트 버튼들]
[Live2D 캔버스 (전체 화면)]
[로그 패널 (하단)]
```

새로운 구조:
```
┌─────────────────────┬──────────────────────┐
│   Live2D Canvas     │   Chat Interface     │
│   (좌측 40%)         │   (우측 60%)          │
│                     │                      │
│   [VTuber 3D 모델]   │   [대화 히스토리]      │
│                     │   [사용자 메시지 ...]   │
│   감정: joy          │   [VTuber 응답 ...]    │
│                     │   [Sub-Worker 작업 상태 ...]   │
│                     │                      │
│                     │   ┌─────────────┐     │
│                     │   │ 입력 필드     │     │
│                     │   └─────────────┘     │
└─────────────────────┴──────────────────────┘
```

**활용 가능한 기존 컴포넌트**:
- Live2D Canvas → 기존 `VTuberTab.tsx`의 캔버스 + `useVTuberStore`
- 대화 히스토리 → 기존 Chat 시스템의 SSE 스트림 (`chat_controller.py` SSE)
- 입력 필드 → 기존 Command 탭의 입력 방식 활용, 단 execute 대상이 VTuber 세션

#### 4-2. 세션 사이드바 VTuber 표시 변경

**수정 파일**: `frontend/src/components/Sidebar.tsx`

VTuber 세션은 시각적으로 구분:
- VTuber 역할 배지 추가 (🎭)
- linked Sub-Worker 세션은 하위 항목으로 표시 (트리 구조)
- Sub-Worker 세션의 실행 상태가 VTuber 항목에도 표시

```
┌─────────────────────┐
│ 🎭 Geny (VTuber)    │  ← VTuber 메인 세션
│   └── 🔧 Geny_sub   │  ← 자동 생성된 Sub-Worker 세션
│ 🟢 다른 워커 세션     │  ← 기존 독립 세션
└─────────────────────┘
```

#### 4-3. 새 세션 생성 모달 수정

**수정 파일**: 프론트엔드 세션 생성 모달 컴포넌트

"VTuber Agent" 생성 옵션 추가:
- VTuber 역할 선택 시 → Sub-Worker 세션 자동 생성 안내 표시
- VTuber 모델 선택 (경량: Sonnet, 초경량: Haiku)
- Sub-Worker 모델 선택 (고성능: Opus, Sonnet)
- 페르소나 커스터마이징 (이름, 말투, 성격)

### Phase 5: 메모리 시스템 공유

#### 5-1. 공유 메모리 경로 설정

**수정 파일**: `backend/service/memory/manager.py`

VTuber와 Sub-Worker 세션이 **동일한 `storage_path`** 를 사용하도록 설정:

```python
# 세션 생성 시 (agent_session_manager.py)
if request.role == SessionRole.VTUBER:
    storage_path = f"sessions/{vtuber_session_id}/"
    # Sub-Worker 세션도 같은 경로 사용
    cli_request.working_dir = storage_path
```

이렇게 하면 `SessionMemoryManager`가 동일한 `memory/` 디렉토리를 참조하여:
- VTuber가 기록한 대화 → Sub-Worker가 참조 가능
- Sub-Worker가 기록한 실행 결과 → VTuber가 참조 가능

#### 5-2. 메모리 분류 태그 확장

**수정 파일**: `backend/service/memory/manager.py` → `record_execution()`

VTuber와 Sub-Worker의 기록을 구분하는 태그 추가:

```python
source_tag = "vtuber" if is_vtuber_session else "sub"
all_tags = ["execution", status_tag, source_tag] + auto_tags
```

### Phase 6: 작업 위임 프로토콜 구조화

#### 6-1. DelegationProtocol 정의

**새 파일**: `backend/service/vtuber/delegation.py`

```python
@dataclass
class DelegationRequest:
    """VTuber → Sub-Worker 작업 위임 요청"""
    task_id: str                    # 고유 태스크 ID
    task_summary: str               # 작업 요약 (사용자 요청 원문)
    task_detail: str                # 구조화된 작업 명세
    priority: str                   # "low" | "medium" | "high" | "urgent"
    expected_duration: Optional[str] # 예상 소요 시간
    callback_type: str              # "dm" | "memory" | "both"

@dataclass
class DelegationResult:
    """Sub-Worker → VTuber 작업 결과 보고"""
    task_id: str
    status: str                     # "completed" | "failed" | "in_progress"
    summary: str                    # 결과 요약
    detail: str                     # 상세 결과
    artifacts: List[str]            # 생성/수정된 파일 목록
    duration_ms: int
    cost_usd: float
```

#### 6-2. DM 메시지 포맷 구조화

현재 DM은 자유형 텍스트지만, VTuber↔Sub-Worker 통신을 위해 구조화:

```
[DELEGATION_REQUEST]
task_id: abc123
summary: Python REST API 서버 만들어줘
detail: FastAPI 기반, /api/users CRUD 엔드포인트 구현
priority: medium
---
(원문 텍스트)
```

```
[DELEGATION_RESULT]
task_id: abc123
status: completed
summary: FastAPI 서버 구현 완료 (3개 파일 생성)
artifacts: backend/api.py, backend/models.py, backend/tests/test_api.py
duration: 45s
cost: $0.12
---
(상세 결과 텍스트)
```

---

## 6. Phase별 실행 로드맵

```
Phase 1 ─── Backend 기반 인프라 ────────────────────────
  1-1. SessionRole.VTUBER 추가
  1-2. CreateSessionRequest 확장
  1-3. SessionStore 스키마 확장
  1-4. AgentSessionManager 쌍 세션 로직
  1-5. VTuber 시스템 프롬프트 (prompts/vtuber.md)
       │
Phase 2 ─── VTuber 워크플로우 ──────────────────────────
  2-1. template-vtuber.json 생성
  2-2. VTuberClassifyNode (위임 판단)
  2-3. VTuberDelegateNode (Sub-Worker 위임)
  2-4. VTuberRespondNode (직접 응답)
  2-5. VTuberThinkNode (자발적 사고)
       │
Phase 3 ─── Thinking 시스템 ────────────────────────────
  3-1. ThinkingTriggerService
  3-2. Sub-Worker 완료 → VTuber 자동 보고
       │
Phase 4 ─── Frontend 통합 ─────────────────────────────
  4-1. VTuber 탭 리디자인 (Live2D + Chat)
  4-2. 사이드바 VTuber 세션 표시
  4-3. 세션 생성 모달 수정
       │
Phase 5 ─── 메모리 공유 ───────────────────────────────
  5-1. 공유 storage_path 설정
  5-2. 메모리 태그 확장
       │
Phase 6 ─── 위임 프로토콜 ─────────────────────────────
  6-1. DelegationProtocol 정의
  6-2. DM 메시지 포맷 구조화
```

### Phase별 의존성 관계

```
Phase 1 (기반) ──────► Phase 2 (워크플로우) ──────► Phase 3 (Thinking)
                              │                          │
                              ▼                          ▼
                      Phase 4 (Frontend) ◄──── Phase 6 (위임 프로토콜)
                              │
                              ▼
                      Phase 5 (메모리)
```

- Phase 1은 **모든 Phase의 전제조건**
- Phase 2, 5는 **독립 병렬 진행 가능**
- Phase 3은 Phase 2 완료 후 진행
- Phase 4는 Phase 2 완료 후 진행 (프론트엔드는 백엔드 API 필요)
- Phase 6은 Phase 2와 병렬 가능하나, Phase 3 이전 완료 권장

---

## 7. 리스크 및 완화 전략

### 7.1 이중 실행 충돌

**리스크**: VTuber가 Sub-Worker에 위임하면서 동시에 사용자가 Sub-Worker 세션에 직접 명령을 보내면 `AlreadyExecutingError` 발생

**완화**:
- `agent_executor.py` L334-340의 `_active_executions` 가드가 이미 이중 실행 방지
- VTuber가 위임 전 Sub-Worker 실행 상태를 확인하도록 `VTuberDelegateNode`에 로직 추가
- Sub-Worker가 바쁠 경우 큐잉 또는 "잠시 기다려주세요" 응답

### 7.2 무한 DM 루프

**리스크**: VTuber→Sub-Worker DM 전송 → Sub-Worker 자동 응답 → VTuber 자동 응답 → 루프

**완화**:
- DM 메시지에 `[DELEGATION_REQUEST]` / `[DELEGATION_RESULT]` 태그를 사용
- VTuber가 `[DELEGATION_RESULT]`를 수신하면 자동 회신하지 않도록 워크플로우에서 처리
- 최대 핑퐁 횟수 제한 (3회)

### 7.3 비용 관리

**리스크**: VTuber가 모든 대화에 LLM 호출 → 비용 급증

**완화**:
- VTuber는 경량 모델 사용 (Haiku/Sonnet)
- 단순 인사는 `VTuberClassifyNode`에서 LLM 없이 패턴 매칭으로 처리 가능
- Thinking 트리거 빈도 제한 (최소 간격 설정)
- 기존 비용 추적 시스템 (`session_store.increment_cost()`) 그대로 활용

### 7.4 메모리 충돌

**리스크**: VTuber와 Sub-Worker가 동시에 같은 메모리 파일에 쓰기

**완화**:
- `manager.py`의 `write_dated()`는 append-only 방식으로 파일 락 불필요
- `StructuredMemoryWriter`는 개별 파일 생성 방식 (충돌 없음)
- FAISS 인덱싱은 이미 `await`으로 직렬화됨

### 7.5 세션 쌍 생명주기 관리

**리스크**: VTuber 세션 삭제 시 Sub-Worker 세션이 남거나, Sub-Worker 세션만 단독 삭제

**완화**:
- VTuber 세션 삭제 시 linked Sub-Worker 세션도 함께 soft-delete
- Sub-Worker 세션 단독 삭제 방지 (linked 상태에서는 VTuber를 통해서만 삭제)
- `session_store.soft_delete()` 확장하여 linked 세션 동시 처리

---

## 변경 대상 파일 요약

### 수정 파일 (기존)

| 파일 | 변경 내용 |
|------|----------|
| `backend/service/claude_manager/models.py` | SessionRole.VTUBER 추가, CreateSessionRequest 확장 |
| `backend/service/claude_manager/session_store.py` | linked_session_id, session_type 스키마 추가 |
| `backend/service/executor/agent_session_manager.py` | VTuber 쌍 세션 생성, 프롬프트 빌더 확장 |
| `backend/service/prompt/builder.py` | VTuber 전용 프롬프트 섹션 |
| `backend/service/execution/agent_executor.py` | Sub-Worker 완료 → VTuber 자동 보고 연결 |
| `backend/service/memory/manager.py` | 소스 태그 (vtuber/sub) 추가 |
| `backend/service/workflow/nodes/base.py` | 새 노드 등록 |
| `backend/controller/agent_controller.py` | VTuber 세션 생성 엔드포인트 변경 |
| `frontend/src/components/tabs/VTuberTab.tsx` | Live2D + Chat 통합 UI |
| `frontend/src/components/Sidebar.tsx` | VTuber 세션 트리 구조 표시 |

### 신규 파일

| 파일 | 내용 |
|------|------|
| `backend/prompts/vtuber.md` | VTuber 페르소나 시스템 프롬프트 |
| `backend/workflows/template-vtuber.json` | VTuber 경량 워크플로우 정의 |
| `backend/service/workflow/nodes/vtuber/vtuber_classify_node.py` | 입력 분류 노드 |
| `backend/service/workflow/nodes/vtuber/vtuber_delegate_node.py` | Sub-Worker 위임 노드 |
| `backend/service/workflow/nodes/vtuber/vtuber_respond_node.py` | 직접 응답 노드 |
| `backend/service/workflow/nodes/vtuber/vtuber_think_node.py` | 자발적 사고 노드 |
| `backend/service/vtuber/thinking_trigger.py` | Thinking 트리거 서비스 |
| `backend/service/vtuber/delegation.py` | 위임 프로토콜 정의 |
