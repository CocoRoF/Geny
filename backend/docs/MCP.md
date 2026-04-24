# MCP (Model Context Protocol) System

> External MCP server management — 2-tier directory loading (built_in / custom), proxy pattern, per-session assembly

## Architecture Overview

```
Claude CLI ←stdio→ _builtin_tools proxy   ←HTTP→ FastAPI (main process)
           ←stdio→ _custom_tools proxy     ←HTTP→ FastAPI (main process)
           ←stdio/http/sse→ External MCP servers (GitHub, Notion, etc.)
```

**Core Design**: Python tools use the Proxy MCP pattern (see [TOOLS.md](TOOLS.md)). External MCP servers are loaded from JSON config files in the `mcp/` directory and connected to Claude CLI directly via stdio/http/sse transport.

---

## Directory Structure

```
mcp/
├── built_in/          ← Always included (bypass preset filtering)
│   └── github.json    ← GitHub API — auto-configured from Settings
├── custom/            ← User-added servers (subject to preset filtering)
│   └── (your .json)
├── *.json.template    ← Example templates (not loaded)
└── README.md
```

### 2-Tier Loading

| Tier | Folder | Preset Filtered | Env Var Skip | Loaded Into | Use Case |
|------|--------|----------------|-------------|-------------|----------|
| 1 | `mcp/built_in/` | **No** — always included | Yes | `builtin_servers` | System-level servers (GitHub) |
| 2 | `mcp/custom/` | **Yes** | Yes | `servers` | User-added servers |

**Key differences:**
- **built_in/** servers cannot be excluded by Tool Sets — they appear in every session
- **custom/** servers skip loading if env vars are unresolved (helpful for optional integrations)

---

## JSON Config Schema

Each `.json` file defines one MCP server. The filename (without extension) becomes the server name.

```json
{
  "type": "stdio | http | sse",
  "command": "command (stdio only)",
  "args": ["arg1", "arg2"],
  "env": {"KEY": "value or ${ENV_VAR}"},
  "url": "server URL (http/sse only)",
  "headers": {"Header": "value"},
  "description": "Shown in Tool Sets & Session Tools UI"
}
```

### Transport Types

| Type | Required Fields | Description |
|------|----------------|-------------|
| `stdio` | `command`, `args` (optional) | Spawns subprocess, communicates via stdin/stdout |
| `http` | `url` | Connects to HTTP endpoint |
| `sse` | `url` | Connects via Server-Sent Events |

### Config Models (Python)

```python
# service/sessions/models.py
MCPServerStdio(command, args, env)
MCPServerHTTP(url, headers)
MCPServerSSE(url, headers)
MCPConfig(servers: Dict[str, MCPServerConfig])
```

---

## MCPLoader

**File**: `service/mcp_loader.py`

Central component that loads JSON configs and manages the global MCP configuration.

### Singleton Pattern

```python
_global_mcp_config: Optional[MCPConfig] = None   # Custom servers (preset-filtered)
_builtin_mcp_config: Optional[MCPConfig] = None   # Built-in servers (always included)
_mcp_loader_instance: Optional[MCPLoader] = None  # Singleton for reload access
```

### Initialization & Loading

```python
# main.py — startup
loader = MCPLoader()
config = loader.load_all()
app.state.mcp_loader = loader
```

`load_all()` executes two phases in order:

1. **`_load_builtin_configs()`** — Scans `mcp/built_in/*.json`
   - Expands `${VAR}` env vars
   - Skips servers with unresolved env vars (`_has_unresolved_env()`)
   - Stores in `self.builtin_servers` + tracks in `self.builtin_server_names`

2. **`_load_custom_configs()`** — Scans `mcp/custom/*.json`
   - Same env var expansion + unresolved skip behavior
   - Stores in `self.servers` + tracks in `self.custom_server_names`

### State Tracking

```python
self.servers: Dict[str, MCPServerConfig]         # custom servers
self.builtin_servers: Dict[str, MCPServerConfig]  # built-in servers
self.server_descriptions: Dict[str, str]          # name → description (all)
self.builtin_server_names: set                    # names from mcp/built_in/
self.custom_server_names: set                     # names from mcp/custom/
```

### Reload Mechanism

When config values that affect built-in MCP servers change (e.g., GitHub token updated in Settings), the reload chain triggers:

```
Settings UI → ConfigField.apply_change → _github_token_sync()
  → env_sync("GITHUB_TOKEN") + env_sync("GH_TOKEN")
  → reload_builtin_mcp()
    → MCPLoader.reload_builtins()
      → clear builtin_servers/builtin_server_names
      → re-run _load_builtin_configs()
      → set_builtin_mcp_config(new_config)
```

This ensures `${GITHUB_TOKEN}` in `mcp/built_in/github.json` is re-expanded with the new value.

---

## Environment Variable Expansion

### Syntax

| Pattern | Behavior |
|---------|----------|
| `${VAR}` | Replaced with `os.environ["VAR"]`, kept as-is if not found |
| `${VAR:-fallback}` | Replaced with `os.environ["VAR"]`, uses `fallback` if not found |

### Implementation

```python
def _expand_env_vars(self, data: Any) -> Any:
    # Pattern: ${VAR} or ${VAR:-default}
    # Empty string ("") is treated as unset (same as None)
```

### Unresolved Check

`_has_unresolved_env(data)` returns `True` if any `${...}` patterns remain after expansion. Used by `built_in/` and `custom/` loaders to skip incomplete configs.

---

## Per-Session MCP Assembly

**Function**: `build_session_mcp_config()`

Builds the complete MCP config for a session by combining 5 layers:

```
Layer 1: _builtin_tools    ← Proxy MCP for built-in Python tools (always)
Layer 2: _custom_tools     ← Proxy MCP for custom Python tools (if allowed)
Layer 3: Built-in MCP      ← mcp/built_in/ servers (always, no filtering)
Layer 4: Custom MCP        ← mcp/custom/ servers (preset-filtered)
Layer 5: Extra per-session ← Additional MCP passed at session creation
```

### Preset Filtering (Layer 4)

```python
allowed_mcp_servers: Optional[List[str]]
# None or ["*"] → include all custom MCP servers
# ["notion", "filesystem"] → include only these
# [] → include none (only built-ins remain)
```

### Parameters

```python
build_session_mcp_config(
    global_config,            # Custom MCP servers
    allowed_builtin_tools,    # Built-in tool names
    allowed_custom_tools,     # Custom tool names (preset-filtered)
    session_id,               # Session ID
    backend_port=8000,        # FastAPI port
    allowed_mcp_servers=None, # MCP server filter (None = all)
    extra_mcp=None,           # Additional per-session MCP
) -> MCPConfig
```

---

## Tool Catalog API

**File**: `controller/tool_controller.py`

### Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/tools/catalog` | Full catalog (built-in + custom + MCP) |
| `GET /api/tools/catalog/mcp-servers` | MCP servers only |

### MCPServerInfo Model

```python
class MCPServerInfo(BaseModel):
    name: str           # Server name (filename stem)
    type: str           # "stdio", "http", "sse"
    description: str    # From JSON config
    is_built_in: bool   # True for mcp/built_in/ servers
    source: str         # "built_in" or "custom"
```

### Source Resolution

The catalog assigns a `source` to each server:

1. **`built_in`** — Loaded from `mcp/built_in/`, always included, `is_built_in=True`
2. **`custom`** — Loaded from `mcp/custom/`, preset-filtered

---

## Frontend Integration

### Types

```typescript
// types/index.ts
interface MCPServerInfo {
  name: string
  type: string
  description?: string
  is_built_in?: boolean
  source?: string  // "built_in" | "custom"
}
```

### UI Components

**SessionToolsTab** — Displays per-session tool state:
- Built-in MCP servers show a **BUILT-IN** badge and are always enabled
- Custom servers show enable/disable based on Tool Set config
- Count: `builtInMcpCount + enabledMcpServers.size`

**ToolSetsTab** — Tool Set editor:
- Built-in MCP servers have a disabled checkbox (always checked) + **BUILT-IN** badge
- Custom MCP servers can be individually toggled
- Description text shown below each server name

---

## Built-in MCP Server: GitHub

**File**: `mcp/built_in/github.json`

```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
  },
  "description": "GitHub MCP — Repository, PR, Issue management (auto-configured from Settings)"
}
```

### Auto-Configuration Flow

1. User enters GitHub token in **Settings → GitHub → Token**
2. `GitHubConfig.apply_change` triggers `_github_token_sync()`
3. `env_sync("GITHUB_TOKEN")` + `env_sync("GH_TOKEN")` update `os.environ`
4. `reload_builtin_mcp()` re-loads `mcp/built_in/github.json`
5. `${GITHUB_TOKEN}` is now expanded with the new token value
6. Next session creation picks up the updated `builtin_mcp_config`

If `GITHUB_TOKEN` is not set, the server is skipped (not an error).

---

## Adding New MCP Servers

### As a Built-in Server (always included)

1. Create `mcp/built_in/{name}.json`
2. Use `${ENV_VAR}` for any secrets
3. Add a corresponding config in `service/config/sub_config/` if the env var should be configurable via Settings
4. Wire `apply_change` → `reload_builtin_mcp()` so changes take effect immediately

### As a Custom Server (user-added, preset-filtered)

1. Create `mcp/custom/{name}.json`
2. Use `${ENV_VAR}` for secrets — server is skipped if vars are missing
3. Server appears in Tool Sets UI and can be toggled per preset

---

## Related Documentation

- [TOOLS.md](TOOLS.md) — Python tools & proxy MCP pattern
- [CONFIG.md](CONFIG.md) — Configuration system (BaseConfig, env_sync)
- [WORKFLOW.md](WORKFLOW.md) — Workflow system & session management
