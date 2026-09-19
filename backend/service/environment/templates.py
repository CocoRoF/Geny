"""The seed environments — WORKER + VTUBER + VSCODE.

An environment says which TOOLS an agent has and which PERSONA it wears.
It no longer says which pipeline it runs or which model answers:

* The pipeline is the one harness (:func:`geny_executor.build_manifest`
  materialises a single blueprint since 2.66.0), so improving it improves
  every agent and no agent quietly runs a weaker one.
* The model is whatever the session's **route** names — the accounts the
  user picked, in order — resolved at Stage 6 by the ``geny_router``
  provider. That is why switching model mid-conversation is cheap: the
  environment does not change, so neither do the tools, the memory, the
  hooks or the permission policy.

Before this, the seeds were eleven: worker and VTuber for each of four
backends, plus VSCode. The backend half of that grid is gone — an
environment pinned to ``openai`` was really a model choice wearing an
environment's clothes, and the user had to rebuild their whole tool roster
to change models. Three seeds remain because three tool rosters genuinely
differ:

============  ============================================================
일반 환경      every tool, no persona
VTuber 환경    every tool + persona + an owned sub-agent
VSCode 확장    ONLY the ``vscode_*`` tools — the agent works the user's real
              editor, and must never reach for the server sandbox instead
============  ============================================================

The seeds are **materialized on disk** at app boot by
:func:`install_environment_templates`, rewritten from the canonical builder
every time, so "what the seed looks like" and "what a session runs" cannot
drift. Custom environments — any id but the three seeds — are never touched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

from geny_executor import EnvironmentManifest, build_manifest
from geny_executor import known_manifest_presets as known_presets

from service.environment.service import EnvironmentService

if TYPE_CHECKING:
    from service.tool_loader import ToolLoader

#: Stage 6's provider for every environment. The accounts behind it are the
#: session's route, so an environment never has to be rebuilt to change model.
ROUTER_PROVIDER = "geny_router"

__all__ = [
    "ROUTER_PROVIDER",
    "WORKER_ENV_ID",
    "create_worker_env",
    "install_environment_templates",
    # Re-export of the library's known_manifest_presets() under the
    # historical Geny name (frontend validation hook).
    "known_presets",
]


WORKER_ENV_ID = "template-worker-env"
VTUBER_ENV_ID = "template-vtuber-env"
# Geny VSCode extension — the one environment whose ONLY external tools are
# the isolated vscode_* local-development set (gated by extras.vscode_enabled).

# Minimal framework built-ins for the VSCode coding agent: plan / interact /
# research + tool discovery. Deliberately EXCLUDES the sandbox fs/shell tools
# (Read/Write/Edit/Bash/Glob/Grep) — those act on the session's server sandbox,
# not the user's VSCode workspace; the vscode_* tools are the only file and
# terminal interface here, so the agent never confuses the two targets.
_VSCODE_BUILT_IN_TOOL_NAMES = [
    "AskUserQuestion", "TodoWrite", "EnterPlanMode", "ExitPlanMode",
    "WebSearch", "WebFetch", "ToolSearch",
]


# Custom tools the VTuber persona should keep access to. Distinct
# from platform-layer builtins (which are identified via
# :data:`_PLATFORM_TOOL_SOURCES` — the file stem under
# ``backend/tools/built_in/*.py``) — this whitelist only controls
# which *custom* (``tools/custom/``) tools make it through. The old
# ``browser_*`` / ``web_fetch*`` custom tools were replaced by the
# executor's an-web built-ins (Browser* / WebFetch) in the geny-executor
# 2.43 migration; page fetching for the persona now comes from the
# ``WebFetch`` built-in in its ``built_in`` list. Matches
# ``backend/tool_presets/template-vtuber-tools.json``.
_VTUBER_CUSTOM_TOOL_WHITELIST = frozenset(
    {
        "web_search", "news_search",
        # Blog AI Agent delegation tools — the VTuber delegates to an
        # external blog AI. BLOG_AGENT_DELEGATION_PLAN.md § Phase 4.
        # Sub-Workers are blocked via _WORKER_CUSTOM_TOOL_DENY.
        "blog_agent_delegate",
        "blog_agent_status",
        "blog_agent_cancel",
        "blog_agent_list_posts",
        "blog_agent_get_post",
        # Whiteboard analysis tools — backing the bundled VTuber-only
        # skills `whiteboard-react-to-share` and `whiteboard-voice-notes`.
        # ``whiteboard_describe`` + ``whiteboard_extract_links`` were
        # latent (skills referenced them but they weren't in the roster);
        # ``whiteboard_transcribe`` ships in the voice-notes feature
        # (docs/voice-notes/02_PLAN.md W4) as the retry surface for the
        # auto-transcribe PostCaptureHook from W2.
        "whiteboard_describe",
        "whiteboard_extract_links",
        "whiteboard_transcribe",
    }
)


# Custom tools to *exclude* from the Worker (Sub-Worker / developer /
# researcher / planner) environment. Default Worker env opts into every
# external tool name from the loader; this set lets us subtract specific
# tools that should be VTuber-only without writing per-role whitelists.
#
# BLOG_AGENT_DELEGATION_PLAN.md § Phase 4 / decision #2 — blog_agent_*
# is VTuber-only by default. To enable for Sub-Workers an operator must
# (1) flip BlogAgentConfig.enabled_for_subworkers and (2) regenerate
# the env template (or hand-edit a custom env). The two-step gate is
# intentional: prevents an accidental UI toggle from giving Sub-Workers
# write access to the live blog.
_WORKER_CUSTOM_TOOL_DENY = frozenset(
    {
        "blog_agent_delegate",
        "blog_agent_status",
        "blog_agent_cancel",
        "blog_agent_list_posts",
        "blog_agent_get_post",
    }
)



def create_worker_env(
    external_tool_names: Optional[List[str]] = None,
) -> EnvironmentManifest:
    """Default worker environment manifest.

    Runs the one harness on the ``geny_router`` provider, so the model is
    whatever the session's route names. Binds to every tool supplied
    via *external_tool_names* — both Geny platform builtins
    (``geny_*``, ``memory_*``, ``knowledge_*``, ``opsidian_*``) and
    custom tools. The executor's manifest loader only registers
    names listed in ``.external``, so callers must pass the full
    union (not just the custom slice) to get platform tools into
    the session's tool registry.

    Worker seeds additionally opt into every framework built-in tool
    (:data:`_WORKER_BUILT_IN_TOOL_NAMES` = ``["*"]``). This gives
    Sub-Workers ``Write`` / ``Read`` / ``Edit`` / ``Bash`` / ``Glob`` /
    ``Grep`` — required to actually create files in the session's
    ``storage_path`` instead of falling back to ``memory_write``.

    The ``model`` block is left empty — session creation fills it in
    via :class:`PipelineConfig` based on the user's LLM settings.

    """
    # All-tools principle: every tool by default (built_in ``["*"]`` + the full
    # external roster). Users narrow per-environment in the editor; the seed is
    # maximal. The ``model`` block is filled at session creation.
    manifest = build_manifest(
        "default",
        provider=ROUTER_PROVIDER,
        external_tools=list(external_tool_names or []),
        built_in_tools=["*"],
    )
    manifest.metadata.id = WORKER_ENV_ID
    manifest.metadata.name = "일반 환경"
    manifest.metadata.description = (
        "범용 작업 환경 — 모든 도구. 모델은 세션이 고른 계정이 정합니다."
    )
    _promote_core_tools(manifest)
    _use_llm_compactor(manifest)
    _budget_belongs_to_the_session(manifest)
    return manifest




def _use_llm_compactor(manifest: "EnvironmentManifest") -> None:
    """Switch Stage-2 context-pressure compaction from the dumb ``truncate``
    default to ``llm_summary`` — a proper, preservation-focused LLM recap when
    the context outgrows the model window (geny-executor >=2.19.0 self-wires the
    compactor's model from the live session). Never fails template build."""
    try:
        entries = manifest.stage_entries()
        for e in entries:
            if e.order == 2:
                e.strategies = {**(e.strategies or {}), "compactor": "llm_summary"}
        manifest.set_stage_entries(entries)
    except Exception:  # noqa: BLE001
        pass


# Platform tool families promoted to *core* exposure — always in the request
# payload, no ToolSearch round-trip. The always-on memory family (memory_* —
# CRUD in ``memory_tools.py`` plus the progressive-inspection ``memory_status``
# / ``memory_with`` / ``memory_event`` / ``memory_artifact`` / ``memory_distill``)
# is high-frequency and cohesive, so the agent should see the whole memory API
# from turn 1 instead of discovering it via ``ToolSearch``.
# ``send_direct_message_internal`` is THE delegation verb for any agent that
# owns a companion sub-agent (VTuber sub-worker) — hiding it behind ToolSearch
# made models narrate delegation without ever calling it (2026-07-14
# regression: "워커한테 넘긴다" with tool_call_count=0). ``knowledge_*`` /
# ``hook_*`` stay deferred (consulted less often; the Stage-3 deferred catalog
# + ToolSearch browse mode make them discoverable). Bash and the other
# executor built-ins are already core via ``built_in_tools=["*"]``.
# NOTE: applied at env-template build AND at every ``build_pipeline`` (see
# environment/service.py) so existing envs receive new patterns too.
_CORE_PROMOTED_TOOL_PATTERNS: Dict[str, bool] = {
    "memory_*": True,
    "send_direct_message_internal": True,
}



def _budget_belongs_to_the_session(manifest: "EnvironmentManifest") -> None:
    """Let the SESSION own the turn budget, and add the cost dimension.

    The canonical manifest ships a Stage-16 cap of 30. There is one
    environment here and every agent runs it, so a number baked into it is
    not "this environment's limit" — it is a second, invisible limit sitting
    on top of the one the user set, and the user's is the one shown on the
    page. Clearing it leaves exactly one number: the session's.

    The cost dimension is added at the same time and costs nothing until a
    budget exists — ``CostBudget`` with no cap defers to
    ``state.cost_budget_usd``, and with none of those set it never fires. It
    is here so that a spend cap, once set, is enforced at the loop and not
    only at the pre-flight guard.
    """
    try:
        entries = manifest.stage_entries()
        for e in entries:
            if e.order != 16:
                continue
            config = dict(e.config or {})
            # 0 = "this environment is not naming a cap" (the library reads
            # the smaller of the two when both do).
            config["max_turns"] = 0
            e.config = config
            configs = dict(e.strategy_configs or {})
            controller = dict(configs.get("controller") or {})
            controller["dimensions"] = ["iterations", "cost_usd"]
            configs["controller"] = controller
            e.strategy_configs = configs
        manifest.set_stage_entries(entries)
    except Exception:  # noqa: BLE001 — a template must always build
        pass


def _promote_core_tools(manifest: "EnvironmentManifest") -> None:
    """Promote the always-on platform tool families to *core* exposure.

    Executor default (geny-executor 2.42+): framework built-ins are core,
    everything else — external / provider / MCP — is *deferred* behind the
    ``ToolSearch`` built-in. Geny's memory tools attach as ``tools.external``,
    so an agent had to ``ToolSearch("memory")`` before it could store or recall.
    Writing ``manifest.tools.core_overrides`` (a wildcard the executor honours
    for external tools too — see ``_resolve_core_flag``) ships them in the
    request payload from turn 1. ``ToolSearch`` itself stays core because
    ``knowledge_*`` / ``hook_*`` / custom / MCP tools remain deferred, so the
    discovery path for the long tail is preserved.

    Idempotent and merge-safe (``setdefault`` keeps any pre-existing override,
    e.g. a user who deliberately deferred a family in a custom env). The
    wildcard is a harmless no-op for a manifest that carries no memory tools
    (e.g. the VSCode env). Never fails template build.
    """
    try:
        overrides = dict(getattr(manifest.tools, "core_overrides", None) or {})
        for pattern, core in _CORE_PROMOTED_TOOL_PATTERNS.items():
            overrides.setdefault(pattern, core)
        manifest.tools.core_overrides = overrides
    except Exception:  # noqa: BLE001
        pass




#: The GAPT control-plane tools — kept out of the always-on roster (heavy).
#: A persona/VTuber env delegates GAPT work to a sub-worker carrying these;
#: a worker env has them directly in its external roster.
_GAPT_TOOL_NAMES = [
    "gapt_overview",
    "gapt_list_projects",
    "gapt_create_project",
    "gapt_list_workspaces",
    "gapt_create_workspace",
    "gapt_manage_workspace",
    "gapt_run_command",
    "gapt_list_environments",
    "gapt_deploy",
]


def install_environment_templates(
    service: EnvironmentService,
    *,
    external_tool_names: Optional[List[str]] = None,
    tool_loader: Optional["ToolLoader"] = None,
) -> int:
    """Save default environment manifests to disk, overwriting existing.

    Mirrors :func:`service.tool_preset.templates.install_templates`.
    Called once at app boot after the tool preset templates are
    installed and the :class:`ToolLoader` has enumerated tools — so
    *external_tool_names* should be ``tool_loader.get_all_names()``
    (builtin + custom) for the worker env. Anything that does not
    land in ``manifest.tools.external`` will never reach the
    session's tool registry.

    There is ONE environment, rewritten every boot from the canonical
    :func:`geny_executor.build_manifest` output, so it stays in lockstep with
    the builder (a new stage in the chain, say) without a migration framework.

    It used to be three, and before that eleven. Each round of shrinking
    removed something that turned out not to belong to an environment at all:
    the model became the session's route, the pipeline became the one harness,
    and now the persona, the tool roster and the sub-agents have become things
    a SESSION carries. What is left is the pipeline every agent runs — which
    is not a choice anybody should have to make, and is the whole reason it is
    no longer presented as one.

    Returns the number of environment files written: one.
    """
    all_names = list(external_tool_names or [])
    manifest = create_worker_env(external_tool_names=all_names)
    manifest.metadata.name = "Geny"
    manifest.metadata.description = (
        "하나의 파이프라인 — 21단계, 모든 도구. 페르소나·도구 묶음·트리거는 "
        "세션에 붙입니다."
    )
    _seed_system_prompt(manifest)
    service._write_manifest(manifest.metadata.id, manifest)
    return 1


def _seed_system_prompt(manifest: "EnvironmentManifest") -> None:
    """env = single source: seed the System stage (order 3) ``config.system_prompt``
    with the role's default prompt text from ``prompts/{role}.md`` so every preset
    env ships a non-empty, editable system prompt (shown in the Stage-3 editor and
    used at session build). VTuber envs get ``vtuber.md``; others ``worker.md``.
    Best-effort; never fails template build."""
    try:
        from service.prompt.template_loader import PromptTemplateLoader

        extras = getattr(manifest.host_selections, "extras", None) or {}
        owned = extras.get("owned_subagent") or {}
        is_vtuber = bool(
            extras.get("persona_preset_id")
            or (isinstance(owned, dict) and owned.get("enabled"))
        )
        if extras.get("vscode_enabled"):
            role = "vscode"
        elif is_vtuber:
            role = "vtuber"
        else:
            role = "worker"
        text = PromptTemplateLoader().load_role_template(role)
        if not text:
            return
        entries = manifest.stage_entries()
        for e in entries:
            if getattr(e, "order", None) == 3:
                # ``prompt`` = the StaticPromptBuilder key the Stage-3 editor binds to.
                e.config = {**(getattr(e, "config", None) or {}), "prompt": text}
        manifest.set_stage_entries(entries)
    except Exception:  # noqa: BLE001 — never fail template build on seeding
        pass
