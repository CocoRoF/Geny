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
_default_mcp_config: Optional[MCPConfig] = None
_mcp_loader_instance: Optional["MCPLoader"] = None

# Project root path
PROJECT_ROOT = Path(__file__).parent.parent


def get_global_mcp_config() -> Optional[MCPConfig]:
    """
    Return global MCP config

    Returns:
        Loaded global MCP config or None
    """
    return _global_mcp_config


def get_default_mcp_config() -> Optional[MCPConfig]:
    """Return default MCP config (from mcp/default/ folder).

    Default MCP servers are always included in all sessions
    regardless of tool preset filtering.
    """
    return _default_mcp_config


def set_global_mcp_config(config: MCPConfig) -> None:
    """
    Set global MCP config

    Args:
        config: MCP config to set
    """
    global _global_mcp_config
    _global_mcp_config = config


def set_default_mcp_config(config: MCPConfig) -> None:
    """Set default MCP config."""
    global _default_mcp_config
    _default_mcp_config = config


def set_mcp_loader_instance(loader: "MCPLoader") -> None:
    """Store the MCPLoader singleton for reload access."""
    global _mcp_loader_instance
    _mcp_loader_instance = loader


def reload_default_mcp() -> None:
    """Reload default MCP configs (mcp/default/) with current env vars.

    Called when a config that affects default MCP servers changes
    (e.g. GitHub token updated via Settings).
    """
    if _mcp_loader_instance is None:
        logger.debug("MCPLoader not initialized yet — skipping default MCP reload")
        return
    _mcp_loader_instance.reload_defaults()


def build_proxy_mcp_server(
    category: str,
    allowed_tools: List[str],
    session_id: str,
    backend_port: int = 8000,
) -> MCPServerStdio:
    """Build a Proxy MCP server config for a session.

    The proxy server is a lightweight subprocess that:
    - Auto-discovers tool files from the specified category folder
    - Registers tool schemas (from Python tool modules)
    - Forwards execution requests to the main process via HTTP

    Args:
        category: 'builtin' or 'custom' — determines which folder to scan.
        allowed_tools: List of tool names to make available.
        session_id: Session ID for context.
        backend_port: Port of the FastAPI backend.

    Returns:
        MCPServerStdio config for the proxy server.
    """
    proxy_script = str(PROJECT_ROOT / "tools" / "_proxy_mcp_server.py")
    backend_url = f"http://localhost:{backend_port}"
    tools_arg = ",".join(allowed_tools) if allowed_tools else ""

    # Pass critical env vars for the proxy subprocess.
    # Claude Code merges these with the parent environment, so we only
    # need to ensure the subprocess can locate user-installed packages
    # (e.g. pip install --user in Docker dev mode) and the project root.
    env: Dict[str, str] = {}
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    if home:
        env["HOME"] = home
    pythonpath = os.environ.get("PYTHONPATH", "")
    # Always include project root so the proxy can find tools/ and service/
    project_root_str = str(PROJECT_ROOT)
    if project_root_str not in pythonpath:
        pythonpath = f"{project_root_str}{os.pathsep}{pythonpath}" if pythonpath else project_root_str
    env["PYTHONPATH"] = pythonpath

    return MCPServerStdio(
        command=sys.executable,
        args=[proxy_script, backend_url, session_id, category, tools_arg],
        env=env if env else None,
    )


def build_session_mcp_config(
    global_config: Optional[MCPConfig],
    allowed_builtin_tools: List[str],
    allowed_custom_tools: List[str],
    session_id: str,
    backend_port: int = 8000,
    allowed_mcp_servers: Optional[List[str]] = None,
    extra_mcp: Optional[MCPConfig] = None,
) -> MCPConfig:
    """Build the complete MCP config for a session.

    Combines:
    1. _builtin_tools: Proxy MCP server for built-in tools (always included)
    2. _custom_tools: Proxy MCP server for custom tools (if any allowed)
    3. Default MCP servers from mcp/default/ (always included, no filtering)
    4. External MCP servers from global config (filtered by preset)
    5. Extra per-session MCP servers

    Args:
        global_config: Global MCP config (external servers from mcp/*.json).
        allowed_builtin_tools: Built-in tool names (always registered).
        allowed_custom_tools: Custom tool names (preset-filtered).
        session_id: Session ID.
        backend_port: FastAPI backend port.
        allowed_mcp_servers: List of external MCP server names to include.
                             None or ["*"] includes all.
        extra_mcp: Additional per-session MCP config.

    Returns:
        Complete MCPConfig for the session's .mcp.json.
    """
    servers: Dict[str, MCPServerConfig] = {}

    # 1. Add Proxy MCP server for built-in tools (always included if tools exist)
    if allowed_builtin_tools:
        servers["_builtin_tools"] = build_proxy_mcp_server(
            category="builtin",
            allowed_tools=allowed_builtin_tools,
            session_id=session_id,
            backend_port=backend_port,
        )

    # 2. Add Proxy MCP server for custom tools (only if allowed)
    if allowed_custom_tools:
        servers["_custom_tools"] = build_proxy_mcp_server(
            category="custom",
            allowed_tools=allowed_custom_tools,
            session_id=session_id,
            backend_port=backend_port,
        )

    # 3. Add default MCP servers (always included, bypass preset filter)
    default_config = get_default_mcp_config()
    if default_config and default_config.servers:
        for name, config in default_config.servers.items():
            servers[name] = config

    # 4. Add external MCP servers (filtered by preset)
    if global_config and global_config.servers:
        for name, config in global_config.servers.items():
            # Skip internal proxy servers (starts with _)
            if name.startswith("_"):
                continue
            # Apply filter
            if allowed_mcp_servers is None or "*" in allowed_mcp_servers:
                servers[name] = config
            elif name in allowed_mcp_servers:
                servers[name] = config

    # 5. Merge extra per-session config
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
        self.default_dir = self.mcp_dir / "default"
        self.tools_dir = tools_dir or PROJECT_ROOT / "tools"
        self.servers: Dict[str, MCPServerConfig] = {}
        self.default_servers: Dict[str, MCPServerConfig] = {}
        self.tools: List[Any] = []  # Legacy — kept for get_tool_count() compatibility

    def load_all(self) -> MCPConfig:
        """
        Load all MCP configs: defaults + external.

        Returns:
            Global MCP config (external servers only).
        """
        logger.info("=" * 60)
        logger.info("🔌 MCP Loader: Starting...")

        # Register singleton for reload access
        set_mcp_loader_instance(self)

        # 1. Load default MCP configs (mcp/default/*.json — always included)
        self._load_default_configs()

        # 2. Load user MCP configs (mcp/*.json — preset-filtered)
        self._load_mcp_configs()

        # 3. Create global configs
        config = MCPConfig(servers=self.servers)
        set_global_mcp_config(config)

        default_config = MCPConfig(servers=self.default_servers)
        set_default_mcp_config(default_config)

        logger.info(f"🔌 MCP Loader: {len(self.default_servers)} default + {len(self.servers)} external MCP servers")
        logger.info("   ℹ️ Python tools managed by ToolLoader (Proxy MCP pattern)")
        logger.info("=" * 60)

        return config

    def reload_defaults(self) -> None:
        """Reload default MCP configs from mcp/default/.

        Called when a relevant config changes (e.g. GitHub token updated)
        so that environment variable expansions pick up the new values.
        """
        self.default_servers.clear()
        self._load_default_configs()
        default_config = MCPConfig(servers=self.default_servers)
        set_default_mcp_config(default_config)
        logger.info(f"🔄 MCP Loader: Reloaded {len(self.default_servers)} default MCP servers")

    def _load_default_configs(self) -> None:
        """Load JSON config files from mcp/default/ folder.

        Default MCP servers are always included in every session
        regardless of tool preset filtering.
        """
        if not self.default_dir.exists():
            return

        json_files = list(self.default_dir.glob("*.json"))
        if not json_files:
            return

        logger.info(f"📁 Loading default MCP configs from: {self.default_dir}")

        for json_file in json_files:
            try:
                server_name = json_file.stem

                with open(json_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)

                # Expand environment variables
                config_data = self._expand_env_vars(config_data)

                # Skip if required env vars were not resolved
                if self._has_unresolved_env(config_data):
                    logger.info(f"   ⏭️ {server_name}: skipped (missing env vars — configure in Settings)")
                    continue

                server_config = self._create_server_config(config_data)

                if server_config:
                    self.default_servers[server_name] = server_config
                    desc = config_data.get('description', '')
                    logger.info(f"   ✅ [default] {server_name}: {desc[:50]}" + ("..." if len(desc) > 50 else ""))

            except json.JSONDecodeError as e:
                logger.warning(f"   ⚠️ Invalid JSON in default/{json_file.name}: {e}")
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to load default/{json_file.name}: {e}")

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
                if not value:  # None or empty string → treat as unset
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

    @staticmethod
    def _has_unresolved_env(data: Any) -> bool:
        """Check if any ${VAR} references remain unresolved."""
        if isinstance(data, str):
            return bool(re.search(r'\$\{[^}]+\}', data))
        elif isinstance(data, dict):
            return any(MCPLoader._has_unresolved_env(v) for v in data.values())
        elif isinstance(data, list):
            return any(MCPLoader._has_unresolved_env(item) for item in data)
        return False

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
