"""
ToolLoader — Loads and manages all Python-defined tools.

Scans ``tools/built_in/`` and ``tools/custom/`` directories at startup,
instantiates tool objects, and provides them to geny-executor Pipeline
via tool_bridge adaptation.

Built-in tools are always available; custom tools are controlled
by Tool Presets on a per-session basis.

Usage:
    loader = ToolLoader(tools_dir=Path("tools"))
    loader.load_all()

    tool = loader.get_tool("web_search")
    result = tool.run(query="hello")
"""

from __future__ import annotations

import importlib.util
import sys
from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolWrapper, is_tool

logger = getLogger(__name__)


class ToolLoader:
    """Loads Python tools from built_in/ and custom/ directories.

    All tools live in the main FastAPI process so they have full access
    to singletons (AgentSessionManager, ChatStore, etc.).
    """

    def __init__(self, tools_dir: Optional[Path] = None) -> None:
        self.tools_dir = tools_dir or Path(__file__).parent.parent / "tools"
        self.builtin_tools: Dict[str, Any] = {}
        self.custom_tools: Dict[str, Any] = {}

        # Track which file each tool came from (for UI grouping)
        self._tool_source: Dict[str, str] = {}

    def load_all(self) -> None:
        """Scan built_in/ and custom/ directories and load all tools."""
        builtin_dir = self.tools_dir / "built_in"
        custom_dir = self.tools_dir / "custom"

        if builtin_dir.exists():
            self._load_from_dir(builtin_dir, self.builtin_tools, "built_in")
        else:
            logger.warning(f"Built-in tools directory not found: {builtin_dir}")

        if custom_dir.exists():
            self._load_from_dir(custom_dir, self.custom_tools, "custom")
        else:
            logger.warning(f"Custom tools directory not found: {custom_dir}")

        total = len(self.builtin_tools) + len(self.custom_tools)
        logger.info(
            f"🔧 ToolLoader: {total} tools loaded "
            f"(built-in: {len(self.builtin_tools)}, custom: {len(self.custom_tools)})"
        )

    def _load_from_dir(
        self, dir_path: Path, target: Dict[str, Any], category: str
    ) -> None:
        """Load all *_tools.py files from a directory."""
        tool_files = sorted(dir_path.glob("*_tools.py"))

        for tool_file in tool_files:
            try:
                tools = self._load_from_file(tool_file)
                for t in tools:
                    name = getattr(t, "name", None)
                    if not name:
                        continue
                    target[name] = t
                    self._tool_source[name] = tool_file.stem
                if tools:
                    logger.info(
                        f"   ✅ [{category}] {tool_file.name}: {len(tools)} tools"
                    )
                    for t in tools:
                        logger.info(f"      - {getattr(t, 'name', '?')}")
            except Exception as e:
                logger.warning(
                    f"   ⚠️ [{category}] Failed to load {tool_file.name}: {e}"
                )

    def _load_from_file(self, file_path: Path) -> List[Any]:
        """Load tool instances from a single Python file."""
        # Ensure project root is on sys.path
        project_root = str(file_path.parent.parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        module_name = f"tools_loader_{file_path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            return []

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Prefer explicit TOOLS list
        if hasattr(module, "TOOLS"):
            return list(module.TOOLS)

        # Fallback: auto-collect BaseTool/ToolWrapper instances
        tools = []
        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if is_tool(obj):
                tools.append(obj)
        return tools

    # ════════════════════════════════════════════════════════════════════
    # Accessors
    # ════════════════════════════════════════════════════════════════════

    def get_tool(self, name: str) -> Optional[Any]:
        """Get a tool by name (searches both built-in and custom)."""
        return self.builtin_tools.get(name) or self.custom_tools.get(name)

    def get_all_tools(self) -> Dict[str, Any]:
        """Return all loaded tools (built-in + custom)."""
        return {**self.builtin_tools, **self.custom_tools}

    def get_builtin_names(self) -> List[str]:
        """Return names of all built-in tools."""
        return list(self.builtin_tools.keys())

    def get_custom_names(self) -> List[str]:
        """Return names of all custom tools."""
        return list(self.custom_tools.keys())

    def get_all_names(self) -> List[str]:
        """Return names of all tools."""
        return self.get_builtin_names() + self.get_custom_names()

    def get_tool_source(self, name: str) -> Optional[str]:
        """Return the source file stem for a tool (e.g. 'browser_tools')."""
        return self._tool_source.get(name)

    def get_tool_category(self, name: str) -> Optional[str]:
        """Return 'built_in' or 'custom' for a tool name."""
        if name in self.builtin_tools:
            return "built_in"
        if name in self.custom_tools:
            return "custom"
        return None

    def get_tools_by_source(self) -> Dict[str, List[str]]:
        """Group tool names by their source file. Useful for UI grouping."""
        groups: Dict[str, List[str]] = {}
        for name, source in self._tool_source.items():
            groups.setdefault(source, []).append(name)
        return groups

    def get_allowed_tools_for_preset(
        self, preset: Any
    ) -> List[str]:
        """Compute the list of allowed tool names for a ToolPresetDefinition.

        Built-in tools are ALWAYS included.
        Custom tools are included based on preset.custom_tools:
          - ["*"] → all custom tools
          - ["web_search", "browser_navigate"] → only those
          - [] → none
        """
        allowed = list(self.builtin_tools.keys())

        custom_selection = getattr(preset, "custom_tools", [])
        if "*" in custom_selection:
            allowed.extend(self.custom_tools.keys())
        else:
            for name in custom_selection:
                if name in self.custom_tools:
                    allowed.append(name)

        return allowed

    def get_allowed_tools_by_category(
        self, preset: Any
    ) -> tuple[List[str], List[str]]:
        """Compute allowed tool names split by category.

        Returns:
            (builtin_tools, custom_tools) tuple:
            - builtin_tools: All built-in tool names (always included)
            - custom_tools: Custom tool names filtered by preset.custom_tools
        """
        builtin_names = list(self.builtin_tools.keys())

        custom_selection = getattr(preset, "custom_tools", [])
        if "*" in custom_selection:
            custom_names = list(self.custom_tools.keys())
        else:
            custom_names = [
                name for name in custom_selection
                if name in self.custom_tools
            ]

        return builtin_names, custom_names

    def get_tool_info_list(self) -> List[Dict[str, Any]]:
        """Return tool metadata for all tools (for catalog API)."""
        result = []
        for name, tool_obj in self.get_all_tools().items():
            result.append({
                "name": name,
                "description": getattr(tool_obj, "description", "") or "",
                "category": self.get_tool_category(name),
                "group": self.get_tool_source(name),
                "parameters": getattr(tool_obj, "parameters", None),
            })
        return result


# ── Singleton ──

_loader_instance: Optional[ToolLoader] = None


def get_tool_loader() -> ToolLoader:
    """Return the global ToolLoader singleton."""
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = ToolLoader()
    return _loader_instance
