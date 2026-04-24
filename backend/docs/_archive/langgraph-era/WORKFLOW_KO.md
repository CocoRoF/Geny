# Workflow System

> 시각적 워크플로우 편집기에서 정의한 그래프를 LangGraph StateGraph로 컴파일하고 실행하는 엔진

## 아키텍처 개요

```
WorkflowDefinition (JSON)
        │
        ▼
  WorkflowExecutor.compile()
        │
        ├── NodeRegistry — 등록된 20종 노드 타입 조회
        ├── ExecutionContext — 모델, 메모리, 로거 주입
        └── StateGraph(AutonomousState) — LangGraph 그래프 빌드
                │
                ▼
        CompiledStateGraph
                │
                ▼
        graph.ainvoke(initial_state)
                │
                ▼
          최종 실행 결과
```

## WorkflowDefinition

워크플로우의 JSON 직렬화 모델. 프론트엔드 에디터와 백엔드 엔진이 공유하는 스키마.

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | `str` | UUID — 워크플로우 고유 ID |
| `name` | `str` | 표시 이름 |
| `description` | `str` | 설명 |
| `nodes` | `List[WorkflowNodeInstance]` | 모든 노드 인스턴스 |
| `edges` | `List[WorkflowEdge]` | 모든 방향 간선 |
| `is_template` | `bool` | 내장 템플릿 여부 |
| `template_name` | `Optional[str]` | 템플릿 식별자 |
| `created_at` / `updated_at` | `str` | ISO 8601 타임스탬프 |

### WorkflowNodeInstance

```json
{
  "id": "abc12345",
  "node_type": "classify",
  "label": "Classify Difficulty",
  "config": {
    "categories": "easy,medium,hard",
    "default_category": "medium"
  },
  "position": {"x": 300, "y": 200}
}
```

| 필드 | 설명 |
|------|------|
| `id` | 인스턴스 고유 ID (8자 UUID) |
| `node_type` | 등록된 BaseNode의 `node_type` 참조 |
| `label` | 에디터 캔버스 이름 |
| `config` | 사용자가 설정한 파라미터 값 |
| `position` | 캔버스 좌표 |

### WorkflowEdge

```json
{
  "id": "edge001",
  "source": "abc12345",
  "target": "def67890",
  "source_port": "hard",
  "label": "Hard Path"
}
```

| 필드 | 설명 |
|------|------|
| `source` | 출발 노드 인스턴스 ID |
| `target` | 도착 노드 인스턴스 ID |
| `source_port` | 출력 포트 ID (`default` 또는 조건부 포트명) |

### 유효성 검증

`validate_graph()` 메서드로 다음을 검증:
- `start` 노드가 정확히 1개
- `end` 노드가 1개 이상
- `start` 노드에 outgoing 엣지 존재
- 모든 엣지의 source/target이 유효한 노드 ID
- 고아 노드 없음

---

## WorkflowExecutor

`WorkflowDefinition` → `CompiledStateGraph` 변환 엔진.

### compile()

1. `validate_graph()` 호출 — 실패 시 `ValueError`
2. `StateGraph(AutonomousState)` 생성
3. 각 `WorkflowNodeInstance` → `BaseNode` (레지스트리 조회, `start`/`end` 의사 노드는 스킵)
4. `_make_node_function(base_node, instance)` — 비동기 LangGraph 노드 함수 생성
   - 실행 전후 `session_logger`를 통한 enter/exit/error 로깅
   - 실행 시간 측정
5. 엣지 와이어링:
   - **단일 대상**: `add_edge(source, target)`
   - **다중 대상**: `add_conditional_edges(source, routing_fn, edge_map)`
   - **START 의사 노드**: `add_edge(START, first_target)`
   - **END 의사 노드**: LangGraph `END` 센티널로 매핑
6. `graph_builder.compile()` → `CompiledStateGraph`

### run()

```python
async def run(self, input_text: str, max_iterations: int = 50, **extra_metadata) -> Dict[str, Any]
```

- 필요 시 자동 컴파일
- `make_initial_autonomous_state()` 로 초기 상태 생성
- `await self._graph.ainvoke(initial_state)` 실행
- 최종 상태 딕셔너리 반환

### 라우팅 결정 로직

조건부 노드의 라우팅은 `BaseNode.get_routing_function(config)` 메서드가 반환:

```python
# classify 예시
def routing_fn(state: Dict) -> str:
    value = state.get("difficulty", "medium").lower()
    if value in categories:
        return value
    return default_category
```

`WorkflowExecutor`는 같은 소스에서 나가는 엣지가 **2개 이상의 서로 다른 타겟**을 가리킬 때만 조건부 라우팅 적용.

---

## 노드 레지스트리 시스템

### @register_node 데코레이터

```python
@register_node
class MyNode(BaseNode):
    node_type = "my_node"
    ...
```

`NodeRegistry` 싱글톤에 자동 등록. 별칭(alias)을 통한 하위 호환성 지원.

### BaseNode ABC

모든 워크플로우 노드의 부모 클래스.

```python
class BaseNode(ABC):
    node_type: str          # 고유 식별자
    label: str              # 표시 이름
    description: str        # 설명
    category: str           # 팔레트 그룹 (model, logic, resilience, task, memory)
    parameters: List[NodeParameter]   # 설정 가능한 파라미터
    output_ports: List[OutputPort]    # 라우팅 포트

    @abstractmethod
    async def execute(self, state, context, config) -> Dict[str, Any]: ...

    def get_routing_function(self, config) -> Optional[Callable]: ...
    def get_dynamic_output_ports(self, config) -> Optional[List[OutputPort]]: ...
```

---

## 전체 노드 카탈로그 (20종)

### Model 카테고리 (6종)

| 노드 | `node_type` | 조건부 | 설명 |
|------|------------|--------|------|
| **LLM Call** | `llm_call` | ✗ | 범용 LLM 호출. `{field}` 치환 프롬프트 템플릿, 다중 출력 매핑, 조건부 프롬프트 전환 |
| **Classify** | `classify` | ✓ | 구조화 출력 LLM 분류. 카테고리별 port로 라우팅. 기본: easy/medium/hard |
| **Adaptive Classify** | `adaptive_classify` | ✓ | 규칙 기반 빠른 경로 + LLM 폴백. 정규식 패턴으로 짧은 입력은 LLM 없이 "easy" 분류 (8-15초 절약) |
| **Direct Answer** | `direct_answer` | ✗ | easy 태스크용 단발 응답. 설정 가능한 출력 필드, 선택적 완료 마킹 |
| **Answer** | `answer` | ✗ | 리뷰 피드백 통합 응답. 첫 시도는 primary 프롬프트, 재시도는 retry_template 사용 |
| **Review** | `review` | ✓ | self-routing 품질 게이트. 구조화 출력 verdict + feedback. 기본: approved/retry |

### Logic 카테고리 (5종)

| 노드 | `node_type` | 조건부 | 설명 |
|------|------------|--------|------|
| **Conditional Router** | `conditional_router` | ✓ | 순수 상태 기반 라우팅. 상태 필드 읽기 → route_map JSON으로 포트 매핑 |
| **Iteration Gate** | `iteration_gate` | ✓ | 루프 방지. 반복 한계, 컨텍스트 예산, 완료 시그널, 커스텀 필드 체크 |
| **Check Progress** | `check_progress` | ✓ | 목록 완료 체크. 인덱스 vs 목록 길이 비교 → continue/complete |
| **State Setter** | `state_setter` | ✗ | 상태 필드를 JSON 설정값으로 세팅. 초기화, 카운터 리셋, 설정 주입 |
| **Relevance Gate** | `relevance_gate` | ✓ | 브로드캐스트 메시지 필터. `is_chat_message=True`일 때만 활성화 |

### Resilience 카테고리 (2종)

| 노드 | `node_type` | 조건부 | 설명 |
|------|------------|--------|------|
| **Context Guard** | `context_guard` | ✗ | 토큰 예산 체크. 메시지에서 사용량 추정 → `context_budget` (safe/warning/block/overflow) |
| **Post Model** | `post_model` | ✗ | LLM 호출 후 처리: (1) iteration 증가, (2) 완료 시그널 감지, (3) 단기 메모리 기록 |

### Task 카테고리 (5종)

| 노드 | `node_type` | 조건부 | 설명 |
|------|------------|--------|------|
| **Create TODOs** | `create_todos` | ✗ | 복잡 작업을 구조화 TODO 목록으로 분해 (Pydantic `CreateTodosOutput` 검증) |
| **Execute TODO** | `execute_todo` | ✗ | 단일 TODO 항목 실행. 컨텍스트 인지형, 상태 자동 갱신 |
| **Final Review** | `final_review` | ✗ | 완료된 모든 항목의 구조화 품질 리뷰 (`FinalReviewOutput`) |
| **Final Answer** | `final_answer` | ✗ | 목록 결과 + 리뷰 피드백에서 최종 응답 합성. 완료 마킹 |
| **Final Synthesis** | `final_synthesis` | ✗ | Final Review + Final Answer를 하나의 LLM 호출로 병합 (1 라운드트립 절약) |

### Memory 카테고리 (2종)

| 노드 | `node_type` | 조건부 | 설명 |
|------|------------|--------|------|
| **Memory Inject** | `memory_inject` | ✗ | LLM 게이트 메모리 주입. 세션 요약, MEMORY.md, FAISS 벡터 검색, 키워드 검색 통합 |
| **Transcript Record** | `transcript_record` | ✗ | 상태 필드를 단기 메모리 트랜스크립트에 기록 |

---

## AutonomousState

LangGraph 그래프의 공유 상태 TypedDict. 모든 노드가 읽고 쓰는 단일 상태 객체.

### 주요 필드

| 필드 | 타입 | Reducer | 설명 |
|------|------|---------|------|
| `input` | `str` | last-wins | 사용자 입력 |
| `messages` | `list` | **append** | LLM 대화 이력 |
| `iteration` | `int` | last-wins | 반복 카운터 |
| `max_iterations` | `int` | last-wins | 최대 반복 수 |
| `difficulty` | `Optional[str]` | last-wins | 난이도 분류 결과 |
| `answer` | `Optional[str]` | last-wins | medium 경로 응답 |
| `review_result` | `Optional[str]` | last-wins | 리뷰 판정 |
| `review_feedback` | `Optional[str]` | last-wins | 리뷰 피드백 |
| `todos` | `List[TodoItem]` | **merge by ID** | hard 경로 할 일 목록 |
| `current_todo_index` | `int` | last-wins | 다음 TODO 인덱스 |
| `final_answer` | `Optional[str]` | last-wins | 합성 최종 응답 |
| `completion_signal` | `Optional[str]` | last-wins | continue/complete/blocked/error/none |
| `is_complete` | `bool` | last-wins | 워크플로우 종료 플래그 |
| `total_cost` | `float` | **accumulate** | 누적 비용 (USD) |
| `memory_refs` | `List[MemoryRef]` | **deduplicate** | 로드된 메모리 청크 |
| `memory_context` | `Optional[str]` | last-wins | 포맷된 메모리 텍스트 |
| `context_budget` | `Optional[ContextBudget]` | last-wins | 토큰 사용량 추적 |
| `fallback` | `Optional[FallbackRecord]` | last-wins | 모델 폴백 상태 |
| `metadata` | `Dict[str, Any]` | last-wins | 확장 메타데이터 |

### 커스텀 Reducer

- **`_add_messages`**: 단순 리스트 연결
- **`_merge_todos`**: `id` 키 기준 병합, right wins
- **`_merge_memory_refs`**: `filename` 기준 중복 제거
- **`_add_floats`**: 값 합산 (비용 누적)

### Enum 타입

| Enum | 값 |
|------|------|
| `Difficulty` | `EASY`, `MEDIUM`, `HARD` |
| `CompletionSignal` | `CONTINUE`, `COMPLETE`, `BLOCKED`, `ERROR`, `NONE` |
| `ReviewResult` | `APPROVED`, `REJECTED` |
| `TodoStatus` | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `ContextBudgetStatus` | `OK`, `WARN`, `BLOCK`, `OVERFLOW` |

---

## ExecutionContext

노드 실행에 필요한 의존성을 담는 컨텍스트 객체.

```python
@dataclass
class ExecutionContext:
    model: Any                          # ClaudeCLIChatModel
    session_id: str = "unknown"
    memory_manager: Any = None          # SessionMemoryManager
    session_logger: Any = None          # SessionLogger
    context_guard: Any = None           # ContextWindowGuard
    max_retries: int = 2
    model_name: Optional[str] = None
```

### resilient_invoke()

LLM 호출의 자동 재시도 및 비용 추적.

```python
async def resilient_invoke(messages, node_name) -> (AIMessage, Dict)
```

- recoverable 오류 (rate_limited, overloaded, timeout, network)에 대해 `max_retries`까지 재시도
- 지수 백오프 적용
- 응답에서 `cost_usd` 추출하여 `{"total_cost": float}` 반환

### resilient_structured_invoke()

구조화 출력 LLM 호출. JSON Schema 지시문 주입 → 파싱 → 검증.

```python
async def resilient_structured_invoke(
    messages, node_name, schema_cls,
    *, allowed_values, coerce_field, coerce_values, coerce_default
) -> (pydantic_instance, Dict)
```

1. 마지막 `HumanMessage`에 JSON 스키마 지시문 추가
2. `resilient_invoke()` → 원시 텍스트
3. `parse_structured_output()` — 4단계 추출: direct JSON → code block → bracket match
4. 파싱 실패 시 보정 프롬프트로 1회 재시도
5. `coerce_field`/`coerce_values`로 enum 유사 필드 퍼지 매칭

---

## 구조화 출력 스키마

| 스키마 | 필드 | 사용 노드 |
|--------|------|----------|
| `ClassifyOutput` | `classification`, `confidence`, `reasoning` | Classify, Adaptive Classify |
| `ReviewOutput` | `verdict`, `feedback`, `issues` | Review |
| `MemoryGateOutput` | `needs_memory`, `reasoning` | Memory Inject |
| `RelevanceOutput` | `relevant`, `reasoning` | Relevance Gate |
| `CreateTodosOutput` | `todos: List[TodoItem]` | Create TODOs |
| `FinalReviewOutput` | `overall_quality`, `completed_summary`, `issues_found`, `recommendations` | Final Review |

---

## 내장 워크플로우 템플릿

### template-simple (6 노드)

가장 단순한 직선 그래프:

```
START → Memory Inject → Context Guard → LLM Call → Post Model → END
```

### template-autonomous (28 노드)

난이도 기반 3경로 분기:

```
START → Memory Inject → Relevance Gate → Context Guard → Classify
  ├── [easy]   → Direct Answer → Post → END
  ├── [medium] → Answer → Post → Review
  │               ↑              ├── [approved] → END
  │               └──────────────┤
  │                              └── [retry] → (loop back)
  └── [hard]   → Create TODOs → Post → Execute TODO → Post → Check Progress
                                          ↑                   ├── [continue] → Iteration Gate
                                          │                   │    ├── [continue] → (loop)
                                          │                   │    └── [stop] → Final Review
                                          └───────────────────┘
                                                              └── [complete] → Final Review
                                                                    → Final Answer → Post → END
```

### template-optimized-autonomous (18 노드)

최적화 변형:
- **Adaptive Classify** → Classify + Guard + Post 통합 (규칙 기반 빠른 경로)
- **LLM Call** → Direct Answer + Guard + Post 통합
- **Final Synthesis** → Final Review + Final Answer + Guard + Post 통합
- 약 25-47% 속도 향상

---

## WorkflowStore

JSON 파일 기반 워크플로우 저장소. `backend/workflows/` 디렉토리에 저장.

| 메서드 | 설명 |
|--------|------|
| `save(workflow)` | 저장/갱신 |
| `load(workflow_id)` | ID로 로드 |
| `delete(workflow_id)` | 파일 삭제 |
| `list_all()` | 전체 목록 |
| `list_templates()` | 내장 템플릿만 |
| `list_user_workflows()` | 사용자 워크플로우만 |

파일명: ID를 sanitize하여 `{safe_id}.json`으로 저장.

---

## WorkflowInspector

컴파일 로직을 미러링하여 구조 분석 리포트 생성:

```python
inspect_workflow(workflow) -> Dict[str, Any]
```

반환값:
- `code`: 컴파일된 그래프의 Python 의사 코드
- `nodes`: 노드별 상세 (타입, 카테고리, 라우팅 로직)
- `edges`: 엣지별 상세 (simple/conditional)
- `state`: `WorkflowStateAnalysis` (필드 사용 현황)
- `summary`: 통계 (노드 수, 엣지 수)
- `validation`: 그래프 유효성 검증 결과

---

## Compiler (Dry-Run)

워크플로우를 LLM 호출 없이 테스트하는 컴파일러. 자세한 내용은 [Compiler 문서](../service/workflow/compiler/SUDO_COMPILER.md) 참조.

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/workflows/nodes` | 노드 타입 카탈로그 |
| `GET` | `/api/workflows/nodes/{type}/help` | 노드 도움말 (다국어) |
| `GET` | `/api/workflows` | 전체 워크플로우 목록 |
| `POST` | `/api/workflows` | 워크플로우 생성 |
| `GET` | `/api/workflows/templates` | 내장 템플릿 목록 |
| `GET` | `/api/workflows/{id}` | 워크플로우 조회 |
| `PUT` | `/api/workflows/{id}` | 워크플로우 수정 (템플릿 불가) |
| `DELETE` | `/api/workflows/{id}` | 워크플로우 삭제 (템플릿 불가) |
| `POST` | `/api/workflows/{id}/clone` | 워크플로우 복제 |
| `POST` | `/api/workflows/{id}/validate` | 그래프 구조 검증 |
| `POST` | `/api/workflows/{id}/compile-view` | 컴파일 뷰 (의사 코드 + 상태 분석) |
| `GET` | `/api/workflows/state/fields` | AutonomousState 필드 정의 |
| `POST` | `/api/workflows/{id}/execute` | 세션에서 워크플로우 실행 |

---

## 관련 파일

```
service/workflow/
├── workflow_model.py          # WorkflowDefinition Pydantic 모델
├── workflow_executor.py       # WorkflowDefinition → CompiledStateGraph 컴파일러
├── workflow_store.py          # JSON 파일 기반 저장소
├── workflow_inspector.py      # 그래프 구조 분석기
├── workflow_state.py          # StateFieldDef, NodeStateUsage, 상태 분석
├── templates.py               # 내장 템플릿 팩토리
├── compiler/                  # Dry-Run 컴파일러 (별도 문서)
└── nodes/
    ├── __init__.py            # register_all_nodes()
    ├── base.py                # BaseNode ABC, ExecutionContext, NodeRegistry
    ├── structured_output.py   # Pydantic 스키마, JSON 파싱
    ├── _helpers.py            # safe_format, parse_categories 유틸리티
    ├── model/                 # llm_call, classify, adaptive_classify, direct_answer, answer, review
    ├── logic/                 # conditional_router, iteration_gate, check_progress, state_setter, relevance_gate
    ├── resilience/            # context_guard, post_model
    ├── task/                  # create_todos, execute_todo, final_review, final_answer, final_synthesis
    └── memory/                # memory_inject, transcript_record
```
