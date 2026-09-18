"""Agent → executor persistent sub-agent bridge.

Owning a persistent companion sub-agent is an ENVIRONMENT capability
(``host_selections.extras.owned_subagent``): the session manager spawns the
companion at create-time for any agent whose env declares one, and
``send_direct_message_internal`` fully delegates to it via the executor
``SubAgentManager``. The companion completes autonomously; completion lands in
the owner's inbox and Geny surfaces it as the alarm via the execute path.

The pre-cutover "bespoke paired Sub-Worker session" path has been removed —
this is now the only delegation mechanism.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def owned_subagent_id(owner_session_id: str) -> str:
    """Deterministic id for the persistent sub-agent an owner owns."""
    return f"{owner_session_id}-subagent"


#: Memory-dependent stages deactivated in the companion (it has no
#: session-level memory provider; conversation continuity comes from the
#: SubAgentManager's persisted state instead).
_MEMORY_STAGE_ORDERS = (2, 18, 19, 20)  # context / memory / summarize / persist
_AGENT_STAGE_ORDER = 12


def _companion_attach_kwargs(workspace_ctx: dict) -> dict:
    """attach_runtime kwargs for the companion — mirrors the OWNER's contract.

    The sandbox is a TOOL surface: the companion's tools run inside the
    session's container (one unified workspace) while the LLM is called
    from the host with Geny's own credentials. Nothing spawns a provider
    into the container — executor 2.68.0 removed the last path that did
    (``containerize_cli``, which used to wrap a ``claude_code_cli``
    client in a ContainerCLIRunner and cost us the 2026-07-15 auth
    regression: the CLI ran in gapt-ws with its own baked binary and
    without the auth Geny configured, failing every turn).
    """
    from geny_executor.tools.base import ToolContext

    kwargs: dict = {
        "tool_context": ToolContext(
            session_id=workspace_ctx.get("sub_agent_id") or "",
            working_dir=workspace_ctx.get("working_dir") or "",
            storage_path=workspace_ctx.get("storage_path") or "",
            extras=dict(workspace_ctx.get("extras") or {}),
        ),
    }
    if workspace_ctx.get("sandbox") is not None:
        kwargs["sandbox"] = workspace_ctx["sandbox"]
    return kwargs


def _make_parent_env_companion_factory(
    env_service: Any,
    parent_env_id: str,
    adhoc_providers: Any = (),
    extra_external_tools: Any = (),
    workspace_ctx: Any = None,
):
    """Build a PipelineFactory that clones the PARENT agent's environment.

    The companion inherits the parent env's tools / model / provider / stages
    (decision: "부모 env 기능 그대로") — NO separate env. We only (a) deactivate
    the memory-dependent stages (no session memory provider is wired for the
    companion), and (b) force Stage-12 to single_agent so the companion can't
    recursively spawn further sub-agents. ``adhoc_providers`` (the parent
    session's GenyToolProvider / Connector / Skill providers) MUST be passed
    through — otherwise the env's external tools (file/memory/web/blog/…) have
    no provider and the companion can do nothing with a delegated task. The
    companion's system prompt (``ctx.descriptor.system_prompt``) is applied via
    attach_runtime.
    """

    async def _factory(ctx: Any) -> Any:
        from geny_executor import EnvironmentManifest, Pipeline

        base = env_service.load_manifest(parent_env_id)
        if base is None:
            raise RuntimeError(f"parent env not found for companion: {parent_env_id}")
        # Clone so we never mutate the cached parent manifest.
        manifest = EnvironmentManifest.from_dict(base.to_dict())
        # Union extra external tools (e.g. connector Computer Use tools) into the
        # clone's tools.external — the companion clones the parent ENV manifest,
        # which does NOT carry the runtime `extra_external_tools` union that
        # instantiate_pipeline applies to the main session, so we add them here.
        _extra_ext = list(dict.fromkeys(extra_external_tools or ()))
        if _extra_ext:
            try:
                cur = list(getattr(manifest.tools, "external", None) or [])
                manifest.tools.external = list(dict.fromkeys([*cur, *_extra_ext]))
            except Exception:  # noqa: BLE001 — never fail the companion on this
                logger.warning("companion: extra_external_tools union failed", exc_info=True)
        entries = manifest.stage_entries()
        for e in entries:
            if e.order in _MEMORY_STAGE_ORDERS:
                e.active = False
            if e.order == _AGENT_STAGE_ORDER:
                e.strategies = {**(e.strategies or {}), "orchestrator": "single_agent"}
        try:
            manifest.set_stage_entries(entries)
        except Exception:  # noqa: BLE001 — in-place mutation already applied
            pass

        pipeline = await Pipeline.from_manifest_async(
            manifest,
            credentials=ctx.credentials,
            adhoc_providers=tuple(adhoc_providers or ()),
            strict=False,
        )
        # Role prompt: the env editor's override when set, otherwise the
        # library's strong default companion persona (executor >=2.8.0). Either
        # way the companion runs with an explicit "autonomous delegate" role on
        # top of the inherited parent env.
        system_prompt = getattr(ctx.descriptor, "system_prompt", None)
        if not system_prompt:
            try:
                from geny_executor.stages.s12_agent.subagent_catalog import (
                    DEFAULT_PERSISTENT_SUBAGENT_PROMPT,
                )

                system_prompt = DEFAULT_PERSISTENT_SUBAGENT_PROMPT
            except Exception:  # noqa: BLE001 — executor < 2.8.0
                system_prompt = None
        if system_prompt:
            try:
                from geny_executor.stages.s03_system.artifact.default.builders import (
                    ComposablePromptBuilder,
                    PersonaBlock,
                )

                pipeline.attach_runtime(
                    system_builder=ComposablePromptBuilder(
                        blocks=[PersonaBlock(system_prompt)]
                    ),
                )
            except Exception:  # noqa: BLE001
                logger.warning("companion: system_prompt attach failed", exc_info=True)
        # One session = one workspace, companion INCLUDED: the companion
        # works in the OWNER's workspace with the OWNER's sandbox handle,
        # so its Bash/files land exactly where the owner (and the web UI)
        # look. Without this the companion ran with a bare ToolContext —
        # host cwd surprises and no sandbox (the 2026-07-15 PPTX
        # delegation ran 20 min partly because Bash had no valid cwd).
        if workspace_ctx is not None:
            try:
                pipeline.attach_runtime(**_companion_attach_kwargs(workspace_ctx))
                logger.info(
                    "companion runtime: tools %s; LLM called from the host",
                    "sandboxed" if workspace_ctx.get("sandbox") is not None else "on host",
                )
            except Exception:  # noqa: BLE001 — never fail companion build
                logger.warning("companion: workspace ctx attach failed", exc_info=True)
        return pipeline

    return _factory


async def spawn_owned_subagent(
    app_state: Any,
    owner_session_id: str,
    *,
    parent_env_id: str,
    env_service: Any,
    system_prompt: Optional[str] = None,
    credentials: Any = None,
    parent_provider: Optional[str] = None,
    adhoc_providers: Any = (),
    extra_external_tools: Any = (),
    sandbox: Any = None,
    working_dir: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> Optional[str]:
    """Spawn the persistent sub-agent an env-declaring agent owns.

    The companion is built from the PARENT agent's environment (it inherits the
    parent's tools / model / stages — no separate env), with an optional
    ``system_prompt`` role override. ``adhoc_providers`` are the parent
    session's tool providers, passed through so the companion's external tools
    actually resolve. Returns the sub-agent id, or None when no SubAgentManager
    is wired / spawn fails."""
    manager = getattr(app_state, "subagent_manager", None)
    if manager is None or env_service is None:
        return None
    sub_agent_id = owned_subagent_id(owner_session_id)
    try:
        factory = _make_parent_env_companion_factory(
            env_service, parent_env_id, adhoc_providers, extra_external_tools,
            workspace_ctx={
                "sub_agent_id": sub_agent_id,
                "working_dir": working_dir,
                "storage_path": storage_path,
                "sandbox": sandbox,
            },
        )
        await manager.spawn(
            "owned",
            owner_session_id,
            factory=factory,
            sub_agent_id=sub_agent_id,
            credentials=credentials,
            parent_provider=parent_provider,
            system_prompt=system_prompt or None,
        )
        logger.info(
            "[%s] 🤖 owned sub-agent spawned: %s (parent env=%s, prompt=%s)",
            owner_session_id, sub_agent_id, parent_env_id,
            "custom" if system_prompt else "default",
        )
        return sub_agent_id
    except Exception:  # noqa: BLE001 — never fail create on this
        logger.warning(
            "[%s] owned sub-agent spawn failed", owner_session_id, exc_info=True,
        )
        return None


async def delegate_to_subagent(
    app_state: Any, sub_agent_id: str, content: str
) -> dict:
    """Fully delegate *content* to the VTuber's owned sub-agent (autonomous)."""
    manager = getattr(app_state, "subagent_manager", None)
    if manager is None:
        return {"error": "subagent_manager not available"}
    out = await manager.assign(sub_agent_id, content, background=True)
    return out


__all__ = [
    "spawn_owned_subagent",
    "owned_subagent_id",
    "delegate_to_subagent",
]
