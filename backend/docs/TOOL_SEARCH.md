# Tool Search Architecture

Dynamic tool discovery for Geny agents, inspired by [graph-tool-call](https://github.com/SonAIengine/graph-tool-call).

## Problem

The traditional approach passes **all** MCP and built-in tool schemas directly into the agent's context window. This creates several issues:

- **Context window waste** — hundreds of tool schemas consume tokens before the agent even starts working
- **Decision paralysis** — too many options degrade tool selection quality
- **Scaling ceiling** — adding more MCP servers linearly increases prompt size

## Solution: Deferred Tool Pattern

Instead of receiving all tool definitions upfront, agents receive only **4 discovery tools** and use them to find, inspect, and then call the tools they actually need.

```
Traditional:  Agent receives [Tool_1, Tool_2, ... Tool_N] → picks one → calls it

Tool Search:  Agent receives [tool_search, tool_schema, tool_browse, tool_workflow]
              → searches for what it needs → gets schema → calls the discovered tool
```

## Architecture

### Components

```
MCPLoader (startup)
  ├── loads MCP servers from mcp/ folder
  ├── loads built-in tools from tools/ folder
  └── populates ToolRegistry with all tools          ← NEW
        │
        ├── ToolGraph (graph-tool-call)               ← optional, graph-based retrieval
        │     BM25 + graph traversal + embeddings
        │
        └── Keyword fallback                          ← always available
              word overlap + name bonus scoring

Agent Session (tool_search_mode=True)
  ├── ToolPolicyEngine(TOOL_SEARCH profile)
  │     only allows _builtin_tools server
  │     only allows tool_search/tool_schema/tool_browse/tool_workflow
  │
  ├── .mcp.json → only _builtin_tools
  │
  ├── System prompt → includes "Tool Discovery Mode" instructions
  │
  └── LangGraph workflow → tool-search-simple or tool-search-autonomous template
        includes ToolDiscoveryPostNode (tracks discoveries in state)
        includes ToolDiscoverySummaryNode (injects context for follow-up turns)
```

### Discovery Tools

| Tool | Purpose |
|------|---------|
| `tool_search(query)` | Natural language search. "read a file" → returns `read_file`, `write_file`, etc. |
| `tool_schema(tool_name)` | Full parameter schema with types, required fields, descriptions. |
| `tool_browse()` | Browse all tools organized by server/category. |
| `tool_workflow(tool_name)` | Recommended execution sequence (e.g., git_status → git_commit → git_push). |

### Agent Workflow

```
1. Agent receives task: "Fix the bug in utils.py"
2. Agent calls: tool_search("read a file")
   → gets: [read_file, write_file, list_directory]
3. Agent calls: tool_schema("read_file")
   → gets: {path: string (required)}
4. Agent calls: read_file(path="utils.py")
   → reads the file and proceeds with the task
```

### ToolRegistry

Central index of all available tools (`backend/service/tool_registry/registry.py`).

- **Registration**: `register_mcp_tools(server, tools)` and `register_builtin_tools(tools)` called at startup by MCPLoader
- **Search**: Uses graph-tool-call's `ToolGraph.retrieve()` for hybrid BM25 + graph retrieval, falls back to keyword matching
- **Schema**: `get_tool_schema(name)` returns full parameter definition
- **Browse**: `browse_categories()` groups tools by server
- **Workflow**: `get_workflow(name)` follows PRECEDES edges in the tool graph
- **Singleton**: accessed via `get_tool_registry()`

### Graph State

When `tool_search_mode=True`, the LangGraph state tracks discoveries:

```python
# In AutonomousState / AgentState
tool_search_mode: bool                                    # flag for discovery nodes
discovered_tools: Dict[str, DiscoveredTool]               # name → schema info
```

`ToolDiscoveryPostNode` parses agent output after each turn, extracting tool names and schemas from tool_search/tool_schema results. `ToolDiscoverySummaryNode` injects a summary of previously discovered tools before each LLM call so the agent doesn't re-search.

## Usage

### Enabling Tool Search Mode

```python
# Via API
request = CreateSessionRequest(
    tool_search_mode=True,
    role="developer",
    model="claude-sonnet-4-20250514",
)
```

When `tool_search_mode=False` (the default), everything works exactly as before — all tools are passed directly.

### Graceful Degradation

The `graph-tool-call` library is optional. When not installed:
- `ToolRegistry` falls back to keyword-based search (word overlap + name bonus scoring)
- All other functionality (schema retrieval, browse, workflow templates) works unchanged
- No runtime errors — the import is wrapped in a try/except

## Files

### New Files
| File | Purpose |
|------|---------|
| `service/tool_registry/__init__.py` | Package exports |
| `service/tool_registry/registry.py` | ToolRegistry + ToolEntry |
| `tools/tool_search_tools.py` | 4 agent-facing discovery tools |
| `service/workflow/nodes/tool_discovery_nodes.py` | ToolDiscoveryPostNode + ToolDiscoverySummaryNode |
| `docs/TOOL_SEARCH.md` | This document |

### Modified Files
| File | Change |
|------|--------|
| `pyproject.toml` | Added `graph-tool-call>=0.9.0` dependency |
| `service/mcp_loader.py` | Added `_populate_tool_registry()` step |
| `service/claude_manager/models.py` | `tool_search_mode` field on request/session models |
| `service/tool_policy/policy.py` | `TOOL_SEARCH` profile in ToolProfile enum |
| `service/prompt/sections.py` | `tool_search_instructions()` section + `tool_search_mode` param |
| `service/langgraph/state.py` | `DiscoveredTool`, `tool_search_mode`, `discovered_tools` in state |
| `service/langgraph/agent_session.py` | Template selection, state init for tool_search_mode |
| `service/langgraph/agent_session_manager.py` | TOOL_SEARCH policy override when mode active |
| `service/workflow/nodes/__init__.py` | Auto-register tool_discovery_nodes |
| `service/workflow/templates.py` | `tool-search-simple` and `tool-search-autonomous` templates |

## Testing

Run integration tests:

```bash
cd backend
python3 -c "
from service.tool_registry import get_tool_registry
from service.tool_registry.registry import reset_tool_registry, HAS_GRAPH_TOOL_CALL

reset_tool_registry()
registry = get_tool_registry()

# Register sample tools
registry.register_mcp_tools('filesystem', [
    {'name': 'read_file', 'description': 'Read a file', 'inputSchema': {}},
])
registry.finalize()

# Search
results = registry.search('read a file')
print(f'Search results: {[r.name for r in results]}')
print(f'Graph mode: {HAS_GRAPH_TOOL_CALL}')
"
```

Full test suite (66 tests): see `_shared/integration-test-results.md` in the project workspace.
