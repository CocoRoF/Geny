# MCP Server Configuration Folder

Add `.json` files to this folder to **automatically enable MCP servers for all Claude Code sessions**.

## Quick Start

### 1. Create JSON File

Create a `{name}.json` file in this folder. The filename becomes the MCP server name.

### 2. JSON Schema

```json
{
  "type": "stdio | http | sse",
  "command": "command to run (for stdio)",
  "args": ["arg1", "arg2"],
  "env": {"ENV_VAR": "value"},
  "url": "server URL (for http/sse)",
  "headers": {"Header-Name": "value"},
  "description": "Server description (optional)"
}
```

### 3. Examples

#### GitHub MCP Server (`github.json`)
```json
{
  "type": "http",
  "url": "https://api.githubcopilot.com/mcp/",
  "description": "GitHub integration - Repository, PR, Issue management"
}
```

#### Filesystem MCP Server (`filesystem.json`)
```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace", "/data"],
  "description": "Filesystem access"
}
```

#### PostgreSQL MCP Server (`database.json`)
```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@bytebase/dbhub", "--dsn", "${DATABASE_URL}"],
  "env": {
    "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
  },
  "description": "PostgreSQL database access"
}
```

#### Notion MCP Server (`notion.json`)
```json
{
  "type": "http",
  "url": "https://mcp.notion.com/mcp",
  "description": "Notion pages and databases access"
}
```

#### Sentry MCP Server (`sentry.json`)
```json
{
  "type": "http",
  "url": "https://mcp.sentry.dev/mcp",
  "description": "Sentry error monitoring"
}
```

#### Custom Python MCP Server (`custom.json`)
```json
{
  "type": "stdio",
  "command": "python",
  "args": ["tools/my_custom_server.py"],
  "env": {
    "API_KEY": "${MY_API_KEY}"
  },
  "description": "Custom tool server"
}
```

## Environment Variables

Use `${VARIABLE_NAME}` syntax to reference environment variables in JSON files:

```json
{
  "type": "http",
  "url": "${API_BASE_URL}/mcp",
  "headers": {
    "Authorization": "Bearer ${API_TOKEN}"
  }
}
```

## Auto-Loading

- All `.json` files in this folder are automatically loaded when `main.py` starts
- Loaded MCP servers are **available in all sessions by default**
- Additional MCP config passed during session creation will be **merged**

## Important Notes

1. **Filename = Server Name**: `github.json` → MCP server name `github`
2. **Override Prevention**: Session-specific config takes priority if same server name exists
3. **Validation**: Invalid JSON files will log a warning and be skipped
4. **Security**: Store API keys in environment variables, not in JSON files

## Popular MCP Servers

| Server | URL | Description |
|--------|-----|-------------|
| GitHub | `https://api.githubcopilot.com/mcp/` | GitHub integration |
| Notion | `https://mcp.notion.com/mcp` | Notion integration |
| Sentry | `https://mcp.sentry.dev/mcp` | Error monitoring |
| Slack | `https://mcp.slack.com/mcp` | Slack integration |
| Linear | `https://mcp.linear.app/mcp` | Issue tracker |

More MCP servers: https://github.com/modelcontextprotocol/servers

---

## GitHub Automation Setup

To enable Claude to automatically clone repos, create branches, and submit PRs:

### Step 1: Create GitHub MCP Config

Copy the template and create your config:

```bash
cp example_github.json.template github.json
```

### Step 2: Configure Git Credentials

Claude Code uses system git configuration. Ensure git is configured:

```bash
# Configure git user
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"

# For HTTPS authentication, use GitHub CLI or credential manager
gh auth login

# Or set up SSH keys for git operations
ssh-keygen -t ed25519 -C "your.email@example.com"
```

### Step 3: Enable Autonomous Mode

In `.env`, ensure:
```
CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true
```

### Step 4: Test GitHub Integration

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "github-test"
  }'

curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Clone https://github.com/user/repo, create a new branch called feature/test, add a README.md, commit and push, then create a PR.",
    "timeout": 600
  }'
```
