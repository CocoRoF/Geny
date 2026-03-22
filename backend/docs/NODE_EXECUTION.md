# Node Execution Principles

## 1. Overview

This document explains in detail **how individual workflow nodes are executed**, how state **propagates**, and how **conditional routing works**.

## 2. Execution Lifecycle

### 2.1 Overall Execution Flow

```
graph.ainvoke(initial_state)
  ↓
LangGraph execution engine starts from START
  ↓
Calls current node's wrapped function: _node_fn(state)
  ↓
BaseNode.execute(state, context, config) runs
  ↓
Returns state update Dict
  ↓
LangGraph merges state with reducers
  ↓
Routing decision (direct edge or conditional routing)
  ↓
Moves to next node (or terminates if END is reached)
```

### 2.2 Single Node Execution Details

```python
# Wrapped function created by WorkflowExecutor
async def _node_fn(state: AutonomousState) -> Dict[str, Any]:
    return await base_node.execute(state, ctx, config)
```

1. **LangGraph invocation**: LangGraph engine calls `_node_fn(state)` mapped to the current node ID
2. **State reception**: The full current state is passed via the `state` parameter
3. **Logic execution**: `base_node.execute()` performs the required processing
4. **State update return**: Returns a Dict containing only the fields to change
5. **State merge**: LangGraph applies reducers to merge into the full state

## 3. execute() Method Details

### 3.1 Signature

```python
async def execute(
    self,
    state: Dict[str, Any],      # Current LangGraph full state
    context: ExecutionContext,   # Runtime dependencies (model, memory, guard, etc.)
    config: Dict[str, Any],     # User-configured parameter values
) -> Dict[str, Any]:            # State update dictionary
```

### 3.2 Input Parameters

#### state (Current State)
- Current values of the `AutonomousState` TypedDict
- Contains all fields updated by previous nodes
- **Treated as read-only** — don't modify directly; update via return value

```python
# Reading values from state
input_text = state.get("input", "")
difficulty = state.get("difficulty")
iteration = state.get("iteration", 0)
todos = state.get("todos", [])
```

#### context (Execution Context)
- `ExecutionContext` instance
- Shared runtime dependencies across all nodes

```python
# Model call
response, fallback = await context.resilient_invoke(messages, "node_name")

# Memory access
if context.memory_manager:
    memories = await context.memory_manager.get_relevant(query)

# Context guard
if context.context_guard:
    budget = context.context_guard.check_budget(messages)
```

#### config (Node Configuration)
- Parameter values set by user in the frontend
- `WorkflowNodeInstance.config` dictionary

```python
# Reading configuration values
template = config.get("prompt_template", "{input}")
max_retries = config.get("max_retries", 3)
output_field = config.get("output_field", "last_output")
```

### 3.3 Return Value (State Updates)

`Dict[str, Any]` — Returns a dictionary containing only the state fields to change.

```python
# Simple example
return {
    "last_output": response.content,
    "current_step": "llm_call_complete",
}

# Adding messages (appended via reducer)
return {
    "messages": [response],     # _add_messages reducer appends to existing list
    "last_output": response.content,
    "current_step": "answer_complete",
}

# TODO update (ID-based merge via reducer)
return {
    "todos": [updated_todo],    # _merge_todos reducer merges by ID
    "current_todo_index": next_index,
}

# On error
return {
    "error": str(e),
    "is_complete": True,
}
```

## 4. Execution Patterns by Category

### 4.1 LLM Call Pattern

Pattern followed by most `model` category nodes:

```python
async def execute(self, state, context, config):
    # 1. Prepare prompt
    template = config.get("prompt_template", "{input}")
    prompt = template.format(**{
        k: (v if isinstance(v, str) else str(v) if v is not None else "")
        for k, v in state.items()
    })

    # 2. Construct messages
    messages = [HumanMessage(content=prompt)]

    # 3. Model call (with retry)
    try:
        response, fallback = await context.resilient_invoke(messages, "node_name")
    except Exception as e:
        return {"error": str(e), "is_complete": True}

    # 4. Parse response (if needed)
    parsed_result = parse_response(response.content)

    # 5. Return state updates
    result = {
        "messages": [response],
        "last_output": response.content,
        "current_step": "step_name",
        "parsed_field": parsed_result,
    }
    result.update(fallback)  # Merge fallback record
    return result
```

### 4.2 Pure Logic Pattern

`logic` category nodes — inspect/modify state only without LLM calls:

```python
async def execute(self, state, context, config):
    # State inspection
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 50)
    signal = state.get("completion_signal")

    # Logic decision
    if iteration >= max_iter or signal == CompletionSignal.COMPLETE.value:
        return {"current_step": "iteration_stopped"}

    return {"current_step": "iteration_continue"}
```

### 4.3 Memory Injection Pattern

`memory` category nodes:

```python
async def execute(self, state, context, config):
    if not context.memory_manager:
        return {"current_step": "memory_skip"}

    # Memory lookup
    query = state.get("input", "")
    memories = await context.memory_manager.get_relevant_memories(query)

    # Inject memory context into messages
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

### 4.4 Guard Pattern (Context Guard)

`resilience` category — context budget check before model calls:

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

## 5. Conditional Routing Details

### 5.1 How It Works

After executing a conditional node, LangGraph calls the **routing function** to determine the next node:

```
execute(state) → state_updates → state merge → routing_fn(merged_state) → port_id → edge_map[port_id] → next node
```

### 5.2 get_routing_function() Implementation

Returns a function that routes based on the state after `execute()` has updated it:

```python
# ClassifyDifficultyNode routing function
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
# IterationGateNode routing function
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
# ReviewNode routing function
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

### 5.3 Integration with Edge Maps

The string (port ID) returned by the routing function is used as the key in the edge map:

```python
# Inside WorkflowExecutor
edge_map = {
    "easy": "node_direct_answer",     # easy port → DirectAnswer node
    "medium": "node_answer",          # medium port → Answer node
    "hard": "node_create_todos",      # hard port → CreateTodos node
    "end": END,                       # end port → graph termination
}

graph_builder.add_conditional_edges("classify_node", routing_fn, edge_map)
```

## 6. State Propagation and Reducers

### 6.1 State Merge Process

```python
# LangGraph internal process (simplified)
node_output = await _node_fn(current_state)

for key, value in node_output.items():
    if key in REDUCER_MAP:
        # Apply custom reducer
        current_state[key] = REDUCER_MAP[key](current_state.get(key), value)
    else:
        # Default: last-write-wins
        current_state[key] = value
```

### 6.2 Reducer Examples

#### _add_messages (append)
```python
# Before: messages = [msg1, msg2]
# Node returns: {"messages": [msg3]}
# After: messages = [msg1, msg2, msg3]
```

#### _merge_todos (ID-based merge)
```python
# Before: todos = [{"id": "a", "status": "pending"}, {"id": "b", "status": "pending"}]
# Node returns: {"todos": [{"id": "a", "status": "done", "result": "..."}]}
# After: todos = [{"id": "a", "status": "done", "result": "..."}, {"id": "b", "status": "pending"}]
```

#### Default (last-write-wins)
```python
# Before: difficulty = None
# Node returns: {"difficulty": "easy"}
# After: difficulty = "easy"
```
