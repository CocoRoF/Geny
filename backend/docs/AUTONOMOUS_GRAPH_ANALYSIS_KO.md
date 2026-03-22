# Autonomous Graph 실행 로직 심층 분석

> 분석일: 2026-03-21
> 대상: `service/langgraph/autonomous_graph.py` 및 관련 모듈 전체

---

## 목차

1. [시스템 아키텍처 개요](#1-시스템-아키텍처-개요)
2. [실행 흐름 전체 맵](#2-실행-흐름-전체-맵)
3. [State 스키마 분석 (AutonomousState)](#3-state-스키마-분석)
4. [노드별 심층 분석 — Input / Output / LLM 호출 여부](#4-노드별-심층-분석)
5. [라우팅 로직 분석 (Conditional Edges)](#5-라우팅-로직-분석)
6. [LLM 호출 횟수 분석 (경로별)](#6-llm-호출-횟수-분석)
7. [시간 소모 분석 — 병목 지점](#7-시간-소모-분석)
8. [Resilience 인프라 분석](#8-resilience-인프라-분석)
9. [Workflow Executor 통합 구조](#9-workflow-executor-통합-구조)
10. [발견된 문제점 및 비효율](#10-발견된-문제점-및-비효율)
11. [부록: 노드 I/O 전체 매트릭스](#11-부록-노드-io-전체-매트릭스)

---

## 1. 시스템 아키텍처 개요

### 핵심 컴포넌트 스택

```
사용자 입력
  ↓
AgentSession.invoke() / .astream()
  ↓
WorkflowExecutor.compile() — WorkflowDefinition(JSON) → CompiledStateGraph
  ↓
LangGraph StateGraph (AutonomousState) — 30 노드, 5 조건부 라우터
  ↓
각 노드 → ClaudeCLIChatModel.ainvoke() → ClaudeProcess(subprocess)
  ↓
Claude CLI (stdin/stdout stream-json) → Anthropic API
```

### 컴포넌트 역할

| 컴포넌트 | 파일 | 역할 |
|----------|------|------|
| `AgentSession` | `agent_session.py` | 세션 생명주기 관리, 실행 진입점 |
| `WorkflowExecutor` | `workflow_executor.py` | JSON 워크플로우 → LangGraph 컴파일 |
| `AutonomousGraph` | `autonomous_graph.py` | 난이도 기반 그래프 정의 (Legacy — 현재는 WorkflowExecutor 사용) |
| `AutonomousState` | `state.py` | 40+ 필드의 상태 스키마 |
| `ClaudeCLIChatModel` | `claude_cli_model.py` | LangChain `BaseChatModel` 래퍼 |
| `ContextWindowGuard` | `context_guard.py` | 토큰 사용량 추정/경고/차단 |
| `SessionFreshness` | `session_freshness.py` | 유휴 세션 감지/부활 |
| `AutonomousPrompts` | `prompt/sections.py` | 각 노드의 프롬프트 템플릿 |

### 실행 경로: JSON 워크플로우 우선

현재 시스템은 `autonomous_graph.py`의 하드코딩된 `build()` 메서드 대신,
**`template-autonomous.json` 워크플로우 정의 → `WorkflowExecutor.compile()`** 경로를 사용한다.

```
AgentSession._build_graph()
  → _load_workflow_definition()
     → WorkflowStore.load("template-autonomous")
  → WorkflowExecutor(workflow, context).compile()
  → self._graph = CompiledStateGraph
```

`AutonomousGraph.build()`는 사실상 **dead code**이며, `WorkflowExecutor`가 동일한 토폴로지를 JSON에서 재구성한다.

---

## 2. 실행 흐름 전체 맵

### 2.1 토폴로지 (30 노드, 37 엣지)

```
START
  │
  ▼
[memory_inject] ─── (no-op 또는 메모리 로드)
  │
  ▼
[relevance_gate] ─── LLM 호출 (chat 모드) 또는 pass-through
  │
  ├─ skip → END (비관련 메시지)
  │
  ▼ continue
[guard_classify] ─── 컨텍스트 예산 체크 (LLM 없음)
  │
  ▼
[classify_difficulty] ─── LLM 호출: easy/medium/hard 분류
  │
  ▼
[post_classify] ─── 이터레이션 증가, 완료 신호 감지 (LLM 없음)
  │
  ├── easy ──────────────────────────────┐
  ├── medium ────────────────────┐       │
  └── hard ──────┐               │       │
                 │               │       │
```

#### Easy 경로 (최소 2회 LLM)
```
guard_direct → direct_answer → post_direct → END
```

#### Medium 경로 (최소 3회 LLM, 리트라이 시 +2N)
```
guard_answer → answer → post_answer → guard_review → review → post_review
   │                                                              │
   │    ┌──── approved ──────────────────────────────── END ◄──────┤
   │    │                                                          │
   │    └──── retry → iter_gate_medium ── continue ────────────────┘
   │                         │                          (루프백)
   │                         └── stop → END
   └─────────────────────────────────────────────────────────────────
```

#### Hard 경로 (최소 5+N회 LLM, N=TODO 개수)
```
guard_create_todos → create_todos → post_create_todos → guard_execute
                                                            │
    ┌───────────────────────────────────────────────────────┘
    │
    ▼
execute_todo → post_execute → check_progress ─── continue → iter_gate_hard
    ▲                              │                              │
    │                              │                              ├─ continue (루프백)
    │                              │                              └─ stop ─┐
    │                              │                                       │
    │                              └── complete ───────────────────────────┐│
    │                                                                     ││
    └─────────────────────────────────────────────────────────────────────┘│
                                                                          │
    guard_final_review → final_review → post_final_review                 │
         ▲                                    │                           │
         │                                    ▼                           │
         └────────────────────────────────────┘                           │
                                                                          │
    guard_final_answer → final_answer → post_final_answer → END ◄────────┘
```

### 2.2 사용자 제공 로그 기반 실행 흐름 (Easy 경로)

```
시각        이벤트                              설명
09:42:18   execution_start                     그래프 실행 시작
09:42:18   node_enter: Memory Inject           메모리 주입 (no-op)
09:42:18   node_exit:  Memory Inject
09:42:18   node_enter: Relevance Gate          관련성 판단
09:42:18   node_exit:  Relevance Gate          (non-chat → pass-through, 0ms)
09:42:18   edge_decision: Relevance Gate       → continue
09:42:18   node_enter: Guard (Classify)        컨텍스트 예산 체크
09:42:18   node_exit:  Guard (Classify)
09:42:18   node_enter: Classify                ★ LLM 호출 #1: 난이도 분류
09:42:29   node_exit:  Classify                ~11초 (LLM 응답)
09:42:29   edge_decision: Classify             → easy
09:42:29   node_enter: Guard (Direct)          컨텍스트 예산 체크
09:42:29   node_exit:  Guard (Direct)
09:42:29   node_enter: Direct Answer           ★ LLM 호출 #2: 실제 답변 생성
09:42:31   STREAM: Model init                  Tools: 46
09:42:36   Tool: WebSearch query=...           도구 사용
09:43:09   node_exit: Direct Answer            ~40초 (검색+답변)
09:43:09   node_enter: Post Direct             이터레이션/완료 처리
09:43:09   node_exit: Post Direct
09:43:09   execution_complete                  ■ 총 53초

총 LLM 호출: 2회 (classify + direct_answer)
```

---

## 3. State 스키마 분석

### AutonomousState 전체 필드 (40+ 필드)

| 카테고리 | 필드 | 타입 | Reducer | 초기값 | 용도 |
|----------|------|------|---------|--------|------|
| **입력** | `input` | `str` | — | 사용자 입력 | 원본 질문 |
| **대화** | `messages` | `list` | `_add_messages` (append) | `[]` | LangChain 메시지 누적 |
| | `current_step` | `str` | — | `"start"` | 현재 실행 단계명 |
| | `last_output` | `Optional[str]` | — | `None` | 마지막 LLM 출력 |
| **이터레이션** | `iteration` | `int` | — | `0` | 전역 반복 카운터 |
| | `max_iterations` | `int` | — | `50` | 반복 상한 |
| **난이도** | `difficulty` | `Optional[str]` | — | `None` | easy/medium/hard |
| **Medium 경로** | `answer` | `Optional[str]` | — | `None` | 생성된 답변 |
| | `review_result` | `Optional[str]` | — | `None` | approved/rejected |
| | `review_feedback` | `Optional[str]` | — | `None` | 리뷰 피드백 |
| | `review_count` | `int` | — | `0` | 리뷰 횟수 |
| **Hard 경로** | `todos` | `List[TodoItem]` | `_merge_todos` | `[]` | TODO 리스트 |
| | `current_todo_index` | `int` | — | `0` | 현재 TODO 인덱스 |
| **최종** | `final_answer` | `Optional[str]` | — | `None` | 최종 응답 |
| **완료** | `completion_signal` | `Optional[str]` | — | `"none"` | 완료 신호 |
| | `completion_detail` | `Optional[str]` | — | `None` | 완료 상세 |
| | `error` | `Optional[str]` | — | `None` | 에러 메시지 |
| | `is_complete` | `bool` | — | `False` | 완료 플래그 |
| **Resilience** | `context_budget` | `Optional[ContextBudget]` | — | `None` | 컨텍스트 예산 |
| | `fallback` | `Optional[FallbackRecord]` | — | `None` | 폴백 기록 |
| **메모리** | `memory_refs` | `List[MemoryRef]` | `_merge_memory_refs` | `[]` | 주입된 메모리 참조 |
| | `memory_context` | `Optional[str]` | `_last_wins` | `None` | 메모리 텍스트 |
| **Chat** | `is_chat_message` | `bool` | — | `False` | 채팅 모드 여부 |
| | `relevance_skipped` | `bool` | — | `False` | 관련성 스킵 여부 |
| **메타** | `metadata` | `Dict` | — | `{}` | 추가 메타데이터 |

### ContextBudget 서브타입

```python
class ContextBudget(TypedDict, total=False):
    estimated_tokens: int       # 추정 토큰 수
    context_limit: int          # 모델 컨텍스트 한도
    usage_ratio: float          # 사용 비율 (0.0~1.0)
    status: str                 # ok / warn / block / overflow
    compaction_count: int       # 컴팩션 횟수
```

---

## 4. 노드별 심층 분석

### 범례 표기

- ★ = LLM 호출 발생
- ○ = LLM 호출 없음 (순수 로직)
- 🔄 = 루프 가능

### 4.1 공통 진입부

#### `memory_inject` ○
| 항목 | 설명 |
|------|------|
| **Input** | `state.messages`, `state.iteration`, `state.memory_refs` |
| **Output** | `{ memory_refs: [...] }` (또는 `{}`) |
| **LLM 호출** | 없음 |
| **로직** | 현재 no-op (실제 메모리 주입은 WorkflowExecutor의 `MemoryInjectNode`에서 수행). 첫 턴 또는 10턴마다 장기 메모리를 검색해 state에 주입. |
| **소요 시간** | ~0ms |

#### `relevance_gate` ★ (chat 모드) / ○ (일반 모드)
| 항목 | 설명 |
|------|------|
| **Input** | `state.is_chat_message`, `state.input`, `state.metadata.{agent_name, agent_role}` |
| **Output** | `{ relevance_skipped: bool }` + `{ is_complete, final_answer, current_step }` (스킵 시) |
| **LLM 호출** | chat 모드에서만 1회 (structured output: `RelevanceOutput`) |
| **로직** | `is_chat_message == False`이면 즉시 pass-through (`{}`를 반환). chat 모드에서는 에이전트의 역할/이름 기반으로 메시지 관련성을 판단. 실패 시 YES/NO 폴백. |
| **소요 시간** | 일반 모드: 0ms / chat 모드: 2~5초 |

#### `guard_classify` ○
| 항목 | 설명 |
|------|------|
| **Input** | `state.messages` |
| **Output** | `{ context_budget: ContextBudget }` |
| **LLM 호출** | 없음 |
| **로직** | 메시지 리스트를 순회하며 문자 수 기반 토큰 추정 (`len(text) / 3.0`). `warn_ratio` (75%), `block_ratio` (90%) 임계값 체크. |
| **소요 시간** | ~1ms |

#### `classify_difficulty` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input` |
| **Output** | `{ difficulty: Difficulty, current_step, messages: [response], last_output }` |
| **LLM 호출** | 1회 — `AutonomousPrompts.classify_difficulty()` |
| **프롬프트** | 입력을 분석하여 easy/medium/hard 중 하나만 응답하도록 지시 |
| **파싱** | 응답 텍스트에서 "easy"/"medium"/"hard" 문자열 검색 |
| **소요 시간** | **~8-15초** (분류를 위한 전체 LLM 호출) |

#### `post_classify` ○
| 항목 | 설명 |
|------|------|
| **Input** | `state.iteration`, `state.last_output` |
| **Output** | `{ iteration: +1, current_step, completion_signal, completion_detail }` |
| **LLM 호출** | 없음 |
| **로직** | 이터레이션 증가, 완료 신호 감지 (여기서는 `detect_completion=False`), 트랜스크립트 기록 |
| **소요 시간** | ~0ms |

### 4.2 Easy 경로

#### `guard_direct` ○
(guard_classify와 동일한 구조의 컨텍스트 가드)

#### `direct_answer` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input` |
| **Output** | `{ answer, final_answer, messages: [response], last_output, is_complete: True }` |
| **LLM 호출** | 1회 — 사용자 입력을 직접 전달 |
| **프롬프트** | `input_text` 그대로 (별도 래핑 없음) |
| **소요 시간** | **~10-45초** (질문 복잡도/도구 사용에 따라) |

#### `post_direct` ○
| 항목 | 설명 |
|------|------|
| **Input** | `state.iteration`, `state.last_output` |
| **Output** | `{ iteration: +1, completion_signal, completion_detail }` |
| **LLM 호출** | 없음 |
| **소요 시간** | ~0ms |

### 4.3 Medium 경로

#### `guard_answer` ○ → 컨텍스트 가드
#### `answer` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input`, `state.review_count`, `state.review_feedback`, `state.context_budget` |
| **Output** | `{ answer, messages: [response], last_output, current_step }` |
| **LLM 호출** | 1회 |
| **프롬프트** | 첫 시도: `input_text` / 재시도: `AutonomousPrompts.retry_with_feedback()` |
| **소요 시간** | ~10-30초 |

#### `post_answer` ○ → 이터레이션/완료 (detect_completion=False)
#### `guard_review` ○ → 컨텍스트 가드
#### `review` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input`, `state.answer`, `state.review_count` |
| **Output** | `{ review_result, review_feedback, review_count, messages, last_output }` |
| **LLM 호출** | 1회 — `AutonomousPrompts.review()` |
| **파싱** | `VERDICT: approved/rejected` + `FEEDBACK:` 포맷 파싱 |
| **특수 로직** | `review_count >= max_review_retries (3)` → 강제 승인 |
| **소요 시간** | ~5-15초 |

#### `post_review` ○ → 이터레이션/완료 감지
#### `iter_gate_medium` ○ → 이터레이션 한도/컨텍스트/완료 신호 체크 🔄

### 4.4 Hard 경로

#### `guard_create_todos` ○ → 컨텍스트 가드
#### `create_todos` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input` |
| **Output** | `{ todos: List[TodoItem], current_todo_index: 0, messages, last_output }` |
| **LLM 호출** | 1회 — `AutonomousPrompts.create_todos()` |
| **파싱** | JSON 파싱 (markdown 코드블록 제거 포함) |
| **특수 로직** | TODO 개수 cap = 20, JSON 실패 시 단일 TODO 폴백 |
| **소요 시간** | ~10-20초 |

#### `post_create_todos` ○ → 이터레이션 (detect_completion=False)
#### `guard_execute` ○ → 컨텍스트 가드 🔄
#### `execute_todo` ★ 🔄
| 항목 | 설명 |
|------|------|
| **Input** | `state.input`, `state.todos`, `state.current_todo_index`, `state.context_budget` |
| **Output** | `{ todos: [updated_todo], current_todo_index: +1, messages, last_output }` |
| **LLM 호출** | 1회 (TODO당) — `AutonomousPrompts.execute_todo()` |
| **특수 로직** | 예산 압박 시 이전 결과 200자로 절단, 실패 시 FAILED 마킹 후 다음으로 진행 |
| **소요 시간** | TODO당 ~10-60초 |

#### `post_execute` ○ → 이터레이션/완료 🔄
#### `check_progress` ○ 🔄
| 항목 | 설명 |
|------|------|
| **Input** | `state.todos`, `state.current_todo_index` |
| **Output** | `{ current_step, metadata.{completed_todos, failed_todos, total_todos} }` |
| **LLM 호출** | 없음 — 순수 인덱스/상태 카운트 |
| **소요 시간** | ~0ms |

#### `iter_gate_hard` ○ 🔄 → 이터레이션/컨텍스트/완료 체크
#### `guard_final_review` ○ → 컨텍스트 가드
#### `final_review` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input`, `state.todos`, `state.context_budget` |
| **Output** | `{ review_feedback, messages, last_output }` |
| **LLM 호출** | 1회 — `AutonomousPrompts.final_review()` |
| **소요 시간** | ~10-20초 |

#### `post_final_review` ○
#### `guard_final_answer` ○ → 컨텍스트 가드
#### `final_answer` ★
| 항목 | 설명 |
|------|------|
| **Input** | `state.input`, `state.todos`, `state.review_feedback`, `state.context_budget` |
| **Output** | `{ final_answer, messages, last_output, is_complete: True }` |
| **LLM 호출** | 1회 — `AutonomousPrompts.final_answer()` |
| **소요 시간** | ~10-30초 |

#### `post_final_answer` ○

---

## 5. 라우팅 로직 분석

### 5개 Conditional Router

| # | 위치 | 라우터 함수 | 입력 필드 | 분기 결과 | 판단 기준 |
|---|------|-----------|----------|----------|----------|
| 1 | `relevance_gate` → | `_route_after_relevance` | `relevance_skipped`, `is_complete`, `current_step` | `continue` / `skip` | 관련성 결과 |
| 2 | `post_classify` → | `_route_by_difficulty` | `error`, `difficulty` | `easy` / `medium` / `hard` / `end` | 분류 결과 |
| 3 | `post_review` → | `_route_after_review` | `is_complete`, `error`, `completion_signal`, `review_result` | `approved` / `retry` / `end` | 리뷰 결과 |
| 4 | `check_progress` → | `_route_after_progress_check` | `is_complete`, `error`, `completion_signal`, `current_todo_index`, `todos` | `continue` / `complete` | TODO 진행 상태 |
| 5 | `iter_gate_{medium,hard}` → | `_route_iteration_gate` | `is_complete`, `error` | `continue` / `stop` | iteration gate 결과 |

### 라우팅 우선순위 패턴

모든 라우터는 동일한 체크 패턴을 따른다:
1. `error` → 즉시 종료
2. `is_complete` → 종료
3. `completion_signal` → COMPLETE/BLOCKED → 종료
4. 본래의 비즈니스 로직 체크

---

## 6. LLM 호출 횟수 분석

### 경로별 최소/최대 LLM 호출 수

| 경로 | 최소 LLM 호출 | 최대 LLM 호출 | 조건 |
|------|--------------|--------------|------|
| **Easy** (일반 모드) | **2** | **2** | classify + direct_answer |
| **Easy** (chat 모드) | **3** | **3** | relevance + classify + direct_answer |
| **Medium** (일반, 1회 승인) | **3** | **3** | classify + answer + review |
| **Medium** (일반, 리트라이) | **3 + 2N** | **3 + 2×3 = 9** | N = 리트라이 횟수 (최대 3) |
| **Hard** (일반, T개 TODO) | **4 + T** | **4 + 20 = 24** | classify + create_todos + T×execute + final_review + final_answer |
| **Hard** (chat, T개 TODO) | **5 + T** | **5 + 20 = 25** | +relevance |

### 사용자 예시 분석 (Easy 경로)

```
"2025 한국 시리즈 우승팀은?" → Easy
총 시간: 53초
├── classify_difficulty: ~11초 (LLM #1)
├── direct_answer: ~40초 (LLM #2 + WebSearch)
├── 나머지 노드들: ~2초 (가드, 포스트, 메모리)
```

**핵심 관찰**: 단순 질문에 대해 `classify_difficulty` LLM 호출이 **전체 시간의 21%** (11초/53초)를 차지.
이 질문은 명백히 EASY이므로, 분류 LLM 호출은 순수 오버헤드.

---

## 7. 시간 소모 분석 — 병목 지점

### 병목 #1: 난이도 분류 LLM 호출 (모든 경로)

모든 요청이 반드시 `classify_difficulty` LLM 호출을 거친다.
- **소요**: 8~15초
- **문제**: 대부분의 질문은 분류 없이도 직접 처리 가능
- **규모**: Easy 질문 비율이 60-80%로 추정되며, 이 모두가 불필요한 분류 비용 부담

### 병목 #2: Guard 노드의 과도한 중복 (모든 경로)

컨텍스트 가드가 **모든 LLM 호출 전**에 존재:
- Easy: `guard_classify` + `guard_direct` = 2회
- Medium: `guard_classify` + `guard_answer` + `guard_review` = 3회 (리트라이 시 +2N)
- Hard: `guard_classify` + `guard_create_todos` + N×`guard_execute` + `guard_final_review` + `guard_final_answer` = 4+N회

각 가드는 ~1ms이지만, **노드 진입/퇴장 로깅** 비용이 가드 로직보다 크다.
LangGraph 노드 전환 오버헤드(상태 직렬화/역직렬화)도 누적된다.

### 병목 #3: Post-Model 노드의 과도한 분리 (모든 경로)

`post_{position}` 노드가 **모든 LLM 호출 후**에 존재:
- `post_classify`, `post_direct`, `post_answer`, `post_review`,
  `post_create_todos`, `post_execute`, `post_final_review`, `post_final_answer`

각각이 하는 일:
1. `iteration += 1`
2. 완료 신호 감지 (regex)
3. 트랜스크립트 기록 (메모리)

이 3가지는 **LLM 호출 노드 자체에 인라인**할 수 있는 로직.

### 병목 #4: Medium 경로의 자체 리뷰 (Medium)

**같은 모델**이 답변을 생성하고, **같은 모델**이 그 답변을 리뷰한다.
- Self-review의 효과성은 제한적
- 첫 시도에 reject 될 확률 × 추가 2회 LLM 호출 = 비용 증가
- 최대 3회 리트라이 후 결국 강제 승인 → 리뷰 루프 자체가 무의미한 경우 많음

### 병목 #5: Hard 경로의 Final Review + Final Answer 이중 처리

`final_review` (모든 TODO 결과 리뷰) + `final_answer` (최종 합성)는 사실상
**동일한 컨텍스트를 두 번 처리**하는 것:
- `final_review`: 입력 + TODO 결과 → 리뷰 텍스트
- `final_answer`: 입력 + TODO 결과 + 리뷰 텍스트 → 최종 답변

리뷰 텍스트를 최종 답변에 포함하는 것보다, **한 번의 합성 호출**로 충분.

### 병목 #6: Relevance Gate의 비효율 (Chat 모드)

Chat 모드에서 `relevance_gate`는:
1. Structured output 시도 (LLM 1회)
2. 파싱 실패 시 → YES/NO 폴백 (LLM 추가 1회)

**최악의 경우 2회 LLM 호출**을 관련성 판단만으로 소비.

### 시간 비용 요약 (Easy 경로 기준)

```
분류 (classify):        ~11초  ████████████  (21%)
가드+포스트 (5개 노드):   ~2초  ██            (4%)
실제 답변 (direct):     ~40초  ████████████████████████████████████████  (75%)
─────────────────────────────
총합:                   ~53초
```

**순수 오버헤드**: ~13초 (25%) — 분류 + 가드/포스트 노드들

---

## 8. Resilience 인프라 분석

### Context Guard (`context_guard.py`)

- **토큰 추정**: `len(text) / 3.0` (매우 보수적)
- **한도**: 모든 Claude 모델 = 200K 토큰
- **임계값**: warn=75%, block=90%
- **컴팩션**: 메시지 truncation (실제 구현은 세션 레벨)
- **문제점**: 문자 기반 추정은 한국어에서 더 보수적 (3 chars/token이지만 한글은 실제로 ~2 chars/token)

### Model Fallback (`model_fallback.py`)

- **에러 분류**: regex 기반 `classify_error()` → 7가지 FailureReason
- **복구 가능**: rate_limited, overloaded, timeout, network_error
- **대기 시간**: rate=5s, overloaded=3s, timeout=2s × (attempt+1)
- **현황**: `AutonomousGraph._resilient_invoke()`에서 **모델 교체 없이** 재시도만 수행 (ModelFallbackRunner는 사용되지 않음)

### Completion Detection (`resilience_nodes.py`)

- **패턴**: `[TASK_COMPLETE]`, `[BLOCKED: ...]`, `[ERROR: ...]`, `[CONTINUE: ...]`
- **레거시 폴백**: "작업이 완료되었습니다", "task completed" 등 문자열 매칭
- **문제점**: Claude CLI는 이 프로토콜을 자발적으로 출력하지 않으므로, 시스템 프롬프트에 해당 프로토콜을 주입하지 않는 한 항상 `NONE` 반환

### Session Freshness (`session_freshness.py`)

- **유휴 감지**: `idle_threshold_seconds` (기본 300초)
- **부활**: 세션 죽이지 않고, 타임스탬프 리셋 후 프로세스 재시작
- **하드 리셋**: 극단적 경우 (나이/이터레이션 초과)

---

## 9. Workflow Executor 통합 구조

### 컴파일 과정

```
WorkflowDefinition (JSON)
  │
  ├── nodes: [{id, node_type, config, ...}]
  ├── edges: [{source, target, source_port, ...}]
  │
  ▼ WorkflowExecutor.compile()
  │
  ├── 1. validate workflow graph (start/end 존재, 연결 무결성)
  ├── 2. NodeRegistry.get(node_type) → BaseNode 인스턴스
  ├── 3. StateGraph(AutonomousState) 생성
  ├── 4. 각 노드 → _make_node_function(node, config, context) 래핑
  ├── 5. 각 엣지 → add_edge() 또는 add_conditional_edges()
  │     └── 조건부 엣지: get_routing_function(config) 또는 fallback router
  ├── 6. graph.compile()
  │
  ▼ CompiledStateGraph
```

### 현재의 이중 구조 문제

1. `AutonomousGraph.build()`: 30개 노드를 **하드코딩**으로 등록
2. `template-autonomous.json` + `WorkflowExecutor`: 28개 노드를 **JSON 워크플로우**로 등록

실제로는 #2만 사용되며, #1은 dead code.
그러나 `AutonomousGraph` 클래스의 인라인 노드 구현체(classify, direct_answer, answer, review 등)는
**NodeRegistry의 BaseNode 서브클래스들과 중복**된다.

---

## 10. 발견된 문제점 및 비효율

### 구조적 문제

| # | 문제 | 영향 | 심각도 |
|---|------|------|--------|
| S1 | **모든 요청에 난이도 분류 LLM 호출 필수** | Easy 질문에도 8-15초 추가 지연 | 🔴 높음 |
| S2 | **Guard/Post 노드 과도한 분리** | 노드 전환 오버헤드 누적, 코드 복잡도 증가 | 🟡 중간 |
| S3 | **Medium 자체 리뷰의 제한적 효과** | 동일 모델 self-review → 불필요한 LLM 호출 | 🟡 중간 |
| S4 | **Hard Final Review + Final Answer 이중 처리** | 동일 컨텍스트 2회 LLM 처리 | 🟡 중간 |
| S5 | **AutonomousGraph 클래스와 WorkflowExecutor 이중 구조** | Dead code 유지 비용, 혼란 | 🟢 낮음 |
| S6 | **Completion Signal 프로토콜 미사용** | 감지 로직 존재하지만 실제 신호 생성 안됨 | 🟢 낮음 |

### 성능 문제

| # | 문제 | 영향 |
|---|------|------|
| P1 | Easy 경로: 2 LLM 호출 (분류 + 답변) → 1회로 가능 | 11초 절약 가능 |
| P2 | Medium 경로: 최소 3 LLM 호출 → 1~2회로 가능 | 15-30초 절약 가능 |
| P3 | Hard 경로: final_review + final_answer → 1회로 가능 | 10-20초 절약 가능 |
| P4 | Chat 모드 relevance gate: 최악 2 LLM → 1회로 가능 | 5-10초 절약 가능 |

### 설계 관찰

1. **과도한 정형화**: 모든 요청을 classify → route → execute → post 파이프라인에 강제 삽입
2. **LLM-as-classifier 비효율**: 간단한 규칙으로 처리 가능한 분류에 LLM 사용
3. **노드 분리 철학의 과적용**: "LangGraph 철학에 따른 관심사 분리"가 성능 비용 초래
4. **Resilience 과설계**: 최대 200K 토큰 컨텍스트에서 대부분의 대화는 10K 미만 — 가드 노드가 거의 항상 "ok" 반환

---

## 11. 부록: 노드 I/O 전체 매트릭스

### 전체 30 노드 Input/Output 매트릭스

| 노드 | 유형 | Reads from State | Writes to State | LLM |
|------|------|-----------------|----------------|-----|
| `memory_inject` | logic | messages, iteration, memory_refs | memory_refs | ✗ |
| `relevance_gate` | model* | is_chat_message, input, metadata | relevance_skipped, is_complete, final_answer, current_step | ✗/★ |
| `guard_classify` | logic | messages | context_budget | ✗ |
| `classify_difficulty` | model | input | difficulty, current_step, messages, last_output | ★ |
| `post_classify` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |
| `guard_direct` | logic | messages | context_budget | ✗ |
| `direct_answer` | model | input | answer, final_answer, messages, last_output, is_complete | ★ |
| `post_direct` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |
| `guard_answer` | logic | messages | context_budget | ✗ |
| `answer` | model | input, review_count, review_feedback, context_budget | answer, messages, last_output, current_step | ★ |
| `post_answer` | logic | iteration, last_output | iteration, current_step | ✗ |
| `guard_review` | logic | messages | context_budget | ✗ |
| `review` | model | input, answer, review_count | review_result, review_feedback, review_count, messages, last_output, current_step, (final_answer, is_complete) | ★ |
| `post_review` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |
| `iter_gate_medium` | logic | iteration, max_iterations, context_budget, completion_signal | is_complete | ✗ |
| `guard_create_todos` | logic | messages | context_budget | ✗ |
| `create_todos` | model | input | todos, current_todo_index, messages, last_output, current_step | ★ |
| `post_create_todos` | logic | iteration, last_output | iteration, current_step | ✗ |
| `guard_execute` | logic | messages | context_budget | ✗ |
| `execute_todo` | model | input, todos, current_todo_index, context_budget | todos (updated), current_todo_index, messages, last_output, current_step | ★ |
| `post_execute` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |
| `check_progress` | logic | todos, current_todo_index | current_step, metadata | ✗ |
| `iter_gate_hard` | logic | iteration, max_iterations, context_budget, completion_signal | is_complete | ✗ |
| `guard_final_review` | logic | messages | context_budget | ✗ |
| `final_review` | model | input, todos, context_budget | review_feedback, messages, last_output, current_step | ★ |
| `post_final_review` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |
| `guard_final_answer` | logic | messages | context_budget | ✗ |
| `final_answer` | model | input, todos, review_feedback, context_budget | final_answer, messages, last_output, is_complete | ★ |
| `post_final_answer` | logic | iteration, last_output | iteration, current_step, completion_signal, completion_detail | ✗ |

### LLM 호출 노드 요약 (10개 중 최대 8개 실제 사용)

| LLM 노드 | 프롬프트 | 경로 |
|-----------|---------|------|
| `relevance_gate` | `AutonomousPrompts.check_relevance()` | 공통 (chat 모드) |
| `classify_difficulty` | `AutonomousPrompts.classify_difficulty()` | 공통 |
| `direct_answer` | `{input}` (raw) | Easy |
| `answer` | `{input}` 또는 `retry_with_feedback()` | Medium |
| `review` | `AutonomousPrompts.review()` | Medium |
| `create_todos` | `AutonomousPrompts.create_todos()` | Hard |
| `execute_todo` | `AutonomousPrompts.execute_todo()` | Hard (×N) |
| `final_review` | `AutonomousPrompts.final_review()` | Hard |
| `final_answer` | `AutonomousPrompts.final_answer()` | Hard |

---

*끝. 이 분석을 기반으로 경량화 제안서를 별도 문서로 작성.*
