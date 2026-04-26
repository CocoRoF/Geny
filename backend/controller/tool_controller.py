"""
Tool Controller — REST API for the tool catalog.

Provides read-only endpoints to browse all available tools
(built-in Python tools, custom Python tools, external MCP servers).
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from service.tool_loader import get_tool_loader
from service.mcp_loader import get_global_mcp_config, get_builtin_mcp_config, get_mcp_loader_instance

logger = getLogger(__name__)

router = APIRouter(prefix="/api/tools", tags=["tools"])


# ════════════════════════════════════════════════════════════════════════════
# Response Models
# ════════════════════════════════════════════════════════════════════════════


class ToolInfo(BaseModel):
    """Metadata for a single Python tool."""
    name: str
    description: str = ""
    category: str = ""         # "built_in" or "custom"
    group: Optional[str] = None  # source file stem (e.g. "browser_tools")
    parameters: Optional[Dict[str, Any]] = None


class MCPServerInfo(BaseModel):
    """Metadata for an external MCP server."""
    name: str
    type: str  # "stdio", "http", "sse"
    description: str = ""
    is_built_in: bool = False  # True for mcp/built_in/ servers (always included)
    source: str = ""  # "built_in" or "custom"


class ToolCatalogResponse(BaseModel):
    """Full tool catalog."""
    built_in: List[ToolInfo] = Field(default_factory=list)
    custom: List[ToolInfo] = Field(default_factory=list)
    mcp_servers: List[MCPServerInfo] = Field(default_factory=list)
    total_python_tools: int = 0
    total_mcp_servers: int = 0


# ════════════════════════════════════════════════════════════════════════════
# Endpoints
# ════════════════════════════════════════════════════════════════════════════


@router.get("/catalog", response_model=ToolCatalogResponse)
async def get_catalog():
    """Return the full tool catalog (built-in + custom + MCP servers)."""
    loader = get_tool_loader()

    built_in_tools = _tools_to_info(loader.builtin_tools, "built_in", loader)
    custom_tools = _tools_to_info(loader.custom_tools, "custom", loader)
    mcp_servers = _get_mcp_server_info()

    return ToolCatalogResponse(
        built_in=built_in_tools,
        custom=custom_tools,
        mcp_servers=mcp_servers,
        total_python_tools=len(built_in_tools) + len(custom_tools),
        total_mcp_servers=len(mcp_servers),
    )


@router.get("/catalog/built-in", response_model=List[ToolInfo])
async def get_builtin_tools():
    """Return all built-in Python tools."""
    loader = get_tool_loader()
    return _tools_to_info(loader.builtin_tools, "built_in", loader)


# ── Executor framework tools (PR-E.1.1) ──────────────────────────────
#
# *Different* concept from /catalog/built-in above. The endpoint above
# lists Geny's tool_loader builtins (web_search / browser / memory_*).
# This endpoint lists the geny-executor framework's BUILT_IN_TOOL_CLASSES
# (Read / Write / Edit / Bash / AgentTool / TaskCreate / ... — the 33
# tools shipped with executor 1.0.0~1.3.0).
#
# These are the tools every executor consumer gets out of the box; the
# UI surface (ToolCatalogTab) shows them grouped by feature_group with
# input_schema + capabilities.


class FrameworkToolDetail(BaseModel):
    """Detailed metadata for a single executor framework built-in tool."""
    name: str
    description: str = ""
    feature_group: str = "uncategorized"
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class FrameworkCatalogResponse(BaseModel):
    """Full executor framework catalog response."""
    tools: List[FrameworkToolDetail] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    total: int = 0


def build_framework_tool_index() -> Dict[str, FrameworkToolDetail]:
    """Inspect every executor BUILT_IN_TOOL_CLASSES entry once.

    Returns a {name: FrameworkToolDetail} mapping. Used by:
      - GET /api/tools/catalog/framework (list view)
      - GET /api/environments/{id}/tools/resolved (PR-E.1.3)

    Empty dict when geny-executor isn't importable.
    """
    try:
        from geny_executor.tools.built_in import (
            BUILT_IN_TOOL_CLASSES,
            BUILT_IN_TOOL_FEATURES,
        )
    except ImportError:
        return {}

    name_to_group: Dict[str, str] = {}
    for group, names in BUILT_IN_TOOL_FEATURES.items():
        for name in names:
            name_to_group[name] = group

    index: Dict[str, FrameworkToolDetail] = {}
    for name, cls in BUILT_IN_TOOL_CLASSES.items():
        try:
            inst = cls()
            description = inst.description or ""
            input_schema = inst.input_schema or {}
            try:
                caps_obj = inst.capabilities({})
                capabilities = {
                    k: getattr(caps_obj, k)
                    for k in (
                        "concurrency_safe", "read_only", "destructive",
                        "idempotent", "network_egress", "interrupt",
                        "max_result_chars",
                    )
                    if hasattr(caps_obj, k)
                }
            except Exception:
                capabilities = {}
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "framework_tool_inspect_failed name=%s err=%s", name, exc,
            )
            description = ""
            input_schema = {}
            capabilities = {}

        index[name] = FrameworkToolDetail(
            name=name,
            description=description,
            feature_group=name_to_group.get(name, "uncategorized"),
            capabilities=capabilities,
            input_schema=input_schema,
        )
    return index


def framework_feature_groups() -> List[str]:
    """Sorted list of BUILT_IN_TOOL_FEATURES keys; empty on import failure."""
    try:
        from geny_executor.tools.built_in import BUILT_IN_TOOL_FEATURES
    except ImportError:
        return []
    return sorted(BUILT_IN_TOOL_FEATURES.keys())


@router.get("/catalog/framework", response_model=FrameworkCatalogResponse)
async def get_framework_tools():
    """List every tool in geny-executor's BUILT_IN_TOOL_CLASSES.

    Each row carries enough metadata for the UI catalog viewer to
    render description / capability badges / JSONSchema preview without
    a follow-up request.

    Empty (graceful) when geny-executor isn't importable.
    """
    index = build_framework_tool_index()
    tools = sorted(index.values(), key=lambda t: (t.feature_group, t.name))
    return FrameworkCatalogResponse(
        tools=tools,
        groups=framework_feature_groups(),
        total=len(tools),
    )


@router.get("/catalog/custom", response_model=List[ToolInfo])
async def get_custom_tools():
    """Return all custom Python tools."""
    loader = get_tool_loader()
    return _tools_to_info(loader.custom_tools, "custom", loader)


@router.get("/catalog/mcp-servers", response_model=List[MCPServerInfo])
async def get_mcp_servers():
    """Return all external MCP servers."""
    return _get_mcp_server_info()


# ── External tool catalog (T.1 / cycle 20260426_2) ─────────────────


class ExternalToolEntry(BaseModel):
    """One Geny-provided tool that a manifest can attach via
    ``manifest.tools.external``. Mirrors the shape of ``ToolInfo`` but
    only carries the fields the picker UI needs."""

    name: str
    category: str = Field(..., description='"built_in" | "custom"')
    description: str = ""


class ExternalToolCatalogResponse(BaseModel):
    tools: List[ExternalToolEntry] = Field(default_factory=list)
    note: str = (
        "These are the tools GenyToolProvider advertises. The manifest's "
        "``tools.external`` whitelist controls which ones attach per session."
    )


@router.get("/catalog/external", response_model=ExternalToolCatalogResponse)
async def get_external_tools():
    """T.1 (cycle 20260426_2) — names that ``GenyToolProvider`` would
    surface to the executor as candidates for ``manifest.tools.external``.

    Returns Geny's tool_loader contents (built-in + custom) flattened
    into a single picker list. Matches the contract
    ``GenyToolProvider.list_names()`` would emit at session boot.
    """
    loader = get_tool_loader()
    out: List[ExternalToolEntry] = []
    for name, tool in (loader.builtin_tools or {}).items():
        out.append(ExternalToolEntry(
            name=name,
            category="built_in",
            description=getattr(tool, "description", "") or "",
        ))
    for name, tool in (loader.custom_tools or {}).items():
        out.append(ExternalToolEntry(
            name=name,
            category="custom",
            description=getattr(tool, "description", "") or "",
        ))
    out.sort(key=lambda r: (r.category != "built_in", r.name))
    return ExternalToolCatalogResponse(tools=out)


# ════════════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════════════


def _tools_to_info(
    tools_dict: Dict[str, Any], category: str, loader: Any
) -> List[ToolInfo]:
    """Convert tool dict to ToolInfo list."""
    result = []
    for name, tool_obj in tools_dict.items():
        result.append(
            ToolInfo(
                name=name,
                description=getattr(tool_obj, "description", "") or "",
                category=category,
                group=loader.get_tool_source(name),
                parameters=getattr(tool_obj, "parameters", None),
            )
        )
    return result


def _get_mcp_server_info() -> List[MCPServerInfo]:
    """Get info for all MCP servers (built-in + custom)."""
    result = []
    seen = set()
    loader = get_mcp_loader_instance()
    descriptions = loader.server_descriptions if loader else {}
    builtin_names = loader.builtin_server_names if loader else set()

    # 1. Built-in MCP servers (always included)
    builtin_config = get_builtin_mcp_config()
    if builtin_config and builtin_config.servers:
        for name, server in builtin_config.servers.items():
            if name.startswith("_"):
                continue
            server_type = type(server).__name__.replace("MCPServer", "").lower()
            result.append(MCPServerInfo(
                name=name,
                type=server_type,
                description=descriptions.get(name, ""),
                is_built_in=True,
                source="built_in",
            ))
            seen.add(name)

    # 2. Custom MCP servers (user-configured, preset-filtered)
    config = get_global_mcp_config()
    if config and config.servers:
        for name, server in config.servers.items():
            if name.startswith("_") or name in seen:
                continue
            server_type = type(server).__name__.replace("MCPServer", "").lower()
            result.append(MCPServerInfo(
                name=name,
                type=server_type,
                description=descriptions.get(name, ""),
                is_built_in=name in builtin_names,
                source="custom",
            ))

    return result
