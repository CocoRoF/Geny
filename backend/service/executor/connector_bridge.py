"""Executor-side capability tools (inverse MCP).

A ConnectorCapabilityTool mirrors MCPToolAdapter 1:1, but instead of calling an
MCP server it sends a ``capability_call`` over the session's connector WebSocket
(via ConnectorRegistry) and awaits the ``capability_result``. The native work
runs on the user's machine (in the connector); the server only proxies.

Registered through a duck-typed AdhocToolProvider (list_names/get) beside
GenyToolProvider; ``manifest.tools.external`` selects which capabilities a
session actually exposes (so adding the provider is inert until a manifest opts
in). Subclasses the already-installed geny_executor Tool ABC — no executor
reinstall needed.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

from geny_executor.tools.base import Tool, ToolCapabilities, ToolContext, ToolResult

from service.executor.connector_registry import get_connector_registry


class ConnectorCapabilityTool(Tool):
    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        capability: str,
        read_only: bool = True,
        destructive: bool = False,
        reason: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._name = name
        self._description = description
        self._schema = input_schema
        self._capability = capability
        self._read_only = read_only
        self._destructive = destructive
        self._reason = reason
        self._timeout = timeout

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> Dict[str, Any]:
        return self._schema

    def capabilities(self, input: Dict[str, Any]) -> ToolCapabilities:
        # destructive → matrix auto-escalates to ASK under PLAN mode; read-only
        # tools may fan out concurrently.
        return ToolCapabilities(
            read_only=self._read_only,
            destructive=self._destructive,
            concurrency_safe=self._read_only and not self._destructive,
        )

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        reg = get_connector_registry()
        conn = reg.get(context.session_id)
        if conn is None:
            return ToolResult(content="connector offline — no desktop session is connected", is_error=True)
        if self._capability not in conn.accepted_capabilities:
            return ToolResult(
                content=f"capability '{self._capability}' is not supported by this connector", is_error=True
            )
        try:
            payload = await conn.capability_call(self._capability, input, self._reason, timeout=self._timeout)
        except Exception as exc:  # transport / timeout — clean is_error, never raw
            return ToolResult(content=f"connector transport error: {exc}", is_error=True)
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("error") or ("denied by the user" if (payload or {}).get("denied") else "capability failed")
            return ToolResult(content=str(msg), is_error=True)
        result = payload.get("result")
        content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return ToolResult(content=content)


class DesktopGlanceTool(ConnectorCapabilityTool):
    """Capture a fresh frame of the user's screen via the connector, caption it
    with the vision LLM, and return the caption text (the agent can't read raw
    bytes). Read-only; uses the existing screen-observation caption path WITHOUT
    firing the proactive [USER_OBSERVATION] trigger (no cooldown-bypass spam)."""

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        reg = get_connector_registry()
        conn = reg.get(context.session_id)
        if conn is None:
            return ToolResult(content="connector offline — no desktop session is connected", is_error=True)
        if "screen_capture" not in conn.accepted_capabilities:
            return ToolResult(content="screen capture is not available on this connector", is_error=True)
        try:
            payload = await conn.capability_call("screen_capture", input, "agent desktop glance", timeout=30.0)
        except Exception as exc:
            return ToolResult(content=f"connector transport error: {exc}", is_error=True)
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("error") or ("denied by the user" if (payload or {}).get("denied") else "capture failed")
            return ToolResult(content=str(msg), is_error=True)
        result = payload.get("result") or {}
        b64 = result.get("image_b64")
        if not b64:
            return ToolResult(content="connector returned no image", is_error=True)
        mime = result.get("mime", "image/jpeg")
        label = result.get("source_name") or "screen"
        try:
            raw = base64.b64decode(b64.split(",", 1)[-1])  # tolerate a data: URL prefix
            from service.vtuber.screen_observation import _caption_image

            caption, source = await _caption_image(raw, mime_type=mime)
        except Exception as exc:
            return ToolResult(content=f"caption failed: {exc}", is_error=True)
        if caption:
            return ToolResult(content=f"[desktop glance — {label}] {caption}")
        return ToolResult(content=f"[desktop glance — {label}] (no caption available; vision {source})")


class DesktopScreenshotTool(ConnectorCapabilityTool):
    """Capture the user's screen and return the IMAGE for the model to SEE
    (vision) — unlike desktop_glance which returns a text caption. The connector
    captures at native resolution (``full_res``) so the image's pixel coordinates
    match the screen, letting desktop_click target what the model sees.

    Requires a vision-capable model — the image rides as a canonical image
    content block on the tool result, which every provider path renders."""

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        reg = get_connector_registry()
        conn = reg.get(context.session_id)
        if conn is None:
            return ToolResult(content="connector offline — no desktop session is connected", is_error=True)
        if "screen_capture" not in conn.accepted_capabilities:
            return ToolResult(content="screen capture is not available on this connector", is_error=True)
        args: Dict[str, Any] = {"full_res": True}
        if input.get("source_id"):
            args["source_id"] = input["source_id"]
        try:
            payload = await conn.capability_call("screen_capture", args, "agent screenshot", timeout=30.0)
        except Exception as exc:
            return ToolResult(content=f"connector transport error: {exc}", is_error=True)
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("error") or ("denied by the user" if (payload or {}).get("denied") else "capture failed")
            return ToolResult(content=str(msg), is_error=True)
        result = payload.get("result") or {}
        b64 = result.get("image_b64")
        if not b64:
            return ToolResult(content="connector returned no image", is_error=True)
        mime = result.get("mime", "image/jpeg")
        w, h = result.get("width"), result.get("height")
        label = result.get("source_name") or "screen"
        data = b64.split(",", 1)[-1] if isinstance(b64, str) and b64.startswith("data:") else b64
        dims = f"{w}×{h}" if w and h else "the shown size"
        note = (
            f"[screenshot — {label}, {dims} px] This is the user's primary screen right now. "
            "To click something, call desktop_click with the pixel coordinates AS SEEN IN THIS IMAGE "
            "(top-left is 0,0)."
        )
        # Canonical content blocks: a text note + a canonical image block
        # ({type:image, source:{type:base64, media_type, data}}). This is the
        # SAME shape the executor uses for message images, so it renders
        # natively on every provider path. See docs/connector-local-bridge-plan.
        return ToolResult(content=[
            {"type": "text", "text": note},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}},
        ])


class BrowserScreenshotTool(ConnectorCapabilityTool):
    """Screenshot of a tab in the automation browser, returned as an IMAGE
    content block so the model can SEE the page (same canonical shape as
    DesktopScreenshotTool). Interaction should still go through
    browser_snapshot/browser_act element ids — no pixel-coordinate clicking."""

    async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
        reg = get_connector_registry()
        conn = reg.get(context.session_id)
        if conn is None:
            return ToolResult(content="connector offline — no desktop session is connected", is_error=True)
        if self._capability not in conn.accepted_capabilities:
            return ToolResult(content="browser control is not supported by this connector (needs ≥0.17)", is_error=True)
        try:
            payload = await conn.capability_call(self._capability, input, self._reason, timeout=self._timeout)
        except Exception as exc:
            return ToolResult(content=f"connector transport error: {exc}", is_error=True)
        if not isinstance(payload, dict) or not payload.get("ok"):
            msg = (payload or {}).get("error") or ("denied by the user" if (payload or {}).get("denied") else "screenshot failed")
            return ToolResult(content=str(msg), is_error=True)
        result = payload.get("result") or {}
        b64 = result.get("image_b64")
        if not b64:
            return ToolResult(content="connector returned no image", is_error=True)
        data = b64.split(",", 1)[-1] if isinstance(b64, str) and b64.startswith("data:") else b64
        title = result.get("title") or ""
        url = result.get("url") or ""
        note = (
            f"[browser screenshot — {title or 'tab'} | {url}] Visual state of the automation-browser tab. "
            "To interact, use browser_snapshot for element ids and browser_act — not pixel coordinates."
        )
        return ToolResult(content=[
            {"type": "text", "text": note},
            {"type": "image", "source": {"type": "base64", "media_type": result.get("mime", "image/jpeg"), "data": data}},
        ])


def _build_tools() -> Dict[str, ConnectorCapabilityTool]:
    """The capability tools advertised to sessions. ``manifest.tools.external``
    selects which a given session actually exposes."""
    tools: Dict[str, ConnectorCapabilityTool] = {
        # ── bridge health ──
        "connector_ping": ConnectorCapabilityTool(
            name="connector_ping",
            description="Ping the user's desktop connector to confirm the capability bridge is live.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="ping",
            read_only=True,
            reason="capability-bridge health check",
            timeout=10.0,
        ),
        # ── Phase 4: desktop awareness (read-only) ──
        "desktop_glance": DesktopGlanceTool(
            name="desktop_glance",
            description=(
                "Look at the user's screen right now: captures a frame and returns a description "
                "of what is visible. Use when the user refers to what's on their screen."
            ),
            input_schema={
                "type": "object",
                "properties": {"source_id": {"type": "string", "description": "Optional capture source id from desktop_window_list; defaults to the primary screen."}},
                "additionalProperties": False,
            },
            capability="screen_capture",
            read_only=True,
            reason="agent desktop glance",
            timeout=30.0,
        ),
        "desktop_window_list": ConnectorCapabilityTool(
            name="desktop_window_list",
            description="List the user's open windows and screens (titles + capture source ids).",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="window_list",
            read_only=True,
            reason="agent enumerates windows",
            timeout=10.0,
        ),
        "desktop_screenshot": DesktopScreenshotTool(
            name="desktop_screenshot",
            description=(
                "Take a screenshot of the user's screen and SEE it (the image is returned to you). "
                "Use this to look at the screen before clicking — read what's shown and pick pixel "
                "coordinates for desktop_click. Prefer this over desktop_glance when you need to act."
            ),
            input_schema={
                "type": "object",
                "properties": {"source_id": {"type": "string", "description": "Optional capture source id; defaults to the primary screen."}},
                "additionalProperties": False,
            },
            capability="screen_capture",
            read_only=True,
            reason="agent screenshot",
            timeout=30.0,
        ),
        # ── Phase 6: guarded actuation (destructive → ASK/HITL + connector master switch) ──
        "desktop_open_app": ConnectorCapabilityTool(
            name="desktop_open_app",
            description="Open an application or URL/path on the user's desktop.",
            input_schema={
                "type": "object",
                "properties": {"target": {"type": "string", "description": "App name, file path, or URL to open."}},
                "required": ["target"],
                "additionalProperties": False,
            },
            capability="open_app",
            read_only=False,
            destructive=True,
            reason="agent opens an app",
            timeout=20.0,
        ),
        "desktop_clipboard_write": ConnectorCapabilityTool(
            name="desktop_clipboard_write",
            description="Write text to the user's clipboard.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            capability="clipboard_write",
            read_only=False,
            destructive=True,
            reason="agent writes the clipboard",
            timeout=10.0,
        ),
        "desktop_type": ConnectorCapabilityTool(
            name="desktop_type",
            description="Type text at the user's current keyboard focus (native input synthesis).",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
                "additionalProperties": False,
            },
            capability="type",
            read_only=False,
            destructive=True,
            reason="agent types on the user's machine",
            timeout=20.0,
        ),
        "desktop_key": ConnectorCapabilityTool(
            name="desktop_key",
            description="Press a key or chord (e.g. 'enter', 'ctrl+s') on the user's machine.",
            input_schema={
                "type": "object",
                "properties": {"keys": {"type": "string", "description": "e.g. 'enter' or 'ctrl+s'"}},
                "required": ["keys"],
                "additionalProperties": False,
            },
            capability="key",
            read_only=False,
            destructive=True,
            reason="agent presses keys",
            timeout=15.0,
        ),
        "desktop_click": ConnectorCapabilityTool(
            name="desktop_click",
            description="Move the mouse and click at absolute screen coordinates.",
            input_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                },
                "required": ["x", "y"],
                "additionalProperties": False,
            },
            capability="click",
            read_only=False,
            destructive=True,
            reason="agent clicks on the user's machine",
            timeout=15.0,
        ),
        "desktop_scroll": ConnectorCapabilityTool(
            name="desktop_scroll",
            description="Scroll the mouse wheel at the current cursor position. Positive `amount` scrolls DOWN, negative UP (in wheel steps).",
            input_schema={
                "type": "object",
                "properties": {"amount": {"type": "integer", "description": "wheel steps; positive = down, negative = up"}},
                "required": ["amount"],
                "additionalProperties": False,
            },
            capability="scroll",
            read_only=False,
            destructive=True,
            reason="agent scrolls the user's screen",
            timeout=10.0,
        ),
        # ── Local MCP proxy (Phase 4): the connector hosts MCP clients to the
        #    user's LOCAL MCP servers; these two tools discover + call them. ──
        "local_mcp_list": ConnectorCapabilityTool(
            name="local_mcp_list",
            description=(
                "List the user's LOCAL MCP servers and their tools (hosted by the desktop connector). "
                "Call this first to discover what local MCP tools are available, then use local_mcp_call. "
                "Returns [{name, connected, error?, tools:[{name, description, inputSchema}]}]."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="mcp_list",
            read_only=True,
            reason="agent lists local MCP tools",
            timeout=30.0,
        ),
        "local_mcp_call": ConnectorCapabilityTool(
            name="local_mcp_call",
            description=(
                "Call a tool on one of the user's LOCAL MCP servers (via the desktop connector). "
                "Use local_mcp_list first to find the server name, tool name, and its input schema. "
                "`args` is the tool's arguments object."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP server name from local_mcp_list."},
                    "tool": {"type": "string", "description": "Tool name on that server."},
                    "args": {"type": "object", "description": "Arguments object for the tool.", "default": {}},
                },
                "required": ["server", "tool"],
                "additionalProperties": False,
            },
            capability="mcp_call",
            read_only=False,
            destructive=True,
            reason="agent calls a local MCP tool",
            timeout=120.0,
        ),
        # ── Structured browser control (Phase 7, connector ≥0.17) ────────────
        # A dedicated Chrome/Edge automation instance on the user's machine,
        # driven over CDP. Element-addressed (snapshot → eN ids → act), not
        # coordinate-blind: no pixel mapping, trusted input events.
        "browser_tabs": ConnectorCapabilityTool(
            name="browser_tabs",
            description=(
                "List the tabs of the agent's automation browser on the user's machine (a dedicated "
                "Chrome/Edge window, separate from the user's own browsing). Shows whether it is running. "
                "Use browser_open to launch it / open pages."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="browser_tabs",
            read_only=True,
            reason="agent lists browser tabs",
            timeout=20.0,
        ),
        "browser_open": ConnectorCapabilityTool(
            name="browser_open",
            description=(
                "Open a URL in the automation browser on the user's machine (launches the dedicated "
                "Chrome/Edge window if needed — the user can watch and intervene). Without tab_id opens a "
                "NEW tab; with tab_id navigates that tab. Then use browser_snapshot to see the page."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to open (https:// is assumed if missing)."},
                    "tab_id": {"type": "string", "description": "Navigate this existing tab instead of opening a new one."},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            capability="browser_open",
            read_only=False,
            destructive=True,
            reason="agent opens a web page",
            timeout=60.0,
        ),
        "browser_snapshot": ConnectorCapabilityTool(
            name="browser_snapshot",
            description=(
                "Structured outline of a page in the automation browser: title/url/headings + every visible "
                "interactive element with a stable id (e0, e1, …), its role, label, value and state. "
                "THE core awareness tool for web work — snapshot, then browser_act on an element id. "
                "Re-snapshot after any navigation (ids go stale)."
            ),
            input_schema={
                "type": "object",
                "properties": {"tab_id": {"type": "string", "description": "Tab to inspect (default: current)."}},
                "additionalProperties": False,
            },
            capability="browser_snapshot",
            read_only=True,
            reason="agent inspects a web page",
            timeout=30.0,
        ),
        "browser_act": ConnectorCapabilityTool(
            name="browser_act",
            description=(
                "Act on the page in the automation browser using element ids from browser_snapshot. "
                "Element actions: click, type (text; keys:'enter' to submit), select (value), check/uncheck, "
                "hover, scroll_to. Page actions (no element): press (keys, e.g. 'enter'/'ctrl+a'), "
                "scroll (amount px), back, forward, reload. Uses trusted browser input events. "
                "If the result says `navigated`, call browser_snapshot again."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["click", "type", "select", "check", "uncheck", "hover", "scroll_to", "press", "scroll", "back", "forward", "reload"],
                    },
                    "element": {"type": "string", "description": "Element id from browser_snapshot (e.g. 'e12'). Required for element actions."},
                    "text": {"type": "string", "description": "Text for 'type' (or option text for 'select')."},
                    "value": {"type": "string", "description": "Option value for 'select'."},
                    "keys": {"type": "string", "description": "Key chord for 'press' (or 'enter' with 'type' to submit)."},
                    "amount": {"type": "integer", "description": "Scroll distance in px for 'scroll' (negative = up). Default 600."},
                    "tab_id": {"type": "string", "description": "Tab to act on (default: current)."},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            capability="browser_act",
            read_only=False,
            destructive=True,
            reason="agent interacts with a web page",
            timeout=45.0,
        ),
        "browser_read": ConnectorCapabilityTool(
            name="browser_read",
            description=(
                "Extract the readable text of a page in the automation browser (reading order, main content "
                "first). Use for reading articles/docs; use browser_snapshot when you need to interact."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "Cap on returned characters (default 18000)."},
                },
                "additionalProperties": False,
            },
            capability="browser_read",
            read_only=True,
            reason="agent reads a web page",
            timeout=30.0,
        ),
        "browser_screenshot": BrowserScreenshotTool(
            name="browser_screenshot",
            description=(
                "SEE a page in the automation browser (vision) — returns a screenshot image of the tab. "
                "Prefer browser_snapshot for interaction (element ids); use this when layout/visuals matter."
            ),
            input_schema={
                "type": "object",
                "properties": {"tab_id": {"type": "string"}},
                "additionalProperties": False,
            },
            capability="browser_screenshot",
            read_only=True,
            reason="agent screenshots a web page",
            timeout=30.0,
        ),
        "browser_eval": ConnectorCapabilityTool(
            name="browser_eval",
            description=(
                "Evaluate a JavaScript expression in a page of the automation browser and return its JSON "
                "result (await-ed; 8k char cap). Power tool for extraction/automation beyond browser_act."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "JS expression, e.g. \"document.title\" or an IIFE."},
                    "tab_id": {"type": "string"},
                },
                "required": ["expression"],
                "additionalProperties": False,
            },
            capability="browser_eval",
            read_only=False,
            destructive=True,
            reason="agent runs a script in the browser",
            timeout=40.0,
        ),
        "browser_close": ConnectorCapabilityTool(
            name="browser_close",
            description="Close a tab of the automation browser (tab_id), or the whole automation browser (all:true).",
            input_schema={
                "type": "object",
                "properties": {
                    "tab_id": {"type": "string"},
                    "all": {"type": "boolean", "description": "Close the entire automation browser window."},
                },
                "additionalProperties": False,
            },
            capability="browser_close",
            read_only=False,
            destructive=True,
            reason="agent closes browser tabs",
            timeout=20.0,
        ),
        # ── Structured Windows app control (UIA, connector ≥0.17) ────────────
        "app_windows": ConnectorCapabilityTool(
            name="app_windows",
            description=(
                "List the open application windows on the user's desktop (title, process, focused) with ids "
                "(w1, w2, …). Windows-only. Start here for app control, then app_snapshot a window."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="app_windows",
            read_only=True,
            reason="agent lists desktop windows",
            timeout=30.0,
        ),
        "app_snapshot": ConnectorCapabilityTool(
            name="app_snapshot",
            description=(
                "Map an application window's controls via Windows UI Automation: every control gets an id "
                "(e1, e2, …) with role, name, value and supported actions ([invoke,value,toggle,…]). "
                "Then drive them with app_act. Far more reliable than screenshot+click for native apps."
            ),
            input_schema={
                "type": "object",
                "properties": {"window": {"type": "string", "description": "Window id from app_windows (e.g. 'w2') or a title substring."}},
                "required": ["window"],
                "additionalProperties": False,
            },
            capability="app_snapshot",
            read_only=True,
            reason="agent inspects an app window",
            timeout=45.0,
        ),
        "app_act": ConnectorCapabilityTool(
            name="app_act",
            description=(
                "Drive a control in an app window using element ids from app_snapshot. Actions: invoke "
                "(click/activate), toggle, select, set_value (value), expand, collapse, focus, "
                "scroll_into_view, close_window; focus_window (window-level, needs `window`). "
                "Controls without automation patterns fall back to a real click at their center."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["invoke", "toggle", "select", "set_value", "expand", "collapse", "focus", "scroll_into_view", "close_window", "focus_window"],
                    },
                    "element": {"type": "string", "description": "Control id from app_snapshot (e.g. 'e5')."},
                    "value": {"type": "string", "description": "Value for set_value."},
                    "window": {"type": "string", "description": "Window id/title — only for focus_window."},
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            capability="app_act",
            read_only=False,
            destructive=True,
            reason="agent drives an application",
            timeout=45.0,
        ),
        "app_read": ConnectorCapabilityTool(
            name="app_read",
            description=(
                "Read the text content of an app window or of one control (element id from app_snapshot). "
                "Uses the app's accessibility text; falls back to aggregating visible labels/values."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "window": {"type": "string", "description": "Window id from app_windows or a title substring."},
                    "element": {"type": "string", "description": "Control id from app_snapshot (overrides window)."},
                },
                "additionalProperties": False,
            },
            capability="app_read",
            read_only=True,
            reason="agent reads an app window",
            timeout=45.0,
        ),
        # ── Live Office documents (COM, connector ≥0.17) ─────────────────────
        "office_status": ConnectorCapabilityTool(
            name="office_status",
            description=(
                "What Office apps are running on the user's machine and which documents are open "
                "(PowerPoint presentations + slide counts, Word documents, Excel workbooks + sheets). "
                "Windows-only. Start here before office_read / office_act."
            ),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="office_status",
            read_only=True,
            reason="agent checks Office apps",
            timeout=30.0,
        ),
        "office_read": ConnectorCapabilityTool(
            name="office_read",
            description=(
                "Read the LIVE content of an open Office document (the one the user is looking at): "
                "powerpoint → slides with each shape's text (slide/shape ids for editing); "
                "word → numbered paragraphs; excel → a sheet's used range values (sheet param optional)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "app": {"type": "string", "enum": ["powerpoint", "word", "excel"]},
                    "document": {"type": "string", "description": "Document name from office_status (default: active)."},
                    "sheet": {"type": "string", "description": "excel: worksheet name (default: active sheet)."},
                },
                "required": ["app"],
                "additionalProperties": False,
            },
            capability="office_read",
            read_only=True,
            reason="agent reads an Office document",
            timeout=60.0,
        ),
        "office_act": ConnectorCapabilityTool(
            name="office_act",
            description=(
                "Edit/drive the LIVE Office document in front of the user. Common: open (path), new, save, "
                "save_as (path), export_pdf (path). PowerPoint: goto_slide (slide), set_shape_text "
                "(slide, shape, text — ids from office_read), add_slide (index?, title?, text?), delete_slide (slide). "
                "Word: append_text (text), replace_text (find, replace, all?). "
                "Excel: set_cell (cell e.g. 'B3', value, sheet?), set_range (start, values [[..],[..]], sheet?)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "app": {"type": "string", "enum": ["powerpoint", "word", "excel"]},
                    "action": {
                        "type": "string",
                        "enum": ["open", "new", "save", "save_as", "export_pdf", "goto_slide", "set_shape_text", "add_slide", "delete_slide", "append_text", "replace_text", "set_cell", "set_range"],
                    },
                    "document": {"type": "string", "description": "Target document name (default: active)."},
                    "path": {"type": "string", "description": "File path for open/save_as/export_pdf."},
                    "slide": {"type": "integer", "description": "Slide number (powerpoint)."},
                    "shape": {"type": "string", "description": "Shape number or name on the slide (powerpoint)."},
                    "text": {"type": "string"},
                    "title": {"type": "string", "description": "add_slide: title placeholder text."},
                    "index": {"type": "integer", "description": "add_slide: position (default: append)."},
                    "find": {"type": "string", "description": "replace_text: text to find."},
                    "replace": {"type": "string", "description": "replace_text: replacement."},
                    "all": {"type": "boolean", "description": "replace_text: replace every occurrence."},
                    "sheet": {"type": "string", "description": "excel: worksheet name."},
                    "cell": {"type": "string", "description": "excel set_cell: A1-style address."},
                    "value": {"description": "excel set_cell: the value."},
                    "start": {"type": "string", "description": "excel set_range: top-left A1-style address."},
                    "values": {"type": "array", "description": "excel set_range: 2D array of rows."},
                },
                "required": ["app", "action"],
                "additionalProperties": False,
            },
            capability="office_act",
            read_only=False,
            destructive=True,
            reason="agent edits an Office document",
            timeout=90.0,
        ),
    }
    return tools


class ConnectorToolProvider:
    """Duck-typed AdhocToolProvider for connector capability tools."""

    def __init__(self) -> None:
        self._tools: Optional[Dict[str, ConnectorCapabilityTool]] = None

    def _ensure(self) -> Dict[str, ConnectorCapabilityTool]:
        if self._tools is None:
            self._tools = _build_tools()
        return self._tools

    def list_names(self) -> List[str]:
        return list(self._ensure().keys())

    def get(self, name: str) -> Optional[ConnectorCapabilityTool]:
        return self._ensure().get(name)
