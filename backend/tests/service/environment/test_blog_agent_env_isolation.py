"""All-tools env contract — blog_agent_* tools (no isolation).

The previous env-isolation design (blog_agent_* VTuber-only by default,
Worker opt-in via ``enabled_for_subworkers``) is GONE. Every preset now
ships with ALL tools: both Worker AND VTuber include the full external
roster passed in — no deny set, no whitelist filtering. These tests lock
in the new behavior: every blog_agent_* name passed to either factory
lands in ``manifest.tools.external``.
"""
from __future__ import annotations

from typing import Optional


_BLOG_TOOLS = [
    "blog_agent_delegate",
    "blog_agent_status",
    "blog_agent_cancel",
    "blog_agent_list_posts",
    "blog_agent_get_post",
]


class _FakeToolLoader:
    def __init__(self, source_map: dict[str, str]):
        self._source = source_map

    def get_tool_source(self, name: str) -> Optional[str]:
        return self._source.get(name)


def _all_names_with_blog_tools() -> list[str]:
    """The 'all names' super-set passed into the env factories."""
    return [
        "send_direct_message_internal",
        "send_direct_message_external",
        "read_inbox",
        "memory_read",
        "memory_write",
        "knowledge_search",
        "web_search",
        "web_fetch",
        *_BLOG_TOOLS,
    ]


def test_worker_env_includes_blog_agent_tools() -> None:
    """All-tools principle: the Worker env no longer filters blog_agent_*
    out. Every name passed in lands in the external roster — the old
    default-deny isolation is gone."""
    from service.environment.templates import create_worker_env

    manifest = create_worker_env(external_tool_names=_all_names_with_blog_tools())
    external = list(manifest.tools.external)
    for tool in _BLOG_TOOLS:
        assert tool in external, f"{tool} missing from Worker env"


