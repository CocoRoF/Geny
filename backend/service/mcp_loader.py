"""
MCP Loader

Automatically loads JSON configs from mcp/ folder to create global MCP
configurations available for all Claude Code sessions.

Python tools are managed by ToolLoader and exposed to Claude CLI
via the Proxy MCP server pattern.

Usage:
    from service.mcp_loader import MCPLoader, get_global_mcp_config

    # Initialize and load
    loader = MCPLoader()
    loader.load_all()

    # Get global MCP config
    config = get_global_mcp_config()

    # Build per-session MCP config with proxy
    session_config = build_session_mcp_config(
        global_config=config,
        allowed_tools=["geny_session_list", "web_search"],
        session_id="abc-123",
        backend_port=8000,
    )
"""
import importlib.util
import json
import os
import re
import sys
from logging import getLogger
from pathlib import Path
from typing import Dict, List, Any, Optional

from service.claude_manager.models import (
    MCPConfig,
    MCPServerStdio,
    MCPServerHTTP,
    MCPServerSSE,
    MCPServerConfig
)

logger = getLogger(__name__)

# Global MCP config storage
_global_mcp_config: Optional[MCPConfig] = None

# Project root path
PROJECT_ROOT = Path(__file__).parent.parent


def get_global_mcp_config() -> Optional[MCPConfig]:
    """
    Return global MCP config

    Returns:
        Loaded global MCP config or None
    """
    return _global_mcp_config


def set_global_mcp_config(config: MCPConfig) -> None:
    """
    Set global MCP config

    Args:
        config: MCP config to set
    """
    global _global_mcp_config
    _global_mcp_config = config


def build_proxy_mcp_server(
    allowed_tools: List[str],
    session_id: str,
    backend_port: int = 8000,
) -> MCPServerStdio:
    """Build a Proxy MCP server config for a session.

    The proxy server is a lightweight subprocess that:
    - Registers tool schemas (from Python tool modules)
    - Forwards execution requests to the main process via HTTP

    Args:
        allowed_tools: List of tool names to make available.
        session_id: Session ID for context.
        backend_port: Port of the FastAPI backend.

    Returns:
        MCPServerStdio config for the proxy server.
    """
    proxy_script = str(PROJECT_ROOT / "tools" / "_proxy_mcp_server.py")
    backend_url = f"http://localhost:{backend_port}"
    tools_arg = ",".join(allowed_tools) if allowed_tools else ""

    return MCPServerStdio(
        command=sys.executable,
        args=[proxy_script, backend_url, session_id, tools_arg],
        env=None,
    )


def build_session_mcp_config(
    global_config: Optional[MCPConfig],
    allowed_tools: List[str],
    session_id: str,
    backend_port: int = 8000,
    allowed_mcp_servers: Optional[List[str]] = None,
    extra_mcp: Optional[MCPConfig] = None,
) -> MCPConfig:
    """Build the complete MCP config for a session.

    Combines:
    1. _python_tools: Proxy MCP server (for Python tools)
    2. External MCP servers from global config (filtered by preset)
    3. Extra per-session MCP servers

    Args:
        global_config: Global MCP config (external servers from mcp/*.json).
        allowed_tools: Python tool names to register in proxy.
        session_id: Session ID.
        backend_port: FastAPI backend port.
        allowed_mcp_servers: List of external MCP server names to include.
                             None or ["*"] includes all.
        extra_mcp: Additional per-session MCP config.

    Returns:
        Complete MCPConfig for the session's .mcp.json.
    """
    servers: Dict[str, MCPServerConfig] = {}

    # 1. Add proxy MCP server for Python tools
    if allowed_tools:
        servers["_python_tools"] = build_proxy_mcp_server(
            allowed_tools=allowed_tools,
            session_id=session_id,
            backend_port=backend_port,
        )

    # 2. Add external MCP servers (filtered)
    if global_config and global_config.servers:
        for name, config in global_config.servers.items():
            # Skip old _builtin_tools server (replaced by proxy)
            if name.startswith("_"):
                continue
            # Apply filter
            if allowed_mcp_servers is None or "*" in allowed_mcp_servers:
                servers[name] = config
            elif name in allowed_mcp_servers:
                servers[name] = config

    # 3. Merge extra per-session config
    if extra_mcp and extra_mcp.servers:
        for name, config in extra_mcp.servers.items():
            servers[name] = config

    return MCPConfig(servers=servers)


class MCPLoader:
    """
    Auto-loader for MCP configs (external MCP servers).

    Loads JSON files from mcp/ folder to create the global MCP configuration.
    Python tools are handled separately by ToolLoader + Proxy MCP pattern.
    """

    def __init__(
        self,
        mcp_dir: Optional[Path] = None,
        tools_dir: Optional[Path] = None
    ):
        """
        Args:
            mcp_dir: MCP JSON config folder path (default: project_root/mcp)
            tools_dir: Tools folder path (default: project_root/tools) — kept for compatibility
        """
        self.mcp_dir = mcp_dir or PROJECT_ROOT / "mcp"
        self.tools_dir = tools_dir or PROJECT_ROOT / "tools"
        self.servers: Dict[str, MCPServerConfig] = {}
        self.tools: List[Any] = []  # Legacy — kept for get_tool_count() compatibility

    def load_all(self) -> MCPConfig:
        """
        Load all external MCP configs.

        Returns:
            Global MCP config (external servers only).
        """
        logger.info("=" * 60)
        logger.info("🔌 MCP Loader: Starting...")

        # 1. Load JSON configs from mcp/ folder
        self._load_mcp_configs()

        # 2. Create global config (external MCP servers only)
        # Python tools are handled by ToolLoader + Proxy MCP pattern
        config = MCPConfig(servers=self.servers)
        set_global_mcp_config(config)

        logger.info(f"🔌 MCP Loader: Loaded {len(self.servers)} external MCP servers")
        logger.info("   ℹ️ Python tools managed by ToolLoader (Proxy MCP pattern)")
        logger.info("=" * 60)

        return config

    def _load_mcp_configs(self) -> None:
        """Load JSON config files from mcp/ folder"""
        if not self.mcp_dir.exists():
            logger.info(f"📁 MCP config directory not found: {self.mcp_dir}")
            return

        json_files = list(self.mcp_dir.glob("*.json"))
        if not json_files:
            logger.info(f"📁 No JSON files in: {self.mcp_dir}")
            return

        logger.info(f"📁 Loading MCP configs from: {self.mcp_dir}")

        for json_file in json_files:
            try:
                server_name = json_file.stem  # Filename without extension

                with open(json_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                # Expand environment variables
                config_data = self._expand_env_vars(config_data)

                # Create server config
                server_config = self._create_server_config(config_data)

                if server_config:
                    self.servers[server_name] = server_config
                    desc = config_data.get('description', '')
                    logger.info(f"   ✅ {server_name}: {desc[:50]}..." if len(desc) > 50 else f"   ✅ {server_name}: {desc}")

            except json.JSONDecodeError as e:
                logger.warning(f"   ⚠️ Invalid JSON in {json_file.name}: {e}")
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to load {json_file.name}: {e}")

    def _expand_env_vars(self, data: Any) -> Any:
        """
        Expand environment variables in config (${VAR} or ${VAR:-default} format)
        """
        if isinstance(data, str):
            # Find ${VAR} or ${VAR:-default} patterns
            pattern = r'\$\{([^}:]+)(?::-([^}]*))?\}'

            def replace_env(match):
                var_name = match.group(1)
                default = match.group(2)
                value = os.environ.get(var_name)
                if value is None:
                    if default is not None:
                        return default
                    return match.group(0)  # Keep original if env var not found
                return value

            return re.sub(pattern, replace_env, data)

        elif isinstance(data, dict):
            return {k: self._expand_env_vars(v) for k, v in data.items()}

        elif isinstance(data, list):
            return [self._expand_env_vars(item) for item in data]

        return data

    def _create_server_config(self, data: Dict[str, Any]) -> Optional[MCPServerConfig]:
        """Create MCP server config from JSON data"""
        server_type = data.get('type', 'stdio')

        if server_type == 'stdio':
            command = data.get('command')
            if not command:
                return None
            return MCPServerStdio(
                command=command,
                args=data.get('args', []),
                env=data.get('env')
            )

        elif server_type == 'http':
            url = data.get('url')
            if not url:
                return None
            return MCPServerHTTP(
                url=url,
                headers=data.get('headers')
            )

        elif server_type == 'sse':
            url = data.get('url')
            if not url:
                return None
            return MCPServerSSE(
                url=url,
                headers=data.get('headers')
            )

        return None

    def get_server_count(self) -> int:
        """Return number of loaded external MCP servers."""
        return len(self.servers)

    def get_tool_count(self) -> int:
        """Return number of loaded tools (from ToolLoader)."""
        try:
            from service.tool_loader import get_tool_loader
            loader = get_tool_loader()
            return len(loader.get_all_tools())
        except Exception:
            return 0

    def get_config(self) -> MCPConfig:
        """Return current MCP config (external servers only)."""
        return MCPConfig(servers=self.servers)

    def get_external_server_names(self) -> List[str]:
        """Return names of all loaded external MCP servers."""
        return [name for name in self.servers.keys() if not name.startswith("_")]


def merge_mcp_configs(base: Optional[MCPConfig], override: Optional[MCPConfig]) -> Optional[MCPConfig]:
    """
    Merge two MCP configs

    Override config takes precedence over base.

    Args:
        base: Base config (global)
        override: Override config (per-session)

    Returns:
        Merged config
    """
    if not base and not override:
        return None

    if not base:
        return override

    if not override:
        return base

    # Merge servers (override takes precedence)
    merged_servers = {**base.servers, **override.servers}

    return MCPConfig(servers=merged_servers)
