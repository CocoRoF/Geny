"""
Per-session tool execution context.

Uses ``contextvars.ContextVar`` to propagate session-specific allowed_tools
restrictions to built-in tool implementations (tool_search, tool_execute, etc.)
without passing them through every function call.

Usage:
    # Before invoking the agent graph:
    token = set_session_allowed_tools(["read_file", "write_file"])

    # Inside tool_search_tools.py:
    allowed = get_session_allowed_tools()  # ["read_file", "write_file"] or None

    # After invocation:
    clear_session_allowed_tools(token)
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import List, Optional

# ContextVar holding the per-session allowed tool names.
# None means "no restriction" (all tools allowed).
_session_allowed_tools: ContextVar[Optional[List[str]]] = ContextVar(
    "session_allowed_tools",
    default=None,
)


def set_session_allowed_tools(
    allowed_tools: Optional[List[str]],
) -> Token[Optional[List[str]]]:
    """Set the allowed tools for the current session context.

    Args:
        allowed_tools: List of tool names to allow, or None for unrestricted.

    Returns:
        Token for resetting the value later.
    """
    return _session_allowed_tools.set(allowed_tools)


def get_session_allowed_tools() -> Optional[List[str]]:
    """Get the allowed tools for the current session context.

    Returns:
        List of allowed tool names, or None if unrestricted.
    """
    return _session_allowed_tools.get()


def clear_session_allowed_tools(
    token: Optional[Token[Optional[List[str]]]] = None,
) -> None:
    """Clear the session allowed tools context.

    Args:
        token: Token from set_session_allowed_tools() for precise reset.
               If None, resets to default (unrestricted).
    """
    if token is not None:
        _session_allowed_tools.reset(token)
    else:
        _session_allowed_tools.set(None)
