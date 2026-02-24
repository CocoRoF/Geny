"""
Tool Policy Engine — profile-based tool / MCP-server access control.

Design goals
~~~~~~~~~~~~
1. Each *role* (worker, developer, manager, researcher, self-manager) has a
   sensible **default profile** that limits which tools and MCP servers are
   available.
2. A session can **override** the profile via ``CreateSessionRequest.allowed_tools``
   or an explicit ``ToolProfile`` enum value.
3. The engine operates on *MCP server names* (the keys of ``MCPConfig.servers``)
   **and** on individual tool names exposed by the built-in tools server
   (``_builtin_tools``).
4. Filtering is **additive-whitelist**: only servers / tools that appear in the
   resolved allow-set are forwarded to the agent.

Public API
~~~~~~~~~~
* ``ToolPolicyEngine.for_role(role, override_profile, explicit_tools)``
    → returns a configured engine instance.
* ``engine.filter_mcp_config(mcp_config)``
    → returns a new ``MCPConfig`` containing only the allowed servers.
* ``engine.filter_tool_names(names)``
    → returns a filtered list of tool names.
* ``engine.is_server_allowed(name)`` / ``engine.is_tool_allowed(name)``
    → single-item checks.
"""

from __future__ import annotations

from copy import deepcopy
from enum import Enum
from logging import getLogger
from typing import (
    Dict,
    FrozenSet,
    List,
    Optional,
)

logger = getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile enum
# ---------------------------------------------------------------------------

class ToolProfile(str, Enum):
    """Predefined tool-access profiles.

    Each profile defines a *server group* and a *tool group* whitelist.
    The groups are expanded by :pyclass:`ToolPolicyEngine` at resolution time.
    """

    MINIMAL = "minimal"
    """Only the built-in tools server — no external MCP connections."""

    CODING = "coding"
    """Built-in tools + filesystem / git / code-analysis MCP servers."""

    MESSAGING = "messaging"
    """Built-in tools + communication-oriented MCP servers (Slack, email, etc.)."""

    RESEARCH = "research"
    """Built-in tools + search / web / knowledge MCP servers."""

    FULL = "full"
    """All available MCP servers and tools — unrestricted."""


# ---------------------------------------------------------------------------
# Server-group definitions  (extend as new MCP servers are added)
# ---------------------------------------------------------------------------

# Each group is a frozenset of *server name prefixes* that are matched
# case-insensitively.  A server whose name starts with any prefix in the
# group is considered a member.

_BUILTIN_SERVERS: FrozenSet[str] = frozenset({"_builtin_tools"})

_CODING_SERVERS: FrozenSet[str] = frozenset({
    "filesystem",
    "git",
    "github",
    "code",
    "lint",
    "docker",
    "terminal",
})

_MESSAGING_SERVERS: FrozenSet[str] = frozenset({
    "slack",
    "email",
    "discord",
    "teams",
    "notion",
    "jira",
    "linear",
})

_RESEARCH_SERVERS: FrozenSet[str] = frozenset({
    "web",
    "search",
    "brave",
    "perplexity",
    "google",
    "bing",
    "arxiv",
    "wikipedia",
    "fetch",
    "browser",
})

# Composite group map:  profile → union of server-group prefixes
_PROFILE_SERVER_GROUPS: Dict[ToolProfile, FrozenSet[str]] = {
    ToolProfile.MINIMAL:   _BUILTIN_SERVERS,
    ToolProfile.CODING:    _BUILTIN_SERVERS | _CODING_SERVERS,
    ToolProfile.MESSAGING: _BUILTIN_SERVERS | _MESSAGING_SERVERS,
    ToolProfile.RESEARCH:  _BUILTIN_SERVERS | _RESEARCH_SERVERS,
    ToolProfile.FULL:      frozenset(),  # empty ⇒ allow-all sentinel
}


# ---------------------------------------------------------------------------
# Tool-name groups  (individual tool names from _builtin_tools)
# ---------------------------------------------------------------------------

_MANAGER_TOOLS: FrozenSet[str] = frozenset({
    "list_workers",
    "delegate_task",
    "get_worker_status",
    "broadcast_task",
})

_EXAMPLE_TOOLS: FrozenSet[str] = frozenset({
    "add_numbers",
    "multiply_numbers",
    "reverse_string",
    "count_words",
    "echo",
    "calculator",
})


# ---------------------------------------------------------------------------
# Role → default profile mapping
# ---------------------------------------------------------------------------

ROLE_DEFAULT_PROFILES: Dict[str, ToolProfile] = {
    "worker":       ToolProfile.CODING,
    "developer":    ToolProfile.CODING,
    "manager":      ToolProfile.FULL,
    "researcher":   ToolProfile.RESEARCH,
    "self-manager": ToolProfile.FULL,
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ToolPolicyEngine:
    """Resolves and enforces tool / MCP-server access for a session.

    Typical usage::

        engine = ToolPolicyEngine.for_role("developer")
        filtered_mcp = engine.filter_mcp_config(merged_mcp)
        allowed_names = engine.filter_tool_names(all_tool_names)
    """

    def __init__(
        self,
        profile: ToolProfile,
        allowed_server_prefixes: FrozenSet[str],
        explicit_tools: Optional[List[str]] = None,
    ) -> None:
        self._profile = profile
        self._server_prefixes = allowed_server_prefixes
        # When explicit_tools is set, it acts as an override whitelist for
        # individual tool names (from _builtin_tools).  If None, all tools
        # from allowed servers pass through.
        self._explicit_tools: Optional[FrozenSet[str]] = (
            frozenset(explicit_tools) if explicit_tools else None
        )

    # -- Factory -----------------------------------------------------------

    @classmethod
    def for_role(
        cls,
        role: str,
        override_profile: Optional[ToolProfile] = None,
        explicit_tools: Optional[List[str]] = None,
    ) -> "ToolPolicyEngine":
        """Create an engine for the given role.

        Args:
            role: Agent role (worker, developer, manager, …).
            override_profile: If provided, overrides the role's default.
            explicit_tools: If provided, only these tool *names* are allowed
                from the built-in tools server.  MCP-server filtering still
                applies via the profile.

        Returns:
            A configured :class:`ToolPolicyEngine`.
        """
        profile = override_profile or ROLE_DEFAULT_PROFILES.get(role, ToolProfile.CODING)
        prefixes = _PROFILE_SERVER_GROUPS.get(profile, frozenset())

        logger.debug(
            "ToolPolicyEngine: role=%s profile=%s prefixes=%s explicit_tools=%s",
            role,
            profile.value,
            sorted(prefixes) if prefixes else "(allow-all)",
            explicit_tools,
        )

        return cls(
            profile=profile,
            allowed_server_prefixes=prefixes,
            explicit_tools=explicit_tools,
        )

    # -- Properties --------------------------------------------------------

    @property
    def profile(self) -> ToolProfile:
        return self._profile

    @property
    def is_unrestricted(self) -> bool:
        """True when the profile imposes no server restrictions (FULL)."""
        return len(self._server_prefixes) == 0

    # -- Server filtering --------------------------------------------------

    def is_server_allowed(self, server_name: str) -> bool:
        """Check whether an MCP server name passes the policy."""
        if self.is_unrestricted:
            return True
        name_lower = server_name.lower()
        return any(name_lower.startswith(prefix) for prefix in self._server_prefixes)

    def filter_mcp_config(self, mcp_config: Optional[object]) -> Optional[object]:
        """Return a copy of *mcp_config* containing only allowed servers.

        Args:
            mcp_config: An ``MCPConfig`` instance (or None).

        Returns:
            A new ``MCPConfig`` with disallowed servers removed,
            or None if no servers remain.
        """
        if mcp_config is None:
            return None
        if self.is_unrestricted:
            return mcp_config

        # Lazy import to avoid circular dependency
        from service.claude_manager.models import MCPConfig

        servers = getattr(mcp_config, "servers", {})
        filtered: Dict[str, object] = {}
        removed: List[str] = []

        for name, cfg in servers.items():
            if self.is_server_allowed(name):
                filtered[name] = deepcopy(cfg)
            else:
                removed.append(name)

        if removed:
            logger.info(
                "ToolPolicy [%s]: removed %d server(s): %s",
                self._profile.value,
                len(removed),
                ", ".join(sorted(removed)),
            )

        if not filtered:
            return None

        return MCPConfig(servers=filtered)

    # -- Tool-name filtering -----------------------------------------------

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check whether an individual tool name passes the policy."""
        if self._explicit_tools is None:
            return True
        return tool_name in set(self._explicit_tools)

    def filter_tool_names(self, names: Optional[List[str]]) -> List[str]:
        """Filter a list of tool names through the policy.

        Args:
            names: Tool name list (may be None).

        Returns:
            Filtered list.  If no explicit tool whitelist is configured,
            returns the original list unchanged.
        """
        if names is None:
            return []
        if self._explicit_tools is None:
            return list(names)

        allowed = [n for n in names if n in set(self._explicit_tools)]
        removed = set(names) - set(allowed)
        if removed:
            logger.info(
                "ToolPolicy [%s]: removed %d tool(s): %s",
                self._profile.value,
                len(removed),
                ", ".join(sorted(removed)),
            )
        return allowed

    # -- Convenience: apply all filters ------------------------------------

    def apply(
        self,
        mcp_config: Optional[object] = None,
        tool_names: Optional[List[str]] = None,
    ) -> dict:
        """Apply all policy filters in one call.

        Returns:
            ``{"mcp_config": ..., "tool_names": ...}`` with filtered values.
        """
        return {
            "mcp_config": self.filter_mcp_config(mcp_config),
            "tool_names": self.filter_tool_names(tool_names),
        }

    # -- Repr --------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ToolPolicyEngine(profile={self._profile.value!r}, "
            f"servers={'*' if self.is_unrestricted else len(self._server_prefixes)}, "
            f"tools={'*' if self._explicit_tools is None else len(self._explicit_tools)})"
        )
