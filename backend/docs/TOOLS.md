# Tools & MCP System

> Python tool definitions → MCP proxy pattern exposed to Claude CLI → Executed in FastAPI main process

## Architecture Overview

```
Claude CLI ←stdio→ _proxy_mcp_server.py ←HTTP→ FastAPI (main.py)
                    (schema registration only)    (actual execution)
```

**Core Design**: Tools need access to singletons in the FastAPI main process such as `AgentSessionManager` and `ChatStore`. The proxy subprocess only registers MCP schemas with Claude CLI, while actual execution is delegated via `POST /internal/tools/execute`.

### Layer Structure

```
Definition Layer ─── BaseTool / ToolWrapper / @tool decorator
     │
Discovery Layer ─── ToolLoader: scans built_in/ + custom/
     │
MCP Exposure ────── _proxy_mcp_server.py: FastMCP stdio server registration
     │
Execution Layer ─── InternalToolController: execution in main process
     │
Policy Layer ────── ToolPolicyEngine: role/profile-based filtering
     │
Presets ─────────── ToolPresetDefinition: per-session tool set definition
     │
Config Layer ────── MCPLoader: external MCP JSON config loading
```

---

## BaseTool

Abstract base class for all tools.

```python
class BaseTool(ABC):
    name: str              # Unique tool name (auto-inferred from class name)
    description: str       # Description shown to Claude (inferred from docstring)
    parameters: Dict       # JSON Schema (auto-generated from run() signature)

    @abstractmethod
    def run(self, **kwargs) -> str: ...

    async def arun(self, **kwargs) -> str: ...  # Async override available
```

### Automatic Parameter Generation

JSON Schema is auto-generated from the `run()` method's signature + type hints + Google-style docstring `Args:` section:

```python
class MyTool(BaseTool):
    def run(self, query: str, limit: int = 5) -> str:
        """Search for items.

        Args:
            query: The search query string
            limit: Maximum results to return
        """
        ...
```

→ Auto-generated JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "The search query string"},
    "limit": {"type": "integer", "description": "Maximum results to return"}
  },
  "required": ["query"]
}
```

### @tool Decorator

Wraps a regular function as a tool:

```python
@tool
def my_function(param: str) -> str:
    """Description here."""
    return result

@tool(name="custom_name", description="Custom description")
def another_function(param: str) -> str: ...
```

Returns a `ToolWrapper` instance with the same interface as `BaseTool`.

---

## Built-in Tools

Always available in every session. Models the Geny platform as a virtual company (session = employee).

### Session Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `geny_session_list` | List all sessions | None |
| `geny_session_info` | Get session details | `session_id` |
| `geny_session_create` | Create new session | `session_name`, `role`, `model` |

### Chat Room Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `geny_room_list` | List all chat rooms | None |
| `geny_room_create` | Create chat room | `room_name`, `session_ids` (comma-separated) |
| `geny_room_info` | Chat room details | `room_id` |
| `geny_room_add_members` | Add members | `room_id`, `session_ids` |

### Messaging

| Tool | Description | Parameters |
|------|-------------|------------|
| `geny_send_room_message` | Send room message | `room_id`, `content`, `sender_session_id`, `sender_name` |
| `geny_send_direct_message` | Send DM | `target_session_id`, `content`, `sender_session_id`, `sender_name` |
| `geny_read_room_messages` | Read room messages | `room_id`, `limit` |
| `geny_read_inbox` | Read inbox | `session_id`, `limit`, `unread_only`, `mark_read` |

---

## Custom Tools

Controllable per session via Tool Presets.

### Browser Tools (Playwright)

Headless Chromium browser automation. `_BrowserManager` singleton maintains cookies/sessions.

| Tool | Description |
|------|-------------|
| `browser_navigate` | Navigate to URL (returns page text) |
| `browser_click` | Click CSS selector |
| `browser_fill` | Fill form field |
| `browser_screenshot` | Capture screenshot |
| `browser_evaluate` | Execute JavaScript |
| `browser_page_info` | Current page info + DOM elements |
| `browser_close` | Close browser |

### Web Search Tools (DuckDuckGo)

| Tool | Description |
|------|-------------|
| `web_search` | Web search (ddgs library) |
| `news_search` | News search |

### Web Fetch Tools (httpx)

| Tool | Description |
|------|-------------|
| `web_fetch` | Fetch URL content (HTML→text conversion) |
| `web_fetch_multiple` | Fetch multiple URLs in parallel |

---

## MCP Server Integration

### Proxy MCP Server (`_proxy_mcp_server.py`)

Lightweight stdio proxy between Claude CLI and FastAPI main process.

```bash
python _proxy_mcp_server.py <backend_url> <session_id> [allowed_tools]
```

**How it works:**
1. Load tool objects from ToolLoader
2. Extract each tool's `name`, `description`, `run()` signature
3. Register proxy functions on FastMCP (keeping schemas identical)
4. On actual call, delegate via `POST {backend_url}/internal/tools/execute` over HTTP
5. Payload: `{"tool_name": name, "args": kwargs, "session_id": session_id}`

When `ALLOWED_TOOLS` is set, only those tools are registered.

### Internal Tool Controller

HTTP execution endpoint for the proxy MCP server. Localhost only.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/internal/tools/execute` | Execute tool (`arun()` first, `run()` fallback) |
| `GET` | `/internal/tools/schemas` | Get tool schemas (optional name filter) |

---

## MCPLoader

Loads external MCP server configs from JSON files.

### Config File Format

`*.json` files in the `mcp/` directory:

```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["@modelcontextprotocol/server-filesystem", "/workspace"],
  "env": {"HOME": "${HOME}"},
  "description": "Filesystem access"
}
```

```json
{
  "type": "http",
  "url": "https://api.example.com/mcp/",
  "headers": {"Authorization": "Bearer ${API_KEY}"},
  "description": "Remote API server"
}
```

Supported types: `stdio`, `http`, `sse`

Environment variable expansion: supports `${VAR}` and `${VAR:-default}` patterns.

### Per-Session MCP Config Assembly

```python
build_session_mcp_config(
    global_config,        # External servers loaded by MCPLoader
    allowed_tools,        # Python tool names allowed by preset
    session_id,
    backend_port,
    allowed_mcp_servers,  # External MCP servers allowed by preset
    extra_mcp,            # Per-session additional MCP
)
```

Result:
1. **`_python_tools`** server: Proxy MCP (with allowed Python tool names)
2. **External MCP servers**: Filtered by `allowed_mcp_servers`
3. **Additional MCP**: Per-request overrides

---

## ToolLoader

Auto-scans `tools/built_in/` + `tools/custom/` directories.

### Discovery Mechanism

1. Glob `*_tools.py` files
2. Dynamic import via `importlib.util.spec_from_file_location()`
3. If module has `TOOLS` attribute, use it
4. Otherwise, auto-collect `BaseTool`/`ToolWrapper` instances from module

### Preset-Based Filtering

```python
get_allowed_tools_for_preset(preset: ToolPresetDefinition) -> List[str]
```

- Built-in tools: **always included**
- Custom tools: Filtered by `preset.custom_tools`
  - `["*"]` → All custom tools
  - `[]` → No custom tools
  - `["web_search", "browser_navigate"]` → Explicitly allowed

---

## Tool Policy System

Role-based MCP server access control.

### Profiles

| Profile | Allowed Servers |
|---------|----------------|
| `MINIMAL` | Built-in tool server only |
| `CODING` | + filesystem, git, github, code, lint, docker, terminal |
| `MESSAGING` | + slack, email, discord, teams, notion, jira, linear |
| `RESEARCH` | + web, search, brave, perplexity, google, bing, arxiv, wikipedia, fetch, browser |
| `FULL` | Unrestricted (all servers) |

### Role → Default Profile

| Role | Default Profile |
|------|----------------|
| `worker` | CODING |
| `developer` | CODING |
| `researcher` | RESEARCH |
| `planner` | FULL |

### ToolPolicyEngine

```python
engine = ToolPolicyEngine.for_role("developer")
filtered_mcp = engine.filter_mcp_config(mcp_config)    # Filter to allowed servers
filtered_tools = engine.filter_tool_names(tool_names)   # Filter to allowed tools
```

Server names are matched case-insensitively against the profile's prefix set. Deny list takes priority over allow list.

---

## Tool Preset System

Presets that define per-session tool sets.

### ToolPresetDefinition

```python
class ToolPresetDefinition(BaseModel):
    id: str                         # UUID (templates use "template-xxx")
    name: str                       # "All Tools"
    description: str
    custom_tools: List[str]         # ["*"] = all, [] = none
    mcp_servers: List[str]          # ["*"] = all, [] = none
    is_template: bool               # Read-only flag
```

### Built-in Templates

| ID | Name | custom_tools | mcp_servers |
|----|------|-------------|-------------|
| `template-all-tools` | All Tools | `["*"]` | `["*"]` |

The default preset for all roles is `template-all-tools`.

### ToolPresetStore

Stored as JSON files in the `tool_presets/` directory.

| Method | Description |
|--------|-------------|
| `save(preset)` | Save/update |
| `load(preset_id)` | Load by ID |
| `delete(preset_id)` | Delete |
| `list_all()` | List all |
| `clone(preset_id, new_name)` | Clone |

---

## Tool → Session Connection Flow

```
CreateSessionRequest
  ├── tool_preset_id (or role default)
  ├── role
  └── mcp_config (additional)
        │
        ▼
┌───────────────────┐      ┌──────────────────┐
│  ToolPresetStore  │─────►│ ToolPresetDef    │
│  (JSON files)     │      │ .custom_tools    │
└───────────────────┘      │ .mcp_servers     │
                           └────────┬─────────┘
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                ▼
         ToolLoader.              MCPLoader.       External MCP
         get_allowed_tools_      global config    server filtering
         for_preset()
                   │                │                │
                   ▼                ▼                ▼
             build_session_mcp_config()
                   │
                   ▼
             MCPConfig {
               "_python_tools": Proxy MCP Server,
               "github": MCPServerHTTP,
               ...
             }
                   │
                   ▼
             Written to session's .mcp.json
             → Claude CLI reads it
             → Spawns _proxy_mcp_server.py subprocess
             → Tool call → POST /internal/tools/execute
             → Executes in main process with singleton access
```

---

## API Endpoints

### Tool Catalog (`/api/tools`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tools/catalog` | Full catalog (built-in + custom + MCP) |
| `GET` | `/api/tools/catalog/built-in` | Built-in tools only |
| `GET` | `/api/tools/catalog/custom` | Custom tools only |
| `GET` | `/api/tools/catalog/mcp-servers` | External MCP servers only |

### Tool Presets (`/api/tool-presets`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/tool-presets/` | List all presets |
| `GET` | `/api/tool-presets/templates` | Templates only |
| `POST` | `/api/tool-presets/` | Create preset |
| `GET` | `/api/tool-presets/{id}` | Get preset |
| `PUT` | `/api/tool-presets/{id}` | Update preset (not templates) |
| `DELETE` | `/api/tool-presets/{id}` | Delete preset (not templates) |
| `POST` | `/api/tool-presets/{id}/clone` | Clone preset |

---

## Related Files

```
tools/
├── __init__.py                # Public API: BaseTool, ToolWrapper, tool, is_tool
├── base.py                    # BaseTool ABC, ToolWrapper, @tool decorator
├── _mcp_server.py             # Direct MCP server (legacy)
├── _proxy_mcp_server.py       # Proxy MCP server (currently used)
├── built_in/
│   └── geny_tools.py          # 11 built-in tools
└── custom/
    ├── browser_tools.py       # 7 browser tools (Playwright)
    ├── web_search_tools.py    # 2 search tools (DuckDuckGo)
    └── web_fetch_tools.py     # 2 web fetch tools (httpx)

service/
├── mcp_loader.py              # External MCP config loading, per-session MCP assembly
├── tool_loader.py             # Python tool discovery and registration
├── tool_policy/
│   └── policy.py              # ToolPolicyEngine, ToolProfile
└── tool_preset/
    ├── models.py              # ToolPresetDefinition
    ├── store.py               # ToolPresetStore (JSON file storage)
    └── templates.py           # Built-in preset templates

controller/
├── tool_controller.py         # /api/tools — catalog API
├── tool_preset_controller.py  # /api/tool-presets — preset CRUD
└── internal_tool_controller.py # /internal/tools — proxy execution endpoint

mcp/
├── README.md                  # MCP config guide
├── example_filesystem.json.template
└── example_github.json.template
```
