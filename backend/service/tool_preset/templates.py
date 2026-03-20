"""
Pre-built Tool Preset Templates.

Provides factory functions for default tool presets that are
installed on first startup. Users can clone these to customize.
"""

from __future__ import annotations

from service.tool_preset.models import ToolPresetDefinition
from service.tool_preset.store import ToolPresetStore


def create_minimal_preset() -> ToolPresetDefinition:
    """Built-in tools only — no custom tools, no external MCP."""
    return ToolPresetDefinition(
        id="template-minimal",
        name="Minimal",
        description="GenY 플랫폼 도구만 사용. 외부 도구 없음.",
        icon="🔒",
        custom_tools=[],
        mcp_servers=[],
        is_template=True,
        template_name="minimal",
    )


def create_web_research_preset() -> ToolPresetDefinition:
    """Web research — search + fetch + browser."""
    return ToolPresetDefinition(
        id="template-web-research",
        name="Web Research",
        description="웹 검색, 페이지 가져오기, 브라우저 자동화.",
        icon="🔍",
        custom_tools=[
            "web_search",
            "news_search",
            "web_fetch",
            "web_fetch_multiple",
            "browser_navigate",
            "browser_click",
            "browser_fill",
            "browser_screenshot",
            "browser_evaluate",
            "browser_get_page_info",
            "browser_close",
        ],
        mcp_servers=[],
        is_template=True,
        template_name="web-research",
    )


def create_full_development_preset() -> ToolPresetDefinition:
    """Full development — all custom tools + dev MCP servers."""
    return ToolPresetDefinition(
        id="template-full-development",
        name="Full Development",
        description="모든 custom 도구 + 개발 관련 MCP 서버.",
        icon="💻",
        custom_tools=["*"],
        mcp_servers=["*"],
        is_template=True,
        template_name="full-development",
    )


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
    create_minimal_preset,
    create_web_research_preset,
    create_full_development_preset,
    create_all_tools_preset,
]


def install_templates(store: ToolPresetStore) -> int:
    """Install default template presets if they don't already exist.

    Returns:
        Number of templates installed.
    """
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
    "developer": "template-full-development",
    "researcher": "template-web-research",
    "planner": "template-all-tools",
}
