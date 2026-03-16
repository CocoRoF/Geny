"""
Lightweight MCP Client — JSON-RPC 2.0 over stdio.

Connects to MCP servers via stdio transport (subprocess) and calls
tools using the MCP protocol. Does not depend on the ``mcp`` Python
package — implements just enough of the protocol for tools/call.

Protocol reference: https://modelcontextprotocol.io/specification

Lifecycle:
    1. Start server subprocess
    2. Send ``initialize`` request
    3. Send ``notifications/initialized``
    4. Call ``tools/list`` to discover available tools
    5. Call ``tools/call`` to execute tools
    6. Close subprocess on shutdown
"""

from __future__ import annotations

import asyncio
import json
import os
from logging import getLogger
from typing import Any, Dict, List, Optional

logger = getLogger(__name__)

# JSON-RPC 2.0 request ID counter
_request_id_counter = 0


def _next_id() -> int:
    global _request_id_counter
    _request_id_counter += 1
    return _request_id_counter


class MCPStdioClient:
    """Minimal MCP client over stdio transport.

    Manages a single server subprocess and provides tool listing
    and execution over JSON-RPC 2.0.
    """

    def __init__(
        self,
        server_name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
    ):
        self._server_name = server_name
        self._command = command
        self._args = args or []
        self._env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._initialized = False
        self._tools: Dict[str, Dict[str, Any]] = {}  # name → tool schema
        self._lock = asyncio.Lock()

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def is_connected(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def connect(self) -> bool:
        """Start the server process and initialize the MCP session."""
        async with self._lock:
            if self._initialized and self.is_connected:
                return True

            try:
                # Build environment
                process_env = dict(os.environ)
                if self._env:
                    process_env.update(self._env)

                # Start subprocess
                self._process = await asyncio.create_subprocess_exec(
                    self._command,
                    *self._args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=process_env,
                )
                logger.info(
                    f"MCPClient[{self._server_name}]: started process "
                    f"pid={self._process.pid}"
                )

                # Initialize MCP session
                init_result = await self._send_request("initialize", {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "geny-tool-executor",
                        "version": "1.0.0",
                    },
                })

                if init_result is None:
                    logger.warning(
                        f"MCPClient[{self._server_name}]: initialize failed"
                    )
                    await self.disconnect()
                    return False

                # Send initialized notification
                await self._send_notification("notifications/initialized", {})

                # Discover tools
                tools_result = await self._send_request("tools/list", {})
                if tools_result and "tools" in tools_result:
                    for tool_def in tools_result["tools"]:
                        name = tool_def.get("name", "")
                        if name:
                            self._tools[name] = tool_def

                self._initialized = True
                logger.info(
                    f"MCPClient[{self._server_name}]: connected, "
                    f"{len(self._tools)} tools available"
                )
                return True

            except FileNotFoundError:
                logger.warning(
                    f"MCPClient[{self._server_name}]: command not found: "
                    f"{self._command}"
                )
                return False
            except Exception as e:
                logger.warning(
                    f"MCPClient[{self._server_name}]: connect failed: {e}"
                )
                await self.disconnect()
                return False

    async def disconnect(self) -> None:
        """Terminate the server subprocess."""
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass
            self._process = None
        self._initialized = False
        self._tools.clear()

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """Return discovered tools (name → schema dict)."""
        return dict(self._tools)

    async def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a tool call on the MCP server.

        Args:
            tool_name: Name of the tool to call.
            arguments: Tool input parameters.

        Returns:
            Dict with ``content`` (list of content blocks) or ``error``.
        """
        if not self.is_connected:
            connected = await self.connect()
            if not connected:
                return {
                    "error": f"Cannot connect to MCP server '{self._server_name}'",
                    "isError": True,
                }

        if tool_name not in self._tools:
            return {
                "error": f"Tool '{tool_name}' not found on server '{self._server_name}'",
                "isError": True,
            }

        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        if result is None:
            return {
                "error": f"Tool call '{tool_name}' failed (no response)",
                "isError": True,
            }

        return result

    # ====================================================================
    # Internal JSON-RPC communication
    # ====================================================================

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request and wait for the response."""
        if not self._process or not self._process.stdin or not self._process.stdout:
            return None

        request_id = _next_id()
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }

        try:
            # Send request
            data = json.dumps(message) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()

            # Read response (skip notifications, find matching id)
            response = await self._read_response(request_id, timeout=30.0)
            if response and "error" in response:
                logger.warning(
                    f"MCPClient[{self._server_name}]: {method} error: "
                    f"{response['error']}"
                )
                return None
            return response.get("result") if response else None

        except Exception as e:
            logger.warning(
                f"MCPClient[{self._server_name}]: request '{method}' failed: {e}"
            )
            return None

    async def _send_notification(
        self,
        method: str,
        params: Dict[str, Any],
    ) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or not self._process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(message) + "\n"
            self._process.stdin.write(data.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            logger.warning(
                f"MCPClient[{self._server_name}]: notification '{method}' "
                f"failed: {e}"
            )

    async def _read_response(
        self,
        request_id: int,
        timeout: float = 30.0,
    ) -> Optional[Dict[str, Any]]:
        """Read lines from stdout until we find the response matching request_id."""
        if not self._process or not self._process.stdout:
            return None

        try:
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break

                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=remaining,
                )

                if not line:
                    return None  # EOF

                line_str = line.decode("utf-8").strip()
                if not line_str:
                    continue

                try:
                    msg = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                # Skip notifications (no id field)
                if "id" not in msg:
                    continue

                if msg.get("id") == request_id:
                    return msg

        except asyncio.TimeoutError:
            logger.warning(
                f"MCPClient[{self._server_name}]: timeout waiting for "
                f"response to request {request_id}"
            )
        except Exception as e:
            logger.warning(
                f"MCPClient[{self._server_name}]: read error: {e}"
            )

        return None
