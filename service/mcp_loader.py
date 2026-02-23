"""
MCP Loader

Automatically loads JSON configs from mcp/ folder and tools from tools/ folder
to create global MCP configurations available for all Claude Code sessions.

Usage:
    from service.mcp_loader import MCPLoader, get_global_mcp_config

    # Initialize and load
    loader = MCPLoader()
    loader.load_all()

    # Get global MCP config
    config = get_global_mcp_config()
"""
import asyncio
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


class MCPLoader:
    """
    Auto-loader for MCP configs and tools

    Loads JSON files from mcp/ folder and Python tools from tools/ folder
    to create unified MCP configuration.
    """

    def __init__(
        self,
        mcp_dir: Optional[Path] = None,
        tools_dir: Optional[Path] = None
    ):
        """
        Args:
            mcp_dir: MCP JSON config folder path (default: project_root/mcp)
            tools_dir: Tools folder path (default: project_root/tools)
        """
        self.mcp_dir = mcp_dir or PROJECT_ROOT / "mcp"
        self.tools_dir = tools_dir or PROJECT_ROOT / "tools"
        self.servers: Dict[str, MCPServerConfig] = {}
        self.tools: List[Any] = []
        self._tools_mcp_process = None

    def load_all(self) -> MCPConfig:
        """
        Load all MCP configs and tools

        Returns:
            Unified MCP config
        """
        logger.info("=" * 60)
        logger.info("🔌 MCP Loader: Starting...")

        # 1. Load JSON configs from mcp/ folder
        self._load_mcp_configs()

        # 2. Load tools from tools/ folder
        self._load_tools()

        # 3. Convert tools to MCP server
        if self.tools:
            self._register_tools_as_mcp()

        # 4. Create global config
        config = MCPConfig(servers=self.servers)
        set_global_mcp_config(config)

        logger.info(f"🔌 MCP Loader: Loaded {len(self.servers)} MCP servers")
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

    def _load_tools(self) -> None:
        """Load tool files from tools/ folder"""
        if not self.tools_dir.exists():
            logger.info(f"📁 Tools directory not found: {self.tools_dir}")
            return

        # Find *_tool.py or *_tools.py files
        tool_files = list(self.tools_dir.glob("*_tool.py")) + list(self.tools_dir.glob("*_tools.py"))

        if not tool_files:
            logger.info(f"📁 No tool files in: {self.tools_dir}")
            return

        logger.info(f"📁 Loading tools from: {self.tools_dir}")

        # Add tools package to sys.path
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))

        for tool_file in tool_files:
            try:
                tools = self._load_tools_from_file(tool_file)
                if tools:
                    self.tools.extend(tools)
                    logger.info(f"   ✅ {tool_file.name}: {len(tools)} tools")
                    for t in tools:
                        name = getattr(t, 'name', t.__name__ if hasattr(t, '__name__') else str(t))
                        logger.info(f"      - {name}")

            except Exception as e:
                logger.warning(f"   ⚠️ Failed to load {tool_file.name}: {e}")

    def _load_tools_from_file(self, file_path: Path) -> List[Any]:
        """Load tools from file"""
        # Dynamically load module
        spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[file_path.stem] = module
        spec.loader.exec_module(module)

        # Use TOOLS list if defined
        if hasattr(module, 'TOOLS'):
            return list(module.TOOLS)

        # Otherwise auto-collect
        tools = []
        from tools.base import is_tool

        for name in dir(module):
            if name.startswith('_'):
                continue
            obj = getattr(module, name)
            if is_tool(obj):
                tools.append(obj)

        return tools

    def _register_tools_as_mcp(self) -> None:
        """Register loaded tools as built-in MCP server"""
        if not self.tools:
            return

        # Create tools MCP server script path
        tools_server_script = self._create_tools_server_script()

        if tools_server_script:
            # Python executable path
            python_exe = sys.executable

            self.servers["_builtin_tools"] = MCPServerStdio(
                command=python_exe,
                args=[str(tools_server_script)],
                env=None
            )

            logger.info(f"   🔧 Registered {len(self.tools)} tools as MCP server: _builtin_tools")

    def _create_tools_server_script(self) -> Optional[Path]:
        """
        Create script to run tools as MCP server
        """
        # Collect tool file list
        tool_files = list(self.tools_dir.glob("*_tool.py")) + list(self.tools_dir.glob("*_tools.py"))

        if not tool_files:
            return None

        # Create script
        script_path = self.tools_dir / "_mcp_server.py"

        imports = []
        tool_names = []

        for tool_file in tool_files:
            module_name = tool_file.stem

            # Collect tool names from this module
            spec = importlib.util.spec_from_file_location(module_name, tool_file)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except Exception:
                continue

            if hasattr(module, 'TOOLS'):
                imports.append(f"from tools.{module_name} import TOOLS as {module_name}_TOOLS")
                tool_names.append(f"*{module_name}_TOOLS")

        if not imports:
            return None

        script_content = f'''#!/usr/bin/env python3
"""
Auto-generated MCP Server for tools/
This file is auto-generated. Do not edit manually.
"""
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import tools
{chr(10).join(imports)}

# Create MCP server
mcp = FastMCP("builtin-tools")

# Collect all tools
all_tools = []
{chr(10).join(f"all_tools.extend({name.replace('*', '')})" for name in tool_names)}

# Register each tool to MCP
for tool_obj in all_tools:
    name = getattr(tool_obj, 'name', None)
    if not name and hasattr(tool_obj, '__name__'):
        name = tool_obj.__name__
    if not name:
        continue

    description = getattr(tool_obj, 'description', '') or getattr(tool_obj, '__doc__', '') or f"Tool: {{name}}"

    # Find run or arun method
    if hasattr(tool_obj, 'arun'):
        func = tool_obj.arun
    elif hasattr(tool_obj, 'run'):
        func = tool_obj.run
    elif callable(tool_obj):
        func = tool_obj
    else:
        continue

    # Register as MCP tool
    wrapper = mcp.tool()(func)
    wrapper.__name__ = name
    wrapper.__doc__ = description

if __name__ == "__main__":
    mcp.run(transport="stdio")
'''

        with open(script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)

        logger.info(f"   📝 Generated MCP server script: {script_path}")

        return script_path

    def get_server_count(self) -> int:
        """Return number of loaded servers"""
        return len(self.servers)

    def get_tool_count(self) -> int:
        """Return number of loaded tools"""
        return len(self.tools)

    def get_config(self) -> MCPConfig:
        """Return current MCP config"""
        return MCPConfig(servers=self.servers)


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
