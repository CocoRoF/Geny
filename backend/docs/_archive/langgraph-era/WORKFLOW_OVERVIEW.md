# Workflow System Overview

## 1. Overview

The workflow system **transforms user-designed visual graphs (nodes + edges) into executable LangGraph StateGraphs and runs them**.
It abstracts the behavior of the hard-coded `AutonomousGraph`, allowing users to freely edit the agent's execution flow.

## 2. System Components

```
┌─────────────────────────────────────────────────────┐
│  Frontend (React Flow Editor)                        │
│  - Drag & drop nodes from the palette               │
│  - Define execution flow by connecting edges         │
│  - Configure parameters in the node property panel   │
└──────────────────────┬──────────────────────────────┘
                       │ REST API (/api/workflows/*)
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowController (workflow_controller.py)          │
│  - CRUD: create/read/update/delete workflows         │
│  - Validation (/validate)                            │
│  - Execution (/execute)                              │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowStore (workflow_store.py)                     │
│  - JSON file-based persistence (backend/workflows/)   │
│  - CRUD methods: save, load, delete, list_all        │
│  - Separate template / user workflow management       │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowDefinition (workflow_model.py)                │
│  - Pydantic model: node instances + edges + metadata  │
│  - Graph structure validation (validate_graph)        │
│  - Start/end node lookup utilities                    │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  WorkflowExecutor (workflow_executor.py)               │
│  - Compiles WorkflowDefinition → LangGraph StateGraph │
│  - Node function wrapping, edge wiring, routing       │
│  - Creates initial state and runs graph.ainvoke()     │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  BaseNode Implementations (nodes/*.py)                 │
│  - Actual logic for each node type                   │
│  - Registered in NodeRegistry, DI via ExecutionContext│
└─────────────────────────────────────────────────────┘
```

## 3. Data Flow

### 3.1 Workflow Save Flow

```
User edits → Frontend JSON → POST /api/workflows → WorkflowStore.save() → backend/workflows/{id}.json
```

### 3.2 Workflow Execution Flow

```
POST /api/workflows/{id}/execute (input_text, session_id)
  ↓
WorkflowStore.load(id) → WorkflowDefinition
  ↓
WorkflowDefinition.validate_graph() → 400 on error
  ↓
Acquire model, memory, guard from AgentSession
  ↓
Create ExecutionContext (model, session_id, memory_manager, ...)
  ↓
WorkflowExecutor(workflow, context)
  ↓
executor.compile() → LangGraph StateGraph
  ↓
executor.run(input_text) → graph.ainvoke(initial_state) → final_state
  ↓
Return result (final_answer, iterations, difficulty, etc.)
```

## 4. Core Data Models

### 4.1 WorkflowNodeInstance

Represents an individual node instance placed on the canvas.

```python
class WorkflowNodeInstance(BaseModel):
    id: str                        # Unique identifier (first 8 chars of UUID)
    node_type: str                 # References registered BaseNode.node_type
    label: str                     # User-defined display name
    config: Dict[str, Any]         # Node parameter settings
    position: Dict[str, float]     # Canvas position {"x": 0, "y": 0}
```

### 4.2 WorkflowEdge

Represents a directed connection between two node instances.

```python
class WorkflowEdge(BaseModel):
    id: str              # Unique identifier
    source: str          # Source node instance ID
    target: str          # Target node instance ID
    source_port: str     # Output port ID (default: "default")
    label: str           # Edge label
```

### 4.3 WorkflowDefinition

The complete workflow graph definition.

```python
class WorkflowDefinition(BaseModel):
    id: str
    name: str
    description: str
    nodes: List[WorkflowNodeInstance]
    edges: List[WorkflowEdge]
    created_at: str              # ISO timestamp
    updated_at: str
    is_template: bool            # True = template (no direct editing, clone only)
    template_name: Optional[str]
```

Key methods:
- `get_node(node_id)` — Look up a node instance by ID
- `get_edges_from(node_id)` — Get outgoing edges from a node
- `get_edges_to(node_id)` — Get incoming edges to a node
- `get_start_node()` — Find the node with `node_type == "start"`
- `get_end_nodes()` — Find nodes with `node_type == "end"`
- `validate_graph()` — Structural validation

## 5. Validation Rules

Checks performed by `validate_graph()`:

| Rule | Description |
|------|-------------|
| Start node required | Exactly 1 `start` node must exist |
| End node required | At least 1 `end` node must exist |
| Start connection required | Start node must have at least 1 outgoing edge |
| Edge reference check | All edge source/target must reference existing node IDs |
| Isolated node detection | Non-start/end nodes must be connected to at least 1 edge |

## 6. Template System

### Built-in Templates

Two built-in templates are provided in `templates.py`:

| Template | ID | Description |
|----------|-----|-------------|
| Simple | `template-simple` | memory_inject → guard → llm_call → post_model → end (5 nodes, 4 edges) |
| Autonomous | `template-autonomous` | Difficulty-based 28-node full graph (easy/medium/hard paths) |

### Template Installation

`install_templates(store)` — Called at server startup; saves default templates as JSON if they don't already exist.

### Template Usage

- Templates are marked with `is_template=True` and cannot be directly modified
- Users can use the `Clone` feature to copy a template and then freely edit it
