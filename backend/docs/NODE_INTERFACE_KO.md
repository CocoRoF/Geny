# Node Interface 정의

## 1. 개요

모든 워크플로우 노드는 `BaseNode` 추상 클래스를 상속받아야 한다. `BaseNode`는 두 가지 관심사를 정의한다:

1. **메타데이터** — 프론트엔드 노드 팔레트에 표시될 정보 (이름, 설명, 카테고리, 파라미터, 출력 포트)
2. **실행 로직** — 런타임에 LangGraph 상태를 입력받아 상태 업데이트를 반환하는 로직

## 2. BaseNode 클래스 구조

```python
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

class BaseNode(ABC):
    """모든 워크플로우 노드의 추상 베이스 클래스"""

    # ── 클래스 레벨 메타데이터 (서브클래스에서 오버라이드) ──
    node_type: str = ""           # 고유 식별자: "llm_call", "classify_difficulty" 등
    label: str = ""               # 표시 이름: "LLM Call", "Classify Difficulty"
    description: str = ""         # 한 줄 설명
    category: str = "general"     # 카테고리: "model", "task", "logic", "memory", "resilience"
    icon: str = "⚡"              # 이모지 아이콘
    color: str = "#3b82f6"        # 16진수 색상

    parameters: List[NodeParameter] = []               # 설정 가능한 파라미터 목록
    output_ports: List[OutputPort] = [                  # 출력 포트 목록
        OutputPort(id="default", label="Next"),
    ]

    # ── 속성 ──
    @property
    def is_conditional(self) -> bool:
        """출력 포트가 2개 이상이면 조건부 노드"""
        return len(self.output_ports) > 1

    # ── 실행 (필수 구현) ──
    @abstractmethod
    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]: ...

    # ── 라우팅 (선택적 구현) ──
    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        return None

    # ── 직렬화 ──
    def to_dict(self) -> Dict[str, Any]: ...
```

## 3. 메타데이터 필드 상세

### 3.1 node_type (필수)

```python
node_type = "classify_difficulty"
```

- 고유 문자열 식별자
- `NodeRegistry`에 이 값으로 등록됨
- `WorkflowNodeInstance.node_type`이 이 값을 참조함
- **반드시 고유해야 하며**, 빈 문자열이면 등록 시 에러 발생

### 3.2 label

```python
label = "Classify Difficulty"
```

- 프론트엔드 노드 팔레트와 캔버스에서 표시되는 이름
- 사용자에게 보여지는 친화적인 이름

### 3.3 description

```python
description = "Classify the input task difficulty (easy/medium/hard)"
```

- 노드의 기능을 설명하는 한 줄 텍스트
- 프론트엔드 노드 팔레트에서 툴팁 등으로 사용

### 3.4 category

```python
category = "model"
```

- 프론트엔드 팔레트에서 노드를 그룹핑하는 키
- 현재 사용 중인 카테고리:

| 카테고리 | 설명 | 노드 예시 |
|---|---|---|
| `model` | LLM 호출 관련 노드 | llm_call, classify_difficulty, direct_answer, answer, review |
| `task` | 태스크 관리 노드 | create_todos, execute_todo, final_review, final_answer |
| `logic` | 흐름 제어 노드 | conditional_router, iteration_gate, check_progress, state_setter |
| `resilience` | 안정성 보장 노드 | context_guard, post_model |
| `memory` | 메모리 관리 노드 | memory_inject, transcript_record |

### 3.5 icon / color

```python
icon = "🔀"
color = "#3b82f6"
```

- `icon`: 프론트엔드에서 노드 카드에 표시되는 이모지
- `color`: 노드 카드의 배경/테두리 색상 (16진수)

## 4. NodeParameter — 파라미터 스키마

각 노드의 설정 가능한 파라미터를 정의한다. 프론트엔드 속성 편집기가 이 스키마를 기반으로 폼을 렌더링한다.

```python
@dataclass
class NodeParameter:
    name: str                # 파라미터 이름 (config 딕셔너리의 키)
    label: str               # 표시 레이블
    type: Literal[           # 입력 타입
        "string",            #   텍스트 필드
        "number",            #   숫자 입력
        "boolean",           #   체크박스/토글
        "select",            #   드롭다운 선택
        "textarea",          #   여러 줄 텍스트
        "json",              #   JSON 에디터
        "prompt_template",   #   프롬프트 템플릿 (변수 치환 지원)
    ]
    default: Any = None      # 기본값
    required: bool = False   # 필수 여부
    description: str = ""    # 파라미터 설명
    placeholder: str = ""    # 플레이스홀더 텍스트
    options: List[Dict[str, str]] = []   # select 타입 전용 옵션
    min: Optional[float] = None          # number 타입 최소값
    max: Optional[float] = None          # number 타입 최대값
    group: str = "general"               # 파라미터 그룹 (UI 탭 분류)
```

### 파라미터 타입별 동작

| 타입 | UI 위젯 | 값 형식 | 설명 |
|---|---|---|---|
| `string` | 텍스트 인풋 | `str` | 단일 줄 텍스트 |
| `number` | 숫자 인풋 | `int` / `float` | min/max 범위 지정 가능 |
| `boolean` | 토글 스위치 | `bool` | True/False |
| `select` | 드롭다운 | `str` | options에서 선택 |
| `textarea` | 멀티라인 텍스트 | `str` | 여러 줄 텍스트 입력 |
| `json` | JSON 에디터 | `dict` / `list` | 구조화된 데이터 |
| `prompt_template` | 프롬프트 에디터 | `str` | `{field_name}` 변수 치환 지원 |

### 파라미터 정의 예시

```python
parameters = [
    NodeParameter(
        name="prompt_template",
        label="Classification Prompt",
        type="prompt_template",
        default="{input}",
        required=True,
        description="모델에게 보낼 프롬프트. {input}은 사용자 입력으로 치환됩니다.",
        group="prompt",
    ),
    NodeParameter(
        name="max_retries",
        label="Max Retries",
        type="number",
        default=3,
        min=0,
        max=10,
        description="최대 재시도 횟수",
        group="advanced",
    ),
    NodeParameter(
        name="output_format",
        label="Output Format",
        type="select",
        default="text",
        options=[
            {"label": "Plain Text", "value": "text"},
            {"label": "JSON", "value": "json"},
            {"label": "Markdown", "value": "markdown"},
        ],
        group="output",
    ),
]
```

## 5. OutputPort — 출력 포트 정의

노드의 실행 후 가능한 분기 경로를 정의한다.

```python
@dataclass
class OutputPort:
    id: str            # 포트 식별자: "default", "easy", "medium", "hard" 등
    label: str         # 표시 레이블
    description: str   # 포트 설명
```

### 비조건부 노드 (단일 포트)

대부분의 노드는 하나의 기본 출력 포트만 가진다:

```python
output_ports = [
    OutputPort(id="default", label="Next"),
]
```

이 경우 `is_conditional == False`이며, 엣지가 단순 `add_edge()`로 연결된다.

### 조건부 노드 (복수 포트)

라우팅이 필요한 노드는 여러 출력 포트를 정의한다:

```python
# ClassifyDifficultyNode
output_ports = [
    OutputPort(id="easy",   label="Easy",   description="Simple, direct tasks"),
    OutputPort(id="medium", label="Medium", description="Moderate complexity"),
    OutputPort(id="hard",   label="Hard",   description="Complex, multi-step tasks"),
    OutputPort(id="end",    label="End",    description="Error / early termination"),
]

# IterationGateNode
output_ports = [
    OutputPort(id="continue", label="Continue", description="Keep iterating"),
    OutputPort(id="stop",     label="Stop",     description="Max iterations reached"),
]

# ReviewNode
output_ports = [
    OutputPort(id="approved", label="Approved", description="Quality check passed"),
    OutputPort(id="retry",    label="Retry",    description="Needs improvement"),
    OutputPort(id="end",      label="End",      description="Max retries reached"),
]
```

이 경우 `is_conditional == True`이며, `get_routing_function()`을 반드시 구현해야 한다.

## 6. ExecutionContext — 런타임 의존성

노드 실행 시 주입되는 공유 의존성 컨텍스트이다:

```python
@dataclass
class ExecutionContext:
    model: Any                     # ClaudeCLIChatModel — LLM 호출 인터페이스
    session_id: str                # 현재 세션 ID
    memory_manager: Any            # SessionMemoryManager — 메모리 읽기/쓰기
    session_logger: Any            # 세션 로거
    context_guard: Any             # ContextWindowGuard — 컨텍스트 윈도우 관리
    max_retries: int = 2           # 모델 호출 재시도 횟수
    model_name: Optional[str]      # 사용 중인 모델 이름
```

### resilient_invoke()

모델 호출 시 일시적 오류에 대한 자동 재시도를 제공한다:

```python
async def resilient_invoke(self, messages, node_name) -> tuple:
    """
    반환: (response, fallback_updates_dict)

    재시도 가능한 오류:
    - RATE_LIMITED: 5초 × attempt 대기
    - OVERLOADED: 3초 × attempt 대기
    - TIMEOUT: 2초 × attempt 대기
    - NETWORK_ERROR: 2초 × attempt 대기

    복구 불가능한 오류는 즉시 raise
    """
```

## 7. NodeRegistry — 전역 노드 등록소

모든 `BaseNode` 서브클래스를 관리하는 싱글턴 레지스트리이다:

```python
class NodeRegistry:
    def register(self, node_class: Type[BaseNode]) -> Type[BaseNode]:
        """노드 클래스 등록 (싱글턴 인스턴스 생성)"""
        instance = node_class()
        self._registry[instance.node_type] = instance

    def get(self, node_type: str) -> Optional[BaseNode]:
        """node_type 문자열로 노드 인스턴스 조회"""

    def to_catalog(self) -> List[Dict[str, Any]]:
        """프론트엔드 노드 팔레트용 직렬화 카탈로그"""
```

### 등록 방법

```python
# 방법 1: 데코레이터 (권장)
@register_node
class MyNode(BaseNode):
    node_type = "my_node"
    ...

# 방법 2: 명시적 호출
get_node_registry().register(MyNode)
```

### 자동 등록

`nodes/__init__.py`에서 모든 노드 모듈을 임포트하므로, 파일을 `nodes/` 디렉토리에 넣고 `@register_node` 데코레이터를 붙이면 자동 등록된다.

## 8. 프론트엔드 타입 미러

프론트엔드의 TypeScript 타입이 백엔드 스키마를 미러링한다:

```typescript
// frontend/src/types/workflow.ts

export interface WfNodeTypeDef {
    node_type: string;
    label: string;
    description: string;
    category: string;
    icon: string;
    color: string;
    is_conditional: boolean;
    parameters: WfNodeParameter[];
    output_ports: WfOutputPort[];
}

export interface WfNodeParameter {
    name: string;
    label: string;
    type: 'string' | 'number' | 'boolean' | 'select' | 'textarea' | 'json' | 'prompt_template';
    default: unknown;
    required: boolean;
    description: string;
    options?: Array<{ label: string; value: string }>;
    min?: number;
    max?: number;
    group: string;
}

export interface WfOutputPort {
    id: string;
    label: string;
    description: string;
}
```

이 타입 정보는 `GET /api/workflows/nodes` API를 통해 프론트엔드에 전달되며, 노드 팔레트와 속성 편집기를 동적으로 렌더링하는 데 사용된다.

## 9. 전체 등록 노드 목록

| node_type | 클래스 | 카테고리 | 조건부 | 출력 포트 |
|---|---|---|---|---|
| `llm_call` | LLMCallNode | model | No | [default] |
| `classify_difficulty` | ClassifyDifficultyNode | model | **Yes** | [easy, medium, hard, end] |
| `direct_answer` | DirectAnswerNode | model | No | [default] |
| `answer` | AnswerNode | model | No | [default] |
| `review` | ReviewNode | model | **Yes** | [approved, retry, end] |
| `create_todos` | CreateTodosNode | task | No | [default] |
| `execute_todo` | ExecuteTodoNode | task | No | [default] |
| `final_review` | FinalReviewNode | task | No | [default] |
| `final_answer` | FinalAnswerNode | task | No | [default] |
| `conditional_router` | ConditionalRouterNode | logic | **Yes** | [dynamic from route_map] |
| `iteration_gate` | IterationGateNode | logic | **Yes** | [continue, stop] |
| `check_progress` | CheckProgressNode | logic | **Yes** | [continue, complete] |
| `state_setter` | StateSetterNode | logic | No | [default] |
| `context_guard` | ContextGuardNode | resilience | No | [default] |
| `post_model` | PostModelNode | resilience | No | [default] |
| `memory_inject` | MemoryInjectNode | memory | No | [default] |
| `transcript_record` | TranscriptRecordNode | memory | No | [default] |

의사 노드 (등록되지 않음):
| 타입 | 용도 |
|---|---|
| `start` | 워크플로우 진입점 → LangGraph `START` sentinel |
| `end` | 워크플로우 종료점 → LangGraph `END` sentinel |
