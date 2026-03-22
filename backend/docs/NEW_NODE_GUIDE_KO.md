# 새로운 Node 설계 가이드

## 1. 개요

이 가이드는 워크플로우 시스템에 **새로운 노드를 추가하는 방법**을 단계별로 설명한다. 간단한 비조건부 노드부터 복잡한 조건부 라우팅 노드까지 모든 유형을 다룬다.

## 2. 핵심 원칙

1. **단일 책임**: 하나의 노드는 하나의 명확한 작업만 수행한다
2. **상태 기반**: 노드는 `state`를 읽고, 변경할 필드만 반환한다 (부수 효과 최소화)
3. **설정 가능**: 하드코딩 대신 `config` 파라미터를 통해 동작을 유연하게 변경할 수 있도록 한다
4. **에러 안전**: 모든 외부 호출(LLM, 메모리 등)은 try-catch로 감싸고, 실패 시 `error` + `is_complete` 반환
5. **등록 필수**: `@register_node` 데코레이터로 `NodeRegistry`에 등록해야 시스템에서 인식된다

## 3. 빠른 시작: 5분 만에 노드 만들기

### 3.1 파일 생성

`backend/service/workflow/nodes/` 디렉토리에 새 Python 파일을 생성한다:

```
backend/service/workflow/nodes/my_nodes.py
```

### 3.2 기본 구조 작성

```python
"""
My Custom Nodes — 사용자 정의 노드 모듈.

이 모듈의 목적과 포함된 노드들에 대한 설명.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict

from langchain_core.messages import HumanMessage

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)

logger = getLogger(__name__)


@register_node
class SummaryNode(BaseNode):
    """입력 텍스트를 요약하는 노드."""

    # ── 메타데이터 ──
    node_type = "summary"
    label = "Summarize"
    description = "입력 텍스트를 지정된 길이로 요약합니다"
    category = "model"
    icon = "📝"
    color = "#10b981"

    # ── 파라미터 ──
    parameters = [
        NodeParameter(
            name="prompt_template",
            label="요약 프롬프트",
            type="prompt_template",
            default="다음 내용을 간결하게 요약해주세요:\n\n{input}",
            required=True,
            description="요약 요청 프롬프트. {input}은 사용자 입력으로 치환됩니다.",
            group="prompt",
        ),
        NodeParameter(
            name="max_length",
            label="최대 길이",
            type="number",
            default=500,
            min=50,
            max=5000,
            description="요약문의 최대 글자 수",
            group="output",
        ),
    ]

    # ── 출력 포트 (비조건부: 기본 1개) ──
    output_ports = [
        OutputPort(id="default", label="Next"),
    ]

    # ── 실행 ──
    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        # 1. 설정값 읽기
        template = config.get("prompt_template", "요약해주세요: {input}")
        max_length = config.get("max_length", 500)

        # 2. 프롬프트 구성
        input_text = state.get("input", "")
        try:
            prompt = template.format(input=input_text)
        except KeyError:
            prompt = template

        # 3. 모델 호출
        messages = [HumanMessage(content=prompt)]
        try:
            response, fallback = await context.resilient_invoke(
                messages, "summary"
            )
        except Exception as e:
            logger.exception(f"[{context.session_id}] summary error: {e}")
            return {"error": str(e), "is_complete": True}

        # 4. 결과 처리
        summary = response.content[:max_length]

        # 5. 상태 업데이트 반환
        result: Dict[str, Any] = {
            "last_output": summary,
            "messages": [response],
            "current_step": "summary_complete",
        }
        result.update(fallback)
        return result
```

### 3.3 __init__.py에 등록

`backend/service/workflow/nodes/__init__.py`에 새 모듈의 import를 추가한다:

```python
# nodes/__init__.py
from service.workflow.nodes import model_nodes    # 기존
from service.workflow.nodes import task_nodes     # 기존
from service.workflow.nodes import logic_nodes    # 기존
from service.workflow.nodes import guard_nodes    # 기존
from service.workflow.nodes import memory_nodes   # 기존
from service.workflow.nodes import my_nodes       # ← 추가!
```

### 3.4 확인

서버 재시작 후 `GET /api/workflows/nodes` API를 호출하면 프론트엔드 노드 팔레트에 새 노드가 나타난다.

## 4. 조건부 노드 만들기

여러 출력 경로를 가진 조건부(라우팅) 노드를 만드는 방법이다.

### 4.1 예시: 감성 분석 라우터

```python
@register_node
class SentimentRouterNode(BaseNode):
    """텍스트 감성을 분석하여 긍정/부정/중립으로 라우팅하는 노드."""

    node_type = "sentiment_router"
    label = "Sentiment Router"
    description = "텍스트 감성을 분석하여 경로를 분기합니다"
    category = "logic"
    icon = "🔀"
    color = "#6366f1"

    parameters = [
        NodeParameter(
            name="input_field",
            label="분석 대상 필드",
            type="string",
            default="last_output",
            description="감성 분석할 상태 필드 이름",
            group="routing",
        ),
    ]

    # ── 복수 출력 포트 정의 ──
    output_ports = [
        OutputPort(id="positive", label="Positive", description="긍정적 감성"),
        OutputPort(id="negative", label="Negative", description="부정적 감성"),
        OutputPort(id="neutral",  label="Neutral",  description="중립적 감성"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_field = config.get("input_field", "last_output")
        text = state.get(input_field, "")

        prompt = f"다음 텍스트의 감성을 분석하세요. 반드시 'positive', 'negative', 'neutral' 중 하나만 답하세요.\n\n{text}"
        messages = [HumanMessage(content=prompt)]

        try:
            response, fallback = await context.resilient_invoke(
                messages, "sentiment_router"
            )
            sentiment = response.content.strip().lower()

            if "positive" in sentiment:
                result_sentiment = "positive"
            elif "negative" in sentiment:
                result_sentiment = "negative"
            else:
                result_sentiment = "neutral"

            result: Dict[str, Any] = {
                "metadata": {**state.get("metadata", {}), "sentiment": result_sentiment},
                "last_output": response.content,
                "current_step": "sentiment_analyzed",
            }
            result.update(fallback)
            return result

        except Exception as e:
            return {
                "metadata": {**state.get("metadata", {}), "sentiment": "neutral"},
                "error": str(e),
                "current_step": "sentiment_error",
            }

    # ── 라우팅 함수 (필수!) ──
    def get_routing_function(self, config):
        """상태의 metadata.sentiment 값에 따라 라우팅"""
        def _route(state: Dict[str, Any]) -> str:
            metadata = state.get("metadata", {})
            sentiment = metadata.get("sentiment", "neutral")
            if sentiment in ("positive", "negative", "neutral"):
                return sentiment
            return "neutral"
        return _route
```

### 4.2 조건부 노드의 핵심 규칙

1. **`output_ports`가 2개 이상** → `is_conditional == True`
2. **`get_routing_function(config)`를 반드시 구현** → 상태를 보고 포트 ID를 반환하는 함수
3. **반환하는 포트 ID가 `output_ports`의 `id`와 일치**해야 함
4. **`execute()`에서 라우팅에 필요한 상태 필드를 반드시 설정**해야 함

## 5. 순수 로직 노드(LLM 호출 없음)

모델을 호출하지 않고 상태만 검사/변경하는 노드:

```python
@register_node
class ThresholdGateNode(BaseNode):
    """iteration 횟수가 임계값에 도달했는지 검사하는 게이트 노드."""

    node_type = "threshold_gate"
    label = "Threshold Gate"
    description = "반복 횟수가 임계값에 도달하면 중단합니다"
    category = "logic"
    icon = "🚧"
    color = "#f59e0b"

    parameters = [
        NodeParameter(
            name="threshold",
            label="Threshold",
            type="number",
            default=10,
            min=1,
            max=100,
            description="이 횟수에 도달하면 stop 포트로 라우팅",
            group="routing",
        ),
    ]

    output_ports = [
        OutputPort(id="continue", label="Continue", description="임계값 미달"),
        OutputPort(id="stop",     label="Stop",     description="임계값 도달"),
    ]

    async def execute(self, state, context, config):
        # LLM 호출 없이 상태만 검사
        return {"current_step": "threshold_checked"}

    def get_routing_function(self, config):
        threshold = config.get("threshold", 10)

        def _route(state):
            iteration = state.get("iteration", 0)
            if iteration >= threshold:
                return "stop"
            return "continue"
        return _route
```

## 6. 상태 커스텀 확장

### 6.1 기존 상태 필드 활용

가능하면 `AutonomousState`에 이미 정의된 필드를 활용한다:

| 필드 | 용도 | 사용 예시 |
|---|---|---|
| `last_output` | 최근 모델 응답 | 범용적으로 사용 |
| `metadata` | 커스텀 데이터 저장 | `metadata["sentiment"]` |
| `answer` | 중간 답변 | Medium 경로용 |
| `final_answer` | 최종 답변 | 결과 전달용 |
| `messages` | 메시지 히스토리 | 대화 맥락 유지 |

### 6.2 metadata 딕셔너리 활용

새로운 상태 필드가 필요하지만 `AutonomousState`를 변경하고 싶지 않을 때:

```python
# 쓰기
return {
    "metadata": {
        **state.get("metadata", {}),
        "my_custom_field": "value",
        "analysis_result": {"score": 0.95},
    }
}

# 읽기 (다음 노드에서)
async def execute(self, state, context, config):
    metadata = state.get("metadata", {})
    custom_value = metadata.get("my_custom_field")
```

### 6.3 AutonomousState 확장 (고급)

정말 필요한 경우 `state.py`에 새 필드를 추가할 수 있다:

```python
# state.py에 추가
class AutonomousState(TypedDict, total=False):
    # ... 기존 필드 ...
    my_new_field: Optional[str]  # 새 필드 추가
```

> **주의**: 상태 확장은 전체 시스템에 영향을 미치므로 신중하게 결정해야 한다. 가능하면 `metadata` 딕셔너리를 먼저 사용하는 것을 권장한다.

## 7. 노드 파라미터 설계 지침

### 7.1 좋은 파라미터 설계

```python
parameters = [
    # ✅ 목적이 명확한 파라미터
    NodeParameter(
        name="prompt_template",
        label="프롬프트 템플릿",
        type="prompt_template",
        default="기본 프롬프트: {input}",
        required=True,
        description="모델에게 보낼 프롬프트. {input}으로 사용자 입력을 참조합니다.",
        group="prompt",
    ),

    # ✅ 범위가 제한된 숫자 파라미터
    NodeParameter(
        name="max_tokens",
        label="최대 토큰",
        type="number",
        default=1000,
        min=100,
        max=10000,
        description="응답의 최대 토큰 수",
        group="advanced",
    ),

    # ✅ 선택지가 명확한 select 파라미터
    NodeParameter(
        name="language",
        label="출력 언어",
        type="select",
        default="ko",
        options=[
            {"label": "한국어", "value": "ko"},
            {"label": "English", "value": "en"},
            {"label": "日本語", "value": "ja"},
        ],
        group="output",
    ),
]
```

### 7.2 피해야 할 패턴

```python
parameters = [
    # ❌ 너무 범용적인 파라미터
    NodeParameter(name="data", label="Data", type="json", default="{}"),

    # ❌ 설명이 없는 파라미터
    NodeParameter(name="x", label="X", type="number"),

    # ❌ 범위가 없는 숫자 파라미터
    NodeParameter(name="count", label="Count", type="number", default=0),
]
```

### 7.3 파라미터 그룹

관련된 파라미터를 `group`으로 묶어 UI에서 탭/섹션으로 표시한다:

| 그룹 | 용도 |
|---|---|
| `prompt` | 프롬프트 관련 설정 |
| `routing` | 라우팅/분기 관련 설정 |
| `output` | 출력 형식/대상 관련 |
| `advanced` | 고급 설정 |
| `general` | (기본) 일반 설정 |

## 8. 테스트

### 8.1 단위 테스트 작성

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from service.workflow.nodes.my_nodes import SummaryNode
from service.workflow.nodes.base import ExecutionContext


@pytest.fixture
def mock_context():
    ctx = ExecutionContext(
        model=AsyncMock(),
        session_id="test-session",
    )
    # resilient_invoke 모킹
    mock_response = MagicMock()
    mock_response.content = "이것은 요약입니다."
    ctx.resilient_invoke = AsyncMock(return_value=(mock_response, {}))
    return ctx


@pytest.mark.asyncio
async def test_summary_node(mock_context):
    node = SummaryNode()

    state = {
        "input": "매우 긴 텍스트...",
        "messages": [],
        "iteration": 0,
    }
    config = {
        "prompt_template": "요약해주세요: {input}",
        "max_length": 100,
    }

    result = await node.execute(state, mock_context, config)

    assert "last_output" in result
    assert result["current_step"] == "summary_complete"
    assert len(result["last_output"]) <= 100


@pytest.mark.asyncio
async def test_summary_node_error(mock_context):
    mock_context.resilient_invoke = AsyncMock(side_effect=Exception("API Error"))

    node = SummaryNode()
    state = {"input": "test"}
    config = {}

    result = await node.execute(state, mock_context, config)

    assert result.get("error") == "API Error"
    assert result.get("is_complete") is True
```

### 8.2 통합 테스트 (워크플로우 편집기에서)

1. 프론트엔드 워크플로우 편집기에서 새 노드를 배치
2. 파라미터 설정
3. 엣지 연결
4. Validate 실행 → 에러 없는지 확인
5. Execute 실행 → 기대한 결과가 나오는지 확인

## 9. 체크리스트

새 노드를 만들기 전에 확인할 사항:

- [ ] `node_type`이 기존 노드와 중복되지 않는가?
- [ ] `@register_node` 데코레이터를 붙였는가?
- [ ] `nodes/__init__.py`에 모듈 import를 추가했는가?
- [ ] `execute()` 메서드를 구현했는가?
- [ ] 조건부 노드인 경우 `get_routing_function()`을 구현했는가?
- [ ] 조건부 노드인 경우 `output_ports`를 2개 이상 정의했는가?
- [ ] 모든 LLM 호출에 try-catch를 적용했는가?
- [ ] 에러 시 `{"error": str(e), "is_complete": True}`를 반환하는가?
- [ ] `current_step` 필드를 업데이트하여 실행 추적이 가능한가?
- [ ] 파라미터에 적절한 description과 group이 설정되었는가?

## 10. 전체 예시: 웹 검색 노드

종합적인 예시로 웹 검색 결과를 LLM에 전달하는 노드를 만들어 본다:

```python
"""
Web Search Node — 웹 검색 결과를 모델에 전달하는 노드.
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage

from service.workflow.nodes.base import (
    BaseNode,
    ExecutionContext,
    NodeParameter,
    OutputPort,
    register_node,
)

logger = getLogger(__name__)


@register_node
class WebSearchNode(BaseNode):
    """웹 검색을 수행하고 결과를 모델에 전달하는 노드.

    외부 검색 API를 호출한 뒤, 결과를 컨텍스트로 주입하여
    모델이 최신 정보를 기반으로 응답할 수 있도록 한다.
    """

    node_type = "web_search"
    label = "Web Search"
    description = "웹 검색 결과를 기반으로 모델이 답변을 생성합니다"
    category = "model"
    icon = "🔍"
    color = "#0ea5e9"

    parameters = [
        NodeParameter(
            name="search_query_template",
            label="검색 쿼리 템플릿",
            type="prompt_template",
            default="{input}",
            required=True,
            description="검색 엔진에 보낼 쿼리. {input}으로 사용자 입력 참조.",
            group="search",
        ),
        NodeParameter(
            name="max_results",
            label="최대 검색 결과 수",
            type="number",
            default=5,
            min=1,
            max=20,
            description="가져올 검색 결과의 최대 개수",
            group="search",
        ),
        NodeParameter(
            name="answer_template",
            label="답변 프롬프트",
            type="prompt_template",
            default="다음 검색 결과를 참고하여 질문에 답하세요.\n\n검색결과:\n{search_results}\n\n질문: {input}",
            required=True,
            description="검색 결과를 포함한 답변 생성 프롬프트",
            group="prompt",
        ),
        NodeParameter(
            name="has_results_routing",
            label="검색 결과 유무 라우팅",
            type="boolean",
            default=False,
            description="True로 설정하면 검색 결과 유무에 따라 다른 경로로 분기합니다",
            group="routing",
        ),
    ]

    output_ports = [
        OutputPort(id="default",    label="Next",       description="기본 출력"),
        OutputPort(id="no_results", label="No Results", description="검색 결과 없음"),
    ]

    @property
    def is_conditional(self) -> bool:
        # config에 따라 조건부 여부가 달라지지만,
        # 출력 포트가 2개이므로 항상 True
        return True

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        query_template = config.get("search_query_template", "{input}")
        max_results = config.get("max_results", 5)
        answer_template = config.get("answer_template", "{input}")
        input_text = state.get("input", "")

        # 1. 검색 쿼리 구성
        try:
            query = query_template.format(input=input_text)
        except KeyError:
            query = input_text

        # 2. 웹 검색 수행 (실제 구현은 외부 서비스 연동 필요)
        try:
            search_results = await self._do_search(query, max_results)
        except Exception as e:
            logger.warning(f"[{context.session_id}] web_search failed: {e}")
            search_results = []

        if not search_results:
            return {
                "metadata": {**state.get("metadata", {}), "search_found": False},
                "last_output": "검색 결과가 없습니다.",
                "current_step": "web_search_no_results",
            }

        # 3. 검색 결과를 텍스트로 포맷팅
        results_text = "\n\n".join(
            f"[{i+1}] {r['title']}\n{r['snippet']}"
            for i, r in enumerate(search_results)
        )

        # 4. 답변 생성 프롬프트 구성
        try:
            prompt = answer_template.format(
                input=input_text,
                search_results=results_text,
            )
        except KeyError:
            prompt = f"{results_text}\n\n{input_text}"

        # 5. 모델 호출
        messages = [HumanMessage(content=prompt)]
        try:
            response, fallback = await context.resilient_invoke(
                messages, "web_search"
            )
        except Exception as e:
            return {"error": str(e), "is_complete": True}

        # 6. 결과 반환
        result: Dict[str, Any] = {
            "last_output": response.content,
            "messages": [response],
            "metadata": {
                **state.get("metadata", {}),
                "search_found": True,
                "search_result_count": len(search_results),
            },
            "current_step": "web_search_complete",
        }
        result.update(fallback)
        return result

    def get_routing_function(self, config):
        has_routing = config.get("has_results_routing", False)

        def _route(state: Dict[str, Any]) -> str:
            if not has_routing:
                return "default"
            metadata = state.get("metadata", {})
            if not metadata.get("search_found", True):
                return "no_results"
            return "default"
        return _route

    async def _do_search(self, query: str, max_results: int) -> List[Dict]:
        """웹 검색 수행 (플레이스홀더 — 실제 구현 시 API 연동 필요)"""
        # TODO: 실제 검색 API 연동
        # 예: Google Custom Search, Bing Search, Tavily 등
        return []
```

## 11. 카테고리별 노드 설계 팁

### model 카테고리
- 반드시 `context.resilient_invoke()` 사용 (수동 model 호출 금지)
- `prompt_template` 파라미터를 제공하여 사용자가 프롬프트를 커스터마이징할 수 있도록
- 응답을 파싱할 때 다양한 형식에 대비 (JSON, 텍스트, 마크다운 등)

### logic 카테고리
- LLM 호출 없이 순수 상태 검사/변환만 수행
- `execute()`는 간결하게, 핵심 로직은 `get_routing_function()`에
- 무한 루프 방지를 위해 iteration/budget 체크 고려

### memory 카테고리
- `context.memory_manager`가 None일 수 있으므로 항상 체크
- `memory_refs` 리스트로 주입 기록 남기기
- 중복 주입 방지 로직 고려

### resilience 카테고리
- 다른 노드의 실행 전/후에 배치되는 가드 노드
- `context.context_guard`가 None일 수 있으므로 체크
- BLOCK 상태 시 `is_complete = True` 설정

### task 카테고리
- `todos` 리스트와 `current_todo_index` 활용
- `_merge_todos` 리듀서를 활용한 점진적 업데이트
- 개별 TODO 항목의 상태 추적 (`pending` → `in_progress` → `completed`/`failed`)
