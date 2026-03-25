# Optimized Graph 경량화 강화 계획 v3

> **목표:** 비용과 실행 시간의 극적 절감 + 치명적 프로세스 버그 수정
> **핵심 원칙:** 난이도 분류는 시스템의 가장 중요한 의사결정이다. LLM Agent가 수행한다.
> **기준 모델:** Claude CLI (Opus 4.6)
> **현재 상태:** Optimized Graph (18노드) 사용 중
> **트리거 사례:** "파일 5개를 GitHub에 Push" → 40분 / $5.37 소모

---

## 0. 설계 철학

### 난이도 분류 = 시스템의 심장

난이도 분류는 이후 모든 실행 경로를 결정하는 **가장 중요한 의사결정**이다.
이것을 regex 패턴 매칭 같은 규칙 기반 로직으로 대체하는 것은 **근본적으로 잘못된 설계**다.

**왜 규칙 기반 분류가 안 되는가:**
- 자연어의 의도는 표면적 키워드로 판단할 수 없다
- "push해줘"가 항상 단순한 건 아니다 — 컨텍스트에 따라 달라진다
- 규칙은 유지보수 불가능한 edge case의 늪이 된다
- 규칙이 틀리면 전체 실행 경로가 잘못된다 — 복구 불가

**올바른 접근:**
- **LLM Agent가 분류한다.** 항상.
- 분류 프롬프트를 **극도로 정밀하게** 작성한다
- 분류에 필요한 **충분한 컨텍스트**를 제공한다
- 분류 결과의 **신뢰도를 높이는 구조**를 만든다

> 분류에 LLM 1회를 쓰는 것은 낭비가 아니다.
> 잘못된 분류로 HARD 경로에 진입해서 LLM 10회를 낭비하는 것이 진짜 낭비다.

---

## 1. 현재 구조 분석

### 1.1 아키텍처 개요

```
┌─ AgentSession ─────────────────────────────────────────────────┐
│                                                                 │
│  ClaudeCLIChatModel (세션당 1개 인스턴스)                        │
│    └─ ClaudeProcess (세션당 1개 인스턴스)                        │
│         ├─ _conversation_id   (--resume용)                      │
│         ├─ _execution_count   (호출 카운터)                      │
│         └─ execute() 호출 시마다:                                │
│              ★ 새 서브프로세스 생성 (create_subprocess)  ← 문제  │
│              ★ stdin에 프롬프트 전달                             │
│              ★ stdout 스트림 파싱                                │
│              ★ 프로세스 종료 → 결과 반환                         │
│                                                                 │
│  ExecutionContext (모든 노드가 공유)                              │
│    ├─ model: ClaudeCLIChatModel (위 인스턴스 참조)               │
│    ├─ session_id                                                │
│    ├─ memory_manager                                            │
│    └─ resilient_invoke() → model.ainvoke() → process.execute()  │
│                                                                 │
│  WorkflowExecutor                                               │
│    └─ _make_node_function() → 각 노드에 context 주입            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 비용의 근본 원인

**모든 `resilient_invoke()` 호출 = 새 OS 서브프로세스 1개 생성.**

```
resilient_invoke(messages)
  → ClaudeCLIChatModel.ainvoke(messages)
    → ClaudeProcess.execute(prompt)
      → create_subprocess_cross_platform(["node", "cli.js", "--print", ...])
        → stdin 쓰기 → close → stdout 스트림 파싱 → process.wait()
```

프로세스당 오버헤드: Node.js 부팅 + CLI 초기화 1-3초 + MCP 연결 0.5-1초

### 1.3 현재 Optimized Graph 토폴로지 (18노드)

```
START
  → memory_inject          [LLM 0~1회: 메모리 필요 여부 판단]
  → relevance_gate         [LLM 0~1회: chat 모드일 때만]
  → adaptive_classify      [LLM 0~1회: _quick_classify 규칙 매칭 시 0회]
      ├─ [easy]   → easy_answer [LLM 1회] → END
      ├─ [medium] → answer → post_ans → review → retry loop → END
      ├─ [hard]   → mk_todos → guard → exec_todo(×N) → post → chk_prog
      │            → gate → ... → final_synth → END
      └─ [end]    → END
```

### 1.4 "파일 5개 Push" 시나리오 — 왜 $5.37인가

```
HARD 경로 실행 흐름:
─────────────────────────────────────────────────
1. memory_inject       → subprocess #1  → LLM 1회  $0.20
2. adaptive_classify   → subprocess #2  → LLM 1회  $0.15   ← "hard"로 분류
3. mk_todos            → subprocess #3  → LLM 1회  $0.30   ← TODO 8개 생성
4. exec_todo ×8        → subprocess #4~#11 → LLM 8회  $3.20   ← 각 TODO 개별 실행
5. final_synth         → subprocess #12 → LLM 1회  $0.30
6. subprocess 오버헤드 → 12 × 2초 = 24초 순수 낭비
7. rate limit 재시도   → 추가 subprocess 재생성      $1.00+
─────────────────────────────────────────────────
합계: ~12회 LLM × 12 subprocess ≈ $5.37 / 40분
```

**근본 원인 2가지:**
1. **분류 실패:** "파일 5개 Push"가 HARD로 분류됨 → TODO 8개 분해 → LLM 12회
2. **subprocess 재생성:** LLM 호출마다 새 OS 프로세스 생성 → 오버헤드 누적

---

## 2. 난이도 체계 재설계

### 2.1 현재 → 제안

```
현재 3단계                      제안 5단계
─────────                      ─────────
easy ─→ 단순 응답               easy ────→ 단순 응답 (LLM 1회)
                                tool_direct → Tool 직접 실행 (LLM 1회)
medium → 답변 + 리뷰            medium ──→ 답변 + 리뷰 (LLM 2~4회)
hard ──→ TODO + 루프            hard ────→ TODO + 일괄실행 (LLM 3~5회)
                                extreme ─→ TODO + 개별실행 (LLM N+3회)
```

### 2.2 각 난이도의 정확한 정의

| 난이도 | 핵심 판단 기준 | 실행 경로 | 예상 LLM 호출 |
|--------|-------------|----------|-------------|
| **easy** | 단순 질문/인사/사실확인. 도구 사용 불필요 | → easy_answer → END | 1회 |
| **tool_direct** | **도구 실행이 본질**인 작업. 계획 불필요. | → direct_tool → END | 1회 |
| **medium** | 추론이 필요하지만 1회 응답으로 완료 가능 | → answer → review → END | 2~4회 |
| **hard** | 다단계 작업. 계획 수립 + 실행 필요. 범위 예측 가능 | → mk_todos → batch_exec → synth → END | 3~5회 |
| **extreme** | 대규모/고난이도. 범위 불확실. 개별 TODO 실행 필요 | → mk_todos → exec(×N) → synth → END | N+3회 |

### 2.3 tool_direct의 핵심 — "도구 실행이 본질"

tool_direct는 단순히 "tool을 쓰는 작업"이 아니다.
**작업의 본질이 도구 실행 자체**인 경우다.

```
tool_direct인 경우:
  "GitHub에 Push해줘"        → git push가 본질
  "npm install lodash"       → 패키지 설치가 본질
  "파일 삭제해줘"             → rm이 본질
  "git status 확인해줘"      → git status가 본질
  "브랜치 만들어줘"           → git branch가 본질

tool_direct가 아닌 경우:
  "버그를 찾아서 고쳐줘"      → 분석이 본질 (도구는 수단)
  "이 코드를 리팩토링해줘"    → 설계가 본질 (도구는 수단)
  "함수를 작성해줘"          → 코드 작성이 본질 (도구는 수단)
  "테스트 결과를 분석해줘"    → 분석이 본질 (도구는 수단)
```

### 2.4 HARD vs EXTREME 경계

```
HARD:
  - 작업 범위가 명확하고 예측 가능
  - TODO 5개 이내로 분해 가능
  - 각 TODO가 독립적 (순서 의존성 낮음)
  예: "이 기능 구현해줘", "테스트 코드 작성해줘", "계획서 따라 구현"

EXTREME:
  - 작업 범위가 불확실하거나 매우 넓음
  - TODO 간 상호 의존성이 높음
  - 중간 결과에 따라 이후 계획이 바뀔 수 있음
  예: "전체 리팩토링", "아키텍처 재설계", "복잡한 시스템 처음부터 구축"

확신이 없으면: HARD 선택 (더 가벼운 경로가 안전)
```

---

## 3. 핵심 전략: LLM 분류 프롬프트 설계

> **이 섹션이 이 계획에서 가장 중요하다.**
> 분류 프롬프트의 품질이 전체 시스템의 비용 효율을 결정한다.

### 3.1 분류 프롬프트 (영문 — Node 내부 프롬프트는 전부 영어)

```
You are a task difficulty classifier for an autonomous coding agent.
Your classification determines the entire execution strategy and cost.
A wrong classification wastes significant time and money.

Classify the user's input into exactly one of these categories:

## EASY
Simple questions, greetings, factual lookups, basic calculations.
No tool usage needed. A single short response suffices.
Examples:
  - "Hello", "Thanks", "What is 2+2?"
  - "What's the capital of France?"
  - "Explain what a variable is"

## TOOL_DIRECT
The task IS a tool operation. The user wants a specific tool executed,
not reasoning or analysis. No planning or decomposition needed —
just run the tool and report the result.
Examples:
  - "Push to GitHub" → just run git push
  - "npm install lodash" → just run the install
  - "Delete the temp folder" → just delete it
  - "Show git status" → just run git status
  - "Create a new branch called feature/login" → just create it
NOT tool_direct (tools are means, not the goal):
  - "Fix this bug" → needs analysis first
  - "Refactor this code" → needs design decisions
  - "Write a function that..." → needs code generation

## MEDIUM
Requires reasoning, explanation, or code generation, but can be
fully addressed in a single response. No multi-step execution needed.
Examples:
  - "Explain how photosynthesis works"
  - "Compare Python and JavaScript"
  - "Write a sorting function"
  - "Review this code snippet"

## HARD
Requires planning and multi-step execution. The task can be
decomposed into a small number of steps (≤5) with predictable scope.
Each step is relatively independent.
Examples:
  - "Implement this feature based on the spec"
  - "Build a simple library with these functions"
  - "Debug this issue across multiple files"
  - "Write comprehensive tests for this module"

## EXTREME
Very high complexity. Large-scale refactoring, architecture redesign,
or building complex systems from scratch. Scope is uncertain and steps
are interdependent — later steps depend on results of earlier ones.
Examples:
  - "Refactor the entire project structure"
  - "Build a distributed system framework from scratch"
  - "Migrate to a microservices architecture"
Important: Following a plan to implement is HARD, not EXTREME.
Building a simple library is HARD, not EXTREME.
When unsure between HARD and EXTREME, choose HARD (cheaper and safer).

{memory_context}

Input to classify:
{input}

Respond with ONLY one word: easy, tool_direct, medium, hard, extreme
```

### 3.2 프롬프트 설계 원칙

1. **분류 기준에 "왜 이 경로인지"를 명시** — LLM이 비용 영향을 이해
2. **각 카테고리에 positive/negative 예시** — 경계 케이스 처리
3. **tool_direct의 "NOT" 예시 강조** — 가장 혼동되기 쉬운 경계
4. **HARD vs EXTREME 우선순위 명시** — "확신 없으면 HARD"
5. **memory_context 포함** — 이전 대화 맥락이 분류에 영향

### 3.3 기존 AdaptiveClassifyNode 수정 방향

현재 `AdaptiveClassifyNode`는 `_quick_classify()` 규칙 기반 분류를 먼저 시도하고,
규칙에 매칭되지 않을 때만 LLM에게 넘긴다.

**수정 방향:**
- `_quick_classify()`의 기존 easy/hard 규칙은 **유지** (이건 이미 존재하는 원본 코드)
- **새로운 규칙 기반 패턴은 추가하지 않는다** (EXTREME, tool_direct 등)
- `categories` 파라미터를 `"easy, tool_direct, medium, hard, extreme"`으로 확장
- LLM fallback 프롬프트를 §3.1의 정밀한 프롬프트로 교체
- `output_ports`에 `tool_direct`, `extreme` 추가

**핵심: 새로운 난이도(tool_direct, extreme)의 분류는 100% LLM이 담당한다.**

---

## 4. 구현 전략 (우선순위순)

### B0. [필수 버그 수정] 서브프로세스 Pre-warming

> Claude CLI는 `--print` 모드로 one-shot 실행된다 (stdin 쓰기 → close → 응답 → 종료).
> 장기 실행(persistent stdin)은 지원하지 않는다.
> 따라서 "프로세스 재활용"은 불가능하며, pre-warming으로 cold-start를 제거한다.

#### 구현

```
[현재: 순차 cold-start]
Node A: create_proc → 실행 → 종료 → [idle]
Node B: create_proc → 실행 → 종료 → [idle]
                          cold-start ─┘

[수정: pre-warm overlap]
Node A: create_proc → 실행 → 종료
                     ↗ 실행 중 백그라운드에서 다음 프로세스 미리 생성
Node B: [warm proc 즉시 사용] → 실행 → 종료
                               ↗ 다음 프로세스 미리 생성
Node C: [warm proc 즉시 사용] → ...
```

**수정 대상:** `process_manager.py` — `ClaudeProcess` 클래스

추가 필드:
- `_warm_process`: 미리 생성된 대기 프로세스
- `_warm_cmd` / `_warm_env`: warm 프로세스 생성에 사용된 인자
- `_prewarm_lock`: 동시 접근 방지 asyncio.Lock
- `_prewarm_task`: 백그라운드 pre-warm asyncio.Task

추가 메서드:
- `_build_prewarm_args()` → (cmd, env) 튜플 반환
- `_create_warm_process(cmd, env)` → subprocess 생성하고 반환
- `_ensure_warm_process()` → warm 프로세스 없으면 생성
- `_take_warm_process(cmd, env)` → warm 프로세스 가져오고 슬롯 비움
- `_discard_warm_process()` → warm 프로세스 kill 및 정리

`execute()` 수정:
- 시작 시: `_take_warm_process()` 시도 → 있으면 사용, 없으면 cold-start
- finally 블록: `_ensure_warm_process()`를 배경 태스크로 시작

`stop()` 수정:
- `_discard_warm_process()` 호출
- `_prewarm_task` 취소

**예상 효과:**

| 지표 | 현재 | 수정 후 |
|------|------|--------|
| 프로세스 초기화 대기 | 매 노드마다 1-3초 | 첫 노드만 1-3초, 이후 0초 |
| 12노드 실행 총 오버헤드 | 24-36초 | 1-3초 |

---

### P1. 난이도 체계 확장 (EXTREME + tool_direct)

#### P1-1. Difficulty enum 확장

**파일:** `state.py`

```python
class Difficulty(str, Enum):
    EASY = "easy"
    TOOL_DIRECT = "tool_direct"  # 신규
    MEDIUM = "medium"
    HARD = "hard"
    EXTREME = "extreme"          # 신규
```

#### P1-2. 분류 프롬프트 교체

**파일:** `sections.py` — `classify_difficulty()` 메서드

기존 easy/medium/hard 3단계 프롬프트를 §3.1의 5단계 프롬프트로 교체.
**프롬프트는 전부 영어로 작성.**

#### P1-3. AdaptiveClassifyNode 확장

**파일:** `adaptive_classify_node.py`

변경 사항:
1. `categories` 파라미터 기본값: `"easy, tool_direct, medium, hard, extreme"`
2. `output_ports`에 `tool_direct`, `extreme` 추가
3. `get_dynamic_output_ports` fallback에도 새 카테고리 반영
4. `get_routing_function`의 categories fallback 업데이트
5. **`_quick_classify` 함수는 건드리지 않음** — 기존 easy/hard 규칙은 원본 유지
   - _quick_classify가 None 반환 → LLM이 5단계 분류 수행
   - _quick_classify가 "easy" 반환 → 그대로 easy 경로
   - _quick_classify가 "hard" 반환 → 그대로 hard 경로 (EXTREME은 LLM만 판단)

#### P1-4. LLM fallback 강화

`adaptive_classify_node.py`의 LLM fallback 경로에서:
- `resilient_structured_invoke`의 `allowed_values`에 `tool_direct`, `extreme` 추가
- `coerce_values`에 새 카테고리 추가
- `extra_instruction`에 5단계 카테고리 명시

---

### P2. 경량 실행 노드

#### P2-1. DirectToolNode (신규)

**파일:** `nodes/task/direct_tool_node.py`

tool_direct로 분류된 작업을 **LLM 1회로 실행 완료**하는 노드.

```python
@register_node
class DirectToolNode(BaseNode):
    node_type = "direct_tool"
    category = "task"

    async def execute(self, state, context, config):
        prompt = (
            "You are a tool execution agent. Your ONLY job is to "
            "execute the requested operation using the available tools.\n\n"
            "Rules:\n"
            "- Execute the tool operation directly and immediately\n"
            "- Do NOT explain what you will do — just do it\n"
            "- Do NOT create plans or break down into steps\n"
            "- Do NOT ask clarifying questions\n"
            "- Report the result concisely after execution\n\n"
            f"Task:\n{state['input']}"
        )
        response, fallback = await context.resilient_invoke(
            [HumanMessage(content=prompt)], "direct_tool"
        )
        return {
            "final_answer": response.content,
            "is_complete": True,
            ...
        }
```

**핵심:** TODO 분해 없이 LLM에게 직접 도구 실행을 지시.
LLM은 Claude CLI를 통해 도구를 호출하므로, 별도 tool invocation 로직 불필요.

#### P2-2. BatchExecuteTodoNode (신규)

**파일:** `nodes/task/batch_execute_todo_node.py`

HARD 경로에서 TODO를 **1회 LLM 호출로 일괄 실행**하는 노드.

```python
@register_node
class BatchExecuteTodoNode(BaseNode):
    node_type = "batch_execute_todo"
    category = "task"

    async def execute(self, state, context, config):
        todos = state.get("todos", [])
        pending = [t for t in todos if t["status"] == "pending"]

        prompt = (
            "You are executing a multi-step task plan. "
            "Complete ALL of the following TODO items in order.\n\n"
            f"Overall Goal:\n{state['input']}\n\n"
            f"TODO Items:\n{format_todos(pending)}\n\n"
            "Execute each item thoroughly and report results."
        )
        response, fallback = await context.resilient_invoke(
            [HumanMessage(content=prompt)], "batch_execute_todo"
        )
        # 모든 pending → completed
        updated = mark_all_completed(todos, response.content)
        return {"todos": updated, "last_output": response.content, ...}
```

#### P2-3. 노드 등록

**파일:** `nodes/__init__.py` — 신규 노드 2개 import 추가

---

### P3. Ultra-Light 그래프 템플릿

#### P3-1. 토폴로지 (5경로)

```
START
  → memory_inject           [LLM 0~1회: 기존 LLM 게이트 유지]
  → adaptive_classify       [LLM 1회: 5단계 분류]
      │
      ├─ [easy]
      │    → easy_answer [LLM 1회, set_complete]
      │    → END
      │
      ├─ [tool_direct]
      │    → direct_tool [LLM 1회, set_complete]
      │    → END
      │
      ├─ [medium]
      │    → answer [LLM 1회] → post_ans → review [LLM 1회]
      │      ├─ [approved] → END
      │      ├─ [retry] → gate_med → answer (loop)
      │      └─ [end] → END
      │
      ├─ [hard]
      │    → mk_todos [LLM 1회, max_todos=5]
      │    → batch_exec [LLM 1회]
      │    → final_synth [LLM 1회, skip_threshold=3]
      │    → END
      │
      └─ [extreme]
           → mk_todos [LLM 1회, max_todos=20]
           → guard_exec → exec_todo [LLM 1회/TODO]
           → post_exec → chk_prog
             ├─ [continue] → gate_ext → guard_exec (loop)
             └─ [complete] → final_synth [LLM 1회]
                            → END
```

#### P3-2. 경로별 LLM 호출 비교

| 경로 | 현재 Optimized | Ultra-Light | 절감 |
|------|---------------|-------------|------|
| 인사말 ("안녕") | mem[1] + classify[0] + easy[1] = **2회** | mem[0~1] + classify[1] + easy[1] = **2~3회** | 동등 |
| 도구 작업 ("Push") | mem[1] + classify[1] + todos[1] + exec×N + synth[1] = **N+4회** | mem[0~1] + classify[1] + direct[1] = **2~3회** | **~90%** |
| 중간 ("함수 작성") | mem[1] + classify[1] + ans[1] + rev[1] = **4회** | mem[0~1] + classify[1] + ans[1] + rev[1] = **3~4회** | 0~25% |
| 복잡 ("기능 구현") | mem[1] + classify[1] + todos[1] + exec×N + synth[1] = **N+4회** | mem[0~1] + classify[1] + todos[1] + batch[1] + synth[0~1] = **3~5회** | **50~70%** |
| 초고난이도 ("리팩토링") | 동일 = **N+4회** | mem[0~1] + classify[1] + todos[1] + exec×N + synth[1] = **N+3~4회** | 0~10% |

#### P3-3. 비용 절감 추정

| 시나리오 | 현재 비용 | Ultra-Light 비용 | 절감율 |
|----------|----------|-----------------|--------|
| "파일 5개 Push" | **$5.37** | **$0.30~0.50** | **90~94%** |
| "안녕하세요" | $0.30 | $0.30~0.45 | 동등 |
| "함수 하나 작성" | $0.60 | $0.45~0.60 | 0~25% |
| "기능 구현" (TODO 5개) | $2.50 | $0.60~1.00 | **60~76%** |
| "전체 리팩토링" | $5.00 | $5.00 | 0% |

---

### P4. FinalSynthesis 조건부 스킵

**파일:** `final_synthesis_node.py`

```python
# skip_threshold 파라미터 추가 (기본값 0 = 항상 실행)
# HARD 경로에서 skip_threshold=3 설정:
# → TODO 3개 이하 + 전부 완료 → LLM 호출 없이 마지막 결과 반환
```

이것은 "규칙 기반 분류"가 아니다.
실행 결과 상태(TODO 개수, 완료 여부)에 기반한 **실행 최적화**다.

---

## 5. 구현 계획

### Phase 0: 필수 버그 수정 [최우선]

| # | 작업 | 대상 파일 |
|---|------|----------|
| B0-1 | Pre-warming 필드 추가 (`__init__`) | `process_manager.py` |
| B0-2 | Pre-warm 메서드 5개 구현 | `process_manager.py` |
| B0-3 | `execute()` 수정: warm process 우선 사용 | `process_manager.py` |
| B0-4 | `execute()` finally: 백그라운드 pre-warm 시작 | `process_manager.py` |
| B0-5 | `stop()` 수정: warm process 정리 | `process_manager.py` |

### Phase 1: 난이도 체계 확장

| # | 작업 | 대상 파일 |
|---|------|----------|
| P1-1 | `Difficulty` enum에 TOOL_DIRECT, EXTREME 추가 | `state.py` |
| P1-2 | 분류 프롬프트 교체 (§3.1) | `sections.py` |
| P1-3 | AdaptiveClassify categories/ports 확장 | `adaptive_classify_node.py` |
| P1-4 | LLM fallback 경로에 새 카테고리 반영 | `adaptive_classify_node.py` |

### Phase 2: 경량 노드 개발

| # | 작업 | 대상 파일 |
|---|------|----------|
| P2-1 | `DirectToolNode` 구현 | 신규: `nodes/task/direct_tool_node.py` |
| P2-2 | `BatchExecuteTodoNode` 구현 | 신규: `nodes/task/batch_execute_todo_node.py` |
| P2-3 | 신규 노드 등록 | `nodes/__init__.py` |
| P2-4 | `FinalSynthesis` skip_threshold 추가 | `final_synthesis_node.py` |

### Phase 3: Ultra-Light 템플릿

| # | 작업 | 대상 파일 |
|---|------|----------|
| P3-1 | `create_ultra_light_template()` 함수 작성 | `templates.py` |
| P3-2 | `ALL_TEMPLATES`에 등록 | `templates.py` |

### Verification

| # | 작업 |
|---|------|
| V1 | 전체 수정 파일 `py_compile` 구문 검사 |
| V2 | 런타임 import 테스트 (노드 등록, 템플릿 빌드) |
| V3 | 분류 프롬프트가 영어인지 확인 |
| V4 | 그래프 무결성 (노드 ID 중복, 깨진 엣지, 도달 불가 노드) |

---

## 6. 수정하지 않는 것

명시적으로 **건드리지 않는** 부분:

| 항목 | 이유 |
|------|------|
| `_quick_classify()` 원본 로직 | 기존 easy/hard 규칙은 원래 코드. 제거하지도, 확장하지도 않음 |
| Memory inject LLM 게이트 | 기존 LLM 기반 게이트 유지. 규칙 기반 스킵 추가 안 함 |
| EXTREME 규칙 기반 패턴 | **추가 안 함.** EXTREME은 오직 LLM이 판단 |
| tool_direct 규칙 기반 패턴 | **추가 안 함.** tool_direct은 오직 LLM이 판단 |
| NOT_EXTREME 안티패턴 | **추가 안 함.** LLM 프롬프트에 경계 예시로 대체 |

---

## 7. 성공 지표

| 지표 | 현재 | 목표 |
|------|------|------|
| "파일 Push" 비용 | $5.37 | **< $0.50** |
| "파일 Push" 시간 | 40분 | **< 2분** |
| subprocess cold-start 오버헤드 | 노드당 1-3초 | 첫 노드만 (이후 0초) |
| HARD 경로 LLM 호출 수 | N+4회 | **3~5회** |
| 분류 정확도 | 미측정 | LLM이 판단 (규칙 기반 X) |
