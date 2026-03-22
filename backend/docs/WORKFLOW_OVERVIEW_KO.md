# 워크플로우 시스템 개요

## 1. 개요

워크플로우 시스템은 **사용자가 시각적으로 설계한 그래프(노드 + 엣지)를 실행 가능한 LangGraph StateGraph로 변환하여 실행**하는 구조이다.
하드코딩된 `AutonomousGraph`의 동작을 추상화하여, 사용자가 자유롭게 에이전트의 동작 흐름을 편집할 수 있도록 한다.

## 2. 시스템 구성요소

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React Flow 에디터)                         │
│  - 노드 팔레트에서 드래그&드롭으로 노드 배치             │
│  - 엣지 연결로 실행 흐름 정의                           │
│  - 노드 속성 패널에서 파라미터 설정                      │
└──────────────────────┬──────────────────────────────┘
                       │ REST API (/api/workflows/*)
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowController (workflow_controller.py)          │
│  - CRUD: 워크플로우 생성/조회/수정/삭제                  │
│  - 유효성 검증 (/validate)                             │
│  - 실행 (/execute)                                    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowStore (workflow_store.py)                     │
│  - JSON 파일 기반 영속화 (backend/workflows/*.json)     │
│  - CRUD 메서드: save, load, delete, list_all           │
│  - 템플릿 / 사용자 워크플로우 분리 관리                   │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowDefinition (workflow_model.py)                │
│  - Pydantic 모델: 노드 인스턴스 + 엣지 + 메타데이터      │
│  - 그래프 구조 검증 (validate_graph)                    │
│  - 시작/종료 노드 탐색 유틸리티                          │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowExecutor (workflow_executor.py)               │
│  - WorkflowDefinition → LangGraph StateGraph 컴파일    │
│  - 노드 함수 래핑, 엣지 와이어링, 조건부 라우팅           │
│  - 초기 상태 생성 후 graph.ainvoke() 실행               │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  BaseNode 구현체들 (nodes/*.py)                        │
│  - 각 노드 타입의 실제 로직 수행                        │
│  - NodeRegistry에 등록, ExecutionContext로 의존성 주입   │
└─────────────────────────────────────────────────────┘
```

## 3. 데이터 흐름

### 3.1 워크플로우 저장 흐름

```
사용자 편집 → Frontend JSON → POST /api/workflows → WorkflowStore.save() → backend/workflows/{id}.json
```

### 3.2 워크플로우 실행 흐름

```
POST /api/workflows/{id}/execute (input_text, session_id)
  ↓
WorkflowStore.load(id) → WorkflowDefinition
  ↓
WorkflowDefinition.validate_graph() → 에러 시 400 반환
  ↓
AgentSession에서 model, memory, guard 획득
  ↓
ExecutionContext 생성 (model, session_id, memory_manager, ...)
  ↓
WorkflowExecutor(workflow, context)
  ↓
executor.compile() → LangGraph StateGraph
  ↓
executor.run(input_text) → graph.ainvoke(initial_state) → final_state
  ↓
결과 반환 (final_answer, iterations, difficulty 등)
```

## 4. 핵심 데이터 모델

### 4.1 WorkflowNodeInstance

캔버스 위에 배치된 개별 노드 인스턴스를 나타낸다.

```python
class WorkflowNodeInstance(BaseModel):
    id: str                        # 고유 식별자 (UUID 앞 8자)
    node_type: str                 # 등록된 BaseNode.node_type 참조
    label: str                     # 사용자 지정 표시 이름
    config: Dict[str, Any]         # 노드 파라미터 설정값
    position: Dict[str, float]     # 캔버스 위치 {"x": 0, "y": 0}
```

### 4.2 WorkflowEdge

두 노드 인스턴스 간의 방향 연결을 나타낸다.

```python
class WorkflowEdge(BaseModel):
    id: str              # 고유 식별자
    source: str          # 출발 노드 인스턴스 ID
    target: str          # 도착 노드 인스턴스 ID
    source_port: str     # 출력 포트 ID (기본값: "default")
    label: str           # 엣지 레이블
```

### 4.3 WorkflowDefinition

전체 워크플로우 그래프 정의이다.

```python
class WorkflowDefinition(BaseModel):
    id: str
    name: str
    description: str
    nodes: List[WorkflowNodeInstance]
    edges: List[WorkflowEdge]
    created_at: str              # ISO 타임스탬프
    updated_at: str
    is_template: bool            # True면 템플릿 (직접 수정 불가, Clone만 가능)
    template_name: Optional[str]
```

주요 메서드:
- `get_node(node_id)` — ID로 노드 인스턴스 검색
- `get_edges_from(node_id)` — 노드에서 나가는 엣지 조회
- `get_edges_to(node_id)` — 노드로 들어오는 엣지 조회
- `get_start_node()` — `node_type == "start"`인 노드 검색
- `get_end_nodes()` — `node_type == "end"`인 노드들 검색
- `validate_graph()` — 구조적 유효성 검증

## 5. 유효성 검증 규칙

`validate_graph()` 메서드가 수행하는 검증:

| 규칙 | 설명 |
|---|---|
| Start 노드 필수 | 정확히 1개의 `start` 노드가 있어야 함 |
| End 노드 필수 | 최소 1개의 `end` 노드가 있어야 함 |
| Start 연결 필수 | Start 노드에서 최소 1개의 나가는 엣지 필요 |
| 엣지 참조 검증 | 모든 엣지의 source/target이 실존하는 노드 ID여야 함 |
| 고립 노드 검출 | start/end 외의 노드는 최소 1개의 엣지와 연결돼야 함 |

## 6. 템플릿 시스템

### 내장 템플릿

`templates.py`에서 두 가지 내장 템플릿을 제공한다:

| 템플릿 | ID | 설명 |
|---|---|---|
| Simple | `template-simple` | memory_inject → guard → llm_call → post_model → end (5노드, 4엣지) |
| Autonomous | `template-autonomous` | 난이도 분류 기반 28노드 풀 그래프 (easy/medium/hard 경로) |

### 템플릿 설치

`install_templates(store)` — 서버 시작 시 호출되어, 해당 ID의 파일이 없으면 기본 템플릿을 JSON으로 저장한다.

### 템플릿 활용

- 템플릿은 `is_template=True`로 표시되어 직접 수정이 불가능하다
- 사용자는 `Clone` 기능으로 템플릿을 복사한 뒤 자유롭게 편집할 수 있다

## 7. Built-in 그래프와의 관계

| 항목 | AutonomousGraph (하드코딩) | WorkflowExecutor (워크플로우) |
|---|---|---|
| 구현 방식 | 인라인 메서드로 직접 구현 | BaseNode 서브클래스를 레지스트리에서 조회 |
| 노드 수 | 28개 고정 | 사용자 정의 (가변) |
| 토폴로지 | 코드 내 고정 | JSON 파일로 정의 |
| 상태 | AutonomousState 공유 | AutonomousState 공유 |
| 실행 | graph.ainvoke(state) | graph.ainvoke(state) |

두 시스템은 **동일한 `AutonomousState`**를 공유하므로 동일한 실행 의미론(semantics)을 가진다. 워크플로우 시스템은 하드코딩된 AutonomousGraph를 **시각적으로 편집 가능한 형태로 추상화**한 것이다.

## 8. 파일 구조

```
backend/service/workflow/
├── __init__.py
├── workflow_model.py         # 데이터 모델 (WorkflowDefinition, NodeInstance, Edge)
├── workflow_store.py         # JSON 파일 기반 영속화
├── workflow_executor.py      # WorkflowDefinition → LangGraph 컴파일러
├── templates.py              # 내장 템플릿 팩토리
├── WORKFLOW_OVERVIEW.md       # ← 이 문서
├── LANGGRAPH_PORTING.md      # LangGraph 포팅 원리
└── nodes/
    ├── __init__.py           # 모든 노드 모듈 자동 임포트
    ├── base.py               # BaseNode, NodeParameter, OutputPort, ExecutionContext, NodeRegistry
    ├── model_nodes.py        # LLM 호출 노드 (llm_call, classify_difficulty, direct_answer, answer, review)
    ├── task_nodes.py         # 태스크 노드 (create_todos, execute_todo, final_review, final_answer)
    ├── logic_nodes.py        # 로직 노드 (conditional_router, iteration_gate, check_progress, state_setter)
    ├── guard_nodes.py        # 레질리언스 노드 (context_guard, post_model)
    ├── memory_nodes.py       # 메모리 노드 (memory_inject, transcript_record)
    ├── NODE_INTERFACE.md     # Node Interface 정의 문서
    ├── NODE_EXECUTION.md     # Node 실행 원리 문서
    └── NEW_NODE_GUIDE.md     # 새로운 Node 설계 가이드
```
