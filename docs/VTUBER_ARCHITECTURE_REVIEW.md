# VTuber 이중 에이전트 아키텍처 검증 및 개선 계획서

> **작성일**: 2026-03-30
> **범위**: VTuber ↔ Sub-Worker 이중 에이전트 시스템 전체
> **상태**: 검증 완료, 개선 계획 수립

---

## 목차

1. [아키텍처 현황 요약](#1-아키텍처-현황-요약)
2. [파일별 역할 맵](#2-파일별-역할-맵)
3. [검증 결과 — 발견된 문제점](#3-검증-결과--발견된-문제점)
4. [개선 계획](#4-개선-계획)
5. [우선순위 로드맵](#5-우선순위-로드맵)

---

## 1. 아키텍처 현황 요약

### 1.1 전체 데이터 흐름

```
사용자 입력
  │
  ▼
VTuber 세션 (template-vtuber 워크플로우)
  │
  ├─ vtuber_classify_node ─┬─ direct_response ──▶ vtuber_respond_node ──▶ 응답 출력
  │                        │
  │                        ├─ delegate_to_cli ──▶ vtuber_delegate_node
  │                        │                        │
  │                        │                        ├─ [DELEGATION_REQUEST] DM 전송
  │                        │                        │       │
  │                        │                        │       ▼
  │                        │                        │   서브 워커 세션 (execute_command 트리거)
  │                        │                        │       │
  │                        │                        │       ▼
  │                        │                        │   작업 완료 → _notify_linked_vtuber()
  │                        │                        │       │
  │                        │                        │       ▼
  │                        │                        │   [SUB_WORKER_RESULT] → VTuber 세션
  │                        │                        │
  │                        │                        └─ 사용자에게 "처리 중" 응답
  │                        │
  │                        └─ thinking ─────────▶ vtuber_think_node
  │                                                  │
  │                                                  ├─ [THINKING_TRIGGER] → 자기 반성
  │                                                  ├─ [SUB_WORKER_RESULT] → 결과 요약
  │                                                  └─ [SILENT] → 무출력
  │
  ▼
Avatar State Manager → SSE → Frontend Live2D 렌더링
```

### 1.2 세션 생성 흐름

```
POST /api/agents (role=vtuber, session_name="ㅋㅋ")
  │
  ▼
create_agent_session(role=VTUBER)
  ├── AgentSession 생성 (workflow_id="template-vtuber")
  ├── sessions.json에 등록
  │
  └── Auto-create 서브 워커 세션:
        ├── session_name="ㅋㅋ_cli"
        ├── role=WORKER
        ├── workflow_id="template-optimized-autonomous"
        ├── linked_session_id=VTuber_ID  (← Sub-Worker → VTuber 역방향 링크)
        │
        └── Back-link:
              ├── VTuber session store에 linked_session_id=SUB_WORKER_ID 저장
              ├── agent._linked_session_id = SUB_WORKER_ID
              └── system_prompt에 SUB_WORKER_ID 주입
```

### 1.3 Thinking Trigger 구조

```
main.py: lifespan()
  │
  ├── start: ThinkingTriggerService.start()
  │     └── 30초마다 폴링 → 120초 idle 감지 → [THINKING_TRIGGER] 전송
  │
  └── shutdown: ThinkingTriggerService.stop()

agent_executor.py: execute_command()
  └── session_type == "vtuber" → record_activity(session_id)
```

---

## 2. 파일별 역할 맵

| 파일 | 역할 | 라인 수 |
|------|------|---------|
| **Backend Core** | | |
| `service/vtuber/thinking_trigger.py` | Idle VTuber에 [THINKING_TRIGGER] 전송 | ~130 |
| `service/vtuber/delegation.py` | 에이전트 간 메시지 프로토콜 (태그, 포맷) | ~100 |
| `service/vtuber/emotion_extractor.py` | `[joy]` 등 감정 태그 파싱 + 상태 매핑 | ~160 |
| `service/vtuber/avatar_state_manager.py` | 세션별 아바타 상태 관리 + SSE 구독자 알림 | ~130 |
| `service/vtuber/live2d_model_manager.py` | model_registry.json 로드, 모델-에이전트 할당 | ~150 |
| **Workflow Nodes** | | |
| `service/workflow/nodes/vtuber/vtuber_classify_node.py` | 입력 분류 (direct/delegate/thinking) | ~150 |
| `service/workflow/nodes/vtuber/vtuber_respond_node.py` | 대화형 응답 생성 + 감정 태그 | ~100 |
| `service/workflow/nodes/vtuber/vtuber_delegate_node.py` | 서브 워커에 작업 위임 + DM 전송 | ~200 |
| `service/workflow/nodes/vtuber/vtuber_think_node.py` | 내부 사고/서브 워커 결과 요약 | ~120 |
| **Session Management** | | |
| `service/executor/agent_session_manager.py` | VTuber 세션 + 서브 워커 세션 자동 생성, 프롬프트 구성 | 핵심 |
| `service/executor/agent_session.py` | `_linked_session_id`, `_session_type` 속성 | 핵심 |
| `service/execution/agent_executor.py` | `_notify_linked_vtuber()`, thinking trigger 기록 | 핵심 |
| `service/sessions/models.py` | `SessionRole.VTUBER`, 링크 필드 | 핵심 |
| `service/sessions/store.py` | Cascade soft-delete, 링크 필드 영속화 | 핵심 |
| **Controller** | | |
| `controller/vtuber_controller.py` | REST API + SSE 엔드포인트 | ~200 |
| **Frontend** | | |
| `frontend/src/store/useVTuberStore.ts` | Zustand 상태 관리 | ~300 |
| `frontend/src/components/tabs/VTuberTab.tsx` | 메인 VTuber UI 탭 | ~300 |
| `frontend/src/components/live2d/VTuberChatPanel.tsx` | 채팅 오버레이 UI | ~150 |
| `frontend/src/components/live2d/Live2DCanvas.tsx` | Pixi.js + Live2D 렌더링 | ~100 |
| `frontend/src/components/live2d/VTuberLogPanel.tsx` | SSE 디버그 로그 | ~100 |

---

## 3. 검증 결과 — 발견된 문제점

### 🔴 심각 (Critical) — 즉시 수정 필요

#### C-1. `template-vtuber` 워크플로우 파일 누락

**위치**: `backend/workflows/` 디렉토리
**현상**: `agent_session_manager.py:426`에서 `workflow_id = "template-vtuber"`를 설정하지만, 실제 `template-vtuber.json` 파일이 존재하지 않음.

**영향**: `agent_session.py:840-847`의 `_resolve_workflow()`에서 store.load("template-vtuber")가 None을 반환하고, fallback 로직에서 `graph_name="VTuber Conversational"`은 'optimized'/'autonomous' 매칭에 실패하여 **`template-simple`로 폴백**됨. 즉, **VTuber 전용 노드(classify → respond/delegate/think)가 전혀 사용되지 않고 단순 Simple 그래프로 동작**할 가능성이 있음.

```python
# agent_session.py _resolve_workflow() fallback 경로:
# 1. store.load("template-vtuber") → None (파일 없음)
# 2. graph_name="VTuber Conversational" → 'optimized' not in name, 'autonomous' not in name
# 3. template_id = "template-simple" ← 여기로 폴백!!
```

**수정**: `template-vtuber.json` 생성 + `templates.py`에 `create_vtuber_template()` 팩토리 함수 추가 + `_template_factories`에 등록

---

#### C-2. 서브 워커의 `_linked_session_id` / `_session_type` 미설정

**위치**: `agent_session_manager.py:517-535`
**현상**: 서브 워커 세션 생성 시 `CreateSessionRequest`에 `linked_session_id`와 `session_type="sub"`를 넘기지만, `create_agent_session()` 내에서 이 값들을 `AgentSession` 객체에 할당하는 코드가 **VTuber 세션 블록(L542-543)에만 존재**.

**영향**: `_notify_linked_vtuber()`(agent_executor.py:154)에서 `getattr(agent, '_session_type', None) != 'sub'` 체크가 항상 True → **Sub-Worker → VTuber 자동 리포트가 절대 실행되지 않음**.

```python
# agent_executor.py:154 — 이 조건이 항상 True (CLI의 _session_type이 "sub"로 정규화되지 않음)
if getattr(agent, '_session_type', None) != 'sub':
    return  # ← 항상 여기서 리턴!
```

**수정**: `create_agent_session()` 플로우 내에서 `request.linked_session_id`와 `request.session_type`이 있으면 agent 객체에 설정

---

### 🟡 중요 (Important) — 조기 수정 권장

#### I-1. 세션 복원(restore) 시 링크 정보 손실

**위치**: `controller/agent_controller.py:376-389`
**현상**: `restore_session()`에서 `CreateSessionRequest`를 재구성할 때 `linked_session_id`와 `session_type`을 포함하지 않음. `get_creation_params()`는 이 값들을 반환하지만, 실제 Request 구성에서 누락.

**영향**: VTuber 세션 복원 시 서브 워커 세션이 **또다시 생성**됨 (이미 존재하는데 새로 만듦). 서브 워커 세션 복원 시 VTuber와의 링크가 끊어짐.

```python
# agent_controller.py:376 — linked_session_id, session_type 누락!
request = CreateSessionRequest(
    session_name=params.get("session_name"),
    ...
    tool_preset_id=params.get("tool_preset_id"),
    # ❌ linked_session_id 없음
    # ❌ session_type 없음
)
```

---

#### I-2. Thinking Trigger 초기 등록 누락

**위치**: `thinking_trigger.py:61`, `agent_executor.py:442-446`
**현상**: `record_activity()`는 `execute_command()` 내에서만 호출됨. VTuber 세션이 생성된 직후에는 `_activity` 딕셔너리에 등록되지 않아, **사용자가 최소 1회 메시지를 보내기 전까지는 Thinking Trigger가 절대 발동되지 않음**.

**영향**: 세션 생성 직후 마치 "멍하니 서 있는" 상태. VTuber가 먼저 말을 거는 경험 불가능.

---

#### I-3. 이중 실행(AlreadyExecutingError)으로 인한 메시지 드랍

**위치**: `agent_executor.py:167-174`, `vtuber_delegate_node.py:227-230`
**현상**: Fire-and-forget으로 서브 워커/VTuber를 트리거할 때 `AlreadyExecutingError`가 발생하면 **조용히 폐기**됨. 재시도 로직이 없음.

**영향**:
- 사용자가 VTuber에게 작업을 요청 → 서브 워커 위임 → 서브 워커가 이미 다른 작업 중 → DM 무시
- 서브 워커 완료 → VTuber 알림 → VTuber가 다른 대화 처리 중 → 결과 무시
- **사용자는 작업 결과를 영영 못 받을 수 있음**

---

#### I-4. DelegateNode의 이중 LLM 호출 (비용 이슈)

**위치**: `vtuber_delegate_node.py:121-170`
**현상**: 위임 시 LLM을 **2번** 호출:
1. `vtuber_delegate_task` — 사용자 요청을 CLI용 명령으로 변환
2. `vtuber_delegate_ack` — 사용자에게 "처리 중" 응답 생성

Sonnet 4.5 기준 위임 한 번에 ~$0.04 추가 비용. 일상적인 대화가 잦으면 누적 비용 상당.

---

#### I-5. VTuber Classify Node — 모든 일반 입력에 LLM 호출

**위치**: `vtuber_classify_node.py:113-135`
**현상**: [THINKING_TRIGGER]/[SUB_WORKER_RESULT] 외의 모든 입력에 대해 LLM 분류 호출. 간단한 인사("안녕")에도 classify + respond = 2회 LLM 호출.

**영향**: 응답 시간 증가 (classify 7초 + respond 10초 = ~17초), 비용 2배.

---

### 🔵 개선 사항 (Enhancement)

#### E-1. 세션쌍 UI 통합 부재

**현상**: 프론트엔드에서 VTuber와 서브 워커 세션이 독립적인 세션 카드로 표시됨 (스크린샷: "ㅋㅋ" + "ㅋㅋ_cli"). 사용자가 서브 워커 세션을 직접 클릭하여 명령을 보내면 VTuber 와의 연동이 깨질 수 있음.

**개선**: VTuber 세션 카드에 서브 워커 세션을 하위 항목으로 표시하거나, 서브 워커 세션을 UI에서 숨기고 VTuber 탭 내에서만 상태를 확인할 수 있도록 변경.

---

#### E-2. Avatar 상태 Emotion → Motion 매핑 부재

**현상**: `avatar_state_manager.py`에서 `emotion`과 `motion_group`이 독립적으로 관리됨. 감정에 따라 자동으로 모션이 트리거되지 않음 (예: `joy` → "Happy" 모션 자동 재생 없음). 터치 인터랙션에서만 모션이 트리거됨.

---

#### E-3. 서브 워커 작업 진행상황 실시간 스트리밍 없음

**현상**: 서브 워커가 작업 중일 때 VTuber/사용자에게 진행 상황이 전달되지 않음. 완료 후에만 `[SUB_WORKER_RESULT]` 1회 전달. 장시간 작업 시 사용자 경험 저하.

---

#### E-4. ThinkingTrigger 고도화 — 컨텍스트 인지

**현상**: Thinking Trigger가 단순 idle 타이머 기반. 시간대(낮/밤), 이전 대화 주제, 서브 워커 작업 진행 여부 등을 고려하지 않음.

---

#### E-5. VTuber 프롬프트의 캐릭터 커스터마이징 미지원

**현상**: `prompts/vtuber.md`가 단일 고정 프롬프트. 캐릭터별 성격, 어조, 반말/존댓말 설정, 캐릭터 배경 스토리 등을 세션/모델별로 커스터마이징할 수 있는 구조가 없음.

---

#### E-6. 메모리 공유의 불완전성

**현상**: VTuber ↔ Sub-Worker가 `working_dir`을 공유하여 Memory 디렉토리를 공유하지만, VTuber의 대화 내용(채팅 히스토리)은 CLI의 memory에 직접 반영되지 않음. CLI가 VTuber의 이전 대화 맥락을 알 수 없어 "VTuber가 사용자에게 어떤 맥락으로 설명했는지" 알 수 없음.

---

#### E-7. `[SILENT]` 응답 시 SSE 이벤트 누락

**현상**: `vtuber_think_node`가 `[SILENT]`를 반환하면 `is_complete=True`만 설정하고 `final_answer` 없이 종료. 이 경우 프론트엔드 SSE에서 별도의 이벤트가 발생하지 않아, VTuber가 잠시 "생각하는 표정"을 보여주는 등의 비언어적 표현이 불가능함.

---

## 4. 개선 계획

### Phase 1: Critical 수정 (즉시)

#### 4.1 `template-vtuber.json` 워크플로우 생성

VTuber 전용 워크플로우 그래프 정의 파일을 생성한다.

```
START → memory_gate → memory_inject → vtuber_classify
                                          │
                      ┌───────────────────┼───────────────────┐
                      ▼                   ▼                   ▼
              vtuber_respond      vtuber_delegate       vtuber_think
                      │                   │                   │
                      ▼                   ▼                   ▼
                  output_gate         output_gate        output_gate(조건부)
                      │                   │                   │
                      └───────────────────┴───────────────────┘
                                          │
                                          ▼
                                   memory_write → END
```

**작업 내용**:
1. `backend/workflows/template-vtuber.json` 생성
2. `backend/service/workflow/templates.py`에 `create_vtuber_template()` 추가
3. `ALL_TEMPLATES` 리스트에 등록
4. `agent_session.py` `_resolve_workflow()`의 `_template_factories`에 등록

---

#### 4.2 서브 워커 링크 속성 설정

`create_agent_session()` 내에서 `request.linked_session_id`와 `request.session_type`이 제공된 경우 `AgentSession` 객체에 자동으로 할당하도록 수정.

**파일**: `agent_session_manager.py`
**위치**: `create_agent_session()` 내, `agent` 객체 생성 직후

```python
# 세션 등록 직후, "✅ AgentSession created successfully" 로그 직전에 추가:
if request.linked_session_id:
    agent._linked_session_id = request.linked_session_id
if request.session_type:
    agent._session_type = request.session_type
```

---

### Phase 2: Important 수정 (1주 내)

#### 4.3 세션 복원 시 링크 정보 보존

`controller/agent_controller.py`의 `restore_session()`에서 `linked_session_id`와 `session_type`을 `CreateSessionRequest`에 포함.

```python
request = CreateSessionRequest(
    ...
    linked_session_id=params.get("linked_session_id"),
    session_type=params.get("session_type"),
)
```

추가로, VTuber 세션 복원 시 이미 존재하는 서브 워커 세션과의 재연결 로직 구현. 서브 워커 세션이 없으면 새로 생성, 있으면 링크만 재설정.

---

#### 4.4 Thinking Trigger 초기 등록

VTuber 세션 생성 시 `ThinkingTriggerService`에 즉시 등록하여 초기 인사 가능하도록 변경.

**파일**: `agent_session_manager.py`
**위치**: VTuber 서브 워커 페어링 블록 내, agent 생성 완료 후

```python
# VTuber 세션 생성 완료 후 즉시 Thinking Trigger에 등록
try:
    from service.vtuber.thinking_trigger import get_thinking_trigger_service
    get_thinking_trigger_service().record_activity(session_id)
except Exception:
    pass
```

---

#### 4.5 메시지 드랍 방지 — 재시도 큐 도입

`AlreadyExecutingError` 발생 시 메시지를 폐기하지 않고, 세션의 inbox에 보관하여 다음 실행 완료 후 자동으로 처리하는 구조 도입.

**설계**:
```
_notify_linked_vtuber() or _send_dm()
  │
  ├── execute_command() 성공 → 완료
  │
  └── AlreadyExecutingError →
        inbox.deliver(target_session_id, content, pending=True)
        └── 다음 execute_command 완료 시 inbox를 체크하고 pending DM 자동 처리
```

---

#### 4.6 ClassifyNode 경량화 — 규칙 기반 fast-path 확장

현재 `[THINKING_TRIGGER]`, `[SUB_WORKER_RESULT]`만 fast-path. 추가 패턴 매칭으로 LLM 호출 최소화.

```python
# 규칙 기반 fast-path 확장
DIRECT_PATTERNS = [
    r"^(안녕|하이|ㅎㅇ|hello|hi|hey)\b",       # 인사
    r"^(ㅋ{2,}|ㅎ{2,}|ㅠ{2,}|ㅜ{2,})",          # 감탄사
    r"^(고마워|땡큐|thx|thanks)\b",              # 감사
    r"^(잘자|바이|bye)\b",                        # 작별
]
DELEGATE_PATTERNS = [
    r"(코드|파일|실행|빌드|테스트|git|npm|docker)",
    r"(만들어|수정해|삭제해|분석해|검색해)",
]
```

---

### Phase 3: Enhancement (2~3주)

#### 4.7 세션쌍 UI 통합

VTuber 세션 카드에서 서브 워커 세션을 하위 항목으로 표시. 서브 워커 세션 직접 접근 방지.

**프론트엔드 변경**:
- `useVTuberStore.ts`: 링크된 세션쌍 정보 관리
- 세션 리스트에서 `session_type === "sub"` && `linked_session_id`가 있는 세션은 개별 카드로 표시하지 않기
- VTuber 카드 하단에 "서브 워커 상태: 실행중/대기중" 표시

---

#### 4.8 서브 워커 작업 진행 스트리밍

서브 워커 작업 중 중간 출력을 VTuber에게 전달하여 실시간 진행 표시.

**설계**:
```
서브 워커 실행 중
  └── 각 tool_call 완료 시 → 중간 스트리밍 콜백
        └── VTuber Avatar: "작업 중" 표정 유지 + 진행 로그 표시

서브 워커 완료
  └── [SUB_WORKER_RESULT] 최종 보고
```

---

#### 4.9 Emotion → Motion 자동 매핑

`avatar_state_manager.py`의 `update_state()`에서 emotion 변경 시 모델의 emotionMap을 참조하여 자동으로 적절한 motion을 트리거.

```python
# emotion별 기본 모션 매핑 (model_registry.json에 정의)
EMOTION_MOTION_MAP = {
    "joy": {"motion_group": "Happy", "motion_index": 0},
    "sadness": {"motion_group": "Sad", "motion_index": 0},
    "anger": {"motion_group": "Angry", "motion_index": 0},
    "surprise": {"motion_group": "Surprise", "motion_index": 0},
    "neutral": {"motion_group": "Idle", "motion_index": 0},
}
```

---

#### 4.10 DelegateNode LLM 호출 최적화

위임 시 2회 LLM 호출을 1회로 합치는 Single-call 방식.

**현재**: task 추출 LLM + ack 생성 LLM = 2회
**개선**: 하나의 프롬프트로 `{task, ack}` JSON 응답을 받거나, ack를 템플릿 기반으로 생성

```python
# ack를 규칙 기반으로 생성 (LLM 호출 제거)
ACK_TEMPLATES = [
    "[joy] 알겠어요! 바로 처리할게요~",
    "[smirk] 오 재밌겠다~ 바로 시작할게요!",
    "[neutral] 네, 지금 작업 시작하겠습니다.",
]
# 랜덤 선택 또는 이전 대화 톤에 따라 선택
```

---

#### 4.11 VTuber 캐릭터 커스터마이징

`prompts/vtuber.md`를 캐릭터별로 확장 가능한 구조로 변경.

```
prompts/
  vtuber_base.md          ← 공통 구조 (task handling, thinking behavior)
  vtuber_characters/
    default.md            ← 기본 캐릭터
    mao_pro.md            ← Mao Pro 모델 전용 캐릭터
    custom_template.md    ← 사용자 생성 캐릭터 템플릿
```

세션 생성 시 모델에 연결된 캐릭터 파일을 system prompt에 주입.

---

#### 4.12 ThinkingTrigger 컨텍스트 인지

단순 idle 타이머 대신 다양한 컨텍스트를 고려.

```python
class ThinkingTriggerService:
    async def _should_trigger(self, session_id: str) -> tuple[bool, str]:
        """컨텍스트 기반 트리거 결정"""

        # 1. 서브 워커 작업 완료 직후 → 결과 공유
        if self._pending_sub_worker_results.get(session_id):
            return True, "[SUB_WORKER_RESULT_PENDING]"

        # 2. 시간대 기반 인사
        hour = datetime.now().hour
        if hour in (9, 12, 18) and not self._greeted_today.get(session_id, {}).get(hour):
            return True, "[TIME_GREETING]"

        # 3. 장기 idle (10분+) → 자연스러운 말 걸기
        if idle > 600:
            return True, "[THINKING_TRIGGER]"

        return False, ""

---

## 6. 구현 현황

> **최종 업데이트**: 2026-03-30

| # | 항목 | 상태 | 수정 파일 |
|---|------|------|-----------|
| C-1 | template-vtuber 워크플로우 | ✅ 완료 | `templates.py`, `agent_session.py` |
| C-2 | Sub-Worker agent 링크 속성 미설정 | ✅ 완료 | `agent_session_manager.py` |
| I-1 | 세션 복원 시 링크 손실 | ✅ 완료 | `agent_controller.py` |
| I-2 | ThinkingTrigger 초기 등록 | ✅ 완료 | `agent_session_manager.py` |
| I-3 | 메시지 드롭 방지 | ✅ 완료 | `agent_executor.py`, `vtuber_delegate_node.py` |
| I-4 | DelegateNode LLM 최적화 | ✅ 완료 | `vtuber_delegate_node.py` |
| 4.6 | ClassifyNode 경량화 | ⏭️ 스킵 | (현행 유지) |
| E-1 | 세션 페어 UI 통합 | ✅ 완료 | `Sidebar.tsx` |
| E-2 | Emotion→Motion 자동 매핑 | ✅ 완료 | `avatar_state_manager.py`, `live2d_model_manager.py`, `vtuber_controller.py` |
| E-3 | 서브 워커 진행 상태 스트리밍 | ✅ 완료 | `agent_executor.py` |
| E-4 | ThinkingTrigger 컨텍스트 인지 | ✅ 완료 | `thinking_trigger.py` |
| E-5 | 캐릭터 커스터마이징 | ✅ 완료 | `vtuber_controller.py`, `prompts/vtuber_characters/` |
| E-6 | 메모리 공유 강화 | ✅ 완료 | `vtuber_delegate_node.py` |
| E-7 | [SILENT] 비언어 표현 | ✅ 완료 | `vtuber_think_node.py` |
```

---

## 5. 우선순위 로드맵

```
Week 0 (즉시)
  ├── [C-1] template-vtuber.json 생성 ★★★
  └── [C-2] 서브 워커 링크 속성 설정 ★★★

Week 1
  ├── [I-1] 세션 복원 링크 보존
  ├── [I-2] Thinking Trigger 초기 등록
  └── [I-4] DelegateNode LLM 최적화

Week 2
  ├── [I-3] 메시지 드랍 방지 (재시도 큐)
  ├── [I-5] ClassifyNode 규칙 기반 fast-path
  └── [E-1] 세션쌍 UI 통합

Week 3~4
  ├── [E-2] Emotion → Motion 자동 매핑
  ├── [E-3] 서브 워커 작업 진행 스트리밍
  ├── [E-5] 캐릭터 커스터마이징
  └── [E-7] [SILENT] 비언어적 표현

이후
  ├── [E-4] ThinkingTrigger 컨텍스트 인지
  └── [E-6] 메모리 공유 강화
```

---

## 부록: 현재 메시지 태그 프로토콜 요약

| 태그 | 방향 | 용도 | 처리 노드 |
|------|------|------|-----------|
| `[THINKING_TRIGGER]` | System → VTuber | 유휴 시 자기 반성 유도 | vtuber_think |
| `[SUB_WORKER_RESULT]` | Sub-Worker → VTuber | 작업 완료 자동 보고 | vtuber_think |
| `[DELEGATION_REQUEST]` | VTuber → Sub-Worker | 작업 위임 | Sub-Worker의 execute_command |
| `[DELEGATION_RESULT]` | Sub-Worker → VTuber | 작업 결과 보고 | vtuber_think |
| `[SILENT]` | VTuber 내부 | 사용자에게 보이지 않는 내부 사고 | (무출력) |
| `[SYSTEM]` | System → Sub-Worker | DM 수신 알림 | Sub-Worker의 execute_command |
