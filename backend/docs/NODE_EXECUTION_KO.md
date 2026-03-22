# Node 실행 원리

## 1. 개요

워크플로우의 개별 노드가 **어떤 과정을 거쳐 실행되는지**, 상태가 **어떻게 전파되는지**, 그리고 **조건부 라우팅이 어떻게 동작하는지**를 상세히 설명한다.

## 2. 실행 생명주기

### 2.1 전체 실행 흐름

```
graph.ainvoke(initial_state)
  ↓
LangGraph 실행 엔진이 START에서 시작
  ↓
현재 노드의 래핑된 함수 호출: _node_fn(state)
  ↓
BaseNode.execute(state, context, config) 실행
  ↓
상태 업데이트 Dict 반환
  ↓
LangGraph가 리듀서로 상태 병합
  ↓
라우팅 결정 (직접 엣지 또는 조건부 라우팅)
  ↓
다음 노드로 이동 (또는 END에 도달하면 종료)
```

### 2.2 단일 노드 실행 상세

```python
# WorkflowExecutor가 생성한 래핑 함수
async def _node_fn(state: AutonomousState) -> Dict[str, Any]:
    return await base_node.execute(state, ctx, config)
```

1. **LangGraph 호출**: LangGraph 엔진이 현재 노드 ID에 매핑된 `_node_fn(state)`를 호출
2. **상태 수신**: `state` 파라미터로 현재 전체 상태가 전달됨
3. **로직 수행**: `base_node.execute()`가 필요한 처리 수행
4. **상태 업데이트 반환**: 변경할 필드만 담은 Dict 반환
5. **상태 병합**: LangGraph가 리듀서를 적용하여 전체 상태에 병합

## 3. execute() 메서드 상세

### 3.1 시그니처

```python
async def execute(
    self,
    state: Dict[str, Any],      # 현재 LangGraph 전체 상태
    context: ExecutionContext,   # 런타임 의존성 (model, memory, guard 등)
    config: Dict[str, Any],     # 사용자가 설정한 파라미터 값
) -> Dict[str, Any]:            # 상태 업데이트 딕셔너리
```

### 3.2 입력 파라미터

#### state (현재 상태)
- `AutonomousState` TypedDict의 현재 값
- 이전 노드들이 업데이트한 모든 필드 포함
- **읽기 전용으로 취급** — 직접 수정하지 않고 반환값으로 업데이트

```python
# 상태에서 값 읽기
input_text = state.get("input", "")
difficulty = state.get("difficulty")
iteration = state.get("iteration", 0)
todos = state.get("todos", [])
```

#### context (실행 컨텍스트)
- `ExecutionContext` 인스턴스
- 모든 노드가 공유하는 런타임 의존성

```python
# 모델 호출
response, fallback = await context.resilient_invoke(messages, "node_name")

# 메모리 접근
if context.memory_manager:
    memories = await context.memory_manager.get_relevant(query)

# 컨텍스트 가드
if context.context_guard:
    budget = context.context_guard.check_budget(messages)
```

#### config (노드 설정)
- 사용자가 프론트엔드에서 설정한 파라미터 값
- `WorkflowNodeInstance.config` 딕셔너리

```python
# 설정값 읽기
template = config.get("prompt_template", "{input}")
max_retries = config.get("max_retries", 3)
output_field = config.get("output_field", "last_output")
```

### 3.3 반환값 (상태 업데이트)

`Dict[str, Any]` — 변경할 상태 필드만 포함하는 딕셔너리를 반환한다.

```python
# 단순 예시
return {
    "last_output": response.content,
    "current_step": "llm_call_complete",
}

# 메시지 추가 (리듀서로 append)
return {
    "messages": [response],     # _add_messages 리듀서가 기존 리스트에 추가
    "last_output": response.content,
    "current_step": "answer_complete",
}

# TODO 업데이트 (리듀서로 ID 기반 병합)
return {
    "todos": [updated_todo],    # _merge_todos 리듀서가 ID 기반으로 병합
    "current_todo_index": next_index,
}

# 에러 발생 시
return {
    "error": str(e),
    "is_complete": True,
}
```

## 4. 실행 패턴별 상세

### 4.1 LLM 호출 패턴

대부분의 `model` 카테고리 노드가 따르는 패턴:

```python
async def execute(self, state, context, config):
    # 1. 프롬프트 준비
    template = config.get("prompt_template", "{input}")
    prompt = template.format(**{
        k: (v if isinstance(v, str) else str(v) if v is not None else "")
        for k, v in state.items()
    })

    # 2. 메시지 구성
    messages = [HumanMessage(content=prompt)]

    # 3. 모델 호출 (재시도 포함)
    try:
        response, fallback = await context.resilient_invoke(messages, "node_name")
    except Exception as e:
        return {"error": str(e), "is_complete": True}

    # 4. 응답 파싱 (필요 시)
    parsed_result = parse_response(response.content)

    # 5. 상태 업데이트 반환
    result = {
        "messages": [response],
        "last_output": response.content,
        "current_step": "step_name",
        "parsed_field": parsed_result,
    }
    result.update(fallback)  # 폴백 기록 병합
    return result
```

### 4.2 순수 로직 패턴

`logic` 카테고리 노드 — LLM 호출 없이 상태만 검사/변경:

```python
async def execute(self, state, context, config):
    # 상태 검사
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 50)
    signal = state.get("completion_signal")

    # 로직 판단
    if iteration >= max_iter or signal == CompletionSignal.COMPLETE.value:
        return {"current_step": "iteration_stopped"}

    return {"current_step": "iteration_continue"}
```

### 4.3 메모리 주입 패턴

`memory` 카테고리 노드:

```python
async def execute(self, state, context, config):
    if not context.memory_manager:
        return {"current_step": "memory_skip"}

    # 메모리 조회
    query = state.get("input", "")
    memories = await context.memory_manager.get_relevant_memories(query)

    # 메시지에 메모리 컨텍스트 주입
    memory_msg = HumanMessage(content=f"[Memory Context]\n{memories}")

    return {
        "messages": [memory_msg],
        "memory_refs": [{
            "filename": ref.filename,
            "source": ref.source,
            "char_count": len(ref.content),
            "injected_at_turn": state.get("iteration", 0),
        } for ref in matched_refs],
        "current_step": "memory_injected",
    }
```

### 4.4 가드 패턴 (Context Guard)

`resilience` 카테고리 — 모델 호출 전 컨텍스트 예산 검사:

```python
async def execute(self, state, context, config):
    if not context.context_guard:
        return {"current_step": "guard_pass"}

    messages = state.get("messages", [])
    budget = context.context_guard.check_budget(messages)

    budget_update = {
        "estimated_tokens": budget.estimated_tokens,
        "context_limit": budget.context_limit,
        "usage_ratio": budget.usage_ratio,
        "status": budget.status.value,
        "compaction_count": budget.compaction_count,
    }

    result = {
        "context_budget": budget_update,
        "current_step": f"guard_{config.get('position', 'unknown')}_done",
    }

    if budget.status == ContextStatus.BLOCK:
        result["is_complete"] = True
        result["error"] = "Context window budget exceeded"

    return result
```

## 5. 조건부 라우팅 상세

### 5.1 동작 원리

조건부 노드는 `execute()` 실행 후, LangGraph가 **라우팅 함수**를 호출하여 다음 노드를 결정한다:

```
execute(state) → state_updates → 상태 병합 → routing_fn(merged_state) → port_id → edge_map[port_id] → 다음 노드
```

### 5.2 get_routing_function() 구현

`execute()`로 상태를 먼저 업데이트하고, 그 결과를 바탕으로 라우팅하는 함수를 반환한다:

```python
# ClassifyDifficultyNode의 라우팅 함수
def get_routing_function(self, config):
    def _route(state):
        if state.get("error"):
            return "end"
        difficulty = state.get("difficulty")
        if difficulty == Difficulty.EASY:
            return "easy"
        elif difficulty == Difficulty.MEDIUM:
            return "medium"
        return "hard"
    return _route
```

```python
# IterationGateNode의 라우팅 함수
def get_routing_function(self, config):
    max_iter = config.get("max_iterations", 50)

    def _route(state):
        iteration = state.get("iteration", 0)
        signal = state.get("completion_signal")

        if iteration >= max_iter:
            return "stop"
        if signal == CompletionSignal.COMPLETE.value:
            return "stop"
        return "continue"
    return _route
```

```python
# ReviewNode의 라우팅 함수
def get_routing_function(self, config):
    max_reviews = config.get("max_reviews", 2)

    def _route(state):
        review_result = state.get("review_result")
        review_count = state.get("review_count", 0)

        if review_result == ReviewResult.APPROVED.value:
            return "approved"
        if review_count >= max_reviews:
            return "end"
        return "retry"
    return _route
```

### 5.3 엣지 맵과의 연동

라우팅 함수가 반환하는 문자열(포트 ID)이 엣지 맵의 키로 사용된다:

```python
# WorkflowExecutor 내부
edge_map = {
    "easy": "node_direct_answer",     # easy 포트 → DirectAnswer 노드
    "medium": "node_answer",          # medium 포트 → Answer 노드
    "hard": "node_create_todos",      # hard 포트 → CreateTodos 노드
    "end": END,                       # end 포트 → 그래프 종료
}

graph_builder.add_conditional_edges("classify_node", routing_fn, edge_map)
```

## 6. 상태 전파와 리듀서

### 6.1 상태 병합 과정

```python
# 노드 execute()가 반환:
updates = {"messages": [new_msg], "difficulty": "hard", "iteration": 1}

# LangGraph가 상태에 병합:
# - messages: _add_messages([기존_메시지들], [new_msg]) → 기존 + 새 메시지
# - difficulty: 단순 덮어쓰기 → "hard"
# - iteration: 단순 덮어쓰기 → 1
```

### 6.2 리듀서 동작 예시

#### messages (append-only)
```python
# 이전 상태: messages = [msg1, msg2]
# 노드 반환: {"messages": [msg3]}
# 병합 후:   messages = [msg1, msg2, msg3]
```

#### todos (ID 기반 병합)
```python
# 이전 상태: todos = [{"id": 1, "status": "pending"}, {"id": 2, "status": "pending"}]
# 노드 반환: {"todos": [{"id": 1, "status": "completed"}]}
# 병합 후:   todos = [{"id": 1, "status": "completed"}, {"id": 2, "status": "pending"}]
```

#### memory_refs (filename 기반 중복 제거)
```python
# 이전 상태: memory_refs = [{"filename": "a.md"}]
# 노드 반환: {"memory_refs": [{"filename": "a.md"}, {"filename": "b.md"}]}
# 병합 후:   memory_refs = [{"filename": "a.md"}, {"filename": "b.md"}]  # a.md 중복 제거
```

## 7. 에러 처리

### 7.1 노드 내부 에러 처리 패턴

```python
async def execute(self, state, context, config):
    try:
        response, fallback = await context.resilient_invoke(messages, "node_name")
        # ... 정상 처리
    except Exception as e:
        logger.exception(f"[{context.session_id}] node error: {e}")
        return {
            "error": str(e),
            "is_complete": True,  # 그래프 실행 중단
        }
```

### 7.2 resilient_invoke 재시도 메커니즘

```
시도 1 → 실패 (rate_limited) → 5초 대기
시도 2 → 실패 (overloaded) → 6초 대기
시도 3 → 성공 → fallback 기록과 함께 반환
          또는 실패 → 예외 raise → 노드가 catch하여 에러 상태 반환
```

재시도 대기 시간:
| 오류 유형 | 기본 대기 (초) | 수식 |
|---|---|---|
| RATE_LIMITED | 5.0 | 5.0 × (attempt + 1) |
| OVERLOADED | 3.0 | 3.0 × (attempt + 1) |
| TIMEOUT | 2.0 | 2.0 × (attempt + 1) |
| NETWORK_ERROR | 2.0 | 2.0 × (attempt + 1) |

## 8. 실행 추적

### 8.1 current_step 필드

모든 노드는 `current_step` 필드를 업데이트하여 현재 진행 상태를 추적한다:

```python
# 예: 실행 흐름
"start" → "memory_injected" → "guard_classify_done" → "difficulty_classified"
→ "direct_answer_complete" (easy path)
→ "answer_complete" → "review_done" (medium path)
→ "todos_created" → "todo_executed" → "progress_checked" (hard path)
```

### 8.2 iteration 카운터

`PostModelNode`가 매 모델 호출 후 `iteration`을 증가시켜, `IterationGateNode`가 무한 루프를 방지한다:

```python
# PostModelNode
return {
    "iteration": state.get("iteration", 0) + 1,
    "current_step": "post_model_done",
}
```
