# Tool Search Architecture

Dynamic tool discovery and execution for Geny agents, inspired by [graph-tool-call](https://github.com/SonAIengine/graph-tool-call).

## Problem

The traditional approach passes **all** MCP and built-in tool schemas directly into the agent's context window. This creates several issues:

- **Context window waste** — hundreds of tool schemas consume tokens before the agent even starts working
- **Decision paralysis** — too many options degrade tool selection quality
- **Scaling ceiling** — adding more MCP servers linearly increases prompt size

## Solution: Deferred Tool Pattern

Instead of receiving all tool definitions upfront, agents receive only **5 discovery/execution tools** and use them to find, inspect, and execute the tools they actually need.

```
Traditional:  Agent receives [Tool_1, Tool_2, ... Tool_N] → picks one → calls it

Tool Search:  Agent receives [tool_search, tool_schema, tool_execute, tool_browse, tool_workflow]
              → searches for what it needs → gets schema → executes via proxy
```

## Architecture

### Components

```
MCPLoader (startup)
  ├── loads MCP servers from mcp/ folder
  ├── loads built-in tools from tools/ folder
  ├── populates ToolRegistry with all tools
  │     │
  │     ├── ToolGraph (graph-tool-call)               ← optional, graph-based retrieval
  │     │     BM25 + graph traversal + embeddings
  │     │
  │     └── Keyword fallback                          ← always available
  │           word overlap + name bonus scoring
  │
  └── populates ToolExecutor with all tools           ← NEW (Phase 2)
        │
        ├── Built-in tools → direct Python execution
        │     calls tool.run() / tool.arun() directly
        │
        └── MCP server tools → JSON-RPC over stdio
              lazy-connects on first tool_execute call

Agent Session (tool_search_mode=True)
  ├── ToolPolicyEngine(TOOL_SEARCH profile)
  │     only allows _builtin_tools server
  │     only allows tool_search/tool_schema/tool_execute/tool_browse/tool_workflow
  │
  ├── .mcp.json → only _builtin_tools
  │
  ├── Per-session allowed_tools filter (ContextVar)
  │     restricts which tools are visible/executable per session
  │
  ├── System prompt → includes "Tool Discovery & Execution Mode" instructions
  │
  └── LangGraph workflow → tool-search-simple or tool-search-autonomous template
        includes ToolDiscoveryPostNode (tracks discoveries in state)
        includes ToolDiscoverySummaryNode (injects context for follow-up turns)
```

### Discovery & Execution Tools

| Tool | Purpose |
|------|---------|
| `tool_search(query)` | Natural language search. "read a file" → returns `read_file`, `write_file`, etc. |
| `tool_schema(tool_name)` | Full parameter schema with types, required fields, descriptions. |
| `tool_execute(tool_name, parameters)` | **Execute** a discovered tool via the proxy engine. |
| `tool_browse()` | Browse all tools organized by server/category. |
| `tool_workflow(tool_name)` | Recommended execution sequence (e.g., git_status → git_commit → git_push). |

### Agent Workflow

```
1. Agent receives task: "Fix the bug in utils.py"
2. Agent calls: tool_search("read a file")
   → gets: [read_file, write_file, list_directory]
3. Agent calls: tool_schema("read_file")
   → gets: {path: string (required)}
4. Agent calls: tool_execute("read_file", {"path": "utils.py"})
   → returns: file contents
5. Agent analyzes the code and continues...
```

### ToolRegistry

Central index of all available tools (`backend/service/tool_registry/registry.py`).

- **Registration**: `register_mcp_tools(server, tools)` and `register_builtin_tools(tools)` called at startup by MCPLoader
- **Search**: Uses graph-tool-call's `ToolGraph.retrieve()` for hybrid BM25 + graph retrieval, falls back to keyword matching
- **Schema**: `get_tool_schema(name)` returns full parameter definition
- **Browse**: `browse_categories()` groups tools by server
- **Workflow**: `get_workflow(name)` follows PRECEDES edges in the tool graph
- **Singleton**: accessed via `get_tool_registry()`

### ToolExecutor (Phase 2)

Proxy execution engine for all tools (`backend/service/tool_executor/executor.py`).

- **Built-in tools**: Calls `tool.run()` / `tool.arun()` directly on Python tool objects loaded by MCPLoader
- **MCP server tools**: JSON-RPC over stdio via `MCPStdioClient` — lazy-connects on first call
- **Per-session filtering**: ContextVar (`session_allowed_tools`) restricts which tools are visible/executable
- **Singleton**: accessed via `get_tool_executor()`

### Per-Session Tool Filtering

When a session has `allowed_tools` configured (from tool preset or API request), a `ContextVar` restricts visibility:

```python
# Set before graph invocation (in AgentSession.invoke)
token = set_session_allowed_tools(["read_file", "write_file"])

# Inside tool_search/tool_execute:
allowed = get_session_allowed_tools()  # ["read_file", "write_file"]
# tool_search only returns these tools
# tool_execute only allows calling these tools

# Clear after invocation
clear_session_allowed_tools(token)
```

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
    allowed_tools=["read_file", "write_file", "git_commit"],  # optional filter
)
```

When `tool_search_mode=False` (the default), everything works exactly as before — all tools are passed directly.

### Per-Session Tool Filtering

```python
# Session A: only 3 tools available
request_a = CreateSessionRequest(
    tool_search_mode=True,
    allowed_tools=["read_file", "write_file", "list_dir"],
)
# Agent A can only search/execute these 3 tools

# Session B: all tools available
request_b = CreateSessionRequest(
    tool_search_mode=True,
    # no allowed_tools → unrestricted
)
# Agent B can search/execute any tool in the registry
```

### Graceful Degradation

The `graph-tool-call` library is optional. When not installed:
- `ToolRegistry` falls back to keyword-based search (word overlap + name bonus scoring)
- All other functionality (schema retrieval, browse, workflow templates) works unchanged
- No runtime errors — the import is wrapped in a try/except

## Files

### Phase 1 Files (Discovery)
| File | Purpose |
|------|---------|
| `service/tool_registry/__init__.py` | Package exports |
| `service/tool_registry/registry.py` | ToolRegistry + ToolEntry |
| `tools/tool_search_tools.py` | 5 agent-facing discovery/execution tools |
| `service/workflow/nodes/tool_discovery_nodes.py` | ToolDiscoveryPostNode + ToolDiscoverySummaryNode |

### Phase 2 Files (Execution + Filtering)
| File | Purpose |
|------|---------|
| `service/tool_executor/__init__.py` | Package exports |
| `service/tool_executor/executor.py` | ToolExecutor — proxy execution engine |
| `service/tool_executor/mcp_client.py` | MCPStdioClient — lightweight JSON-RPC client |
| `service/tool_executor/context.py` | Per-session ContextVar for allowed_tools filtering |

### Modified Files
| File | Change |
|------|--------|
| `pyproject.toml` | Added `graph-tool-call>=0.9.0` dependency |
| `service/mcp_loader.py` | Added `_populate_tool_registry()` + `_populate_tool_executor()` steps |
| `service/claude_manager/models.py` | `tool_search_mode` field on request/session models |
| `service/tool_policy/policy.py` | `TOOL_SEARCH` profile with `tool_execute` in allowed set |
| `service/prompt/sections.py` | `tool_search_instructions()` with tool_execute instructions |
| `service/langgraph/state.py` | `DiscoveredTool`, `tool_search_mode`, `discovered_tools` in state |
| `service/langgraph/agent_session.py` | `session_allowed_tools`, ContextVar set/clear in invoke/astream |
| `service/langgraph/agent_session_manager.py` | Passes allowed_tools to AgentSession |
| `service/workflow/nodes/__init__.py` | Auto-register tool_discovery_nodes |
| `service/workflow/templates.py` | `tool-search-simple` and `tool-search-autonomous` templates |
| `docs/TOOL_SEARCH.md` | This document |

## Testing

Run integration tests:

```bash
cd backend
python3 -c "
from service.tool_executor import get_tool_executor, reset_tool_executor
from service.tool_executor.context import set_session_allowed_tools, clear_session_allowed_tools
from service.tool_registry import get_tool_registry
from service.tool_registry.registry import reset_tool_registry

# Setup registry
reset_tool_registry()
registry = get_tool_registry()
registry.register_mcp_tools('filesystem', [
    {'name': 'read_file', 'description': 'Read a file', 'inputSchema': {}},
])
registry.finalize()

# Setup executor
reset_tool_executor()
executor = get_tool_executor()

class MockTool:
    name = 'read_file'
    description = 'Read a file'
    def run(self, path=''):
        return f'Contents of {path}'

executor.register_builtin_tools([MockTool()])
executor.finalize()

# Test search + execute
from tools.tool_search_tools import ToolSearchTool, ToolExecuteTool
search = ToolSearchTool()
print(search.run('read a file'))

exec_tool = ToolExecuteTool()
print(exec_tool.run('read_file', {'path': 'test.py'}))

# Test per-session filtering
token = set_session_allowed_tools(['read_file'])
print(exec_tool.run('read_file', {'path': 'ok.py'}))  # allowed
print(exec_tool.run('write_file', {}))                  # blocked
clear_session_allowed_tools(token)
"
```

Full test suite: 46 Phase 2 tests + 11 Phase 1 backward compat tests = **57 tests, 0 failures**.
