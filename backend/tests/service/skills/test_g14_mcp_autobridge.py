"""G14 — MCP prompts → Skills auto-bridge.

The agent_session_manager calls bridge_mcp_prompts after pipeline
instantiation. This file covers the bridge helper directly with a
stub MCPManager — the integration with the manager singleton is
exercised by end-to-end smoke tests in CI.
"""

from __future__ import annotations

from typing import Any, List

import pytest

pytest.importorskip("geny_executor.skills")

from geny_executor.skills import SkillRegistry  # noqa: E402

from service.skills import install as skill_install  # noqa: E402


class _StubMCPManager:
    """Mimics the surface mcp_prompts_to_skills calls on the real
    MCPManager: list_servers / list_prompts / get_prompt-like reads."""

    def __init__(self, prompts_by_server: dict[str, list[dict]]) -> None:
        self._prompts = prompts_by_server

    def list_servers(self) -> List[str]:
        return list(self._prompts)

    server_names = list_servers

    async def list_prompts(self, server_name: str) -> List[dict]:
        return list(self._prompts.get(server_name, []))


@pytest.mark.asyncio
async def test_bridge_returns_zero_when_no_registry() -> None:
    added = await skill_install.bridge_mcp_prompts(None, _StubMCPManager({}))
    assert added == 0


@pytest.mark.asyncio
async def test_bridge_returns_zero_when_no_manager() -> None:
    registry = SkillRegistry()
    added = await skill_install.bridge_mcp_prompts(registry, None)
    assert added == 0


@pytest.mark.asyncio
async def test_bridge_no_op_when_no_prompts() -> None:
    registry = SkillRegistry()
    manager = _StubMCPManager({"empty_server": []})
    added = await skill_install.bridge_mcp_prompts(registry, manager)
    assert added == 0
