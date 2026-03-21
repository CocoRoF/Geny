"""
Tool Preset Templates — default preset mapping by role.

Only the "All Tools" template is auto-installed on startup.
"""

from __future__ import annotations

from service.tool_preset.models import ToolPresetDefinition
from service.tool_preset.store import ToolPresetStore


def create_all_tools_preset() -> ToolPresetDefinition:
    """Everything enabled."""
    return ToolPresetDefinition(
        id="template-all-tools",
        name="All Tools",
        description="모든 custom 도구와 MCP 서버 활성화.",
        icon="🚀",
        custom_tools=["*"],
        mcp_servers=["*"],
        is_template=True,
        template_name="all-tools",
    )


_TEMPLATE_FACTORIES = [
    create_all_tools_preset,
]


def install_templates(store: ToolPresetStore) -> int:
    """Install default template presets if they don't already exist."""
    installed = 0
    for factory in _TEMPLATE_FACTORIES:
        preset = factory()
        if not store.exists(preset.id):
            store.save(preset)
            installed += 1
    return installed


# ── Default preset mapping by role ──

ROLE_DEFAULT_PRESET: dict[str, str] = {
    "worker": "template-all-tools",
    "developer": "template-all-tools",
    "researcher": "template-all-tools",
    "planner": "template-all-tools",
}
