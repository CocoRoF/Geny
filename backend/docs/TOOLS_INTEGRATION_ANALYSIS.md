# GenY Tools Integration Deep Analysis Report (v4)

> **Purpose**: Architecture analysis for systematically integrating Tools functionality (built-in / custom classification, Tool Preset, per-Session Tool assignment) into the Agent execution system
>
> **Core Principles**:
> - Claude CLI is maintained. LLM call paths are not changed.
> - **Actual execution** of all Python-defined tools occurs in the main process (FastAPI).
> - MCP is used only as a **communication protocol** between Claude CLI and tools. Tool execution itself is performed directly by the main process, not the MCP subprocess.

---

## 0. Core Problem Analysis — Why the Current Structure Is Wrong

### 0.1 Current Tool Execution Path

```
LangGraph Node
  └─ _resilient_invoke(messages)
      └─ ClaudeCLIChatModel.ainvoke()
          └─ ClaudeProcess.execute(prompt)
              └─ Claude CLI (node.exe → cli.js)     ← Maintained (no changes)
                  └─ Read .mcp.json
                      └─ _builtin_tools MCP server (Python subprocess #2)
                          └─ geny_tools.py execution     ← ❌ Problem occurs here
                          └─ browser_tools.py execution
                          └─ web_search_tools.py execution
```

### 0.2 Fundamental Problems

**Problem 1: Singleton Access Failure Due to Process Isolation**

```
Python Process #1 (FastAPI main)
  ├─ AgentSessionManager (singleton)     ← Target geny_tools needs to access
  ├─ ChatStore (singleton)
  └─ ClaudeProcess.execute()
       └─ Claude CLI (Node.js subprocess)
           └─ _builtin_tools (Python Process #2)   ← Separate process!
               └─ geny_tools._get_agent_manager()
                   → Returns independent instance from Process #2  ← ❌ Not Process #1's singleton!
```

`_mcp_server.py` runs as a separate Python subprocess.
When `_get_agent_manager()` is called from this process,
it returns an independent instance of the MCP process itself, not the main FastAPI process singleton.
**In other words, geny_tools currently does not function properly.**

**Problem 2: All Tools Mixed in a Single MCP Server**

```
_builtin_tools MCP server:
  ├─ geny_session_list    (GenY platform control — built-in)
  ├─ geny_send_message    (GenY platform control — built-in)
  ├─ web_search           (general-purpose tool — custom)
  ├─ browser_navigate     (general-purpose tool — custom)
  └─ ... (all in one server without distinction)
```

- No distinction between built-in and custom
- Per-session tool selection/restriction impossible (all-or-nothing)
- ToolPolicyEngine exists but is not actually applied

### 0.3 Claude CLI Constraints

Claude CLI calls tools **exclusively through the MCP protocol**.
This is an immutable constraint.

- Tool calls happen inside the CLI black box
- `tool_use` events are output via stream-json after execution
- Python cannot intervene during execution
- Only loop count can be controlled via `--max-turns`

**Therefore**: Maintain the MCP "protocol" but change the MCP server's **execution method**.

---

## 1. Solution Architecture — Proxy MCP Pattern

### 1.1 Core Idea

```
Current:  MCP server (subprocess) executes tools directly → singleton access failure
Solution: MCP server (subprocess) acts as thin proxy only
          Actual execution routed to main FastAPI process → singleton access works correctly
```

The MCP server subprocess **does not execute tools**.
It receives tool call requests from Claude CLI,
forwards them to the main FastAPI process via HTTP,
and returns the results from the main process back to Claude CLI.

### 1.2 New Tool Execution Path

```
LangGraph Node
  └─ _resilient_invoke(messages)
      └─ ClaudeCLIChatModel.ainvoke()
          └─ ClaudeProcess.execute(prompt)
              └─ Claude CLI (node.exe)               ← No changes
                  └─ Read .mcp.json
                      │
                      ├─ _python_tools MCP server (Proxy — thin subprocess)
                      │   └─ Receive tool_call (MCP protocol)
                      │       └─ HTTP POST → localhost:PORT/internal/tools/execute
                      │           └─ Executed in FastAPI main process!
                      │               ├─ geny_tools → _get_agent_manager() ✅ Works!
                      │               ├─ browser_tools → Playwright ✅
                      │               ├─ web_search_tools → DuckDuckGo ✅
                      │               └─ web_fetch_tools → httpx ✅
                      │           └─ Return result → MCP response → Claude CLI
                      │
                      ├─ github (external MCP — existing method maintained)
                      └─ filesystem (external MCP — existing method maintained)
```

### 1.3 Why This Architecture Is Correct

| Property | Current (Wrong) | Proxy MCP (Correct) |
|----------|----------------|---------------------|
| **geny_tools singleton** | ❌ Independent instance in separate process | ✅ Actual singleton in main process |
| **Claude CLI compatibility** | ✅ MCP protocol | ✅ MCP protocol (same) |
| **Tool execution location** | MCP subprocess (Process #2) | FastAPI main (Process #1) |
| **IPC overhead** | stdio (MCP protocol) | stdio + localhost HTTP (negligible) |
| **Tool filtering** | Impossible (single server) | ✅ Proxy registers only allowed tools |
| **Unified logging** | Distributed (two processes) | ✅ Unified in main process |

### 1.4 Proxy MCP Server Structure

```python
# tools/_proxy_mcp_server.py (auto-generated)
#
# Role: Thin proxy between Claude CLI ↔ FastAPI main process
# Execution: Spawned by Claude CLI as MCP server (stdio communication)
# Behavior:
#   1. On startup: Import tool modules → extract schemas (preserve function signatures)
#   2. On tool call: Forward via HTTP POST to main process → return result

import sys
import asyncio
import functools
import httpx
from pathlib import Path
from mcp.server.fastmcp import FastMCP

BACKEND_URL = sys.argv[1]   # e.g., "http://localhost:8000"
SESSION_ID = sys.argv[2]    # Session identifier
ALLOWED_TOOLS = sys.argv[3].split(",") if len(sys.argv) > 3 else None

mcp = FastMCP("python-tools")

def _register_proxy_tool(tool_obj, mcp_server, backend_url, session_id):
    """Take schema from original tool, proxy execution to main process."""
    name = getattr(tool_obj, 'name', None)
    if not name:
        return

    description = getattr(tool_obj, 'description', '') or f"Tool: {name}"

    # Preserve original function's signature (for FastMCP to generate correct input_schema)
    source_fn = tool_obj.run if hasattr(tool_obj, 'run') else tool_obj

    @functools.wraps(source_fn)
    async def proxy_fn(*args, **kwargs):
        """Proxy tool execution to main process."""
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{backend_url}/internal/tools/execute",
                json={
                    "tool_name": name,
                    "args": kwargs,
                    "session_id": session_id,
                },
            )
            data = resp.json()
            if data.get("error"):
                return f"Error: {data['error']}"
            return data.get("result", "")

    proxy_fn.__name__ = name
    proxy_fn.__doc__ = f"{description}"
    mcp_server.tool(name=name, description=description)(proxy_fn)


# Import tool modules → extract schemas (no execution)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.built_in.geny_tools import TOOLS as builtin
from tools.custom.browser_tools import TOOLS as browser
from tools.custom.web_search_tools import TOOLS as web_search
from tools.custom.web_fetch_tools import TOOLS as web_fetch

all_tools = [*builtin, *browser, *web_search, *web_fetch]

for tool_obj in all_tools:
    tool_name = getattr(tool_obj, 'name', '')
    if ALLOWED_TOOLS and tool_name not in ALLOWED_TOOLS:
        continue  # Skip tools not in Preset
    _register_proxy_tool(tool_obj, mcp, BACKEND_URL, SESSION_ID)

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Key Design Points:**

1. **`@functools.wraps(source_fn)`**: Copies `__wrapped__`, `__annotations__`, etc. from the original function. When FastMCP calls `inspect.signature()`, it extracts the exact parameter schema from the original function. Delivers correct `input_schema` to Claude.

2. **Execution proxy**: `proxy_fn` does not execute any tools directly. It sends an `httpx.post()` request to the main process's `/internal/tools/execute` endpoint. The main process executes the same Python function **in the same process**.

3. **Tool filtering**: Preset-based filtering via `ALLOWED_TOOLS` argument. Tools not allowed are not registered with MCP, so they are invisible to Claude. Built-in tools are always included in `ALLOWED_TOOLS`.

### 1.5 Main Process — Internal Tool Execution Endpoint

```python
# controller/internal_tool_controller.py (new)
# Internal only — called exclusively by Proxy MCP server

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/internal/tools", tags=["internal"])

class ToolExecuteRequest(BaseModel):
    tool_name: str
    args: dict
    session_id: str

class ToolExecuteResponse(BaseModel):
    result: Optional[str] = None
    error: Optional[str] = None

@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(req: ToolExecuteRequest, request: Request):
    """Handle tool execution requests from Proxy MCP server.

    Executes Python tools directly in the main process.
    Same process ensures singleton access, DB connections, etc. all work correctly.
    """
    tool_loader: ToolLoader = request.app.state.tool_loader

    tool = tool_loader.get_tool(req.tool_name)
    if not tool:
        return ToolExecuteResponse(error=f"Unknown tool: {req.tool_name}")

    try:
        if asyncio.iscoroutinefunction(tool.run):
            result = await tool.run(**req.args)
        else:
            result = tool.run(**req.args)
        return ToolExecuteResponse(result=str(result))
    except Exception as e:
        logger.error(f"Tool execution error [{req.tool_name}]: {e}")
        return ToolExecuteResponse(error=str(e))


@router.get("/schemas")
async def get_tool_schemas(request: Request, names: Optional[str] = None):
    """Return available tool schemas (called during Proxy server startup)."""
    tool_loader: ToolLoader = request.app.state.tool_loader
    tools = tool_loader.get_all_tools()

    if names:
        allowed = set(names.split(","))
        tools = {k: v for k, v in tools.items() if k in allowed}

    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters or {},
        }
        for t in tools.values()
    ]
```

### 1.6 ToolLoader — Tool Loading and Management

```python
# service/tool_loader.py (new)
# Loads and manages all Python tools in the main process

class ToolLoader:
    """Python tool loader — scans tools/built_in/, tools/custom/.

    Loaded once in the main process,
    executed directly on /internal/tools/execute requests.
    """

    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir
        self.builtin_tools: Dict[str, BaseTool] = {}  # Always active
        self.custom_tools: Dict[str, BaseTool] = {}    # Controlled by Preset

    def load_all(self):
        """Load all Python tools."""
        self._load_from_dir(self.tools_dir / "built_in", self.builtin_tools)
        self._load_from_dir(self.tools_dir / "custom", self.custom_tools)

    def _load_from_dir(self, dir_path: Path, target: Dict):
        for tool_file in dir_path.glob("*_tools.py"):
            tools = self._load_from_file(tool_file)
            for t in tools:
                target[t.name] = t

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self.builtin_tools.get(name) or self.custom_tools.get(name)

    def get_all_tools(self) -> Dict[str, BaseTool]:
        return {**self.builtin_tools, **self.custom_tools}

    def get_builtin_names(self) -> List[str]:
        return list(self.builtin_tools.keys())

    def get_custom_names(self) -> List[str]:
        return list(self.custom_tools.keys())

    def get_allowed_tools_for_preset(
        self, preset: ToolPresetDefinition
    ) -> List[str]:
        """Return allowed tool name list based on Preset. Built-in always included."""
        allowed = list(self.builtin_tools.keys())  # Built-in always included

        if "*" in preset.custom_tools:
            allowed.extend(self.custom_tools.keys())
        else:
            for name in preset.custom_tools:
                if name in self.custom_tools:
                    allowed.append(name)

        return allowed
```

---

## 2. Current System Analysis (AS-IS)

### 2.1 Current Tools Structure

```
backend/tools/
├── __init__.py              # BaseTool, ToolWrapper, @tool decorator export
├── base.py                  # Tool definition framework (abstract class + decorator)
├── _mcp_server.py           # Auto-generated — FastMCP wrapper (all tools in one MCP server)  ⛔ Removal target
├── browser_tools.py         # Playwright-based browser automation (7 tools)
├── geny_tools.py            # GenY platform control tools (11 tools)
├── web_fetch_tools.py       # HTTP-based web page fetching (2 tools)
├── web_search_tools.py      # DuckDuckGo search (2 tools)
└── README.md
```

### 2.2 Current MCP Loading Pipeline

```
MCPLoader.load_all()
  ├─ (1) _load_mcp_configs()        → mcp/*.json → register external MCP servers
  ├─ (2) _load_tools()              → tools/*_tools.py → collect all tools
  └─ (3) _register_tools_as_mcp()   → all → auto-generate _mcp_server.py → "_builtin_tools" server
                                       ⛔ This step is the problem
```

### 2.3 Current Session Creation Flow

```
POST /api/agents
  └─ AgentSessionManager.create_agent_session()
      ├─ merge_mcp_configs(global_mcp, request.mcp_config)
      ├─ build_agent_prompt(role, mcp_servers, tools, ...)
      ├─ AgentSession.create() → Create ClaudeProcess
      │   └─ _create_mcp_config() → Generate .mcp.json
      │       └─ Start Claude CLI
      └─ ※ No tool_preset applied
```

### 2.4 Workflow Preset Pattern (Reference Model for Tool Preset)

```
backend/service/workflow/
├── workflow_model.py       # WorkflowDefinition (Pydantic)
├── workflow_store.py       # JSON file CRUD (singleton)
├── templates.py            # Factory + install_templates()
└── workflow_executor.py    # Compile + execute
```

Pattern: Pydantic model → JSON Store → factory templates → REST API → CRUD + clone

---

## 3. Target System Design (TO-BE)

### 3.1 Core Requirements

| # | Requirement | Solution |
|---|------------|----------|
| R1 | Maintain Claude CLI | ✅ No changes. MCP protocol used as-is |
| R2 | All Python tools run in main process | ✅ Proxy MCP → HTTP → main process |
| R3 | Built-in / Custom classification | ✅ Directory separation + ToolLoader |
| R4 | Built-in always active | ✅ Always included in ALLOWED_TOOLS regardless of Preset |
| R5 | Tool Preset | ✅ Replicate Workflow Preset pattern |
| R6 | Per-session Tool assignment | ✅ Preset → ALLOWED_TOOLS → Proxy registers only allowed tools |
| R7 | Block unauthorized tools | ✅ Proxy doesn't register → invisible to Claude |

### 3.2 New Tools Directory Structure

```
backend/tools/
├── __init__.py                    # BaseTool, @tool decorator export (existing, maintained)
├── base.py                        # Tool definition framework (no changes)
├── _proxy_mcp_server.py           # ⭐ New — Proxy MCP server (auto-generated)
│
├── built_in/                      # GenY platform self-control (always active)
│   ├── __init__.py
│   └── geny_tools.py              # 11 tools (moved from existing geny_tools.py)
│
└── custom/                        # General-purpose tools (controlled by Preset)
    ├── __init__.py
    ├── browser_tools.py           # 7 tools (moved from existing)
    ├── web_search_tools.py        # 2 tools (moved from existing)
    └── web_fetch_tools.py         # 2 tools (moved from existing)
```

**Logical Classification:**
- `built_in/`: Tools that control the GenY platform itself. **Platform-level** actions like creating Agents or sending messages. Always available in every Session.
- `custom/`: General-purpose tools that interact with the outside world. **Task-level** actions like web search, browser, HTTP. Controlled by Tool Preset.

**Execution layer is identical:** Both use Proxy MCP → HTTP → direct execution in the main process.
The only difference is **logical classification** (built-in always included in Preset, custom is selectable).

### 3.3 Full Execution Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Main Process                      │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ ToolLoader (app.state.tool_loader)                   │    │
│  │  ├─ builtin_tools:                                   │    │
│  │  │   ├─ geny_session_list → GenySessionListTool()   │    │
│  │  │   ├─ geny_send_message → GenySendRoomMsgTool()   │    │
│  │  │   └─ ... (11 tools)                               │    │
│  │  └─ custom_tools:                                    │    │
│  │      ├─ web_search → WebSearchTool()                 │    │
│  │      ├─ browser_navigate → BrowserNavigateTool()     │    │
│  │      └─ ... (11 tools)                               │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                     │
│  ┌──────────────────────┼──────────────────────────────┐     │
│  │ POST /internal/tools/execute                        │     │
│  │  ├─ tool_name: "geny_send_message"                  │     │
│  │  ├─ args: {room_id: "...", content: "..."}          │     │
│  │  └─ → tool_loader.get_tool("geny_send_message")    │     │
│  │      → await tool.run(**args)   ← Same process!      │     │
│  │      → _get_agent_manager() → ✅ Correct singleton!  │     │
│  │      → Return result                                 │     │
│  └─────────────────────────────────────────────────────┘     │
│                         ▲                                     │
│              HTTP (localhost)                                  │
│                         │                                     │
│  ┌──────────────────────┴──────────────────────────────┐     │
│  │ AgentSessionManager.create_agent_session()          │     │
│  │  ├─ preset = tool_preset_store.load(preset_id)      │     │
│  │  ├─ allowed = tool_loader.get_allowed(preset)       │     │
│  │  ├─ Generate .mcp.json:                             │     │
│  │  │   ├─ _python_tools: Proxy MCP (allowed only)     │     │
│  │  │   ├─ github: External MCP (per preset)           │     │
│  │  │   └─ filesystem: External MCP (per preset)       │     │
│  │  └─ ClaudeProcess.execute()                         │     │
│  │      └─ Claude CLI                                  │     │
│  │          └─ _python_tools MCP (Proxy subprocess)    │     │
│  │              └─ HTTP POST → /internal/tools/execute │     │
│  └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 .mcp.json Generation Example

```json
{
  "mcpServers": {
    "_python_tools": {
      "command": "python",
      "args": [
        "tools/_proxy_mcp_server.py",
        "http://localhost:8000",
        "session-abc-123",
        "geny_session_list,geny_send_message,geny_room_create,web_search,web_fetch"
      ]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-github"],
      "env": { "GITHUB_TOKEN": "..." }
    }
  }
}
```

- `_python_tools`: Proxy MCP server. 3rd argument is the allowed tool list.
  When Claude CLI connects to this server, only allowed tool schemas are visible.
- `github`: External MCP server. Maintained as-is.

---

## 4. Tool Preset System

### 4.1 Data Model

```python
# service/tool_preset/models.py

class ToolPresetDefinition(BaseModel):
    """Tool Preset definition — same pattern as WorkflowDefinition"""
    id: str                     # UUID or "template-xxx"
    name: str                   # "Web Research"
    description: str            # Description
    icon: Optional[str] = None

    # Custom tool name list to include (built-in always included, no need to specify)
    custom_tools: List[str] = []    # ["web_search", "browser_navigate", ...]
                                     # ["*"] → all custom tools

    # External MCP server name list to include
    mcp_servers: List[str] = []     # ["github", "filesystem"]
                                     # ["*"] → all external MCP

    # Metadata
    created_at: str
    updated_at: str
    is_template: bool = False       # True → read-only, clone only
    template_name: Optional[str] = None
```

### 4.2 Store (WorkflowStore Pattern)

```python
# service/tool_preset/store.py

class ToolPresetStore:
    """JSON file-based Tool Preset CRUD. Same pattern as WorkflowStore."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, preset: ToolPresetDefinition) -> None: ...
    def load(self, preset_id: str) -> Optional[ToolPresetDefinition]: ...
    def delete(self, preset_id: str) -> bool: ...
    def list_all(self) -> List[ToolPresetDefinition]: ...
    def list_templates(self) -> List[ToolPresetDefinition]: ...
    def list_user_presets(self) -> List[ToolPresetDefinition]: ...
    def exists(self, preset_id: str) -> bool: ...
    def clone(self, preset_id: str, new_name: str) -> ToolPresetDefinition: ...
```

### 4.3 Default Preset Templates

```python
# service/tool_preset/templates.py

def create_minimal_preset() -> ToolPresetDefinition:
    """Built-in only (no custom, no external MCP)"""
    return ToolPresetDefinition(
        id="template-minimal",
        name="Minimal",
        description="GenY platform tools only",
        custom_tools=[],
        mcp_servers=[],
        is_template=True,
        template_name="minimal",
    )

def create_web_research_preset() -> ToolPresetDefinition:
    """Web research focused"""
    return ToolPresetDefinition(
        id="template-web-research",
        name="Web Research",
        description="Web search, page fetching, browser automation",
        custom_tools=[
            "web_search", "news_search",
            "web_fetch", "web_fetch_multiple",
            "browser_navigate", "browser_click", "browser_fill",
            "browser_screenshot", "browser_evaluate",
            "browser_get_page_info", "browser_close",
        ],
        mcp_servers=[],
        is_template=True,
        template_name="web-research",
    )

def create_full_development_preset() -> ToolPresetDefinition:
    """Development work — all custom + development MCP"""
    return ToolPresetDefinition(
        id="template-full-development",
        name="Full Development",
        description="All custom tools + development-related MCP servers",
        custom_tools=["*"],
        mcp_servers=["filesystem", "github", "git"],
        is_template=True,
        template_name="full-development",
    )

def create_all_tools_preset() -> ToolPresetDefinition:
    """Everything active"""
    return ToolPresetDefinition(
        id="template-all-tools",
        name="All Tools",
        description="All custom tools and MCP servers enabled",
        custom_tools=["*"],
        mcp_servers=["*"],
        is_template=True,
        template_name="all-tools",
    )

def install_templates(store: ToolPresetStore) -> None:
    for factory in [create_minimal_preset, create_web_research_preset,
                    create_full_development_preset, create_all_tools_preset]:
        preset = factory()
        if not store.exists(preset.id):
            store.save(preset)
```

### 4.4 ToolRegistry — Tool Catalog

```python
# service/tool_preset/registry.py

class ToolInfo(BaseModel):
    """Individual tool metadata"""
    name: str               # "web_search"
    display_name: str        # "Web Search"
    description: str         # "Search the web..."
    category: str            # "built_in" | "custom"
    group: str               # File-based group name

class ToolRegistry:
    """Catalog of all currently loaded tools. For frontend UI."""

    def __init__(self, tool_loader: ToolLoader, mcp_loader: MCPLoader):
        self._tool_loader = tool_loader
        self._mcp_loader = mcp_loader

    def get_all_tools(self) -> List[ToolInfo]: ...
    def get_builtin_tools(self) -> List[ToolInfo]: ...
    def get_custom_tools(self) -> List[ToolInfo]: ...
    def get_mcp_servers(self) -> List[dict]: ...
```

---

## 5. Session Creation Integration Flow

### 5.1 CreateSessionRequest Extension

```python
# models.py

class CreateSessionRequest(BaseModel):
    # ... existing fields ...
    tool_preset_id: Optional[str] = Field(
        default=None,
        description="Tool Preset ID. None defaults to role-based preset"
    )
```

### 5.2 Default Preset Mapping

```python
ROLE_DEFAULT_PRESET = {
    "worker":     "template-all-tools",
    "developer":  "template-full-development",
    "researcher": "template-web-research",
    "planner":    "template-all-tools",
}
```

### 5.3 Tool Configuration Flow During Session Creation

```
AgentSessionManager.create_agent_session(request)
  │
  ├─ (1) Determine Preset
  │      preset_id = request.tool_preset_id or ROLE_DEFAULT_PRESET[role]
  │      preset = tool_preset_store.load(preset_id)
  │
  ├─ (2) Determine Python tool list
  │      allowed_tools = tool_loader.get_allowed_tools_for_preset(preset)
  │      → all built-in + custom based on preset.custom_tools
  │      → e.g.: ["geny_session_list", ..., "web_search", "web_fetch"]
  │
  ├─ (3) Filter external MCP servers
  │      if "*" in preset.mcp_servers:
  │          mcp_servers = global_mcp_config.servers  # all
  │      else:
  │          mcp_servers = {name: cfg for name, cfg in global_mcp_config
  │                         if name in preset.mcp_servers}
  │
  ├─ (4) Add _python_tools Proxy MCP server
  │      mcp_servers["_python_tools"] = MCPServerStdio(
  │          command=sys.executable,
  │          args=[
  │              "tools/_proxy_mcp_server.py",
  │              f"http://localhost:{port}",
  │              session_id,
  │              ",".join(allowed_tools),   ← Preset-based filtering
  │          ],
  │      )
  │
  ├─ (5) Assemble MCPConfig → generate .mcp.json
  │      merged_config = MCPConfig(servers=mcp_servers)
  │      → ClaudeProcess._create_mcp_config()
  │
  └─ (6) ClaudeProcess.execute() → Start Claude CLI
         → Claude recognizes only allowed tools from _python_tools
         → Tool call → Proxy MCP → HTTP → main process execution
```

---

## 6. REST API Design

### 6.1 Tool Preset API

```
/api/tool-presets/
├── GET    /                     # List all presets
├── POST   /                     # Create new preset
├── GET    /{id}                 # Preset details
├── PUT    /{id}                 # Update preset (templates not allowed)
├── DELETE /{id}                 # Delete preset (templates not allowed)
├── POST   /{id}/clone           # Clone preset
└── GET    /templates            # List templates only
```

### 6.2 Tool Catalog API

```
/api/tools/
├── GET    /catalog              # All tools (built-in + custom + MCP)
├── GET    /catalog/built-in     # Built-in only
├── GET    /catalog/custom       # Custom only
└── GET    /catalog/mcp-servers  # External MCP server list
```
