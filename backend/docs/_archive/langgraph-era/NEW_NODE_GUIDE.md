# New Node Design Guide

## 1. Overview

This guide explains **how to add new nodes to the workflow system** step by step. It covers all types from simple unconditional nodes to complex conditional routing nodes.

## 2. Core Principles

1. **Single responsibility**: One node performs one clear task
2. **State-based**: Nodes read `state` and return only the fields to change (minimize side effects)
3. **Configurable**: Use `config` parameters for flexible behavior instead of hardcoding
4. **Error-safe**: Wrap all external calls (LLM, memory, etc.) in try-catch; return `error` + `is_complete` on failure
5. **Registration required**: Must be registered in `NodeRegistry` via `@register_node` decorator for system recognition

## 3. Quick Start: Create a Node in 5 Minutes

### 3.1 Create File

Create a new Python file in the `backend/service/workflow/nodes/` directory:

```
backend/service/workflow/nodes/my_nodes.py
```

### 3.2 Write Basic Structure

```python
"""
My Custom Nodes — Custom node module.

Description of this module's purpose and included nodes.
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
    """Node that summarizes input text."""

    # ── Metadata ──
    node_type = "summary"
    label = "Summarize"
    description = "Summarizes input text to a specified length"
    category = "model"
    icon = "📝"
    color = "#10b981"

    # ── Parameters ──
    parameters = [
        NodeParameter(
            name="prompt_template",
            label="Summary Prompt",
            type="prompt_template",
            default="Please summarize the following content concisely:\n\n{input}",
            required=True,
            description="Summary request prompt. {input} is replaced with user input.",
            group="prompt",
        ),
        NodeParameter(
            name="max_length",
            label="Max Length",
            type="number",
            default=500,
            min=50,
            max=5000,
            description="Maximum character count for the summary",
            group="output",
        ),
    ]

    # ── Output ports (unconditional: 1 default) ──
    output_ports = [
        OutputPort(id="default", label="Next"),
    ]

    # ── Execution ──
    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        # 1. Read config values
        template = config.get("prompt_template", "Please summarize: {input}")
        max_length = config.get("max_length", 500)

        # 2. Build prompt
        input_text = state.get("input", "")
        try:
            prompt = template.format(input=input_text)
        except KeyError:
            prompt = template

        # 3. Model invocation
        messages = [HumanMessage(content=prompt)]
        try:
            response, fallback = await context.resilient_invoke(
                messages, "summary"
            )
        except Exception as e:
            logger.exception(f"[{context.session_id}] summary error: {e}")
            return {"error": str(e), "is_complete": True}

        # 4. Process result
        summary = response.content[:max_length]

        # 5. Return state update
        result: Dict[str, Any] = {
            "last_output": summary,
            "messages": [response],
            "current_step": "summary_complete",
        }
        result.update(fallback)
        return result
```

### 3.3 Register in __init__.py

Add the new module import to `backend/service/workflow/nodes/__init__.py`:

```python
# nodes/__init__.py
from service.workflow.nodes import model_nodes    # existing
from service.workflow.nodes import task_nodes     # existing
from service.workflow.nodes import logic_nodes    # existing
from service.workflow.nodes import guard_nodes    # existing
from service.workflow.nodes import memory_nodes   # existing
from service.workflow.nodes import my_nodes       # ← add this!
```

### 3.4 Verify

After server restart, call the `GET /api/workflows/nodes` API and the new node will appear in the frontend node palette.

## 4. Creating Conditional Nodes

How to create conditional (routing) nodes with multiple output paths.

### 4.1 Example: Sentiment Analysis Router

```python
@register_node
class SentimentRouterNode(BaseNode):
    """Node that analyzes text sentiment and routes to positive/negative/neutral."""

    node_type = "sentiment_router"
    label = "Sentiment Router"
    description = "Analyzes text sentiment and branches the execution path"
    category = "logic"
    icon = "🔀"
    color = "#6366f1"

    parameters = [
        NodeParameter(
            name="input_field",
            label="Analysis Target Field",
            type="string",
            default="last_output",
            description="State field name to perform sentiment analysis on",
            group="routing",
        ),
    ]

    # ── Multiple output port definition ──
    output_ports = [
        OutputPort(id="positive", label="Positive", description="Positive sentiment"),
        OutputPort(id="negative", label="Negative", description="Negative sentiment"),
        OutputPort(id="neutral",  label="Neutral",  description="Neutral sentiment"),
    ]

    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_field = config.get("input_field", "last_output")
        text = state.get(input_field, "")

        prompt = f"Analyze the sentiment of the following text. Reply with ONLY one of: 'positive', 'negative', 'neutral'.\n\n{text}"
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

    # ── Routing function (required!) ──
    def get_routing_function(self, config):
        """Route based on state's metadata.sentiment value"""
        def _route(state: Dict[str, Any]) -> str:
            metadata = state.get("metadata", {})
            sentiment = metadata.get("sentiment", "neutral")
            if sentiment in ("positive", "negative", "neutral"):
                return sentiment
            return "neutral"
        return _route
```

### 4.2 Key Rules for Conditional Nodes

1. **2+ `output_ports`** → `is_conditional == True`
2. **Must implement `get_routing_function(config)`** → a function that inspects state and returns a port ID
3. **Returned port ID must match an `output_ports` `id`**
4. **`execute()` must set the state fields needed for routing**

## 5. Pure Logic Nodes (No LLM Call)

Nodes that only inspect/modify state without calling the model:

```python
@register_node
class ThresholdGateNode(BaseNode):
    """Gate node that checks whether iteration count has reached a threshold."""

    node_type = "threshold_gate"
    label = "Threshold Gate"
    description = "Stops execution when iteration count reaches the threshold"
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
            description="Route to stop port when this count is reached",
            group="routing",
        ),
    ]

    output_ports = [
        OutputPort(id="continue", label="Continue", description="Below threshold"),
        OutputPort(id="stop",     label="Stop",     description="Threshold reached"),
    ]

    async def execute(self, state, context, config):
        # Inspect state only, no LLM call
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

## 6. Custom State Extension

### 6.1 Using Existing State Fields

Prefer leveraging fields already defined in `AutonomousState`:

| Field | Purpose | Usage Example |
|-------|---------|---------------|
| `last_output` | Latest model response | General purpose |
| `metadata` | Custom data storage | `metadata["sentiment"]` |
| `answer` | Intermediate answer | For Medium path |
| `final_answer` | Final answer | For result delivery |
| `messages` | Message history | Maintaining conversation context |

### 6.2 Using the metadata Dictionary

When new state fields are needed but you don't want to modify `AutonomousState`:

```python
# Write
return {
    "metadata": {
        **state.get("metadata", {}),
        "my_custom_field": "value",
        "analysis_result": {"score": 0.95},
    }
}

# Read (in the next node)
async def execute(self, state, context, config):
    metadata = state.get("metadata", {})
    custom_value = metadata.get("my_custom_field")
```

### 6.3 Extending AutonomousState (Advanced)

When truly necessary, add new fields to `state.py`:

```python
# Add to state.py
class AutonomousState(TypedDict, total=False):
    # ... existing fields ...
    my_new_field: Optional[str]  # New field
```

> **Caution**: State extension affects the entire system, so decide carefully. Prefer using the `metadata` dictionary first whenever possible.

## 7. Node Parameter Design Guidelines

### 7.1 Good Parameter Design

```python
parameters = [
    # ✅ Parameter with clear purpose
    NodeParameter(
        name="prompt_template",
        label="Prompt Template",
        type="prompt_template",
        default="Default prompt: {input}",
        required=True,
        description="Prompt to send to the model. Use {input} to reference user input.",
        group="prompt",
    ),

    # ✅ Number parameter with range limits
    NodeParameter(
        name="max_tokens",
        label="Max Tokens",
        type="number",
        default=1000,
        min=100,
        max=10000,
        description="Maximum token count for the response",
        group="advanced",
    ),

    # ✅ Select parameter with clear options
    NodeParameter(
        name="language",
        label="Output Language",
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

### 7.2 Patterns to Avoid

```python
parameters = [
    # ❌ Overly generic parameter
    NodeParameter(name="data", label="Data", type="json", default="{}"),

    # ❌ Parameter without description
    NodeParameter(name="x", label="X", type="number"),

    # ❌ Number parameter without range
    NodeParameter(name="count", label="Count", type="number", default=0),
]
```

### 7.3 Parameter Groups

Group related parameters with `group` to display as tabs/sections in the UI:

| Group | Purpose |
|-------|---------|
| `prompt` | Prompt-related settings |
| `routing` | Routing/branching settings |
| `output` | Output format/target settings |
| `advanced` | Advanced settings |
| `general` | (Default) General settings |

## 8. Testing

### 8.1 Writing Unit Tests

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
    # Mock resilient_invoke
    mock_response = MagicMock()
    mock_response.content = "This is a summary."
    ctx.resilient_invoke = AsyncMock(return_value=(mock_response, {}))
    return ctx


@pytest.mark.asyncio
async def test_summary_node(mock_context):
    node = SummaryNode()

    state = {
        "input": "Very long text...",
        "messages": [],
        "iteration": 0,
    }
    config = {
        "prompt_template": "Please summarize: {input}",
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

### 8.2 Integration Testing (In the Workflow Editor)

1. Place the new node in the frontend workflow editor
2. Configure parameters
3. Connect edges
4. Run Validate → confirm no errors
5. Run Execute → confirm expected results

## 9. Checklist

Items to verify before creating a new node:

- [ ] Is `node_type` unique (no conflict with existing nodes)?
- [ ] Is the `@register_node` decorator applied?
- [ ] Is the module import added to `nodes/__init__.py`?
- [ ] Is the `execute()` method implemented?
- [ ] For conditional nodes: is `get_routing_function()` implemented?
- [ ] For conditional nodes: are 2+ `output_ports` defined?
- [ ] Are all LLM calls wrapped in try-catch?
- [ ] Does error handling return `{"error": str(e), "is_complete": True}`?
- [ ] Is `current_step` updated for execution tracing?
- [ ] Do parameters have appropriate `description` and `group` settings?

## 10. Full Example: Web Search Node

A comprehensive example creating a node that passes web search results to the LLM:

```python
"""
Web Search Node — Node that passes web search results to the model.
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
    """Node that performs web search and passes results to the model.

    Calls an external search API, then injects results as context
    so the model can respond based on up-to-date information.
    """

    node_type = "web_search"
    label = "Web Search"
    description = "Model generates answers based on web search results"
    category = "model"
    icon = "🔍"
    color = "#0ea5e9"

    parameters = [
        NodeParameter(
            name="search_query_template",
            label="Search Query Template",
            type="prompt_template",
            default="{input}",
            required=True,
            description="Query to send to the search engine. Use {input} for user input.",
            group="search",
        ),
        NodeParameter(
            name="max_results",
            label="Max Search Results",
            type="number",
            default=5,
            min=1,
            max=20,
            description="Maximum number of search results to retrieve",
            group="search",
        ),
        NodeParameter(
            name="answer_template",
            label="Answer Prompt",
            type="prompt_template",
            default="Answer the question based on the following search results.\n\nSearch Results:\n{search_results}\n\nQuestion: {input}",
            required=True,
            description="Answer generation prompt including search results",
            group="prompt",
        ),
    ]
```

> **Note**: The source KO file is truncated at this point. The full `WebSearchNode` implementation would include `output_ports`, `execute()` with search API call, result formatting, LLM invocation, and optionally a `get_routing_function()` for conditional routing based on whether search results were found.
