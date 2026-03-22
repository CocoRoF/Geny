# Workflow System

> Engine that compiles visual workflow editor graphs into LangGraph StateGraphs and executes them

## Architecture Overview

```
WorkflowDefinition (JSON)
        │
        ▼
  WorkflowExecutor.compile()
        │
        ├── NodeRegistry — Lookup from 20 registered node types
        ├── ExecutionContext — Inject model, memory, logger
        └── StateGraph(AutonomousState) — Build LangGraph graph
                │
                ▼
        CompiledStateGraph
                │
                ▼
        graph.ainvoke(initial_state)
                │
                ▼
          Final execution result
```

## WorkflowDefinition

JSON serialization model for workflows. Shared schema between the frontend editor and backend engine.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID — unique workflow ID |
| `name` | `str` | Display name |
| `description` | `str` | Description |
| `nodes` | `List[WorkflowNodeInstance]` | All node instances |
| `edges` | `List[WorkflowEdge]` | All directed edges |
| `is_template` | `bool` | Whether this is a built-in template |
| `template_name` | `Optional[str]` | Template identifier |
| `created_at` / `updated_at` | `str` | ISO 8601 timestamps |

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

| Field | Description |
|-------|-------------|
| `id` | Unique instance ID (8-char UUID) |
| `node_type` | References a registered BaseNode's `node_type` |
| `label` | Display name on the editor canvas |
| `config` | User-configured parameter values |
| `position` | Canvas coordinates |

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

| Field | Description |
|-------|-------------|
| `source` | Source node instance ID |
| `target` | Target node instance ID |
| `source_port` | Output port ID (`default` or conditional port name) |

### Graph Validation

`validate_graph()` checks:
- Exactly 1 `start` node
- At least 1 `end` node
- `start` node has outgoing edges
- All edge source/target reference valid node IDs
- No orphan nodes

---

## WorkflowExecutor

Engine that transforms `WorkflowDefinition` → `CompiledStateGraph`.

### compile()

1. Call `validate_graph()` — raises `ValueError` on failure
2. Create `StateGraph(AutonomousState)`
3. Map each `WorkflowNodeInstance` → `BaseNode` (registry lookup, skip `start`/`end` pseudo-nodes)
4. `_make_node_function(base_node, instance)` — generates async LangGraph node function
   - Pre/post logging via `session_logger` (enter/exit/error)
   - Execution time measurement
5. Edge wiring:
   - **Single target**: `add_edge(source, target)`
   - **Multiple targets**: `add_conditional_edges(source, routing_fn, edge_map)`
   - **START pseudo-node**: `add_edge(START, first_target)`
   - **END pseudo-node**: mapped to LangGraph `END` sentinel
6. `graph_builder.compile()` → `CompiledStateGraph`

### run()

```python
async def run(self, input_text: str, max_iterations: int = 50, **extra_metadata) -> Dict[str, Any]
```

- Auto-compiles if needed
- Creates initial state via `make_initial_autonomous_state()`
- Executes `await self._graph.ainvoke(initial_state)`
- Returns final state dictionary

### Routing Decision Logic

Conditional node routing is returned by `BaseNode.get_routing_function(config)`:

```python
# classify example
def routing_fn(state: Dict) -> str:
    value = state.get("difficulty", "medium").lower()
    if value in categories:
        return value
    return default_category
```

`WorkflowExecutor` applies conditional routing only when a source has **2+ edges pointing to different targets**.

---

## Node Registry System

### @register_node Decorator

```python
@register_node
class MyNode(BaseNode):
    node_type = "my_node"
    ...
```

Auto-registers into the `NodeRegistry` singleton. Supports aliases for backward compatibility.

### BaseNode ABC

Parent class for all workflow nodes.

```python
class BaseNode(ABC):
    node_type: str          # Unique identifier
    label: str              # Display name
    description: str        # Description
    category: str           # Palette group (model, logic, resilience, task, memory)
    parameters: List[NodeParameter]   # Configurable parameters
    output_ports: List[OutputPort]    # Routing ports

    @abstractmethod
    async def execute(self, state, context, config) -> Dict[str, Any]: ...

    def get_routing_function(self, config) -> Optional[Callable]: ...
    def get_dynamic_output_ports(self, config) -> Optional[List[OutputPort]]: ...
```

---

## Full Node Catalog (20 Types)

### Model Category (6)

| Node | `node_type` | Conditional | Description |
|------|------------|-------------|-------------|
| **LLM Call** | `llm_call` | ✗ | General-purpose LLM call. `{field}` substitution prompt templates, multi-output mapping, conditional prompt switching |
| **Classify** | `classify` | ✓ | Structured output LLM classification. Routes via category-specific ports. Default: easy/medium/hard |
| **Adaptive Classify** | `adaptive_classify` | ✓ | Rule-based fast path + LLM fallback. Regex patterns classify short inputs without LLM (saves 8-15s) |
| **Direct Answer** | `direct_answer` | ✗ | Single-shot response for easy tasks. Configurable output field, optional completion marking |
| **Answer** | `answer` | ✗ | Review-feedback-aware response. First attempt uses primary prompt, retries use retry_template |
| **Review** | `review` | ✓ | Self-routing quality gate. Structured output verdict + feedback. Default ports: approved/retry |

### Logic Category (5)

| Node | `node_type` | Conditional | Description |
|------|------------|-------------|-------------|
| **Conditional Router** | `conditional_router` | ✓ | Pure state-based routing. Reads state field → route_map JSON for port mapping |
| **Iteration Gate** | `iteration_gate` | ✓ | Loop prevention. Iteration limit, context budget, completion signal, custom field checks |
| **Check Progress** | `check_progress` | ✓ | List completion check. Index vs list length comparison → continue/complete |
| **State Setter** | `state_setter` | ✗ | Sets state fields from JSON config values. For initialization, counter resets, config injection |
| **Relevance Gate** | `relevance_gate` | ✓ | Broadcast message filter. Only activates when `is_chat_message=True` |

### Resilience Category (2)

| Node | `node_type` | Conditional | Description |
|------|------------|-------------|-------------|
| **Context Guard** | `context_guard` | ✗ | Token budget check. Estimates usage from messages → `context_budget` (safe/warning/block/overflow) |
| **Post Model** | `post_model` | ✗ | Post-LLM processing: (1) increment iteration, (2) detect completion signals, (3) record short-term memory |

### Task Category (5)

| Node | `node_type` | Conditional | Description |
|------|------------|-------------|-------------|
| **Create TODOs** | `create_todos` | ✗ | Breaks complex tasks into structured TODO list (Pydantic `CreateTodosOutput` validation) |
| **Execute TODO** | `execute_todo` | ✗ | Executes a single TODO item. Context-aware, auto-updates state |
| **Final Review** | `final_review` | ✗ | Structured quality review of all completed items (`FinalReviewOutput`) |
| **Final Answer** | `final_answer` | ✗ | Synthesizes final response from list results + review feedback. Marks completion |
| **Final Synthesis** | `final_synthesis` | ✗ | Merges Final Review + Final Answer into a single LLM call (saves 1 round-trip) |

### Memory Category (2)

| Node | `node_type` | Conditional | Description |
|------|------------|-------------|-------------|
| **Memory Inject** | `memory_inject` | ✗ | LLM-gated memory injection. Integrates session summary, MEMORY.md, FAISS vector search, keyword search |
| **Transcript Record** | `transcript_record` | ✗ | Records state fields to short-term memory transcript |

---

## AutonomousState

LangGraph graph's shared state TypedDict. Single state object read/written by all nodes.

### Key Fields

| Field | Type | Reducer | Description |
|-------|------|---------|-------------|
| `input` | `str` | last-wins | User input |
| `messages` | `list` | **append** | LLM conversation history |
| `iteration` | `int` | last-wins | Iteration counter |
| `max_iterations` | `int` | last-wins | Maximum iterations |
| `difficulty` | `Optional[str]` | last-wins | Difficulty classification result |
| `answer` | `Optional[str]` | last-wins | Medium-path response |
| `review_result` | `Optional[str]` | last-wins | Review verdict |
| `review_feedback` | `Optional[str]` | last-wins | Review feedback |
| `todos` | `List[TodoItem]` | **merge by ID** | Hard-path TODO list |
| `current_todo_index` | `int` | last-wins | Next TODO index |
| `final_answer` | `Optional[str]` | last-wins | Synthesized final response |
| `completion_signal` | `Optional[str]` | last-wins | continue/complete/blocked/error/none |
| `is_complete` | `bool` | last-wins | Workflow termination flag |
| `total_cost` | `float` | **accumulate** | Accumulated cost (USD) |
| `memory_refs` | `List[MemoryRef]` | **deduplicate** | Loaded memory chunks |
| `memory_context` | `Optional[str]` | last-wins | Formatted memory text |
| `context_budget` | `Optional[ContextBudget]` | last-wins | Token usage tracking |
| `fallback` | `Optional[FallbackRecord]` | last-wins | Model fallback state |
| `metadata` | `Dict[str, Any]` | last-wins | Extension metadata |

### Custom Reducers

- **`_add_messages`**: Simple list concatenation
- **`_merge_todos`**: Merge by `id` key, right wins
- **`_merge_memory_refs`**: Deduplicate by `filename`
- **`_add_floats`**: Sum values (cost accumulation)

### Enum Types

| Enum | Values |
|------|--------|
| `Difficulty` | `EASY`, `MEDIUM`, `HARD` |
| `CompletionSignal` | `CONTINUE`, `COMPLETE`, `BLOCKED`, `ERROR`, `NONE` |
| `ReviewResult` | `APPROVED`, `REJECTED` |
| `TodoStatus` | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED` |
| `ContextBudgetStatus` | `OK`, `WARN`, `BLOCK`, `OVERFLOW` |

---

## ExecutionContext

Context object carrying dependencies for node execution.

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

Auto-retry and cost tracking for LLM calls.

```python
async def resilient_invoke(messages, node_name) -> (AIMessage, Dict)
```

- Retries up to `max_retries` for recoverable errors (rate_limited, overloaded, timeout, network)
- Exponential backoff
- Extracts `cost_usd` from response, returns `{"total_cost": float}`

### resilient_structured_invoke()

Structured output LLM call. Injects JSON Schema directives → parses → validates.

```python
async def resilient_structured_invoke(
    messages, node_name, schema_cls,
    *, allowed_values, coerce_field, coerce_values, coerce_default
) -> (pydantic_instance, Dict)
```

1. Appends JSON schema directive to last `HumanMessage`
2. `resilient_invoke()` → raw text
3. `parse_structured_output()` — 4-stage extraction: direct JSON → code block → bracket match
4. On parse failure, retries once with a correction prompt
5. Fuzzy-matches enum-like fields via `coerce_field`/`coerce_values`

---

## Structured Output Schemas

| Schema | Fields | Used By |
|--------|--------|---------|
| `ClassifyOutput` | `classification`, `confidence`, `reasoning` | Classify, Adaptive Classify |
| `ReviewOutput` | `verdict`, `feedback`, `issues` | Review |
| `MemoryGateOutput` | `needs_memory`, `reasoning` | Memory Inject |
| `RelevanceOutput` | `relevant`, `reasoning` | Relevance Gate |
| `CreateTodosOutput` | `todos: List[TodoItem]` | Create TODOs |
| `FinalReviewOutput` | `overall_quality`, `completed_summary`, `issues_found`, `recommendations` | Final Review |

---

## Built-in Workflow Templates

### template-simple (6 nodes)

Simplest linear graph:

```
START → Memory Inject → Context Guard → LLM Call → Post Model → END
```

### template-autonomous (28 nodes)

Difficulty-based 3-path branching:

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

### template-optimized-autonomous (18 nodes)

Optimized variant:
- **Adaptive Classify** → Merges Classify + Guard + Post (rule-based fast path)
- **LLM Call** → Merges Direct Answer + Guard + Post
- **Final Synthesis** → Merges Final Review + Final Answer + Guard + Post
- ~25-47% speed improvement

---

## WorkflowStore

JSON file-based workflow storage. Saved in `backend/workflows/` directory.

| Method | Description |
|--------|-------------|
| `save(workflow)` | Save/update |
| `load(workflow_id)` | Load by ID |
| `delete(workflow_id)` | Delete file |
| `list_all()` | List all |
| `list_templates()` | Built-in templates only |
| `list_user_workflows()` | User workflows only |

Filename: sanitized ID as `{safe_id}.json`.

---

## WorkflowInspector

Mirrors compilation logic to generate structural analysis reports:

```python
inspect_workflow(workflow) -> Dict[str, Any]
```

Returns:
- `code`: Python pseudo-code of the compiled graph
- `nodes`: Per-node details (type, category, routing logic)
- `edges`: Per-edge details (simple/conditional)
- `state`: `WorkflowStateAnalysis` (field usage)
- `summary`: Statistics (node count, edge count)
- `validation`: Graph validation result

---

## Compiler (Dry-Run)

Tests workflows without LLM calls. See [Compiler docs](../service/workflow/compiler/SUDO_COMPILER.md).

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/workflows/nodes` | Node type catalog |
| `GET` | `/api/workflows/nodes/{type}/help` | Node help (multilingual) |
| `GET` | `/api/workflows` | List all workflows |
| `POST` | `/api/workflows` | Create workflow |
| `GET` | `/api/workflows/templates` | List built-in templates |
| `GET` | `/api/workflows/{id}` | Get workflow |
| `PUT` | `/api/workflows/{id}` | Update workflow (templates immutable) |
| `DELETE` | `/api/workflows/{id}` | Delete workflow (templates immutable) |
| `POST` | `/api/workflows/{id}/clone` | Clone workflow |
| `POST` | `/api/workflows/{id}/validate` | Validate graph structure |
| `POST` | `/api/workflows/{id}/compile-view` | Compile view (pseudo-code + state analysis) |
| `GET` | `/api/workflows/state/fields` | AutonomousState field definitions |
| `POST` | `/api/workflows/{id}/execute` | Execute workflow in a session |

---

## Related Files

```
service/workflow/
├── workflow_model.py          # WorkflowDefinition Pydantic models
├── workflow_executor.py       # WorkflowDefinition → CompiledStateGraph compiler
├── workflow_store.py          # JSON file-based storage
├── workflow_inspector.py      # Graph structural analyzer
├── workflow_state.py          # StateFieldDef, NodeStateUsage, state analysis
├── templates.py               # Built-in template factory
├── compiler/                  # Dry-run compiler (separate docs)
└── nodes/
    ├── __init__.py            # register_all_nodes()
    ├── base.py                # BaseNode ABC, ExecutionContext, NodeRegistry
    ├── structured_output.py   # Pydantic schemas, JSON parsing
    ├── _helpers.py            # safe_format, parse_categories utilities
    ├── model/                 # llm_call, classify, adaptive_classify, direct_answer, answer, review
    ├── logic/                 # conditional_router, iteration_gate, check_progress, state_setter, relevance_gate
    ├── resilience/            # context_guard, post_model
    ├── task/                  # create_todos, execute_todo, final_review, final_answer, final_synthesis
    └── memory/                # memory_inject, transcript_record
```
