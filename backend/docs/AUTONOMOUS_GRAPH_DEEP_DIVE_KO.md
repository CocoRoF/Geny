# Autonomous Difficulty-Based Graph — 심층 분석 문서

> **대상**: `template-autonomous.json` 기반 CompiledStateGraph
> **노드 수**: 26 (START/END 제외 24개 실행 노드)
> **엣지 수**: 35
> **상태 스키마**: `AutonomousState(TypedDict)`

---

## 목차

1. [전체 아키텍처 개요](#1-전체-아키텍처-개요)
2. [AutonomousState 상태 스키마](#2-autonomousstate-상태-스키마)
3. [실행 경로별 상세 분석](#3-실행-경로별-상세-분석)
   - 3.1 [공통 진입부: Memory Inject → Guard → Classify](#31-공통-진입부)
   - 3.2 [EASY 경로: Direct Answer](#32-easy-경로)
   - 3.3 [MEDIUM 경로: Answer → Review 루프](#33-medium-경로)
   - 3.4 [HARD 경로: TODO 분할 실행](#34-hard-경로)
4. [LLM 호출 노드 상세 분석](#4-llm-호출-노드-상세-분석)
   - 4.1 [ClassifyNode — 난이도 분류](#41-classifynode--난이도-분류)
   - 4.2 [ReviewNode — 자가 라우팅 품질 게이트](#42-reviewnode--자가-라우팅-품질-게이트)
   - 4.3 [CreateTodosNode — JSON 파싱 의존성](#43-createtodosnode--json-파싱-의존성)
   - 4.4 [AnswerNode / DirectAnswerNode](#44-answernode--directanswernode)
   - 4.5 [FinalReviewNode / FinalAnswerNode](#45-finalreviewnode--finalanswernode)
5. [인프라 노드 상세 분석](#5-인프라-노드-상세-분석)
   - 5.1 [ContextGuardNode](#51-contextguardnode)
   - 5.2 [PostModelNode](#52-postmodelnode)
   - 5.3 [IterationGateNode](#53-iterationgatenode)
   - 5.4 [CheckProgressNode](#54-checkprogressnode)
   - 5.5 [MemoryInjectNode](#55-memoryinjectnode)
6. [라우팅 로직 완전 분석](#6-라우팅-로직-완전-분석)
7. [현재 시스템의 취약점 분석](#7-현재-시스템의-취약점-분석)
8. [Structured JSON Output 적용 방안](#8-structured-json-output-적용-방안)
9. [강건성 개선 제안 종합](#9-강건성-개선-제안-종합)

---

## 1. 전체 아키텍처 개요

```
START
  │
  ▼
mem_inject ─── guard_cls ─── classify
                                │
                 ┌──────────────┼──────────────┐
                 │              │              │
                easy         medium          hard
                 │              │              │
                 ▼              ▼              ▼
             guard_dir      guard_ans      guard_todo
                 │              │              │
                 ▼              ▼              ▼
              dir_ans        answer         mk_todos
                 │              │              │
                 ▼              ▼              ▼
             post_dir       post_ans      post_todos
                 │              │              │
                 ▼              ▼              ▼
                END         guard_rev      guard_exec
                                │              │
                                ▼              ▼
                             review        exec_todo
                               │              │
                    ┌──────────┤              ▼
                    │          │          post_exec
                 approved    retry            │
                    │          │              ▼
                    ▼          ▼          chk_prog
                   END     gate_med          │
                               │        ┌────┴────┐
                        ┌──────┤      continue  complete
                     continue stop       │        │
                        │      │         ▼        ▼
                        ▼      ▼     gate_hard  guard_fr
                    guard_ans END        │        │
                                    ┌────┤        ▼
                                 cont. stop    fin_rev
                                    │    │        │
                                    ▼    ▼        ▼
                              guard_exec guard_fr post_fr
                                                  │
                                                  ▼
                                              guard_fa
                                                  │
                                                  ▼
                                               fin_ans
                                                  │
                                                  ▼
                                               post_fa
                                                  │
                                                  ▼
                                                 END
```

그래프는 **3가지 실행 경로**(Easy / Medium / Hard)로 분기하며, 각 경로는 작업 복잡도에 맞는 처리 파이프라인을 가집니다.

### 핵심 설계 원칙

| 원칙 | 구현 |
|------|------|
| **모든 LLM 호출 앞에 Guard** | `ContextGuardNode`가 토큰 예산을 확인 |
| **모든 LLM 호출 뒤에 Post** | `PostModelNode`가 iteration++, completion signal 감지, transcript 기록 |
| **루프에는 반드시 Gate** | `IterationGateNode`가 무한루프 방지 |
| **상태 기반 라우팅** | Conditional 노드의 `get_routing_function()`이 state 필드를 읽어 포트 결정 |

---

## 2. AutonomousState 상태 스키마

```python
class AutonomousState(TypedDict, total=False):
    # ── 입력 ──
    input: str                                     # 사용자 요청 원문

    # ── 대화 이력 ──
    messages: Annotated[list, _add_messages]        # LangChain 메시지 리스트 (reducer: 누적)
    current_step: str                               # 현재 실행 단계 이름
    last_output: Optional[str]                      # 마지막 LLM 응답 원문

    # ── 반복 관리 ──
    iteration: int                                  # 전역 반복 카운터 (PostModel에서 증가)
    max_iterations: int                             # 최대 허용 반복 횟수

    # ── 난이도 ──
    difficulty: Optional[str]                       # "easy" | "medium" | "hard"

    # ── Answer & Review (MEDIUM 경로) ──
    answer: Optional[str]                           # 생성된 답변
    review_result: Optional[str]                    # "approved" | "retry" 등
    review_feedback: Optional[str]                  # 리뷰어 피드백 텍스트
    review_count: int                               # 리뷰 횟수 카운터

    # ── TODO (HARD 경로) ──
    todos: Annotated[List[TodoItem], _merge_todos]  # TODO 항목 리스트 (reducer: 병합)
    current_todo_index: int                         # 현재 실행 중인 TODO 인덱스

    # ── 최종 결과 ──
    final_answer: Optional[str]                     # 최종 합성 답변

    # ── 완료 신호 ──
    completion_signal: Optional[str]                # CompletionSignal enum value
    completion_detail: Optional[str]                # 신호 상세 내용

    # ── 에러 ──
    error: Optional[str]                            # 에러 메시지
    is_complete: bool                               # 워크플로우 완료 여부

    # ── 컨텍스트 예산 ──
    context_budget: Optional[ContextBudget]         # 토큰 사용량 추적

    # ── 모델 Fallback ──
    fallback: Optional[FallbackRecord]              # 모델 폴백 이력

    # ── 메모리 ──
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]  # 로드된 메모리 참조

    # ── 메타데이터 ──
    metadata: Dict[str, Any]                        # 기타 메타데이터
```

### Reducer 동작

- `messages`: `_add_messages` — LangChain의 메시지 누적 리듀서. 새 메시지가 기존 리스트에 **추가**됨.
- `todos`: `_merge_todos` — 같은 `id`를 가진 TODO를 **덮어쓰기** 병합. 새 항목은 추가.
- `memory_refs`: `_merge_memory_refs` — `filename` 기준 중복 제거 후 병합.
- 기타 스칼라 필드: **last-write-wins** — 마지막에 쓴 값이 이전 값을 덮어씀.

---

## 3. 실행 경로별 상세 분석

### 3.1 공통 진입부

```
START → mem_inject → guard_cls → classify → [분기]
```

| 단계 | 노드 | 동작 |
|------|------|------|
| 1 | `mem_inject` | SessionMemoryManager에서 `input` 관련 메모리 검색 (최대 5개). 입력을 단기 transcript에 기록. |
| 2 | `guard_cls` | 누적 messages의 토큰 수 추정 → `context_budget` 상태 업데이트 |
| 3 | `classify` | **LLM 호출** — 난이도 분류. 응답에서 `easy`/`medium`/`hard` 키워드 매칭 |

### 3.2 EASY 경로

```
classify[easy] → guard_dir → dir_ans → post_dir → END
```

가장 단순한 경로. LLM을 한 번만 호출하며 리뷰 없이 곧바로 종료합니다.

| 단계 | 노드 | 상태 변경 |
|------|------|----------|
| 1 | `guard_dir` | `context_budget` 갱신 |
| 2 | `dir_ans` | `answer`, `final_answer`, `is_complete=True` 설정 |
| 3 | `post_dir` | `iteration++`, completion signal 감지, transcript 기록 |

### 3.3 MEDIUM 경로

```
classify[medium] → guard_ans → answer → post_ans → guard_rev → review
                       ▲                                         │
                       │                               ┌────────┼────────┐
                       │                            approved   retry    end
                       │                               │        │        │
                       │                              END    gate_med   END
                       │                                        │
                       │                                ┌───────┤
                       │                             continue  stop
                       │                                │       │
                       └────────────────────────────────┘      END
```

**핵심**: Answer → Review → (approved이면 END / retry이면 gate → answer 루프)

| 단계 | 노드 | 상태 변경 |
|------|------|----------|
| 1 | `guard_ans` | `context_budget` 갱신 |
| 2 | `answer` | `review_count`가 0이면 primary prompt, >0이면 retry prompt + feedback 사용. `answer`, `last_output` 설정 |
| 3 | `post_ans` | `iteration++`. **`detect_completion=false`** — 완료 신호 감지 안 함 (의도: answer 후 반드시 review로 진행) |
| 4 | `guard_rev` | `context_budget` 갱신 |
| 5 | `review` | **LLM 호출** — `VERDICT:` / `FEEDBACK:` 구조화 파싱. `review_result` 설정 |
| 6 | `gate_med` | (retry 경우) iteration ≥ 5 또는 `is_complete` → stop, 아니면 continue |

**리뷰 루프 최대 횟수**: `review.max_retries=3` (3회 초과 시 강제 approved) × `gate_med.max_iterations=5` (iteration 게이트). 실질적으로 review_count 3에서 강제 종료.

### 3.4 HARD 경로

```
classify[hard] → guard_todo → mk_todos → post_todos → guard_exec → exec_todo
                                                          ▲            │
                                                          │         post_exec
                                                          │            │
                                                          │         chk_prog
                                                          │            │
                                                     ┌────┤      ┌────┤
                                                  continue│   continue│
                                                     │  stop   │  complete
                                                     │    │    │     │
                                                 gate_hard │  (위)  guard_fr
                                                     │    │         │
                                                  ┌──┤    │      fin_rev → post_fr → guard_fa → fin_ans → post_fa → END
                                               cont. stop │
                                                  │    │  │
                                              guard_exec guard_fr
```

**핵심**: TODO 생성 → 개별 실행 루프 → 진행률 체크 → 최종 리뷰 → 최종 답변

| 단계 | 노드 | 상태 변경 |
|------|------|----------|
| 1 | `guard_todo` | `context_budget` 갱신 |
| 2 | `mk_todos` | **LLM 호출** — JSON 배열 파싱 → `todos` 리스트 생성, `current_todo_index=0` |
| 3 | `post_todos` | `iteration++`, **`detect_completion=false`** |
| 4 | `guard_exec` | `context_budget` 갱신 |
| 5 | `exec_todo` | **LLM 호출** — 현재 TODO 실행. `todos[index].status=completed`, `current_todo_index++` |
| 6 | `post_exec` | `iteration++`, completion signal 감지, transcript 기록 |
| 7 | `chk_prog` | `current_todo_index >= len(todos)` → complete, 아니면 continue |
| 8 | `gate_hard` | iteration ≥ 5 → stop(→guard_fr), 아니면 continue(→guard_exec 루프) |
| 9 | `guard_fr` | `context_budget` 갱신 |
| 10 | `fin_rev` | **LLM 호출** — 모든 TODO 결과 종합 리뷰 |
| 11 | `post_fr` | `iteration++`, signal 감지 |
| 12 | `guard_fa` | `context_budget` 갱신 |
| 13 | `fin_ans` | **LLM 호출** — 최종 답변 합성, `is_complete=True` |
| 14 | `post_fa` | `iteration++`, signal 감지 |

---

## 4. LLM 호출 노드 상세 분석

### 4.1 ClassifyNode — 난이도 분류

**파일**: `model_nodes.py` / **타입**: `classify`

#### 프롬프트

```
You are a task difficulty classifier. Analyze the given input and classify its difficulty level.

Classification criteria:
- EASY: Simple questions, factual lookups, basic calculations, straightforward requests
- MEDIUM: Moderate complexity, requires some reasoning or multi-step thinking
- HARD: Complex tasks requiring multiple steps, research, planning, or iterative execution

IMPORTANT: Respond with ONLY one of these exact words: easy, medium, hard

Input to classify:
{input}
```

#### LLM 응답 파싱 로직

```python
response_text = response.content.strip().lower()

matched = default_cat  # "medium"
for cat in categories:  # ["easy", "medium", "hard"]
    if cat.lower() in response_text:
        matched = cat
        break
```

#### ⚠️ 취약점 분석

| 문제 | 심각도 | 설명 |
|------|--------|------|
| **단순 substring 매칭** | 🔴 높음 | `"This is not easy"` → `easy` 매칭! `in` 연산자가 부분 문자열을 검사하므로 맥락 무시 |
| **순서 의존성** | 🟡 중간 | `for ... break` 구조로 첫 매칭 우선. `"medium-hard"` → `medium` |
| **기본값 편향** | 🟡 중간 | 매칭 실패 시 항상 `medium`. LLM이 전혀 다른 응답을 하면 medium 경로 진입 |
| **자유 형식 응답** | 🔴 높음 | `"ONLY one of these exact words"` 지시가 있지만 LLM 준수를 보장할 수 없음 |

#### 라우팅 함수 (엣지 결정)

```python
def _route(state):
    if state.get("error"):
        return "end"
    value = state.get("difficulty")      # Difficulty enum or string
    if hasattr(value, "value"):
        value = value.value              # enum → string
    value = value.strip().lower()
    if value in {"easy", "medium", "hard"}:
        return value
    return "medium"                      # default
```

에러 발생 시 → `end` 포트 → END (즉시 종료).
난이도 파싱 결과가 유효하면 해당 포트로 라우팅.

---

### 4.2 ReviewNode — 자가 라우팅 품질 게이트

**파일**: `model_nodes.py` / **타입**: `review`

#### 프롬프트

```
You are a quality reviewer. Review the following answer for accuracy and completeness.

Original Question:
{question}

Answer to Review:
{answer}

Review the answer and determine:
1. Is the answer accurate and correct?
2. Does it fully address the question?
3. Is there anything missing or incorrect?

Respond in this exact format:
VERDICT: approved OR rejected
FEEDBACK: (your detailed feedback)
```

#### LLM 응답 파싱 로직 (상세)

```python
matched_verdict = default_verdict  # "retry"
feedback = ""

if verdict_prefix in review_text:     # "VERDICT:" 존재?
    lines = review_text.split("\n")
    for line in lines:
        if line.startswith("VERDICT:"):
            verdict_str = line.replace("VERDICT:", "").strip().lower()
            for v in verdicts:         # ["approved", "retry"]
                if v.lower() in verdict_str:
                    matched_verdict = v
                    break
        elif line.startswith("FEEDBACK:"):
            feedback = line.replace("FEEDBACK:", "").strip()
            idx = lines.index(line)
            feedback = "\n".join([feedback] + lines[idx + 1:])
            break
else:
    # 구조화된 prefix 없음 → 전체 응답을 feedback으로 취급
    feedback = review_text
    review_lower = review_text.lower()
    for v in verdicts:
        if v.lower() in review_lower:
            matched_verdict = v
            break
```

#### ⚠️ 취약점 분석

| 문제 | 심각도 | 설명 |
|------|--------|------|
| **프롬프트에 `rejected`가 있지만 verdicts에는 `retry`** | 🔴 높음 | 기본 프롬프트는 `"VERDICT: approved OR rejected"` 지시이나, 실제 설정된 verdicts는 `["approved", "retry"]`. LLM이 `rejected`를 출력하면 **어떤 verdict에도 매칭되지 않아** default인 `retry`로 처리됨. 결과적으로 동작은 하지만, LLM의 의도 파싱이 우연에 의존 |
| **substring 매칭** | 🟡 중간 | `"not approved"` → `approved` 매칭. `"I'd say approve rather than retry"` → `approved` (첫 매칭) |
| **FEEDBACK 파싱 취약** | 🟡 중간 | VERDICT 줄 없이 FEEDBACK만 있으면 전체가 feedback이 되고 verdict는 keyword 검색 |
| **강제 approve 로직** | 🟢 낮음 | `review_count >= max_retries(3)` → 첫 번째 verdict (approved) 강제. 무한 retry 방지는 잘 작동 |

#### 라우팅 함수 (엣지 결정)

```python
def _route(state):
    if state.get("error"):
        return "end"                     # → END

    if state.get("is_complete"):
        # approved + max_retries 도달 후 → is_complete==True
        value = state.get("review_result", "").lower()
        if value in {"approved", "retry"}:
            return value
        return "approved"                # 강제

    # completion signal 체크
    signal = state.get("completion_signal")
    if signal in ("complete", "blocked"):
        return "approved"                # 강제

    value = state.get("review_result", "").lower()
    if value in {"approved", "retry"}:
        return value
    return "retry"                       # default
```

**라우팅 맵**:
- `approved` → **END** (리뷰 통과)
- `retry` → **gate_med** (재시도 게이트)
- `end` → **END** (에러 종료)

---

### 4.3 CreateTodosNode — JSON 파싱 의존성

**파일**: `task_nodes.py` / **타입**: `create_todos`

#### 프롬프트

```
You are a task planner. Break down the following complex task into smaller, manageable TODO items.

Task:
{input}

Create a list of TODO items that, when completed in order, will fully accomplish the task.
Each TODO should be:
- Specific and actionable
- Self-contained (can be executed independently)
- Ordered logically (dependencies respected)

Respond in this exact JSON format only (no markdown, no explanation):
[
  {"id": 1, "title": "Short title", "description": "Detailed description of what to do"},
  {"id": 2, "title": "Short title", "description": "Detailed description of what to do"}
]
```

#### LLM 응답 파싱 로직

```python
response_text = response.content.strip()

# 1단계: 마크다운 코드 블록 제거
if "```json" in response_text:
    response_text = response_text.split("```json")[1].split("```")[0]
elif "```" in response_text:
    response_text = response_text.split("```")[1].split("```")[0]

# 2단계: JSON 파싱
try:
    todos_raw = json.loads(response_text.strip())
except json.JSONDecodeError:
    # 실패 시 단일 항목 fallback
    todos_raw = [{"id": 1, "title": "Execute task", "description": input_text}]

# 3단계: TodoItem 형식으로 변환
todos = []
for item in todos_raw:
    todos.append({
        "id": item.get("id", len(todos) + 1),
        "title": item.get("title", f"Task {len(todos) + 1}"),
        "description": item.get("description", ""),
        "status": "pending",
        "result": None,
    })

# 4단계: 개수 제한
if len(todos) > max_todos:  # default: 20
    todos = todos[:max_todos]
```

#### ⚠️ 취약점 분석

| 문제 | 심각도 | 설명 |
|------|--------|------|
| **JSON 파싱 실패 → 단일 항목 fallback** | 🔴 높음 | LLM이 설명 텍스트를 앞에 붙이면 마크다운 블록 제거로도 불충분. fallback은 전체 input을 하나의 TODO로 만들어 실질적으로 Hard 경로의 분할 이점을 완전히 상실 |
| **마크다운 블록 파싱이 단순 split** | 🟡 중간 | 중첩 코드 블록이나 다중 코드 블록 시 잘못된 부분을 추출 가능 |
| **items가 dict가 아닌 경우 처리 없음** | 🟡 중간 | `item.get("id")` 호출 시 item이 string이면 `AttributeError` |
| **빈 배열 응답** | 🟡 중간 | `[]` 파싱 성공 → `todos=[]` → `chk_prog`에서 즉시 complete → 아무 작업 안 함 |

---

### 4.4 AnswerNode / DirectAnswerNode

#### AnswerNode (Medium 경로)

| 상황 | 사용 프롬프트 | 조건 |
|------|-------------|------|
| 첫 시도 | `prompt_template` (기본: `{input}`) | `review_count == 0` |
| 재시도 | `retry_template` | `review_count > 0 && review_feedback 존재` |

**재시도 프롬프트**:
```
Previous attempt was rejected with this feedback:
{previous_feedback}

Please try again with the following request, addressing the feedback:
{input_text}
```

Budget 긴축 시 feedback을 500자로 자름.

#### DirectAnswerNode (Easy 경로)

단순 LLM 호출. `output_fields`에 지정된 모든 state 필드에 응답을 복사.
기본: `["answer", "final_answer"]` + `mark_complete=True`.

**⚠️ DirectAnswerNode 취약점**: `prompt_template` 기본값이 `{input}` — 시스템 프롬프트나 역할 지시 없이 입력을 그대로 전달. 사실상 모델의 기본 동작에 의존.

---

### 4.5 FinalReviewNode / FinalAnswerNode

#### FinalReviewNode

모든 TODO 결과를 마크다운으로 포맷하여 종합 리뷰 요청:

```python
def _format_list_items(items, max_chars):
    text = ""
    for item in items:
        status = item.get("status", "pending")
        result = item.get("result", "No result")
        if result and len(result) > max_chars:
            result = result[:max_chars] + "... (truncated)"
        text += f"\n### {item.get('title', 'Item')} [{status}]\n{result}\n"
    return text
```

Budget-aware: `context_budget.status in ("block", "overflow")` → 항목당 500자로 축소.

#### FinalAnswerNode

리뷰 피드백 + TODO 결과 + 원본 요청을 합성. `is_complete=True` 설정.
에러 시에도 `is_complete=True`와 함께 부분 결과를 반환 (graceful degradation).

---

## 5. 인프라 노드 상세 분석

### 5.1 ContextGuardNode

**목적**: LLM 호출 전 토큰 예산 점검

```python
result = context.context_guard.check(msg_dicts)

budget = {
    "estimated_tokens": result.estimated_tokens,
    "context_limit": result.context_limit,
    "usage_ratio": result.usage_ratio,
    "status": result.status.value,     # "ok" | "warn" | "block" | "overflow"
    "compaction_count": prev_budget.get("compaction_count", 0),
}
```

**상태 레벨**:
| 상태 | 의미 | 후속 동작 |
|------|------|----------|
| `ok` | 여유 있음 | 정상 진행 |
| `warn` | 감소 추세 | 모델 노드가 프롬프트 축소 가능 |
| `block` | 위험 수준 | 컨텍스트 compaction 수행, `compaction_count++` |
| `overflow` | 초과 | IterationGate가 중단 결정 |

### 5.2 PostModelNode

**목적**: 모든 LLM 호출 후 3가지 관심사 처리

```python
# 1. 이터레이션 증가
updates["iteration"] = iteration + 1

# 2. 완료 신호 감지 (detect_completion=True일 때만)
signal, detail = detect_completion_signal(last_output)
# 정규식 기반:
#   [TASK_COMPLETE]        → CompletionSignal.COMPLETE
#   [BLOCKED: reason]      → CompletionSignal.BLOCKED
#   [ERROR: description]   → CompletionSignal.ERROR
#   [CONTINUE: next_action] → CompletionSignal.CONTINUE

# 3. Transcript 기록
context.memory_manager.record_message("assistant", last_output[:5000])
```

**중요 구성 차이**:
| 노드 인스턴스 | `detect_completion` | 이유 |
|--------------|---------------------|------|
| `post_dir` (Easy 후) | `True` (기본) | 최종 출력이므로 completion 감지 의미 있음 |
| `post_ans` (Answer 후) | **`False`** | 반드시 Review로 진행해야 하므로 completion 감지 차단 |
| `post_todos` (CreateTodos 후) | **`False`** | TODO 리스트 자체가 출력이므로 completion 감지 무의미 |
| `post_exec` (ExecuteTodo 후) | `True` (기본) | TODO 실행 중 에러/완료 감지 유의미 |
| `post_fr`, `post_fa` | `True` (기본) | 최종 단계에서 completion 감지 필요 |

### 5.3 IterationGateNode

**목적**: 루프 무한 실행 방지

```python
# 4가지 정지 조건 (순서대로 평가)
stop_reason = None

# 1. 이터레이션 상한
if check_iteration and iteration >= max_iterations:
    stop_reason = "Iteration limit"

# 2. 컨텍스트 예산
if check_budget and budget.status in ("block", "overflow"):
    stop_reason = "Context budget"

# 3. 완료 신호
if check_completion and signal in ("complete", "blocked", "error"):
    stop_reason = "Completion signal"

# 4. 커스텀 중단 필드
if custom_stop_field and state.get(custom_stop_field):
    stop_reason = "Custom stop"
```

**라우팅 함수**:
```python
def _route(state):
    if state.get("is_complete") or state.get("error"):
        return "stop"
    return "continue"
```

> Note: `execute()`에서 `is_complete=True`를 설정하고, 라우팅 함수에서 이를 읽음.
> 실행 → 상태 갱신 → 라우팅 순서이므로 정합성 보장.

### 5.4 CheckProgressNode

**목적**: TODO 리스트 진행률 확인

```python
def _route(state):
    if state.get("is_complete") or state.get("error"):
        return "complete"
    signal = state.get("completion_signal")
    if signal in ("complete", "blocked"):
        return "complete"
    current_index = state.get("current_todo_index", 0)
    items = state.get("todos", [])
    if current_index >= len(items):
        return "complete"               # 모든 항목 처리 완료
    return "continue"                   # 남은 항목 있음
```

### 5.5 MemoryInjectNode

**목적**: 세션 메모리에서 관련 컨텍스트 로드

```python
# 단기 transcript에 사용자 입력 기록
context.memory_manager.record_message("user", input_text[:5000])

# 관련 메모리 검색 (벡터/키워드 기반)
results = context.memory_manager.search(
    input_text[:search_chars],    # default: 500자
    max_results=max_results,      # default: 5
)
```

반환: `MemoryRef` 리스트 → state에 추적용으로 저장. 실제 메모리 내용은 messages에 주입되지 않고 참조만 남김.

---

## 6. 라우팅 로직 완전 분석

### Conditional 노드 목록

| 노드 | 포트 | 근거 | 타입 |
|------|------|------|------|
| `classify` | easy, medium, hard, end | `difficulty` 필드 (LLM 분류) | LLM 의존 |
| `review` | approved, retry, end | `review_result` 필드 (LLM 판정) | LLM 의존 |
| `gate_med` | continue, stop | `is_complete` / `iteration >= 5` | 순수 상태 기반 |
| `chk_prog` | continue, complete | `current_todo_index >= len(todos)` | 순수 상태 기반 |
| `gate_hard` | continue, stop | `is_complete` / `iteration >= 5` | 순수 상태 기반 |

### 라우팅 신뢰도 분류

```
┌──────────────────────────────────────────────────────────┐
│  높은 신뢰도 (순수 상태 기반)                              │
│  ├─ gate_med:  iteration 카운터 비교                      │
│  ├─ gate_hard: iteration 카운터 비교                      │
│  └─ chk_prog:  index vs list length 비교                 │
│                                                          │
│  낮은 신뢰도 (LLM 응답 파싱 의존)                          │
│  ├─ classify:  자유 형식 응답에서 keyword substring 매칭    │
│  └─ review:    VERDICT: 접두어 파싱 + keyword 매칭         │
└──────────────────────────────────────────────────────────┘
```

---

## 7. 현재 시스템의 취약점 분석

### 7.1 LLM 응답 파싱의 구조적 문제

#### 문제 1: Classify의 substring 매칭

```python
# 현재 코드
for cat in categories:
    if cat.lower() in response_text:  # ← substring!
        matched = cat
        break
```

**실패 케이스**:
- `"The task is not easy, it requires medium effort"` → `easy` 매칭 (첫 매칭 우선)
- `"This requires some easygoing meditation"` → `easy` 매칭
- `"I cannot determine the difficulty"` → default `medium`
- `"It's a HARD task but could be medium depending on context"` → `hard`는 안 됨 (`hard`가 대문자), `.lower()` 적용 후 매칭

#### 문제 2: Review의 VERDICT 파싱 불일치

```
프롬프트: "VERDICT: approved OR rejected"
verdicts 설정: ["approved", "retry"]
```

LLM이 지시에 따라 `"VERDICT: rejected"`를 출력하면:
1. `"rejected"` 문자열에서 `"approved"` 검색 → 불일치
2. `"rejected"` 문자열에서 `"retry"` 검색 → 불일치
3. **default verdict `"retry"` 적용** — 우연히 정상 동작하지만, LLM이 정확히 따른 것은 아님

#### 문제 3: CreateTodos의 JSON 의존성

LLM이 JSON 앞뒤에 설명 텍스트를 추가하면:
```
Here are the TODO items:
```json
[{"id": 1, ...}]
```
Some additional notes...
```

현재 split 로직으로는 처리 가능하지만:
```
I'll break this down into tasks:

1. First, we need to...
[{"id": 1, ...}]
```
이 경우 `"```json"`도 `"```"`도 없으므로 전체를 `json.loads()`에 넘겨 실패 → fallback.

### 7.2 상태 일관성 문제

| 문제 | 영향 |
|------|------|
| `review_count`는 ReviewNode가 증가시키지만, AnswerNode가 확인 | 두 노드 간 상태 동기화 의존 |
| `is_complete`는 여러 노드가 설정 | 의도치 않은 조기 완료 가능 |
| `error` 필드 설정 → 모든 라우터가 즉시 종료 | 에러에서 복구하는 메커니즘 없음 |
| `iteration`은 전역 카운터 | HARD 경로에서 TODO 4개 + guard/post 반복으로 빠르게 소진 가능 |

### 7.3 Iteration 소진 분석 (HARD 경로)

TODO 항목 하나 실행 시 소비되는 iteration:
```
guard_exec(0) → exec_todo(0) → post_exec(+1) → chk_prog(0) → gate_hard(0)
```
= **1 iteration per TODO item**

추가로:
```
guard_todo(0) → mk_todos(0) → post_todos(+1)  = 1 iteration
fin_rev → post_fr(+1)                         = 1 iteration
fin_ans → post_fa(+1)                         = 1 iteration
classify 이후 post 없음                        = 0 iteration
```

**총 iteration 소비**: `1(create) + N(todos) + 1(final_review) + 1(final_answer)` = **N + 3**

`gate_hard`의 기본 `max_iterations=5`인 경우:
- `iteration ≥ 5`이면 stop
- TODO 생성 시 이미 iteration=1 (classify 경로에는 post 없으므로 mem_inject 이후 첫 post_todos에서 1)
- 실질적으로 TODO 약 **2-3개** 실행 후 gate에서 중단될 수 있음

> **이것은 `max_iterations_override`가 0(기본)이면 `state.max_iterations`(기본 50-100)을 사용하므로 실제 운영에서는 문제가 덜함. 다만 template에서 override가 5로 설정되어 있다면 제한적.**

---

## 8. Structured JSON Output 적용 방안

### 8.1 현재 문제 요약

| 노드 | LLM에게 기대하는 출력 | 현재 파싱 방식 | 실패 확률 |
|------|---------------------|---------------|----------|
| `classify` | 단일 단어 (`easy`/`medium`/`hard`) | substring 매칭 | 중간 |
| `review` | `VERDICT: {v}\nFEEDBACK: {f}` | 라인 split + prefix 매칭 | 높음 |
| `create_todos` | JSON 배열 | `json.loads()` + code block 제거 | 높음 |
| `execute_todo` | 자유 형식 | 없음 (전체가 결과) | 없음 |
| `answer`, `direct_answer` | 자유 형식 | 없음 (전체가 결과) | 없음 |
| `final_review`, `final_answer` | 자유 형식 | 없음 (전체가 결과) | 없음 |

**Structured Output이 필요한 노드**: `classify`, `review`, `create_todos` (3개)

### 8.2 Structured JSON Output 구현 전략

#### 전략 A: 프롬프트 레벨 JSON 강제 (Soft Enforcement)

프롬프트에서 JSON 스키마를 명시적으로 제시하고, 파싱 로직을 강화:

**ClassifyNode 개선 프롬프트 예시:**
```
Analyze the input and classify its difficulty.

You MUST respond with EXACTLY this JSON format, nothing else:
{"classification": "<easy|medium|hard>"}

Input: {input}
```

**ReviewNode 개선 프롬프트 예시:**
```
Review the answer for quality.

You MUST respond with EXACTLY this JSON format, nothing else:
{"verdict": "<approved|retry>", "feedback": "<your detailed feedback>"}

Question: {question}
Answer: {answer}
```

**장점**: 기존 아키텍처 변경 최소
**단점**: LLM이 여전히 JSON 외 텍스트를 출력할 수 있음

#### 전략 B: 파싱 계층 강화 (Robust Parsing Layer)

JSON 추출 → 검증 → 재시도를 하나의 공통 유틸리티로:

```python
# 제안: 새로운 유틸리티 모듈
# service/workflow/nodes/structured_output.py

import json
import re
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass

@dataclass
class FieldSpec:
    """JSON 필드 스키마 정의."""
    name: str
    type: type                  # str, int, list, etc.
    required: bool = True
    allowed_values: Optional[List[str]] = None
    default: Any = None

@dataclass
class ParseResult:
    """파싱 결과."""
    success: bool
    data: Dict[str, Any]
    raw_text: str
    method: str                 # "direct_json" | "code_block" | "regex" | "fallback"

def extract_structured_output(
    text: str,
    fields: List[FieldSpec],
    *,
    strict: bool = False,
) -> ParseResult:
    """LLM 응답에서 구조화된 데이터 추출.

    시도 순서:
    1. 전체를 JSON으로 파싱
    2. ```json 코드 블록에서 추출
    3. {} 또는 [] 패턴으로 JSON 부분 추출
    4. 필드별 regex 추출
    5. strict=False이면 기본값 사용
    """
    ...

def validate_against_schema(
    data: Dict[str, Any],
    fields: List[FieldSpec],
) -> tuple[bool, Dict[str, Any], List[str]]:
    """스키마 검증 + 정규화.

    Returns:
        (valid, normalized_data, errors)
    """
    ...
```

**적용 예시 — ClassifyNode:**

```python
CLASSIFY_SCHEMA = [
    FieldSpec(
        name="classification",
        type=str,
        required=True,
        allowed_values=None,  # 동적: config의 categories에서 결정
    ),
]

async def execute(self, state, context, config):
    categories = _parse_categories(config.get("categories", ...))
    schema = [
        FieldSpec(
            name="classification",
            type=str,
            required=True,
            allowed_values=categories,
            default=config.get("default_category", "medium"),
        ),
    ]

    prompt = f"""...

    You MUST respond with this exact JSON format:
    {{"classification": "<{'|'.join(categories)}>"}}
    """

    response = await context.resilient_invoke(messages, "classify")

    result = extract_structured_output(
        response.content,
        schema,
        strict=False,
    )

    matched = result.data.get("classification", default_cat)
    ...
```

**적용 예시 — ReviewNode:**

```python
REVIEW_SCHEMA = [
    FieldSpec(
        name="verdict",
        type=str,
        required=True,
        allowed_values=None,  # 동적: config의 verdicts에서 결정
    ),
    FieldSpec(
        name="feedback",
        type=str,
        required=True,
        default="No feedback provided",
    ),
]
```

**적용 예시 — CreateTodosNode:**

```python
TODO_ITEM_SCHEMA = [
    FieldSpec(name="id", type=int, required=True),
    FieldSpec(name="title", type=str, required=True),
    FieldSpec(name="description", type=str, required=True, default=""),
]

# 배열 스키마
TODO_LIST_SCHEMA = FieldSpec(
    name="todos",
    type=list,
    required=True,
    # 각 원소는 TODO_ITEM_SCHEMA를 따름
)
```

#### 전략 C: LLM Tool Use / Function Calling (Hard Enforcement)

Claude API의 `tool_use` 기능을 활용하여 JSON 스키마를 강제:

```python
# Claude API tool definition
classify_tool = {
    "name": "classify_difficulty",
    "description": "Classify the task difficulty",
    "input_schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["easy", "medium", "hard"],
                "description": "The difficulty level"
            }
        },
        "required": ["classification"]
    }
}
```

**장점**: API 레벨에서 JSON 스키마 강제. 파싱 실패가 구조적으로 불가능.
**단점**: 현재 시스템이 Claude CLI 래퍼(`ClaudeCLIChatModel`)를 사용하므로 tool_use 지원 여부 확인 필요. LangChain의 `with_structured_output()` 통합 가능성 검토 필요.

### 8.3 권장 구현 순서

```
Phase 1: 전략 B (파싱 계층 강화) — 즉시 적용 가능
  ├─ structured_output.py 유틸리티 모듈 생성
  ├─ ClassifyNode.execute() 파싱 로직 교체
  ├─ ReviewNode.execute() 파싱 로직 교체
  └─ CreateTodosNode.execute() 파싱 로직 교체

Phase 2: 전략 A (프롬프트 개선) — Phase 1과 동시 적용
  ├─ AutonomousPrompts 프롬프트를 JSON 스키마 명시 형태로 수정
  ├─ 각 노드의 default prompt_template 업데이트
  └─ 기존 workflow 호환성 유지 (구 프롬프트도 파싱 가능)

Phase 3: 전략 C (Tool Use) — 모델 인터페이스 확인 후
  ├─ ClaudeCLIChatModel에서 tool_use 지원 조사
  ├─ 지원 시 structured_output fallback chain 구현
  └─ tool_use → json_prompt → regex_fallback 3단계 체계
```

---

## 9. 강건성 개선 제안 종합

### 9.1 즉시 적용 가능한 개선 (코드 변경 소규모)

#### 개선 1: ClassifyNode — 정확한 매칭

```python
# Before (취약)
for cat in categories:
    if cat.lower() in response_text:
        matched = cat
        break

# After (개선)
import re

# exact word boundary 매칭
for cat in categories:
    pattern = r'\b' + re.escape(cat.lower()) + r'\b'
    if re.search(pattern, response_text):
        matched = cat
        break
```

정규식 `\b` word boundary를 사용하면 `"not easy"` 에서도 `easy`를 매칭하지만, 최소한 `"easygoing"` 같은 부분 문자열 매칭은 방지.

#### 개선 2: ReviewNode — 프롬프트/verdicts 정합성

```python
# verdicts가 ["approved", "retry"]이면 프롬프트도 일치시킴
default_prompt = (
    "...\n"
    "Respond in this exact format:\n"
    f"VERDICT: {' OR '.join(verdicts)}\n"  # ← 동적 생성
    "FEEDBACK: (your detailed feedback)"
)
```

#### 개선 3: CreateTodosNode — 다단계 JSON 추출

```python
def _extract_json_array(text: str) -> Optional[list]:
    """여러 전략으로 JSON 배열 추출 시도."""

    # 1. 직접 파싱
    try:
        result = json.loads(text.strip())
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # 2. 코드 블록 추출
    for pattern in [r'```json\s*(.*?)\s*```', r'```\s*(.*?)\s*```']:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                result = json.loads(m.group(1).strip())
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue

    # 3. 첫 번째 [ ... ] 블록 찾기
    stack = 0
    start = None
    for i, c in enumerate(text):
        if c == '[':
            if start is None:
                start = i
            stack += 1
        elif c == ']':
            stack -= 1
            if stack == 0 and start is not None:
                try:
                    result = json.loads(text[start:i+1])
                    if isinstance(result, list):
                        return result
                except json.JSONDecodeError:
                    start = None
                    continue

    return None  # 모든 전략 실패
```

#### 개선 4: 에러 복구 메커니즘

현재 `error` 필드가 설정되면 모든 라우터가 즉시 종료합니다. 일시적 에러(네트워크 타임아웃 등)에서도 복구 불가:

```python
# 제안: error_recovery 파라미터 추가 (BaseNode 레벨)
NodeParameter(
    name="error_recovery",
    label="Error Recovery Strategy",
    type="select",
    default="terminate",
    options=[
        {"label": "Terminate (즉시 종료)", "value": "terminate"},
        {"label": "Skip (건너뛰기)", "value": "skip"},
        {"label": "Retry (재시도)", "value": "retry"},
    ],
)
```

### 9.2 아키텍처 레벨 개선

#### 개선 5: Structured Output 노드 타입 추가

LLM 호출 + JSON 파싱이 결합된 새로운 논드 탑을 도입:

```python
@register_node
class StructuredLLMNode(BaseNode):
    """LLM 호출 + 구조화 출력 파싱이 통합된 노드.

    JSON 스키마를 정의하면:
    1. 프롬프트에 스키마가 자동 삽입
    2. 응답에서 다단계 JSON 추출
    3. 스키마 검증 + 정규화
    4. 검증 실패 시 자동 재시도 (1회)
    """
    node_type = "structured_llm"

    parameters = [
        NodeParameter(
            name="output_schema",
            label="Output JSON Schema",
            type="json",
            default='{"field": "string"}',
            description="Expected JSON output schema",
        ),
        NodeParameter(
            name="retry_on_parse_fail",
            label="Retry on Parse Failure",
            type="boolean",
            default=True,
        ),
    ]
```

#### 개선 6: 경로별 Iteration 분리

현재 `iteration`이 전역이므로, HARD 경로에서 빠르게 소진됩니다:

```python
# 제안: 경로별 카운터
class AutonomousState(TypedDict, total=False):
    iteration: int              # 전역 (유지)
    path_iteration: int         # 경로 내 루프 카운터 (신규)
```

`IterationGateNode`가 `path_iteration`을 기준으로 판단하도록 변경하면, 전역 iteration과 독립적으로 루프 제어 가능.

#### 개선 7: Review 프롬프트 동적 생성

```python
# ReviewNode.execute()에서 프롬프트 빌드 시
verdicts = config.get("verdicts", ["approved", "retry"])
template = config.get("prompt_template", ...)

# 프롬프트에 사용 가능한 verdict 목록을 동적으로 주입
# 현재 기본 프롬프트에 "rejected"가 하드코딩되어 있는 문제 해결
final_prompt = template.replace(
    "approved OR rejected",
    " OR ".join(verdicts)
)
```

### 9.3 개선 우선순위 매트릭스

| 우선순위 | 개선 | 영향 | 난이도 | 호환성 |
|---------|------|------|--------|--------|
| 🔴 P0 | Review 프롬프트/verdict 정합성 | 높음 | 낮음 | ✅ 호환 |
| 🔴 P0 | ClassifyNode word boundary 매칭 | 높음 | 낮음 | ✅ 호환 |
| 🟡 P1 | CreateTodos 다단계 JSON 추출 | 높음 | 중간 | ✅ 호환 |
| 🟡 P1 | Structured Output 유틸리티 생성 | 높음 | 중간 | ✅ 호환 |
| 🟡 P1 | JSON 스키마 명시 프롬프트 개선 | 중간 | 낮음 | ✅ 호환 |
| 🔵 P2 | StructuredLLMNode 신규 노드 | 중간 | 높음 | ✅ 호환 |
| 🔵 P2 | 에러 복구 전략 파라미터 | 중간 | 중간 | ✅ 호환 |
| ⚪ P3 | Tool Use / Function Calling | 높음 | 높음 | ⚠️ 모델 의존 |
| ⚪ P3 | 경로별 Iteration 분리 | 낮음 | 높음 | ⚠️ 스키마 변경 |

---

## 부록: 전체 엣지 맵

| # | Source | Target | Type | 조건 |
|---|--------|--------|------|------|
| 1 | START | mem_inject | simple | — |
| 2 | mem_inject | guard_cls | simple | — |
| 3 | guard_cls | classify | simple | — |
| 4 | classify | guard_dir | conditional | difficulty == "easy" |
| 5 | classify | guard_ans | conditional | difficulty == "medium" |
| 6 | classify | guard_todo | conditional | difficulty == "hard" |
| 7 | classify | END | conditional | error 발생 |
| 8 | guard_dir | dir_ans | simple | — |
| 9 | dir_ans | post_dir | simple | — |
| 10 | post_dir | END | simple | — |
| 11 | guard_ans | answer | simple | — |
| 12 | answer | post_ans | simple | — |
| 13 | post_ans | guard_rev | simple | — |
| 14 | guard_rev | review | simple | — |
| 15 | review | END | conditional | verdict == "approved" |
| 16 | review | gate_med | conditional | verdict == "retry" |
| 17 | review | END | conditional | error 발생 |
| 18 | gate_med | guard_ans | conditional | continue (iteration < max) |
| 19 | gate_med | END | conditional | stop (iteration ≥ max) |
| 20 | guard_todo | mk_todos | simple | — |
| 21 | mk_todos | post_todos | simple | — |
| 22 | post_todos | guard_exec | simple | — |
| 23 | guard_exec | exec_todo | simple | — |
| 24 | exec_todo | post_exec | simple | — |
| 25 | post_exec | chk_prog | simple | — |
| 26 | chk_prog | gate_hard | conditional | continue (items remaining) |
| 27 | chk_prog | guard_fr | conditional | complete (all items done) |
| 28 | gate_hard | guard_exec | conditional | continue (iteration < max) |
| 29 | gate_hard | guard_fr | conditional | stop (iteration ≥ max) |
| 30 | guard_fr | fin_rev | simple | — |
| 31 | fin_rev | post_fr | simple | — |
| 32 | post_fr | guard_fa | simple | — |
| 33 | guard_fa | fin_ans | simple | — |
| 34 | fin_ans | post_fa | simple | — |
| 35 | post_fa | END | simple | — |
