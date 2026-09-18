"""Connector-hosted local MCP servers → FIRST-CLASS session tools.

The desktop connector hosts MCP clients to the user's local MCP servers and
advertises their tool catalog over the ``/ws/connector`` bridge (``hello``
carries ``mcp_catalog``; later ``mcp_catalog`` frames update it). This module
turns that catalog into real, individually-schema'd tools registered into the
LIVE session's executor ToolRegistry:

    mcp_<server>_<tool>   (sanitized, ≤64 chars)

Registering into the live registry bumps its version, which triggers the
per-turn ``state.tools`` rebuild — so the tools appear on the very next
model iteration, on every backend, without a session restart.

The generic ``local_mcp_list`` / ``local_mcp_call`` dispatchers stay as a
fallback (manual exploration + servers that connect mid-turn), but agents no
longer need the two-step indirection: the catalog IS the tool list.

Sync sources (both funnel into :func:`sync_session`):
  * WS hello / ``mcp_catalog`` frames  → connector connected or catalog changed
  * session build                      → session created while connector already up
  * WS close                           → catalog cleared, tools unregistered
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set

from geny_executor.tools.base import ToolCapabilities, ToolContext, ToolResult

from service.executor.connector_bridge import ConnectorCapabilityTool
from service.executor.connector_registry import get_connector_registry

logger = logging.getLogger(__name__)

#: Per-session names WE registered — so sync/clear never touches other tools.
_registered: Dict[str, Set[str]] = {}

_NAME_MAX = 64  # Anthropic tool-name limit; CLI adds mcp__geny__ on top → stay short


def sanitize_mcp_tool_name(server: str, tool: str) -> str:
    """``mcp_<server>_<tool>`` normalized to [a-zA-Z0-9_-], length-capped.

    Same rule for every backend so a given local tool always has one name.
    """
    raw = f"mcp_{server}_{tool}"
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", raw)
    return name[:_NAME_MAX]


class ConnectorLocalMcpTool(ConnectorCapabilityTool):
    """One local MCP tool, exposed first-class; relays via the ``mcp_call``
    capability on the session's connector WebSocket."""

    def __init__(
        self,
        *,
        server: str,
        tool: str,
        description: str,
        input_schema: Optional[Dict[str, Any]],
        annotations: Optional[Dict[str, Any]] = None,
    ) -> None:
        ann = annotations or {}
        read_only = bool(ann.get("readOnlyHint"))
        super().__init__(
            name=sanitize_mcp_tool_name(server, tool),
            description=(
                f"[local MCP · {server}] {description or tool}"
            ),
            input_schema=input_schema or {"type": "object", "properties": {}},
            capability="mcp_call",
            read_only=read_only,
            # Local MCP tools act on the user's machine — same posture as
            # local_mcp_call unless the server says read-only.
            destructive=not read_only,
            reason=f"local MCP tool {server}/{tool}",
            timeout=120.0,
        )
        self._server = server
        self._tool = tool

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        reg = get_connector_registry()
        conn = reg.get(context.session_id)
        if conn is None:
            return ToolResult(
                content="connector offline — no desktop session is connected", is_error=True
            )
        if "mcp_call" not in conn.accepted_capabilities:
            return ToolResult(
                content="this connector does not support local MCP calls", is_error=True
            )
        try:
            payload = await conn.capability_call(
                "mcp_call",
                {"server": self._server, "tool": self._tool, "args": input or {}},
                self._reason,
                timeout=self._timeout,
            )
        except Exception as exc:  # transport / timeout — clean is_error, never raw
            return ToolResult(content=f"connector transport error: {exc}", is_error=True)
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("error") or (
                "denied by the user" if (payload or {}).get("denied") else "local MCP call failed"
            )
            return ToolResult(content=str(msg), is_error=True)
        return _map_mcp_result(payload.get("result"))


def _map_mcp_result(result: Any) -> ToolResult:
    """Raw MCP ``CallToolResult`` → executor ToolResult.

    Text parts join into text; image parts become the executor's canonical
    image blocks (same shape as message images, so vision works on the
    Anthropic API and via the CLI bridge's ``_to_mcp_content``)."""
    if not isinstance(result, dict):
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return ToolResult(content=content)
    parts = result.get("content")
    if not isinstance(parts, list):
        return ToolResult(
            content=json.dumps(result, ensure_ascii=False),
            is_error=bool(result.get("isError")),
        )
    blocks: List[Any] = []
    texts: List[str] = []
    has_image = False
    for p in parts:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "text":
            texts.append(str(p.get("text") or ""))
            blocks.append({"type": "text", "text": str(p.get("text") or "")})
        elif p.get("type") == "image" and p.get("data"):
            has_image = True
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": p.get("mimeType") or "image/png",
                        "data": p.get("data"),
                    },
                }
            )
    is_error = bool(result.get("isError"))
    if has_image:
        return ToolResult(content=blocks or [{"type": "text", "text": ""}], is_error=is_error)
    return ToolResult(content="\n".join(t for t in texts if t) or "(empty result)", is_error=is_error)


# ─── catalog → live registry sync ────────────────────────────────────


def _desired_tools(catalog: Any) -> Dict[str, ConnectorLocalMcpTool]:
    """Catalog (list of server adverts) → {tool_name: Tool} for connected,
    non-errored servers."""
    desired: Dict[str, ConnectorLocalMcpTool] = {}
    if not isinstance(catalog, list):
        return desired
    for srv in catalog:
        if not isinstance(srv, dict):
            continue
        server = str(srv.get("name") or "").strip()
        if not server or srv.get("connected") is False:
            continue
        for t in srv.get("tools") or []:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            tool = ConnectorLocalMcpTool(
                server=server,
                tool=str(t["name"]),
                description=str(t.get("description") or ""),
                input_schema=t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else None,
                annotations=t.get("annotations") if isinstance(t.get("annotations"), dict) else None,
            )
            desired[tool.name] = tool
    return desired


def _live_registry(session_id: str) -> Optional[Any]:
    """The live session's executor ToolRegistry, or None (session not live).

    Non-blocking ``get_agent`` — same rationale as the mcp bridge: never take
    the rehydrate lock from a bridge/WS context."""
    try:
        from service.executor.agent_session_manager import get_agent_session_manager

        agent = get_agent_session_manager().get_agent(session_id)
        if agent is None:
            return None
        pipeline = getattr(agent, "_pipeline", None)
        return getattr(pipeline, "_tool_registry", None) if pipeline is not None else None
    except Exception:  # noqa: BLE001 — sync must never break the WS/build path
        logger.debug("connector_mcp: no live registry for %s", session_id, exc_info=True)
        return None


def sync_session(session_id: str, catalog: Any, registry: Optional[Any] = None) -> Dict[str, int]:
    """Diff-register the catalog's tools into the live session registry.

    Idempotent; returns counts. A missing live registry is a no-op (the
    session-build hook will sync when the session comes up). *registry* can be
    passed explicitly at session build, when the pipeline exists but the agent
    is not yet resolvable through the manager."""
    if registry is None:
        registry = _live_registry(session_id)
    if registry is None:
        return {"registered": 0, "removed": 0, "skipped": 1}
    desired = _desired_tools(catalog)
    have = _registered.setdefault(session_id, set())
    removed = 0
    for name in list(have):
        if name not in desired:
            try:
                registry.unregister(name)
            except Exception:  # noqa: BLE001
                pass
            have.discard(name)
            removed += 1
    added = 0
    for name, tool in desired.items():
        if name in have and registry.get(name) is not None:
            continue
        try:
            registry.register(tool, core=True)
            have.add(name)
            added += 1
        except Exception:  # noqa: BLE001
            logger.warning("connector_mcp: register failed for %s", name, exc_info=True)
    if added or removed:
        logger.info(
            "connector_mcp[%s]: %d local MCP tool(s) live (+%d/-%d)",
            session_id[:8], len(have), added, removed,
        )
    return {"registered": added, "removed": removed, "skipped": 0}


def clear_session(session_id: str) -> int:
    """Unregister everything we registered for this session (connector gone)."""
    have = _registered.pop(session_id, set())
    if not have:
        return 0
    registry = _live_registry(session_id)
    if registry is not None:
        for name in have:
            try:
                registry.unregister(name)
            except Exception:  # noqa: BLE001
                pass
        logger.info("connector_mcp[%s]: cleared %d local MCP tool(s)", session_id[:8], len(have))
    return len(have)


def sync_from_registry(session_id: str, registry: Optional[Any] = None) -> Dict[str, int]:
    """Sync using the catalog already held by the session's connector (if any).

    Called at session build so a session created AFTER the connector connected
    still gets the tools; pass the freshly built pipeline's registry directly
    (the agent isn't in the manager yet at that point)."""
    conn = get_connector_registry().get(session_id)
    catalog = getattr(conn, "mcp_catalog", None) if conn is not None else None
    if not catalog:
        return {"registered": 0, "removed": 0, "skipped": 1}
    return sync_session(session_id, catalog, registry=registry)
