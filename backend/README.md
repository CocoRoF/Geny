# Claude Control

Multi-session management system for Claude Code

## Overview

Claude Control enables simultaneous management and control of multiple Claude Code sessions.

### Key Features

- **Multi-session Management**: Create and manage multiple Claude Code instances per session
- **Independent Storage per Session**: Each session has its own isolated working directory
- **Multi-pod Support**: Session management across multiple Kubernetes Pods
- **Redis-based Session Sharing**: Share session metadata via Redis
- **🔌 MCP Auto-loading**: Automatically load JSON configs from `mcp/` folder
- **🔧 Custom Tools**: Auto-register Python tools from `tools/` folder

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Control                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   [API Layer]                                                    │
│   ├── POST /api/sessions          - Create session              │
│   ├── GET  /api/sessions          - List sessions               │
│   ├── GET  /api/sessions/{id}     - Get session                 │
│   ├── DELETE /api/sessions/{id}   - Delete session              │
│   ├── POST /api/sessions/{id}/execute - Execute Claude          │
│   └── GET  /api/sessions/{id}/storage - Get storage info        │
│                                                                  │
│   [Session Manager]                                              │
│   ├── Session lifecycle management                               │
│   ├── Redis-based metadata storage                               │
│   └── Multi-pod session routing                                  │
│                                                                  │
│   [Claude Process]                                               │
│   ├── Claude CLI process management                              │
│   ├── Independent storage directory                              │
│   └── Prompt execution and response collection                   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites

| Requirement | Version | Description |
|-------------|---------|-------------|
| Python | 3.11+ | Main runtime |
| Node.js | 18+ | Required for Claude CLI and MCP servers |
| npm | 9+ | Package manager (comes with Node.js) |
| Git | 2.30+ | Version control |
| GitHub CLI | 2.0+ | For PR/Issue automation (optional) |
| Redis | 6+ | Multi-pod session sharing (optional) |

### 1. Install Node.js

#### Windows
```powershell
# Option 1: Using winget (recommended)
winget install OpenJS.NodeJS.LTS

# Option 2: Using Chocolatey
choco install nodejs-lts

# Option 3: Download installer from https://nodejs.org/
```

#### macOS
```bash
# Option 1: Using Homebrew (recommended)
brew install node@20

# Option 2: Using nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 20
nvm use 20
```

#### Linux (Ubuntu/Debian)
```bash
# Using NodeSource repository
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Or using nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
nvm install 20
```

#### Linux (RHEL/CentOS/Fedora)
```bash
# Using NodeSource repository
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
sudo yum install -y nodejs
```

### 2. Install Claude CLI

```bash
# All platforms (requires Node.js)
npm install -g @anthropic-ai/claude-code

# Verify installation
claude --version
```

### 3. Install GitHub CLI (for PR/Issue automation)

#### Windows
```powershell
# Option 1: Using winget (recommended)
winget install GitHub.cli

# Option 2: Using Chocolatey
choco install gh

# Option 3: Using Scoop
scoop install gh
```

#### macOS
```bash
# Using Homebrew
brew install gh
```

#### Linux (Ubuntu/Debian)
```bash
# Add GitHub CLI repository
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

#### Linux (RHEL/CentOS/Fedora)
```bash
sudo dnf install gh
# or
sudo yum install gh
```

### 4. Install Python 3.11+

#### Windows
```powershell
# Using winget
winget install Python.Python.3.11

# Or download from https://www.python.org/downloads/
```

#### macOS
```bash
# Using Homebrew
brew install python@3.11
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

### 5. Install Git

#### Windows
```powershell
winget install Git.Git
```

#### macOS
```bash
# Git comes with Xcode Command Line Tools
xcode-select --install
# Or using Homebrew
brew install git
```

#### Linux
```bash
# Ubuntu/Debian
sudo apt install git

# RHEL/CentOS/Fedora
sudo dnf install git
```

### 6. Install Redis (Optional - for multi-pod)

#### Windows
```powershell
# Using Docker (recommended for Windows)
docker run -d --name redis -p 6379:6379 redis:alpine

# Or using WSL2
wsl --install
# Then install Redis inside WSL
```

#### macOS
```bash
brew install redis
brew services start redis
```

#### Linux
```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# RHEL/CentOS/Fedora
sudo dnf install redis
sudo systemctl enable redis
sudo systemctl start redis
```

### 7. Install Claude Control

```bash
# Clone repository
git clone https://github.com/your-org/claude-control.git
cd claude-control

# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Windows CMD:
.\venv\Scripts\activate.bat
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Or using pyproject.toml
pip install -e .
```

### 8. Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit .env with your settings
# Required: ANTHROPIC_API_KEY
# Optional: GITHUB_TOKEN (for PR automation)
```

### Quick Verification

```bash
# Check all installations
node --version      # Should be v18+
npm --version       # Should be v9+
python --version    # Should be 3.11+
git --version       # Should be 2.30+
gh --version        # Should be 2.0+ (optional)
claude --version    # Claude CLI installed
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_HOST` | Server host | `0.0.0.0` |
| `APP_PORT` | Server port | `8000` |
| `DEBUG_MODE` | Debug mode | `false` |
| `REDIS_HOST` | Redis host | `redis` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis password | - |
| `CLAUDE_STORAGE_ROOT` | Session storage root path | OS-dependent* |
| `ANTHROPIC_API_KEY` | Anthropic API key (required) | - |
| `GITHUB_TOKEN` | GitHub Personal Access Token (for PR/Issue automation) | - |
| `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Autonomous mode - skip permission prompts | `true` |

*Default storage paths:
- Windows: `%LOCALAPPDATA%\claude_sessions`
- macOS/Linux: `/tmp/claude_sessions`

## Running

```bash
# Development mode (hot reload)
DEBUG_MODE=true python main.py

# Production mode
python main.py
```

## API Usage Examples

### Create Session

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "my-session",
    "model": "claude-sonnet-4-20250514"
  }'
```

### Execute Claude (Basic)

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Hello, Claude!"
  }'
```

### 🤖 Autonomous Mode Examples

Autonomous mode allows Claude to complete tasks independently without asking questions.

#### Create Next.js Project and Push to Git

```bash
# Create session (autonomous mode enabled by default)
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "nextjs-project",
    "max_turns": 100,
    "autonomous": true
  }'

# Autonomously create Next.js project and push to Git
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a complete Next.js 14 project with: 1) App Router, 2) Tailwind CSS, 3) TypeScript, 4) A modern landing page with hero section, features section, and footer. 5) Initialize git, make initial commit, and push to https://github.com/user/my-nextjs-project.git",
    "timeout": 1800,
    "skip_permissions": true,
    "system_prompt": "You are an autonomous AI agent. Complete all tasks without asking for confirmation. Create files, run commands, and push to git independently. Do not ask questions - make reasonable decisions and proceed."
  }'
```

#### Automatic Code Refactoring

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze all files in this project. Refactor for better code quality: add TypeScript types, improve naming conventions, add JSDoc comments, and fix any bugs. Commit changes with descriptive messages.",
    "system_prompt": "Work autonomously without asking questions. Make all necessary changes directly.",
    "max_turns": 50
  }'
```

#### Automated Test Writing

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Write comprehensive unit tests for all components and utilities in this project using Jest and React Testing Library. Aim for 80%+ coverage. Run tests and fix any failures.",
    "timeout": 1200
  }'
```

### Delete Session

```bash
curl -X DELETE http://localhost:8000/api/sessions/{session_id}
```

## 🔄 GitHub Automation

Claude Control can automate GitHub workflows - clone repos, create branches, make changes, and submit PRs.

### Prerequisites

1. **Git Configuration**:
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "your.email@example.com"
   ```

2. **GitHub Authentication** (choose one):

   **Option A: GITHUB_TOKEN in .env (Recommended for automation)**
   ```bash
   # Add to .env file
   GITHUB_TOKEN=ghp_your_personal_access_token_here
   ```
   Generate token at: https://github.com/settings/tokens
   Required scopes: `repo`, `workflow`

   > Note: Claude Control automatically sets `GH_TOKEN` from `GITHUB_TOKEN` on startup,
   > enabling `gh` CLI commands without manual authentication.

   **Option B: GitHub CLI Interactive Login**
   ```bash
   gh auth login
   # Follow the prompts to authenticate
   ```

   **Option C: SSH Keys**
   ```bash
   # Generate SSH key
   ssh-keygen -t ed25519 -C "your.email@example.com"

   # Add to ssh-agent
   eval "$(ssh-agent -s)"
   ssh-add ~/.ssh/id_ed25519

   # Copy public key and add to GitHub Settings > SSH Keys
   cat ~/.ssh/id_ed25519.pub
   ```

   **Option D: HTTPS with Credential Manager (Windows)**
   ```powershell
   git config --global credential.helper manager
   # Credentials will be prompted on first push
   ```

3. **Enable Autonomous Mode** in `.env`:
   ```
   CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS=true
   ```

### Example: Clone, Enhance, and Create PR

```bash
# Create session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "github-automation",
    "max_turns": 100
  }'

# Execute GitHub workflow
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "1. Clone https://github.com/user/my-repo.git, 2. Create a new branch called feature/improvements, 3. Add comprehensive documentation to all functions, 4. Add unit tests for existing code, 5. Commit all changes with descriptive messages, 6. Push the branch, 7. Create a pull request with a detailed description of all changes.",
    "timeout": 1800,
    "system_prompt": "You are an autonomous coding agent. Complete all tasks without asking questions. Use git commands directly. Make reasonable decisions about code improvements."
  }'
```

### Example: Automated Code Review and Fix

```bash
curl -X POST http://localhost:8000/api/sessions/{session_id}/execute \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Clone https://github.com/user/project.git, review all code for bugs and security issues, fix any problems found, create a branch called fix/security-audit, commit all fixes, push, and create a PR titled Security Audit Fixes.",
    "timeout": 1200
  }'
```

## Project Structure

```
claude_control/
├── main.py                         # FastAPI app entrypoint
├── controller/
│   └── claude_controller.py        # API endpoints
├── service/
│   ├── claude_manager/             # Core session management
│   │   ├── models.py               # Data models
│   │   ├── process_manager.py      # Claude process management
│   │   ├── session_manager.py      # Session lifecycle
│   │   └── mcp_tools_server.py     # LangChain → MCP wrapper
│   ├── redis/
│   │   └── redis_client.py         # Redis client
│   ├── pod/
│   │   └── pod_info.py             # Pod info (multi-pod)
│   ├── middleware/
│   │   └── session_router.py       # Session routing middleware
│   ├── proxy/
│   │   └── internal_proxy.py       # Inter-pod proxy
│   ├── utils/
│   │   └── utils.py                # Utilities
│   └── mcp_loader.py               # MCP/tools auto-loader
├── mcp/                            # 📁 MCP server configs (auto-load)
│   ├── README.md                   # Usage guide
│   └── *.json                      # MCP server config files
├── tools/                          # 📁 Custom tools (auto-load)
│   ├── README.md                   # Usage guide
│   ├── base.py                     # BaseTool, @tool decorator
│   └── *_tool.py                   # Custom tool files
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 📁 MCP/Tools Auto-Loading

### mcp/ Folder (MCP Server Auto-Registration)

Add `.json` files to `mcp/` folder to make them **automatically available in all sessions**.

```bash
# Example: mcp/github.json
{
  "type": "http",
  "url": "https://api.githubcopilot.com/mcp/",
  "description": "GitHub MCP server"
}

# Example: mcp/database.json
{
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@bytebase/dbhub", "--dsn", "${DATABASE_URL}"],
  "description": "PostgreSQL MCP server"
}
```

👉 Details: [mcp/README.md](mcp/README.md)

### tools/ Folder (Custom Tool Auto-Registration)

Add `*_tool.py` files to `tools/` folder to make them **automatically available in all sessions**.

```python
# Example: tools/my_tool.py
from tools.base import tool

@tool
def search_database(query: str) -> str:
    """Search the database for records"""
    return f"Results for: {query}"

TOOLS = [search_database]
```

👉 Details: [tools/README.md](tools/README.md)

## 🔌 MCP Server Configuration (API)

Connect MCP servers to Claude Code sessions to access external tools and data.

### MCP Server Config Example

```bash
# Connect GitHub, filesystem, and PostgreSQL MCP servers
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "full-stack-session",
    "mcp_config": {
      "servers": {
        "github": {
          "type": "http",
          "url": "https://api.githubcopilot.com/mcp/"
        },
        "filesystem": {
          "type": "stdio",
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
        },
        "database": {
          "type": "stdio",
          "command": "npx",
          "args": ["-y", "@bytebase/dbhub", "--dsn", "postgresql://user:pass@localhost:5432/mydb"]
        }
      }
    }
  }'
```

### Supported MCP Transports

| Type | Description | Use Case |
|------|-------------|----------|
| `stdio` | Local process | npx, python scripts |
| `http` | Remote HTTP server | GitHub, Notion, Sentry |
| `sse` | Server-Sent Events (deprecated) | Legacy servers |

### Popular MCP Servers

```json
{
  "servers": {
    "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
    "notion": {"type": "http", "url": "https://mcp.notion.com/mcp"},
    "sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp"},
    "slack": {"type": "http", "url": "https://mcp.slack.com/mcp"}
  }
}
```

## 🔧 LangChain Tool Integration

LangChain tools can be wrapped as MCP servers for use in Claude Code sessions.

### Convert LangChain Tools to MCP Server

```python
from langchain_core.tools import tool
from service.claude_manager.mcp_tools_server import MCPToolsServer

# Define LangChain tools
@tool
def search_web(query: str) -> str:
    """Search the web for information"""
    return f"Search results for: {query}"

@tool
def analyze_code(code: str, language: str = "python") -> str:
    """Analyze code for potential issues"""
    return f"Analysis of {language} code: No issues found"

# Create and run MCP server
server = MCPToolsServer(
    name="custom-tools",
    tools=[search_web, analyze_code]
)

# Run with stdio transport
server.run(transport="stdio")

# Or run as HTTP server
# server.run(transport="http", port=8080)
```

### Connect LangChain MCP Server to Session

```bash
# Connect LangChain tool MCP server to session
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "session_name": "langchain-session",
    "mcp_config": {
      "servers": {
        "custom-tools": {
          "type": "stdio",
          "command": "python",
          "args": ["/path/to/my_tools_server.py"]
        }
      }
    }
  }'
```

### Convenience Functions for MCP Config

```python
from service.claude_manager.mcp_tools_server import (
    create_filesystem_mcp_config,
    create_github_mcp_config,
    create_postgres_mcp_config,
    create_custom_mcp_config
)

# Filesystem access
fs_config = create_filesystem_mcp_config(["/workspace", "/data"])

# GitHub connection
github_config = create_github_mcp_config()

# PostgreSQL connection
db_config = create_postgres_mcp_config("postgresql://user:pass@localhost:5432/mydb")

# Custom server
custom_config = create_custom_mcp_config(
    server_type="stdio",
    command="python",
    args=["my_server.py"],
    env={"API_KEY": "xxx"}
)
```

## Cross-Platform Support

Claude Control works on Windows, macOS, and Linux:

- **Windows**: Uses `%LOCALAPPDATA%\claude_sessions` for storage, auto-detects `.cmd`/`.exe` executables
- **macOS/Linux**: Uses `/tmp/claude_sessions` for storage, uses standard executable paths

## License

MIT License
