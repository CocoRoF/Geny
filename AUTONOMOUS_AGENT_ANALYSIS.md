# Autonomous Agent 심층 분석 보고서

> 작성 목적: Autonomous Agent의 현재 구현을 심층 분석하고, 설계된 Enhanced State 필드가
> 실제로 활용되지 않는 갭(Gap)을 식별하여 고도화 방향을 도출한다.

---

## 1. 시스템 아키텍처 개요

### 1.1 두 가지 그래프 모드

| 구분 | Simple Graph | Autonomous Graph |
|------|-------------|------------------|
| **State** | `AgentState` | `AutonomousState` |
| **용도** | 테스트 / 단일 턴 에이전트 | **기본 Agent** (난이도 기반 자율 실행) |
| **위치** | `agent_session.py` `_build_simple_graph()` | `autonomous_graph.py` `AutonomousGraph.build()` |
| **Resilience 노드** | ✅ context_guard, completion_detect | ❌ **없음** |
| **메모리 주입** | ✅ `_memory_manager` 활용 | ❌ **없음** |
| **폴백** | ❌ (세션 레벨에서만) | ❌ **없음** |
| **컨텍스트 예산** | ✅ guard → state 기록 | ❌ **없음** |

**핵심 문제**: 기본 Agent인 Autonomous Graph에는 Phase 1~3에서 설계 · 구현한 Resilience 기능이 전혀 통합되어 있지 않다.

### 1.2 Autonomous Graph 토폴로지

```
START → classify_difficulty ─┬─ [easy]   → direct_answer → END
                             ├─ [medium] → answer → review ─┬─ [approved] → END
                             │                               └─ [retry]    → answer
                             └─ [hard]   → create_todos → execute_todo → check_progress
                                                           ↑                    │
                                                           └── [continue] ─────┘
                                                                [complete] → final_review → final_answer → END
```

총 9개 노드, 3개 조건부 라우터, 3개 실행 경로.

---

## 2. AutonomousState 필드 활용 감사 (Field Utilization Audit)

### 2.1 정의 vs 실제 사용

아래 표에서 **"기록됨"** 은 노드가 해당 필드를 state에 write하는 경우,
**"읽힘"** 은 노드가 해당 필드를 state에서 read하는 경우를 의미한다.

| State 필드 | 정의 위치 | 초기값 | 기록됨 (Write) | 읽힘 (Read) | 실제 활용 여부 |
|------------|-----------|--------|----------------|-------------|----------------|
| `input` | `state.py:210` | 사용자 입력 | ❌ | ✅ 전체 노드 | ✅ |
| `messages` | `state.py:213` | `[]` | ✅ 전체 노드 | ❌ 어디서도 누적 메시지를 읽지 않음 | ⚠️ **쌓기만 하고 안 읽음** |
| `current_step` | `state.py:214` | `"start"` | ✅ 전체 노드 | ❌ | ⚠️ 디버그 전용 |
| `last_output` | `state.py:215` | `None` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| `difficulty` | `state.py:218` | `None` | ✅ classify_difficulty | ✅ _route_by_difficulty | ✅ |
| `answer` | `state.py:221` | `None` | ✅ answer, direct_answer | ✅ review | ✅ |
| `review_result` | `state.py:222` | `None` | ✅ review | ✅ _route_after_review | ✅ |
| `review_feedback` | `state.py:223` | `None` | ✅ review, final_review | ✅ answer(retry), final_answer | ✅ |
| `review_count` | `state.py:224` | `0` | ✅ review | ✅ answer, review | ✅ |
| `todos` | `state.py:227` | `[]` | ✅ create_todos, execute_todo | ✅ execute_todo, check_progress, final_review, final_answer | ✅ |
| `current_todo_index` | `state.py:228` | `0` | ✅ create_todos, execute_todo | ✅ execute_todo, check_progress, _route_after_progress_check | ✅ |
| `final_answer` | `state.py:231` | `None` | ✅ review(approved), direct_answer, final_answer | ✅ invoke에서 결과 추출 | ✅ |
| **`completion_signal`** | `state.py:234` | `"none"` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| **`completion_detail`** | `state.py:235` | `None` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| `error` | `state.py:238` | `None` | ✅ 에러 발생 시 | ✅ invoke에서 확인 | ✅ (에러 전용) |
| `is_complete` | `state.py:239` | `False` | ✅ 여러 노드 | ❌ 그래프 내부에서 안 읽음 | ⚠️ 외부 확인용 |
| **`context_budget`** | `state.py:242` | `None` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| **`fallback`** | `state.py:245` | `None` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| **`memory_refs`** | `state.py:248` | `[]` | ❌ **기록 안 함** | ❌ | ❌ **미사용** |
| `metadata` | `state.py:251` | `{}` | ✅ check_progress | ⚠️ 일부 | ⚠️ 최소 활용 |

### 2.2 미사용 필드 요약

**완전 미사용 (Defined but Never Touched by Autonomous Graph)**:
1. `completion_signal` — 구조화된 완료 신호. 노드가 모델 응답에서 신호를 파싱하지 않음
2. `completion_detail` — 완료 상세 정보
3. `context_budget` — 컨텍스트 윈도우 사용량 추적
4. `fallback` — 모델 폴백 기록
5. `memory_refs` — 메모리 참조 목록
6. `last_output` — 마지막 출력 (completion_detect의 입력인데 기록 자체가 안 됨)

---

## 3. 노드별 상세 분석

### 3.1 공통 패턴: 모든 노드의 모델 호출 방식

```python
# 모든 9개 노드가 동일한 패턴을 사용:
messages = [HumanMessage(content=prompt)]    # ← 매번 새 메시지 1개
response = await self._model.ainvoke(messages)  # ← bare 호출, 보호 없음
```

**문제점 목록**:

| # | 문제 | 설명 |
|---|------|------|
| P1 | **컨텍스트 무상태** | 매 노드에서 새 `[HumanMessage]` 생성. 누적 messages를 활용하지 않음. 이전 노드의 결과가 prompt 텍스트 내에만 존재하고 LangChain message chain을 형성하지 않음 |
| P2 | **컨텍스트 예산 검사 없음** | 긴 hard task에서 TODO 항목이 15개면 15번 모델 호출. 각 호출의 prompt 길이 검사 없음 |
| P3 | **모델 폴백 없음** | `self._model.ainvoke()` 실패 시 except로 잡아서 `error + is_complete=True`. 재시도나 대체 모델 시도 없이 즉시 종료 |
| P4 | **완료 신호 미파싱** | 모델 응답에서 `[TASK_COMPLETE]`, `[BLOCKED]`, `[ERROR]` 등을 파싱하지 않음. `detect_completion_signal()` 호출이 어디에도 없음 |
| P5 | **메모리 미주입** | 장기/단기 메모리에서 관련 정보를 가져와 prompt에 포함하지 않음 |
| P6 | **트랜스크립트 미기록** | 모델 응답이 short-term memory에 기록되지 않음 |
| P7 | **반복 카운터 없음** | 전체 실행의 iteration 카운터가 없음 (review_count는 medium 경로 전용) |
| P8 | **에러 복구 불가** | hard 경로에서 TODO 1개 실패 시 다음 TODO로 진행하지만, 기본 에러는 전체 그래프를 즉시 종료 |

### 3.2 노드별 상세

#### `classify_difficulty` (분류)
- **하는 일**: 입력을 모델에 보내 easy/medium/hard 파싱
- **누락**:
  - 분류 실패 시 fallback 전략 없음 (default medium으로 가지만 모델 호출 자체 실패 시 즉시 종료)
  - 이 단계에서 메모리를 참조하면 이전 대화 맥락으로 더 정확한 분류 가능

#### `direct_answer` (Easy 경로)
- **하는 일**: 입력을 그대로 모델에 전달, 응답 = 최종 답변
- **누락**:
  - 완료 신호 파싱 없음
  - 컨텍스트 예산 검사 없음 (입력이 길면 문제 가능)

#### `answer` → `review` 루프 (Medium 경로)
- **하는 일**: answer가 응답 생성, review가 VERDICT/FEEDBACK 파싱, rejected면 answer로 재라우팅
- **잘된 점**: retry 로직, max_review_retries 체크, feedback 포함 재시도
- **누락**:
  - review_count만 카운팅. 전체 iteration 미추적
  - 각 retry에서 이전 응답의 messages를 활용하지 않음 (prompt 텍스트로만 feedback 전달)
  - 모델 폴백 없음

#### `create_todos` → `execute_todo` → `check_progress` 루프 (Hard 경로)
- **하는 일**: JSON TODO 파싱 → 각 항목 순차 실행 → progress 체크 → final_review → final_answer
- **잘된 점**: 이전 TODO 결과를 다음 TODO의 prompt에 포함
- **누락**:
  - TODO 개수에 관계없이 무한 루프 가능 (check_progress → execute_todo 반복) — max iteration cap 없음
  - 각 execute_todo에서 모델 폴백 없음
  - execute_todo 실패 시 skip하고 다음으로 가지만, 3번 연속 실패 같은 circuit breaker 없음
  - 전체 TODO 실행 중 컨텍스트 예산 미체크
  - previous_results가 길어질수록 prompt 비대화 → 컴팩션 없음

---

## 4. Simple Graph와의 비교: Resilience 격차

### 4.1 Simple Graph의 Resilience 스택

```
START → context_guard → agent → process_output → [continue/end]
                                                       ↑
                                                  completion_detect (내장)
```

`agent_session.py`의 Simple Graph는:
1. **`context_guard` 노드** — 매 iteration마다 messages 토큰 추정, BLOCK 시 compaction 요청
2. **`_agent_node`** — 모델 호출 후 `_memory_manager.record_message()` 로 트랜스크립트 기록
3. **`_process_output_node`** — `detect_completion_signal()` 호출, iteration 증가, completion_signal/detail 기록
4. **`_should_continue`** — completion_signal 기반 structured 라우팅

### 4.2 Resilience 격차 매트릭스

| Resilience 기능 | Simple Graph | Autonomous Graph | 격차 |
|----------------|-------------|------------------|------|
| Context Guard (토큰 예산) | ✅ 매 iteration | ❌ | **CRITICAL** |
| Completion Signal Detection | ✅ `detect_completion_signal()` | ❌ | **HIGH** |
| Memory Injection | ✅ record + search | ❌ | **HIGH** |
| Transcript Recording | ✅ `record_message()` | ❌ | **MEDIUM** |
| Model Fallback | ❌ (미통합) | ❌ | MEDIUM |
| Iteration Cap (전체) | ✅ max_iterations | ❌ (경로별만) | **HIGH** |
| Error Recovery / Retry | ❌ (단순 종료) | ❌ (단순 종료) | MEDIUM |
| Session Freshness | ✅ `_check_freshness()` | ✅ (세션 레벨) | OK |
| Checkpointing | ✅ 지원 | ✅ 지원 | OK |

---

## 5. 구조적 문제 심층 분석

### 5.1 메시지 누적의 비활용

`AutonomousState.messages`는 `Annotated[list, _add_messages]` reducer를 사용하여 **append-only**로 설계되었다.
실제로 모든 노드가 `"messages": [response]` 이나 `"messages": [HumanMessage(...)]`을 반환하여 messages 리스트에 쌓인다.

**그런데 어떤 노드도 `state.get("messages")`를 읽지 않는다.**

각 노드는 `state.get("input")`과 prompt template으로 독립적인 `[HumanMessage]`를 제작한다.
즉 messages가 쌓이지만 모델에게 전달하는 것은 항상 단일 HumanMessage이므로, 모델은 대화의 흐름을 알 수 없다.

#### 영향

- Hard 경로에서 TODO 10개 실행 시 messages에 20개 이상 쌓이지만, 각 execute_todo는 독립적 prompt만 보냄
- 이전 노드의 모델 응답 퀄리티를 다음 노드가 직접 볼 수 없음 (prompt 문자열에 결과 일부를 수동 삽입하는 방식)
- messages의 유일한 용도: 외부에서 `_invoke_autonomous` 결과를 읽을 때

### 5.2 전체 Iteration Cap 부재

Simple Graph는 `max_iterations`로 무한 루프를 방지한다.
Autonomous Graph는:
- Medium 경로: `max_review_retries` (기본 3) — 리뷰 횟수만 제한
- Hard 경로: TODO 개수가 상한 — 하지만 create_todos에서 모델이 50개 TODO를 만들면 50번 실행

**전체 실행에 대한 타임아웃이나 iteration 상한이 없다.**

### 5.3 에러 처리의 취약성

```python
except Exception as e:
    return {
        "error": str(e),
        "is_complete": True,  # ← 즉시 종료
    }
```

모든 노드에서 동일한 패턴. 문제점:
- Rate limit → 재시도 없이 종료
- 일시적 네트워크 오류 → 재시도 없이 종료
- `ModelFallbackRunner`가 존재하지만 어디에도 사용되지 않음

### 5.4 하드 경로의 Prompt 비대화

`execute_todo`에서 이전 결과를 prompt에 포함:

```python
for i, t in enumerate(todos):
    if i < current_index and t.get("result"):
        previous_results += f"\n[{t['title']}]: {t['result'][:500]}...\n"
```

TODO 10개 실행 시 마지막 TODO의 prompt에는 ~4500자의 이전 결과가 포함된다.
`final_review`와 `final_answer`에서는 **모든 TODO 결과를 full로** 포함하여 prompt가 매우 커질 수 있다.
**컨텍스트 가드가 없으므로 이 비대화를 감지/방지할 수 없다.**

---

## 6. 이미 존재하지만 미통합된 컴포넌트

다음 컴포넌트들은 이미 구현되어 있으나 Autonomous Graph에 연결되지 않았다:

### 6.1 `resilience_nodes.py`

| 함수 | 하는 일 | Autonomous 통합 여부 |
|------|---------|---------------------|
| `make_context_guard_node()` | messages 토큰 예산 체크, compaction 요청 | ❌ |
| `make_memory_inject_node()` | 장기/단기 메모리 검색 → `memory_refs` 기록 | ❌ |
| `make_transcript_record_node()` | 모델 응답을 JSONL 트랜스크립트에 기록 | ❌ |
| `completion_detect_node()` | 출력에서 `[TASK_COMPLETE]` 등 파싱 → `completion_signal` 기록 | ❌ |
| `detect_completion_signal()` | Pure function — 텍스트에서 신호 추출 | ❌ |

### 6.2 `model_fallback.py`

`ModelFallbackRunner` 클래스:
- 선호 모델 실패 시 후보 모델로 자동 전환
- `FallbackRecord`를 생성하여 state에 기록 가능
- `classify_error()`: 에러 유형 분류 (rate_limit, overloaded, timeout 등)
- `is_recoverable()`: 폴백 가능 여부 판단

**현재 상태**: `model_fallback.py`는 어디에도 import/사용되지 않음.

### 6.3 `context_guard.py`

`ContextWindowGuard` 클래슴:
- 토큰 추정 (문자 기반 휴리스틱)
- Warn(75%) / Block(90%) 2단계 경고
- `compact()` 메서드로 오래된 메시지 제거

**현재 상태**: Simple Graph의 `make_context_guard_node()`에서만 사용.

### 6.4 `service/memory/`

`SessionMemoryManager`:
- `record_message()`: 대화 기록 저장
- `search()`: 유사 메모리 검색
- `build_memory_context()`: prompt 주입용 문자열 생성

**현재 상태**: Simple Graph의 `_agent_node()`에서 record만 사용. Autonomous Graph에서 미사용.

---

## 7. Autonomous Graph의 설계 의도 vs 현실

### 7.1 원래 설계 의도 (state.py 주석)

```python
"""
Design principles (referencing OpenClaw patterns):
- Every resilience concern lives IN state, not in ad-hoc instance vars
- Completion detection via structured signal enum, not string matching
- Context budget tracked as first-class state field
- Model fallback state recorded so nodes can react to degraded mode
- Memory references surfaced in state for traceability
"""
```

### 7.2 현실

| 설계 원칙 | 현실 |
|-----------|------|
| Resilience가 state에 존재 | State 필드만 정의됨. 노드가 사용하지 않음 |
| 구조화된 완료 신호 | `is_complete` boolean만 사용. CompletionSignal 미파싱 |
| 컨텍스트 예산 추적 | `context_budget` 필드 있지만 기록/읽기 없음 |
| 모델 폴백 기록 | `fallback` 필드 있지만 기록/읽기 없음 |
| 메모리 참조 추적 | `memory_refs` 필드 있지만 기록/읽기 없음 |

**결론: State schema는 올바르게 설계되었으나, Graph 노드가 이를 활용하도록 구현되지 않았다.**

---

## 8. 고도화 방향 (개선 후보)

> ⚠️ 이 섹션은 검토를 위한 후보 목록입니다. 실행 결정은 검토 후에 합니다.

### 8.1 개선 후보 목록

| ID | 개선 항목 | 우선순위 | 영향 범위 | 복잡도 |
|----|----------|---------|----------|--------|
| **R1** | **Resilience Wrapper 패턴 도입** — 개별 노드에 resilience 로직을 넣는 대신, 모든 모델 호출을 감싸는 공통 wrapper 함수 생성 | 🔴 Critical | autonomous_graph.py | Medium |
| **R2** | **Context Guard 통합** — 모델 호출 전 prompt 토큰 예산 체크. BLOCK 시 prompt 요약/축소 | 🔴 Critical | autonomous_graph.py, state update | Medium |
| **R3** | **Model Fallback 통합** — `ModelFallbackRunner`를 모든 model.ainvoke() 호출에 적용 | 🔴 Critical | autonomous_graph.py | Medium |
| **R4** | **Completion Signal 감지** — 모델 응답에서 structured signal 파싱하여 state에 기록 | 🟡 High | autonomous_graph.py | Low |
| **R5** | **전체 Iteration Cap** — hard 경로의 TODO 실행 + medium의 retry를 포함한 전체 모델 호출 횟수 제한 | 🟡 High | autonomous_graph.py, state.py | Low |
| **R6** | **Memory Injection** — classify_difficulty 전에 메모리 검색하여 prompt에 컨텍스트 포함 | 🟡 High | autonomous_graph.py | Medium |
| **R7** | **Transcript Recording** — 모든 모델 응답을 short-term memory에 기록 | 🟢 Medium | autonomous_graph.py | Low |
| **R8** | **Hard 경로 Prompt Compaction** — previous_results가 길어질 때 요약 또는 截단 | 🟢 Medium | autonomous_graph.py | Medium |
| **R9** | **에러 복구 전략** — recoverable error 발생 시 즉시 종료 대신 재시도/스킵/폴백 | 🟡 High | autonomous_graph.py | High |
| **R10** | **Graph 구조 개선** — resilience 노드를 그래프 토폴로지에 추가 (guard → node → record 패턴) | 🟢 Medium | autonomous_graph.py build() | High |

### 8.2 구현 접근법 선택지

#### 접근법 A: 노드 내부 Wrapper 방식

각 노드의 `self._model.ainvoke(messages)` 호출을 공통 wrapper로 교체:

```python
# 새로운 공통 메서드
async def _resilient_invoke(self, state, messages, node_name):
    # 1. Context budget check
    # 2. Memory injection (optional)
    # 3. Model fallback wrapper
    # 4. Completion signal detection
    # 5. Transcript recording
    # 6. Iteration increment
    return response, state_updates
```

**장점**: 그래프 토폴로지 변경 불필요, 노드 수 유지
**단점**: 각 노드에서 wrapper 호출 필요, 관심사 혼합

#### 접근법 B: 그래프 토폴로지에 Resilience 노드 추가

```
START → memory_inject → context_guard → classify_difficulty → ...
                                              ↓
                        각 모델 호출 전후에 guard/record 노드 삽입
```

**장점**: 관심사 완전 분리, LangGraph 철학에 부합
**단점**: 노드 수 크게 증가 (9 → 20+), 그래프 복잡도 상승, 디버깅 어려움

#### 접근법 C: 하이브리드 — Pre/Post Hook + Wrapper

```python
# 모델 호출을 감싸는 resilient wrapper (접근법 A의 핵심)
# + 그래프 시작/끝에만 guard/memory 노드 추가 (접근법 B의 최소 적용)

START → memory_inject → classify_difficulty → ...
                              ↓
              모든 노드 내부: _resilient_invoke() 사용
                              ↓
                        ... → transcript_record → END
```

**장점**: 그래프 토폴로지 최소 변경 + 공통 로직 중앙 관리
**단점**: 두 패턴 혼용

---

## 9. 부록: 코드 참조

| 파일 | 줄 수 | 설명 |
|------|-------|------|
| `service/langgraph/state.py` | 307 | AgentState, AutonomousState 정의 |
| `service/langgraph/autonomous_graph.py` | 986 | AutonomousGraph 9개 노드 + 빌드 |
| `service/langgraph/agent_session.py` | 1400 | Simple Graph 빌드 + invoke/astream |
| `service/langgraph/resilience_nodes.py` | 313 | context_guard, memory_inject, transcript_record, completion_detect |
| `service/langgraph/model_fallback.py` | 364 | ModelFallbackRunner |
| `service/langgraph/context_guard.py` | 496 | ContextWindowGuard |
| `service/memory/manager.py` | 349 | SessionMemoryManager |
| `service/prompt/sections.py` | 730 | SectionLibrary + AutonomousPrompts |

---

## 10. 결론

**Autonomous Agent는 현재 "난이도 기반 라우팅 + 기본 모델 호출"만 수행하는 상태이다.**

Phase 1~3에서 설계한 핵심 resilience 및 observability 기능들이:
- State에는 **필드로 정의**되어 있고
- 독립 모듈로 **구현**까지 되어 있지만
- Autonomous Graph에는 **전혀 통합되지 않았다**

이 갭을 해소하면 Autonomous Agent는:
1. 장기 실행에서도 컨텍스트 윈도우를 초과하지 않고
2. 모델 장애 시 자동 폴백하여 작업을 지속하고
3. 완료/에러/차단 상태를 구조화된 신호로 추적하고
4. 이전 대화와 메모리를 참조하여 더 정확한 답변을 생성하는

**진정한 Production-grade Autonomous Agent**가 될 수 있다.
