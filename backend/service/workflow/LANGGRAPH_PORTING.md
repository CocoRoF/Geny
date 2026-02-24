# LangGraph 포팅 원리

## 1. 개요

워크플로우 시스템의 핵심은 **사용자가 시각적으로 설계한 JSON 기반 워크플로우(`WorkflowDefinition`)를 LangGraph의 `StateGraph`로 컴파일하는 것**이다. 이 과정은 `WorkflowExecutor` 클래스가 담당하며, 5단계 파이프라인으로 동작한다.

```
JSON(WorkflowDefinition)
  → 1. 유효성 검증
  → 2. 노드 인스턴스 ↔ BaseNode 타입 매핑
  → 3. LangGraph 노드 함수 등록
  → 4. 엣지 와이어링 (직접 / 조건부)
  → 5. 컴파일 및 실행
```

## 2. 상세 파이프라인

### 2.1 단계 1: 유효성 검증

```python
errors = self._workflow.validate_graph()
if errors:
    raise ValueError("Workflow validation failed: ...")
```

`WorkflowDefinition.validate_graph()`가 그래프 구조를 검증한다:
- Start 노드 존재 여부 (정확히 1개)
- End 노드 존재 여부 (최소 1개)
- Start 노드에서 나가는 엣지 존재 여부
- 모든 엣지의 source/target이 실존하는 노드 ID인지
- 고립된 노드(start/end 제외)가 없는지

### 2.2 단계 2: 노드 인스턴스 → BaseNode 타입 해석

```python
graph_builder = StateGraph(AutonomousState)

instance_map: Dict[str, WorkflowNodeInstance] = {}
node_type_map: Dict[str, BaseNode] = {}

for inst in self._workflow.nodes:
    instance_map[inst.id] = inst

    if inst.node_type in ("start", "end"):
        continue  # 의사(pseudo) 노드 — LangGraph의 START/END로 처리

    base_node = self._registry.get(inst.node_type)
    if base_node is None:
        raise ValueError(f"Unknown node type '{inst.node_type}'")
    node_type_map[inst.id] = base_node
```

**핵심 개념:**
- `WorkflowNodeInstance.node_type`은 문자열 (예: `"llm_call"`, `"classify_difficulty"`)
- `NodeRegistry`에서 해당 문자열로 `BaseNode` 싱글턴 인스턴스를 조회
- `start`와 `end`는 실제 노드가 아닌 **의사 노드(pseudo-node)** — LangGraph의 `START`/`END` sentinel로 매핑됨

### 2.3 단계 3: LangGraph 노드 함수 등록

각 `BaseNode`의 `execute()` 메서드를 LangGraph 노드 함수로 래핑한다:

```python
for inst_id, base_node in node_type_map.items():
    inst = instance_map[inst_id]
    node_fn = self._make_node_function(base_node, inst)
    graph_builder.add_node(inst_id, node_fn)
```

래핑 함수의 구조:

```python
def _make_node_function(self, base_node: BaseNode, instance: WorkflowNodeInstance):
    ctx = self._context        # ExecutionContext (model, memory, guard 등)
    config = dict(instance.config)  # 사용자가 설정한 파라미터 값

    async def _node_fn(state: AutonomousState) -> Dict[str, Any]:
        return await base_node.execute(state, ctx, config)

    _node_fn.__name__ = f"node_{instance.id}_{instance.node_type}"
    return _node_fn
```

**변환 과정:**
```
BaseNode.execute(state, context, config)
  → 클로저로 context와 config를 바인딩
  → LangGraph 호환 함수: async def _node_fn(state) -> dict
```

LangGraph의 노드 함수는 `(state) → state_updates` 시그니처를 가져야 하므로, `ExecutionContext`와 `config`를 **클로저(closure)** 로 캡처하여 LangGraph가 요구하는 인터페이스에 맞춘다.

### 2.4 단계 4: 엣지 와이어링

엣지를 source 노드별로 그룹핑한 뒤, 노드 타입에 따라 다른 방식으로 연결한다:

```python
edges_by_source: Dict[str, List[WorkflowEdge]] = {}
for edge in self._workflow.edges:
    edges_by_source.setdefault(edge.source, []).append(edge)
```

#### 4a. Start 의사 노드 처리

```python
if source_inst.node_type == "start":
    first_target = self._resolve_target(edges[0].target, instance_map)
    graph_builder.add_edge(START, first_target)
```

LangGraph의 `START` sentinel → 첫 번째 대상 노드로 직접 연결.

#### 4b. End 의사 노드 처리

```python
def _resolve_target(self, target_id, instance_map):
    inst = instance_map.get(target_id)
    if inst and inst.node_type == "end":
        return END  # LangGraph END sentinel
    return target_id
```

대상이 `end` 노드이면 LangGraph의 `END` sentinel로 변환.

#### 4c. 조건부 노드 (Conditional Node)

조건부 노드란 **출력 포트가 2개 이상**이거나, **다수의 서로 다른 대상이 있는** 노드를 말한다:

```python
if base_node.is_conditional or self._has_multiple_targets(edges):
    config = source_inst.config
    routing_fn = base_node.get_routing_function(config)

    if routing_fn is None:
        routing_fn = self._make_fallback_router(edges, instance_map)

    edge_map = self._build_edge_map(edges, instance_map)
    graph_builder.add_conditional_edges(source_id, routing_fn, edge_map)
```

**라우팅 함수:**
- `BaseNode.get_routing_function(config)` → 상태를 보고 출력 포트 ID를 반환하는 함수
- 예: `ClassifyDifficultyNode`의 라우팅 함수는 `state["difficulty"]`를 읽어 `"easy"`, `"medium"`, `"hard"` 중 하나를 반환

**엣지 맵:**
```python
def _build_edge_map(self, edges, instance_map):
    edge_map = {}
    for edge in edges:
        port = edge.source_port or "default"
        target = self._resolve_target(edge.target, instance_map)
        edge_map[port] = target  # {"easy": "node_abc", "medium": "node_def", "hard": "node_ghi"}
    return edge_map
```

LangGraph의 `add_conditional_edges(source, routing_fn, edge_map)`은:
1. `source` 노드 실행 후 `routing_fn(state)`를 호출
2. 반환된 포트 ID로 `edge_map`에서 다음 노드를 결정

#### 4d. 단순 노드 (Direct Edge)

```python
else:
    target = self._resolve_target(edges[0].target, instance_map)
    graph_builder.add_edge(source_id, target)
```

출력 포트가 하나뿐인 노드는 단순 직접 연결.

### 2.5 단계 5: 컴파일 및 실행

```python
self._graph = graph_builder.compile()
```

`StateGraph.compile()` → `CompiledStateGraph` — LangGraph가 내부적으로 실행 엔진을 생성한다.

실행:

```python
async def run(self, input_text, max_iterations=50):
    initial_state = make_initial_autonomous_state(input_text, max_iterations=max_iterations)
    final_state = await self._graph.ainvoke(initial_state)
    return dict(final_state)
```

## 3. 상태 (State) 스키마

### 3.1 AutonomousState

LangGraph의 `TypedDict` 기반 상태 스키마이다. 모든 워크플로우 노드는 이 상태를 읽고 쓴다.

```python
class AutonomousState(TypedDict, total=False):
    input: str                      # 사용자 입력 프롬프트
    messages: Annotated[list, _add_messages]  # 메시지 누적 (append-only)
    current_step: str               # 현재 단계 추적
    last_output: Optional[str]      # 최근 모델 응답
    iteration: int                  # 전역 반복 카운터
    max_iterations: int             # 최대 반복 횟수
    difficulty: Optional[str]       # 난이도 분류 결과
    answer: Optional[str]           # Medium 경로 답변
    review_result: Optional[str]    # 리뷰 결과
    review_feedback: Optional[str]  # 리뷰 피드백
    review_count: int               # 리뷰 횟수
    todos: Annotated[List[TodoItem], _merge_todos]  # TODO 목록 (ID 기반 병합)
    current_todo_index: int         # 현재 실행 중인 TODO 인덱스
    final_answer: Optional[str]     # 최종 답변
    completion_signal: Optional[str]  # 완료 신호
    completion_detail: Optional[str]
    error: Optional[str]
    is_complete: bool
    context_budget: Optional[ContextBudget]  # 컨텍스트 예산
    fallback: Optional[FallbackRecord]       # 모델 폴백 기록
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]  # 메모리 참조
    metadata: Dict[str, Any]
```

### 3.2 커스텀 리듀서(Reducer)

LangGraph에서 `Annotated[type, reducer_fn]`으로 지정하면, 상태 업데이트 시 단순 덮어쓰기 대신 **커스텀 병합 로직**이 적용된다:

| 필드 | 리듀서 | 동작 |
|---|---|---|
| `messages` | `_add_messages` | 새 메시지를 기존 리스트에 **추가(append)** |
| `todos` | `_merge_todos` | TODO ID 기준 병합 (동일 ID면 새 값으로 덮어쓰기) |
| `memory_refs` | `_merge_memory_refs` | filename 기준 중복 제거 |
| 기타 모든 필드 | (기본) | 마지막 쓰기 우선 (last-write-wins) |

### 3.3 초기 상태 생성

```python
def make_initial_autonomous_state(input_text, *, max_iterations=50, **extra_metadata):
    return {
        "input": input_text,
        "messages": [],
        "current_step": "start",
        "iteration": 0,
        "max_iterations": max_iterations,
        "difficulty": None,
        "todos": [],
        "current_todo_index": 0,
        "completion_signal": CompletionSignal.NONE.value,
        "is_complete": False,
        "memory_refs": [],
        "metadata": extra_metadata,
        # ... 그 외 필드 None/기본값
    }
```

## 4. 시각적 매핑 다이어그램

### JSON 워크플로우 → LangGraph 변환

```
WorkflowDefinition (JSON)              LangGraph StateGraph
─────────────────────                   ─────────────────────

"start" node ──────────────────→  START (sentinel)
    ↓ edge                              ↓ add_edge(START, target)

"memory_inject" node ──────────→  graph.add_node("mem01", wrapped_fn)
    ↓ edge (source_port: default)       ↓ add_edge("mem01", "grd01")

"context_guard" node ──────────→  graph.add_node("grd01", wrapped_fn)
    ↓ edge                              ↓ add_edge("grd01", "cls01")

"classify_difficulty" node ────→  graph.add_node("cls01", wrapped_fn)
    ↓ edges (easy/medium/hard/end)      ↓ add_conditional_edges("cls01", route_fn, {
                                              "easy": "da01",
                                              "medium": "ans01",
                                              "hard": "todo01",
                                              "end": END
                                          })

"end" node ────────────────────→  END (sentinel)
```

## 5. Built-in AutonomousGraph와의 비교

### AutonomousGraph (하드코딩 방식)

```python
class AutonomousGraph:
    def build(self):
        graph = StateGraph(AutonomousState)
        graph.add_node("memory_inject", self._memory_inject_node)
        graph.add_node("guard_classify", self._make_context_guard_node("classify"))
        # ... 28개 노드를 인라인 메서드로 직접 등록
        graph.add_edge(START, "memory_inject")
        graph.add_conditional_edges("post_classify", self._route_by_difficulty, {...})
        # ... 모든 엣지를 코드로 직접 연결
        return graph.compile()
```

### WorkflowExecutor (워크플로우 방식)

```python
class WorkflowExecutor:
    def compile(self):
        graph = StateGraph(AutonomousState)
        for inst_id, base_node in node_type_map.items():
            graph.add_node(inst_id, self._make_node_function(base_node, inst))
        for source_id, edges in edges_by_source.items():
            # 엣지 타입에 따라 add_edge 또는 add_conditional_edges
        return graph.compile()
```

**차이점:**
- AutonomousGraph: 노드 로직이 **클래스 메서드**에 인라인으로 구현
- WorkflowExecutor: 노드 로직이 **BaseNode 서브클래스**에 분리되어 재사용 가능

**공통점:**
- 둘 다 `StateGraph(AutonomousState)`를 사용
- 둘 다 `graph.ainvoke(initial_state)`로 실행
- 동일한 상태 스키마, 동일한 리듀서 사용

## 6. 폴백 라우터

노드에 `get_routing_function()`이 구현되지 않은 경우, Executor가 자동으로 폴백 라우터를 생성한다:

```python
def _make_fallback_router(self, edges, instance_map):
    port_list = [e.source_port or "default" for e in edges]
    default_port = port_list[0] if port_list else "default"

    def _fallback(state):
        return default_port  # 항상 첫 번째 포트로 라우팅
    return _fallback
```

이 폴백은 **조건부 노드처럼 보이지만 실제 라우팅 로직이 없는** 경우에 사용된다. 일반적으로 노드 설계 시 `get_routing_function()`을 올바르게 구현하는 것이 권장된다.

## 7. ExecutionContext — 런타임 의존성

모든 노드는 `ExecutionContext`를 통해 런타임 의존성에 접근한다:

```python
@dataclass
class ExecutionContext:
    model: Any                 # ClaudeCLIChatModel — LLM 호출용
    session_id: str            # 세션 식별자
    memory_manager: Any        # SessionMemoryManager — 메모리 조회/기록
    session_logger: Any        # 세션 로거
    context_guard: Any         # ContextWindowGuard — 컨텍스트 예산 관리
    max_retries: int = 2       # 재시도 횟수
    model_name: Optional[str]  # 모델 이름

    async def resilient_invoke(self, messages, node_name) -> tuple:
        # 일시적 오류 시 지수 백오프 재시도
        # 반환: (response, fallback_updates)
```

`resilient_invoke()`는 rate_limit, overloaded, timeout, network_error에 대해 자동 재시도를 수행하며, 재시도 기록을 상태의 `fallback` 필드에 기록한다.
