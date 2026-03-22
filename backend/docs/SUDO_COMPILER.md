# Sudo Compiler — Workflow Dry-Run Testing

> A test compiler that validates workflow graphs without making real LLM calls.

## Overview

Sudo Compiler is a **dry-run testing tool** that executes LangGraph StateGraphs compiled by `WorkflowExecutor` without any actual Claude CLI invocations.

All LLM calls (`resilient_invoke`, `resilient_structured_invoke`) are automatically replaced by `SudoModel`, which auto-detects the expected response format (structured output schema) per node and returns valid mock values.

## Architecture

```
┌──────────────────────────────────────────────────┐
│                 SudoCompiler                      │
│                                                   │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │  SudoModel   │   │  WorkflowExecutor        │  │
│  │  (mock LLM)  │──▶│  (real graph compiler)   │  │
│  └─────────────┘   └──────────────────────────┘  │
│         │                       │                  │
│         ▼                       ▼                  │
│  ┌─────────────┐   ┌──────────────────────────┐  │
│  │  AIMessage   │   │  LangGraph StateGraph     │  │
│  │  (fake cost) │   │  (real nodes, real edges) │  │
│  └─────────────┘   └──────────────────────────┘  │
│                           │                        │
│                           ▼                        │
│                  ┌─────────────────┐               │
│                  │  SudoRunReport   │               │
│                  │  (full telemetry)│               │
│                  └─────────────────┘               │
└──────────────────────────────────────────────────┘
```

## Core Components

### `SudoModel` (`model.py`)

A mock model that replaces the real `ClaudeCLIChatModel`:

- **Auto schema detection**: When a node expects structured output (ClassifyOutput, ReviewOutput, etc.), it auto-generates valid JSON
- **Deterministic execution**: Seed-based `random.Random` for reproducible results
- **Override support**: Specific node responses can be forced (e.g., classify → "hard")
- **Cost simulation**: Mock `cost_usd` included in `AIMessage.additional_kwargs`

Supported structured output schemas:

| Schema | Node | Generated Fields |
|--------|------|-----------------|
| `ClassifyOutput` | classify, adaptive_classify | classification, confidence, reasoning |
| `ReviewOutput` | review | verdict, feedback, issues |
| `MemoryGateOutput` | memory_inject (gate) | needs_memory, reasoning |
| `RelevanceOutput` | relevance_gate | relevant, reasoning |
| `CreateTodosOutput` | create_todos | todos[] (2–4 random items) |
| `FinalReviewOutput` | final_review | overall_quality, completed_summary |

### `SudoCompiler` (`compiler.py`)

Workflow compilation and execution engine:

- **`run(input_text)`**: Single execution, returns `SudoRunReport`
- **`run_all_paths(workflow, input_text)`**: Auto-detects all categories in the classify node and runs each path
- **`validate(workflow, input_text)`**: Quick pass/fail verification

### `SudoRunReport` (`report.py`)

Execution result report:

- Node execution order and duration
- Routing decisions (conditional edge choices)
- Final state snapshot
- LLM call log
- `.summary()` — human-readable text report
- `.to_json()` — JSON serialization

### `runner.py` (CLI)

Command-line execution tool:

```bash
# Single workflow run
python -m service.workflow.compiler.runner -w template-autonomous

# Auto-test all paths (easy/medium/hard)
python -m service.workflow.compiler.runner -w template-autonomous --all-paths

# Force hard path
python -m service.workflow.compiler.runner -w template-autonomous -o classify=hard

# Validate all workflows
python -m service.workflow.compiler.runner --validate

# JSON output
python -m service.workflow.compiler.runner -w template-simple --json

# List available workflows
python -m service.workflow.compiler.runner --list
```

## Usage Example

### Python API

```python
from service.workflow.compiler import SudoCompiler
from service.workflow.workflow_model import WorkflowDefinition
```

## Related Files

| File | Description |
|------|-------------|
| `service/workflow/compiler/model.py` | SudoModel mock LLM implementation |
| `service/workflow/compiler/compiler.py` | SudoCompiler main class |
| `service/workflow/compiler/report.py` | SudoRunReport result structure |
| `service/workflow/compiler/runner.py` | CLI runner script |
| `service/workflow/workflow_executor.py` | Real workflow executor (used by SudoCompiler internally) |
