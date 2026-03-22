# Node Interface Definition

## 1. Overview

All workflow nodes must inherit from the `BaseNode` abstract class. `BaseNode` defines two concerns:

1. **Metadata** — Information displayed in the frontend node palette (name, description, category, parameters, output ports)
2. **Execution Logic** — Logic that receives LangGraph state at runtime and returns state updates

## 2. BaseNode Class Structure

```python
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

class BaseNode(ABC):
    """Abstract base class for all workflow nodes"""

    # ── Class-level metadata (override in subclasses) ──
    node_type: str = ""           # Unique identifier: "llm_call", "classify_difficulty", etc.
    label: str = ""               # Display name: "LLM Call", "Classify Difficulty"
    description: str = ""         # One-line description
    category: str = "general"     # Category: "model", "task", "logic", "memory", "resilience"
    icon: str = "⚡"              # Emoji icon
    color: str = "#3b82f6"        # Hex color

    parameters: List[NodeParameter] = []               # Configurable parameter list
    output_ports: List[OutputPort] = [                  # Output port list
        OutputPort(id="default", label="Next"),
    ]

    # ── Properties ──
    @property
    def is_conditional(self) -> bool:
        """Conditional node if 2+ output ports"""
        return len(self.output_ports) > 1

    # ── Execution (required implementation) ──
    @abstractmethod
    async def execute(
        self,
        state: Dict[str, Any],
        context: ExecutionContext,
        config: Dict[str, Any],
    ) -> Dict[str, Any]: ...

    # ── Routing (optional implementation) ──
    def get_routing_function(
        self, config: Dict[str, Any],
    ) -> Optional[Callable[[Dict[str, Any]], str]]:
        return None

    # ── Serialization ──
    def to_dict(self) -> Dict[str, Any]: ...
```

## 3. Metadata Field Details

### 3.1 node_type (Required)

```python
node_type = "classify_difficulty"
```

- Unique string identifier
- Registered in `NodeRegistry` under this value
- Referenced by `WorkflowNodeInstance.node_type`
- **Must be unique** — empty string causes registration error

### 3.2 label

```python
label = "Classify Difficulty"
```

- Display name shown in the frontend node palette and canvas
- User-friendly name shown to the user

### 3.3 description

```python
description = "Classify the input task difficulty (easy/medium/hard)"
```

- One-line text describing the node's function
- Used for tooltips etc. in the frontend node palette

### 3.4 category

```python
category = "model"
```

- Key for grouping nodes in the frontend palette
- Currently used categories:

| Category | Description | Node Examples |
|----------|-------------|---------------|
| `model` | LLM call-related nodes | llm_call, classify_difficulty, direct_answer, answer, review |
| `task` | Task management nodes | create_todos, execute_todo, final_review, final_answer |
| `logic` | Flow control nodes | conditional_router, iteration_gate, check_progress, state_setter |
| `resilience` | Stability assurance nodes | context_guard, post_model |
| `memory` | Memory management nodes | memory_inject, transcript_record |

### 3.5 icon / color

```python
icon = "🔀"
color = "#3b82f6"
```

- `icon`: Emoji displayed on the node card in the frontend
- `color`: Background/border color for the node card (hex)

## 4. NodeParameter — Parameter Schema

Defines configurable parameters for each node. The frontend property editor renders forms based on this schema.

```python
@dataclass
class NodeParameter:
    name: str                # Parameter name (key in config dictionary)
    label: str               # Display label
    type: Literal[           # Input type
        "string",            #   Text field
        "number",            #   Number input
        "boolean",           #   Checkbox/toggle
        "select",            #   Dropdown selection
        "textarea",          #   Multi-line text
        "json",              #   JSON editor
        "prompt_template",   #   Prompt template (supports variable substitution)
    ]
    default: Any = None      # Default value
    required: bool = False   # Required flag
    description: str = ""    # Parameter description
    placeholder: str = ""    # Placeholder text
    options: List[Dict[str, str]] = []   # Options for select type only
    min: Optional[float] = None          # Minimum for number type
    max: Optional[float] = None          # Maximum for number type
    group: str = "general"               # Parameter group (UI tab classification)
```

### Behavior by Parameter Type

| Type | UI Widget | Value Format | Description |
|------|-----------|--------------|-------------|
| `string` | Text input | `str` | Single-line text |
| `number` | Number input | `int` / `float` | min/max range supported |
| `boolean` | Toggle switch | `bool` | True/False |
| `select` | Dropdown | `str` | Selection from options |
| `textarea` | Multi-line text | `str` | Multi-line text input |
| `json` | JSON editor | `dict` / `list` | Structured data |
| `prompt_template` | Prompt editor | `str` | Supports `{field_name}` variable substitution |

### Parameter Definition Example

```python
parameters = [
    NodeParameter(
        name="prompt_template",
        label="Classification Prompt",
        type="prompt_template",
        default="{input}",
        required=True,
        description="Prompt to send to the model. {input} is replaced with user input.",
        group="prompt",
    ),
    NodeParameter(
        name="max_retries",
        label="Max Retries",
        type="number",
        default=3,
        min=0,
        max=10,
        description="Maximum retry count",
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

## 5. OutputPort — Output Port Definition

Defines possible branching paths after a node's execution.

```python
@dataclass
class OutputPort:
    id: str            # Port identifier: "default", "easy", "medium", "hard", etc.
    label: str         # Display label
    description: str   # Port description
```

### Non-Conditional Nodes (Single Port)

Most nodes have only one default output port:

```python
output_ports = [
    OutputPort(id="default", label="Next"),
]
```

In this case, `is_conditional == False`, and edges are connected via simple `add_edge()`.

### Conditional Nodes (Multiple Ports)

Nodes requiring routing define multiple output ports:

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

In this case, `is_conditional == True`, and `get_routing_function()` must be implemented.

## 6. ExecutionContext — Runtime Dependencies

Shared dependency context injected during node execution:

```python
@dataclass
class ExecutionContext:
    model: Any                     # ClaudeCLIChatModel — LLM call interface
    session_id: str                # Current session ID
    memory_manager: Any            # SessionMemoryManager — memory read/write
    session_logger: Any            # Session logger
    context_guard: Any             # ContextWindowGuard — context window management
    max_retries: int = 2           # Model call retry count
    model_name: Optional[str]      # Model name in use
```

### resilient_invoke()

Provides automatic retry for transient errors during model calls:

```python
async def resilient_invoke(self, messages, node_name) -> tuple:
    """
    Returns: (response, fallback_updates_dict)

    Retryable errors:
    - RATE_LIMITED: Wait 5s × attempt
    - OVERLOADED: Wait 3s × attempt
    - TIMEOUT: Wait 2s × attempt
    - NETWORK_ERROR: Wait 2s × attempt

    Non-recoverable errors are raised immediately
    """
```

## 7. NodeRegistry — Global Node Registry

A singleton registry that manages all `BaseNode` subclasses:

```python
class NodeRegistry:
    def register(self, node_class: Type[BaseNode]) -> Type[BaseNode]:
        """Register a node class (creates singleton instance)"""
        instance = node_class()
        self._registry[instance.node_type] = instance

    def get(self, node_type: str) -> Optional[BaseNode]:
        """Look up node instance by node_type string"""

    def to_catalog(self) -> List[Dict[str, Any]]:
        """Serialized catalog for frontend node palette"""
```

### Registration Methods

```python
# Method 1: Decorator (recommended)
@register_node
class MyNode(BaseNode):
    node_type = "my_node"
    ...
```
