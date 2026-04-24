# LangGraph Porting Principles

## 1. Overview

The core of the workflow system is **compiling user-designed JSON-based workflows (`WorkflowDefinition`) into LangGraph `StateGraph` instances**. This process is handled by the `WorkflowExecutor` class and operates as a 5-stage pipeline.

```
JSON (WorkflowDefinition)
  → 1. Validation
  → 2. Node instance ↔ BaseNode type mapping
  → 3. LangGraph node function registration
  → 4. Edge wiring (direct / conditional)
  → 5. Compilation and execution
```

## 2. Detailed Pipeline

### 2.1 Stage 1: Validation

```python
errors = self._workflow.validate_graph()
if errors:
    raise ValueError("Workflow validation failed: ...")
```

`WorkflowDefinition.validate_graph()` validates the graph structure:
- Start node existence (exactly 1)
- End node existence (at least 1)
- Outgoing edges from the start node
- All edge source/target reference existing node IDs
- No isolated nodes (excluding start/end)

### 2.2 Stage 2: Node Instance → BaseNode Type Resolution

```python
graph_builder = StateGraph(AutonomousState)

instance_map: Dict[str, WorkflowNodeInstance] = {}
node_type_map: Dict[str, BaseNode] = {}

for inst in self._workflow.nodes:
    instance_map[inst.id] = inst

    if inst.node_type in ("start", "end"):
        continue  # Pseudo-nodes — handled as LangGraph's START/END

    base_node = self._registry.get(inst.node_type)
    if base_node is None:
        raise ValueError(f"Unknown node type '{inst.node_type}'")
    node_type_map[inst.id] = base_node
```

**Key concepts:**
- `WorkflowNodeInstance.node_type` is a string (e.g., `"llm_call"`, `"classify_difficulty"`)
- The `NodeRegistry` resolves this string to a `BaseNode` singleton instance
- `start` and `end` are **pseudo-nodes** — they map to LangGraph's `START`/`END` sentinels

### 2.3 Stage 3: LangGraph Node Function Registration

Each `BaseNode`'s `execute()` method is wrapped as a LangGraph node function:

```python
for inst_id, base_node in node_type_map.items():
    inst = instance_map[inst_id]
    node_fn = self._make_node_function(base_node, inst)
    graph_builder.add_node(inst_id, node_fn)
```

Wrapper function structure:

```python
def _make_node_function(self, base_node: BaseNode, instance: WorkflowNodeInstance):
    ctx = self._context        # ExecutionContext (model, memory, guard, etc.)
    config = dict(instance.config)  # User-configured parameter values

    async def _node_fn(state: AutonomousState) -> Dict[str, Any]:
        return await base_node.execute(state, ctx, config)

    _node_fn.__name__ = f"node_{instance.id}_{instance.node_type}"
    return _node_fn
```

**Transformation process:**
```
BaseNode.execute(state, context, config)
  → context and config bound via closure
  → LangGraph-compatible function: async def _node_fn(state) -> dict
```

LangGraph node functions must have the `(state) → state_updates` signature, so `ExecutionContext` and `config` are captured as **closures** to match LangGraph's required interface.

### 2.4 Stage 4: Edge Wiring

Edges are grouped by source node, then connected differently based on node type:

```python
edges_by_source: Dict[str, List[WorkflowEdge]] = {}
for edge in self._workflow.edges:
    edges_by_source.setdefault(edge.source, []).append(edge)
```

#### 4a. Start Pseudo-Node Handling

```python
if source_inst.node_type == "start":
    first_target = self._resolve_target(edges[0].target, instance_map)
    graph_builder.add_edge(START, first_target)
```

LangGraph's `START` sentinel → direct connection to the first target node.

#### 4b. End Pseudo-Node Handling

```python
def _resolve_target(self, target_id, instance_map):
    inst = instance_map.get(target_id)
    if inst and inst.node_type == "end":
        return END  # LangGraph END sentinel
    return target_id
```

If the target is an `end` node, it's converted to LangGraph's `END` sentinel.

#### 4c. Conditional Nodes

A conditional node is one that has **2 or more output ports** or **multiple different targets**:

```python
if base_node.is_conditional or self._has_multiple_targets(edges):
    config = source_inst.config
    routing_fn = base_node.get_routing_function(config)

    if routing_fn is None:
        routing_fn = self._make_fallback_router(edges, instance_map)

    edge_map = self._build_edge_map(edges, instance_map)
    graph_builder.add_conditional_edges(source_id, routing_fn, edge_map)
```

**Routing function:**
- `BaseNode.get_routing_function(config)` → a function that inspects the state and returns an output port ID
- Example: `ClassifyDifficultyNode`'s routing function reads `state["difficulty"]` and returns one of `"easy"`, `"medium"`, `"hard"`

**Edge map:**
```python
def _build_edge_map(self, edges, instance_map):
    edge_map = {}
    for edge in edges:
        port = edge.source_port or "default"
        target = self._resolve_target(edge.target, instance_map)
        edge_map[port] = target  # {"easy": "node_abc", "medium": "node_def", "hard": "node_ghi"}
    return edge_map
```

LangGraph's `add_conditional_edges(source, routing_fn, edge_map)`:
1. After executing the `source` node, calls `routing_fn(state)`
2. Uses the returned port ID to determine the next node from `edge_map`

#### 4d. Simple Nodes (Direct Edge)

```python
else:
    target = self._resolve_target(edges[0].target, instance_map)
    graph_builder.add_edge(source_id, target)
```

Nodes with only one output port use a simple direct connection.

### 2.5 Stage 5: Compilation and Execution

```python
self._graph = graph_builder.compile()
```

`StateGraph.compile()` → `CompiledStateGraph` — LangGraph internally creates the execution engine.

Execution:

```python
async def run(self, input_text, max_iterations=50):
    initial_state = make_initial_autonomous_state(input_text, max_iterations=max_iterations)
    final_state = await self._graph.ainvoke(initial_state)
    return dict(final_state)
```

## 3. State Schema

### 3.1 AutonomousState

A LangGraph `TypedDict`-based state schema. All workflow nodes read from and write to this state.

```python
class AutonomousState(TypedDict, total=False):
    input: str                      # User input prompt
    messages: Annotated[list, _add_messages]  # Message accumulation (append-only)
    current_step: str               # Current step tracker
    last_output: Optional[str]      # Most recent model response
    iteration: int                  # Global iteration counter
    max_iterations: int             # Maximum iteration count
    difficulty: Optional[str]       # Difficulty classification result
    answer: Optional[str]           # Medium path answer
    review_result: Optional[str]    # Review result
    review_feedback: Optional[str]  # Review feedback
    review_count: int               # Review count
    todos: Annotated[List[TodoItem], _merge_todos]  # TODO list (ID-based merge)
    current_todo_index: int         # Current executing TODO index
    final_answer: Optional[str]     # Final answer
    completion_signal: Optional[str]  # Completion signal
    completion_detail: Optional[str]
    error: Optional[str]
    is_complete: bool
    context_budget: Optional[ContextBudget]  # Context budget
    fallback: Optional[FallbackRecord]       # Model fallback record
    memory_refs: Annotated[List[MemoryRef], _merge_memory_refs]  # Memory references
    metadata: Dict[str, Any]
```

### 3.2 Custom Reducers

In LangGraph, specifying `Annotated[type, reducer_fn]` applies **custom merge logic** during state updates instead of simple overwrites:

| Field | Reducer | Behavior |
|-------|---------|----------|
| `messages` | `_add_messages` | **Appends** new messages to the existing list |
| `todos` | `_merge_todos` | Merges by TODO ID (overwrites existing entries with matching IDs) |
| `memory_refs` | `_merge_memory_refs` | Deduplicates by filename |
| All other fields | (default) | Last-write-wins |

### 3.3 Initial State Creation

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
        # ... other fields set to None/defaults
    }
```

## 4. Visual Mapping Diagram

### JSON Workflow → LangGraph Transformation

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
                                              "end": END })

"direct_answer" node ──────────→  graph.add_node("da01", wrapped_fn)
    ↓ edge                              ↓ add_edge("da01", END)

"end" node ────────────────────→  END (sentinel)
```
