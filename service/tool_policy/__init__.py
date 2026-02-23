"""
Tool Policy Engine

Profile-based tool/MCP-server filtering for role-aware access control.
Inspired by OpenClaw's tool permission model.

Exports:
    ToolProfile     – Enum of predefined access profiles.
    ToolPolicyEngine – Resolves allowed MCP servers and tool names.
    ROLE_DEFAULT_PROFILES – Mapping from role → default profile.
"""

from service.tool_policy.policy import (
    ToolProfile,
    ToolPolicyEngine,
    ROLE_DEFAULT_PROFILES,
)

__all__ = [
    "ToolProfile",
    "ToolPolicyEngine",
    "ROLE_DEFAULT_PROFILES",
]
