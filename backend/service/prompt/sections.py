"""
Prompt Section Library

Defines core prompt sections for Geny Agent, inspired by
OpenClaw's 25+ section design.

Each section is created as a PromptSection object and
registered with PromptBuilder for conditional assembly.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from logging import getLogger
from typing import Dict, List, Optional

from service.prompt.builder import PromptBuilder, PromptMode, PromptSection

logger = getLogger(__name__)

# Configured timezone (respects GENY_TIMEZONE env var)
from service.utils.utils import _configured_tz as _get_tz, _configured_tz_abbr as _get_tz_abbr


class SectionLibrary:
    """Prompt section factory.

    Each static method creates and returns a PromptSection object.
    Register via PromptBuilder.add_section().
    """

    # ========================================================================
    # §1 Identity — Agent identity
    # ========================================================================

    # Role-specific identity lines — concise, purposeful
    _ROLE_IDENTITY = {
        "worker":     "You are a Geny Worker agent.",
        "developer":  "You are a Geny Developer agent.",
        "researcher": "You are a Geny Researcher agent.",
        "planner":    "You are a Geny Plan Architect agent.",
        "vtuber":     "You are a Geny VTuber agent — a conversational persona that interacts with users.",
    }

    @staticmethod
    def identity(
        agent_name: str = "Great Agent",
        role: str = "worker",
        agent_id: Optional[str] = None,
        session_name: Optional[str] = None,
        character_display_name: Optional[str] = None,
    ) -> PromptSection:
        """Agent identity section (concise one-liner).

        Naming policy (cycle 20260422_6, principle E ─ "name is data"):

        * ``character_display_name`` — authoritative in-character name.
          When set, presented as ``Your character name is "X".`` so the
          model adopts it as its own name.
        * ``session_name`` — operational handle (user-typed slug,
          e.g. ``"ertsdfg"``). When ``character_display_name`` is unset,
          the handle is *not* exposed as a name. It is exposed as
          ``Session handle: "X"`` with an explicit disclaimer so the
          model does not adopt it. When *both* are set, the handle line
          is omitted so only the in-character name remains.
        * When neither is set, no name lines are emitted; the persona is
          anonymous until the user gives it a name (handled by the PR2
          first-encounter overlay, which instructs the persona to ask).

        This separation structurally blocks the failure mode where a
        random session slug like ``"ertsdfg"`` was being recited by the
        VTuber as its own name.
        """
        identity_line = SectionLibrary._ROLE_IDENTITY.get(
            role, f"You are a Geny agent (role: {role})."
        )
        parts = [identity_line]

        if character_display_name:
            parts.append(f'Your character name is "{character_display_name}".')
        elif session_name:
            parts.append(
                f'Session handle: "{session_name}" '
                "(internal identifier; this is NOT your character name)."
            )

        if agent_id:
            parts.append(f"Agent ID: {agent_id}")

        return PromptSection(
            name="identity",
            content=" ".join(parts),
            priority=10,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §1.5 User Context — Who the user is
    # ========================================================================

    @staticmethod
    def user_context() -> Optional[PromptSection]:
        """User persona context section.

        Injects the configured user identity so agents know
        who they are working with/for.
        Returns None if no user info is configured.
        """
        from service.config.sub_config.general.user_config import UserConfig

        ctx = UserConfig.get_user_context()
        if not ctx:
            return None

        return PromptSection(
            name="user_context",
            content=ctx,
            priority=12,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §1.7 Geny Platform — Built-in platform tools awareness
    # ========================================================================

    @staticmethod
    def geny_platform(session_id: Optional[str] = None) -> PromptSection:
        """Geny platform awareness section.

        Informs the agent it runs inside Geny and has platform tools
        via MCP. Individual tool names are NOT listed here because
        Claude CLI receives full tool schemas through MCP automatically.
        """
        # Tool categories are NOT listed — the model receives every platform
        # tool's full schema via MCP. The prompt states only what the schemas
        # can't: that this runs inside a multi-agent platform.
        parts = [
            "## Geny Platform",
            "",
            "You run inside the Geny multi-agent platform; your platform tools "
            "(sessions, messaging, rooms, …) are provided via MCP.",
        ]
        if session_id:
            parts.append(f"Your session ID: `{session_id}`")

        return PromptSection(
            name="geny_platform",
            content="\n".join(parts),
            priority=13,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §2 Role Protocol — Per-role behavior instructions
    # ========================================================================

    @staticmethod
    def role_protocol(role: str = "worker") -> PromptSection:
        """Per-role behavior protocol section.

        Worker has no role-specific prompt — it operates as a
        general-purpose agent with only the base identity.
        """

        # Lean fallback protocols — only used when no prompts/*.md file exists.
        # When a prompts/{role}.md file exists, it overrides this entirely.
        protocols = {
            "worker": "",
            "developer": "",
            "researcher": "",
            "planner": "",
            "vtuber": "",
        }

        content = protocols.get(role, "")

        return PromptSection(
            name="role_protocol",
            content=content,
            priority=15,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §3 Capabilities — REMOVED
    # ========================================================================
    # Previously listed tool names and MCP server names in the prompt.
    # Removed because Claude CLI receives full tool schemas via MCP
    # automatically — repeating them in the system prompt wastes tokens
    # and adds no value.

    # ========================================================================
    # §6 Workspace — Working environment
    # ========================================================================

    @staticmethod
    def workspace(
        working_dir: str,
        project_name: Optional[str] = None,
        file_tree: Optional[str] = None,
    ) -> PromptSection:
        """Working directory info section (concise)."""
        content = f"Working directory: {working_dir}"
        if project_name:
            content += f" (project: {project_name})"
        if file_tree:
            content += f"\n```\n{file_tree}\n```"

        return PromptSection(
            name="workspace",
            content=content,
            priority=40,
            condition=lambda: bool(working_dir),
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    @staticmethod
    def files_workspace(
        workspace_addr: str, cloud_linked: str = ""
    ) -> PromptSection:
        """Short manifest of the session's FILES WORKSPACE.

        *workspace_addr* must be the address the session's TOOLS resolve
        against — ``/workspace`` when a sandbox is bound, the host path when
        one is not. An agent that is told a second address uses it, and half
        its files land somewhere the user never looks.

        Deliberately terse (workspace-canvas plan): the prompt states only the
        non-discoverable facts — where the space is, what it is FOR, and that
        it is not an execution environment. Concrete contents are fetched on
        demand via the WorkspaceInfo tool; the sandbox counterpart (when
        bound) is described by the GAPT section with the SandboxPut/
        SandboxFetch bridge.
        """
        content = (
            # ONE address, and it is the one the TOOLS accept — `/workspace`
            # for a sandbox-bound session, the host path otherwise. This used
            # to print the host path unconditionally while the sandbox tools
            # only understood /workspace, so the prompt held two equally
            # absolute answers to "where am I". Two providers, same
            # instruction, two different places: OpenAI wrote
            # /workspace/x.txt and Claude Code wrote <host>/workspace/x.txt,
            # which the container mapper re-rooted into workspace/workspace/.
            f"Files workspace (host storage, not an execution environment): "
            f"{workspace_addr} — uploads/ (files the user sent), "
            f"drafts/ (in-progress document edits), outputs/ (artifacts "
            f"delivered to the user). This space serves the built-in file & "
            f"document tools; never install software or run services against "
            f"it. Inspect contents on demand with WorkspaceInfo. Office files "
            f"(.docx/.xlsx/.pptx) are binary — never Read them: use "
            f"doc_analyze for the outline, doc_edit for precise edits (the "
            f"user watches the updated preview in the Canvas tab), "
            f"doc_convert for pdf/png/text, doc_generate to create new ones."
        )
        if cloud_linked:
            # Non-discoverable facts, not instructions. The agent's space is
            # INSIDE GenyCloud now, so the layout above it — the user's
            # folders, the other agents, the two kinds of GAPT workspace —
            # is reachable and is not this session's private property. An
            # agent that does not know this either never looks (and asks the
            # user to re-upload what is already there) or overwrites shared
            # work believing it was scratch.
            content += (
                f" This space is inside GenyCloud at `{cloud_linked}` — shared "
                "storage that mirrors live to the user's PCs and to the other "
                "connected agents, so anything written here appears on their "
                "machines and anything deleted disappears from them. Sibling "
                "paths in the cloud: the user's own folders at the top level "
                "(their linked PC folders), `agents/<id>/` for each other "
                "agent's space, `gapt/` for the user's own sandbox workspace, "
                "and `.gapt/` inside a space for that agent's sandbox scratch "
                "(the only part that does NOT mirror to the user's PCs)."
            )
        return PromptSection(
            name="files_workspace",
            content=content,
            priority=41,
            condition=lambda: bool(storage_path),
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §7 DateTime — Current time
    # ========================================================================

    @staticmethod
    def computer_use() -> PromptSection:
        """Desktop-control guardrails (conditional — connector sessions only).

        The desktop_* tool schemas already teach the mechanics
        (screenshot-first clicking, offline errors, local MCP discovery);
        the prompt only states what NO tool description can: which
        execution surface is the user's real machine, and that the
        connector is bound to THIS session. Injected only when computer
        use is enabled for the session (2026-07 prompt diet — this
        replaced a ~1.5KB unconditional block in vtuber.md).
        """
        content = (
            "Desktop control: when the user asks you to act on THEIR "
            "computer, use the desktop_* tools yourself — never Bash (that "
            "runs in a server-side sandbox, not their machine) and never "
            "the sub-worker (the connector is bound to your session). If a "
            "tool reports the connector offline, ask the user to connect "
            "their Geny 접속기 and enable the capability. Their local MCP "
            "servers are reachable via local_mcp_list / local_mcp_call."
        )
        return PromptSection(
            name="computer_use",
            content=content,
            priority=45,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    @staticmethod
    def datetime_info() -> PromptSection:
        """Current time (1-line). Captures the time at prompt build."""
        from service.utils.utils import time_of_day_label

        tz = _get_tz()
        now_local = datetime.now(timezone.utc).astimezone(tz)
        abbr = now_local.strftime("%Z")
        # Weekday + part-of-day so the persona has an explicit anchor and never
        # mistakes e.g. a 09:51 morning for "evening".
        weekday = now_local.strftime("%A")
        part = time_of_day_label(now_local, "en")

        return PromptSection(
            name="datetime",
            content=(
                f"Current time: {now_local.strftime('%Y-%m-%d %H:%M:%S')} {abbr} "
                f"({weekday}, {part})"
            ),
            priority=45,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §11 Bootstrap Context — Project context files
    # ========================================================================

    @staticmethod
    def bootstrap_context(
        file_name: str,
        file_content: str,
        tag: Optional[str] = None,
    ) -> PromptSection:
        """Inject bootstrap file content into the prompt.

        Inspired by OpenClaw's <project-context> / <persona> pattern.
        """
        tag = tag or "project-context"

        return PromptSection(
            name=f"bootstrap_{file_name.replace('.', '_').replace('/', '_')}",
            content=file_content,
            priority=90,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
            tag=f'{tag} file="{file_name}"',
        )

    # ========================================================================
    # §12 Runtime Line — Runtime metadata
    # ========================================================================

    @staticmethod
    def runtime_line(
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        role: Optional[str] = None,
        version: str = "1.0.0",
    ) -> PromptSection:
        """Runtime metadata (1-line)."""
        parts = [f"Geny v{version}"]
        if model:
            parts.append(model)
        if session_id:
            parts.append(session_id[:8])
        if role:
            parts.append(role)

        return PromptSection(
            name="runtime_line",
            content=f"---\n{' | '.join(parts)}",
            priority=99,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )


class AutonomousPrompts:
    """Prompt templates for the AutonomousGraph execution paths.

    These were previously hardcoded as class attributes of ``AutonomousGraph``.
    Centralising them here keeps all prompt content in the prompt package and
    makes future refinement (e.g. A/B testing, per-model tuning) simple.

    Every method returns a format-string with named placeholders that the
    graph nodes fill via ``.format(**kwargs)``.
    """

    @staticmethod
    def classify_difficulty() -> str:
        """Prompt for difficulty classification (5-level)."""
        return (
            "You are a task difficulty classifier for an autonomous coding agent.\n"
            "Your classification determines the entire execution strategy and cost.\n"
            "A wrong classification wastes significant time and money.\n\n"
            "Classify the user's input into exactly one of these categories:\n\n"
            "## EASY\n"
            "Simple questions, greetings, factual lookups, basic calculations.\n"
            "No tool usage needed. A single short response suffices.\n"
            "Examples:\n"
            "  - \"Hello\", \"Thanks\", \"What is 2+2?\"\n"
            "  - \"What's the capital of France?\"\n"
            "  - \"Explain what a variable is\"\n\n"
            "## TOOL_DIRECT\n"
            "The task IS a tool operation. The user wants a specific tool executed,\n"
            "not reasoning or analysis. No planning or decomposition needed —\n"
            "just run the tool and report the result.\n"
            "Examples:\n"
            "  - \"Push to GitHub\" → just run git push\n"
            "  - \"npm install lodash\" → just run the install\n"
            "  - \"Delete the temp folder\" → just delete it\n"
            "  - \"Show git status\" → just run git status\n"
            "  - \"Create a new branch called feature/login\" → just create it\n"
            "NOT tool_direct (tools are means, not the goal):\n"
            "  - \"Fix this bug\" → needs analysis first\n"
            "  - \"Refactor this code\" → needs design decisions\n"
            "  - \"Write a function that...\" → needs code generation\n\n"
            "## MEDIUM\n"
            "Requires reasoning, explanation, or code generation, but can be\n"
            "fully addressed in a single response. No multi-step execution needed.\n"
            "Examples:\n"
            "  - \"Explain how photosynthesis works\"\n"
            "  - \"Compare Python and JavaScript\"\n"
            "  - \"Write a sorting function\"\n"
            "  - \"Review this code snippet\"\n\n"
            "## HARD\n"
            "Requires planning and multi-step execution. The task can be\n"
            "decomposed into a small number of steps (<=5) with predictable scope.\n"
            "Each step is relatively independent.\n"
            "Examples:\n"
            "  - \"Implement this feature based on the spec\"\n"
            "  - \"Build a simple library with these functions\"\n"
            "  - \"Debug this issue across multiple files\"\n"
            "  - \"Write comprehensive tests for this module\"\n\n"
            "## EXTREME\n"
            "Very high complexity. Large-scale refactoring, architecture redesign,\n"
            "or building complex systems from scratch. Scope is uncertain and steps\n"
            "are interdependent — later steps depend on results of earlier ones.\n"
            "Examples:\n"
            "  - \"Refactor the entire project structure\"\n"
            "  - \"Build a distributed system framework from scratch\"\n"
            "  - \"Migrate to a microservices architecture\"\n"
            "Important: Following a plan to implement is HARD, not EXTREME.\n"
            "Building a simple library is HARD, not EXTREME.\n"
            "When unsure between HARD and EXTREME, choose HARD (cheaper and safer).\n\n"
            "{memory_context}\n\n"
            "Input to classify:\n{input}\n\n"
            "Respond with ONLY one word: easy, tool_direct, medium, hard, extreme"
        )

    @staticmethod
    def classify_easy_or_not_easy() -> str:
        """Prompt for low-cost binary classification in optimized-autonomous."""
        return (
            "You are a cost-sensitive request router for an autonomous coding agent.\n"
            "Choose the cheapest route that can still solve the task correctly.\n\n"
            "Classify the user's request into exactly one category:\n\n"
            "## EASY\n"
            "Use EASY only when the request can be fully answered in one very short reply.\n"
            "No tools, no file changes, no planning, no multi-step reasoning.\n"
            "Examples:\n"
            "  - Greetings or acknowledgements\n"
            "  - Very small factual questions\n"
            "  - Tiny explanations that fit in 1-3 sentences\n\n"
            "## NOT_EASY\n"
            "Use NOT_EASY for everything else.\n"
            "This includes coding, debugging, analysis, tool execution, file edits,\n"
            "multi-step work, implementation, review, planning, and anything that\n"
            "benefits from a structured procedure.\n\n"
            "When uncertain, choose NOT_EASY.\n\n"
            "User request:\n{input}\n\n"
            "Respond with ONLY one word: easy or not_easy"
        )

    @staticmethod
    def optimized_easy_answer() -> str:
        """Prompt for the concise easy path in optimized-autonomous."""
        return (
            "You are on the EASY path.\n"
            "Answer the user's request as briefly as possible while remaining correct.\n"
            "Use 1-3 short sentences. Do not add plans, headings, extra caveats, or\n"
            "expanded background unless the user explicitly asks for them.\n\n"
            "User request:\n{input}"
        )

    @staticmethod
    def optimized_create_todos() -> str:
        """Prompt for a compact, execution-focused Not-Easy plan."""
        return (
            "Break the request into a minimal high-value execution plan.\n\n"
            "{memory_context}\n\n"
            "Request:\n{input}\n\n"
            "Return 1 to 4 TODO items only.\n"
            "Rules:\n"
            "- Each item should represent a major deliverable, not micro-steps\n"
            "- Prefer merging closely related work into one item\n"
            "- Keep the plan compact enough for batch execution\n"
            "- Order items logically\n\n"
            "Respond with JSON only in this form:\n"
            "[\n"
            '  {{"id": 1, "title": "Short title", "description": "What to do"}},\n'
            '  {{"id": 2, "title": "Short title", "description": "What to do"}}\n'
            "]"
        )

    @staticmethod
    def optimized_batch_execute() -> str:
        """Prompt for the low-call Not-Easy execution path."""
        return (
            "Execute the following compact plan efficiently and produce the final user-facing result.\n\n"
            "Overall Goal:\n{input}\n\n"
            "TODO Items:\n{todo_list}\n\n"
            "Requirements:\n"
            "- Complete all items in one coherent pass\n"
            "- Keep the response focused on the actual solution, not internal process\n"
            "- Include only the detail needed to solve the request correctly\n"
            "- If code or edits are required, provide the completed result directly\n"
            "- Avoid repeating the TODO list back verbatim unless necessary"
        )

    @staticmethod
    def review() -> str:
        """Prompt for quality review of a medium-path answer."""
        return (
            "You are a quality reviewer. Review the following answer "
            "for accuracy and completeness.\n\n"
            "Original Question:\n{question}\n\n"
            "Answer to Review:\n{answer}\n\n"
            "Review the answer and determine:\n"
            "1. Is the answer accurate and correct?\n"
            "2. Does it fully address the question?\n"
            "3. Is there anything missing or incorrect?\n\n"
            "Respond in this exact format:\n"
            "VERDICT: approved OR rejected\n"
            "FEEDBACK: (your detailed feedback)"
        )

    @staticmethod
    def create_todos() -> str:
        """Prompt for breaking a hard task into a JSON TODO list."""
        return (
            "You are a task planner. Break down the following complex task "
            "into smaller, manageable TODO items.\n\n"
            "{memory_context}\n\n"
            "Task:\n{input}\n\n"
            "Create a list of TODO items that, when completed in order, "
            "will fully accomplish the task.\n"
            "Each TODO should be:\n"
            "- Specific and actionable\n"
            "- Self-contained (can be executed independently)\n"
            "- Ordered logically (dependencies respected)\n\n"
            "Respond in this exact JSON format only (no markdown, no explanation):\n"
            "[\n"
            '  {{"id": 1, "title": "Short title", '
            '"description": "Detailed description of what to do"}},\n'
            '  {{"id": 2, "title": "Short title", '
            '"description": "Detailed description of what to do"}}\n'
            "]"
        )

    @staticmethod
    def execute_todo() -> str:
        """Prompt for executing a single TODO item from the plan."""
        return (
            "You are executing a specific task from a larger plan.\n\n"
            "Overall Goal:\n{goal}\n\n"
            "Current TODO Item:\n"
            "Title: {title}\n"
            "Description: {description}\n\n"
            "Previous completed items and their results:\n{previous_results}\n\n"
            "Execute this TODO item now. Provide a complete "
            "solution/implementation/answer for this specific item.\n"
            "Be thorough and ensure this item is fully completed."
        )

    @staticmethod
    def final_review() -> str:
        """Prompt for the final review of all completed TODO items."""
        return (
            "You are conducting a final review of a completed complex task.\n\n"
            "Original Request:\n{input}\n\n"
            "TODO Items and Results:\n{todo_results}\n\n"
            "Review the entire work:\n"
            "1. Was the original request fully addressed?\n"
            "2. Are all TODO items completed satisfactorily?\n"
            "3. Is there any integration work needed?\n"
            "4. Identify any gaps or issues.\n\n"
            "Provide your comprehensive review."
        )

    @staticmethod
    def final_answer() -> str:
        """Prompt for synthesizing the final comprehensive answer."""
        return (
            "Based on the completed work and review, provide the final "
            "comprehensive answer.\n\n"
            "Original Request:\n{input}\n\n"
            "Completed Work:\n{todo_results}\n\n"
            "Review Feedback:\n{review_feedback}\n\n"
            "Now provide the final, polished answer that addresses the "
            "original request completely.\n"
            "Synthesize all the completed work into a coherent, complete response."
        )

    @staticmethod
    def retry_with_feedback() -> str:
        """Prompt for retrying after a review rejection (medium path)."""
        return (
            "Previous attempt was rejected with this feedback:\n"
            "{previous_feedback}\n\n"
            "Please try again with the following request, "
            "addressing the feedback:\n{input_text}"
        )

    @staticmethod
    def check_relevance() -> str:
        """Prompt for the relevance gate in chat/broadcast mode.

        The gate determines whether a broadcast message is relevant
        to this agent's role and persona. Must be token-efficient.
        Returns format string with placeholders: agent_name, role, message.

        Uses structured JSON output for reliable parsing.
        """
        return (
            "You are **{agent_name}** (role: {role}).\n"
            "A message was broadcast to all agents in a group chat.\n\n"
            "Message: \"{message}\"\n\n"
            "Determine whether YOU should respond. Answer relevant=true when:\n"
            "- The message mentions your name (or a similar/abbreviated form)\n"
            "- The message targets your role or expertise area\n"
            "- It is a general request that clearly falls under your responsibilities\n\n"
            "Answer relevant=false when:\n"
            "- The message is directed at a DIFFERENT agent by name\n"
            "- The task is outside your role/expertise\n"
            "- Another agent is clearly better suited\n"
        )


def build_agent_prompt(
    agent_name: str = "Great Agent",
    role: str = "worker",
    agent_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    session_name: Optional[str] = None,
    character_display_name: Optional[str] = None,
    mode: PromptMode = PromptMode.FULL,
    context_files: Optional[Dict[str, str]] = None,
    extra_system_prompt: Optional[str] = None,
    in_gapt_workspace: bool = False,
    gapt_workspace_id: Optional[str] = None,
    gapt_cli_on_host: bool = False,
    role_protocol_override: Optional[str] = None,
    storage_path: Optional[str] = None,
    computer_use_enabled: bool = False,
) -> str:
    """Build the agent system prompt via the modular prompt builder.

    Final prompt layout::

        [Base prompt]          identity + geny_platform + role_protocol
                               + workspace + datetime + context_files
        ---
        [Template prompt]      additional specialization (from prompt template)
        ---
        [GAPT workspace]       sandbox + gapt_* tool guidance (when bound)

    Layers:
        1. Role prompt — auto-loaded from ``prompts/{role}.md``.
           Worker has none.  Fallback: empty.
        2. Template prompt — optional specialization from ``extra_system_prompt``.
           Selected independently via the Prompt Template dropdown.
        3. GAPT workspace — auto-appended when the session is bound to a GAPT
           workspace (the agent runs inside an isolated sandbox container).

    Design philosophy:
    - Claude API receives full tool schemas via MCP — no tool listing needed.
    - `geny-executor` Pipeline controls execution loop, retry, and completion.
    - The system prompt only needs: Identity + Role Behavior + Context.

    Sections NOT included (handled by infrastructure):
    - Tool descriptions / usage style / safety / status formats — the model
      receives full tool schemas via MCP and handles these natively; role .md
      files cover anything role-specific. (These dead section builders were
      removed in the 2026-06-25 prompt diet.)

    Args:
        agent_name: Display name for the agent.
        role: Role (worker/developer/researcher/planner/vtuber).
        agent_id: Agent identifier.
        working_dir: Working directory path.
        model: Model name.
        session_id: Session identifier.
        session_name: Operational session slug (e.g. user-typed ID). Exposed
            in the system prompt only as a labelled handle, NOT as the
            persona's name. See ``SectionLibrary.identity`` docstring for
            the full naming policy (cycle 20260422_6, principle E).
        character_display_name: Authoritative in-character display name.
            When set, the persona is told to use this as its own name.
            When unset, the persona is anonymous and (per first-encounter
            overlay) will ask the user how to be addressed. Ignored by
            non-VTuber roles.
        mode: Prompt detail level.
        context_files: Bootstrap file dict ``{filename: content}``.
        extra_system_prompt: Additional specialization prompt (from template or manual input).
        in_gapt_workspace: True when this session is bound to a GAPT workspace
            (the agent runs inside an isolated sandbox container at
            ``/workspace``). Appends the GAPT workspace + tool guidance section.

    Returns:
        Assembled system prompt string.
    """
    from service.prompt.template_loader import PromptTemplateLoader

    builder = PromptBuilder(mode=mode)

    # §1 Identity (1 line)
    builder.add_section(
        SectionLibrary.identity(
            agent_name,
            role,
            agent_id,
            session_name,
            character_display_name=character_display_name,
        )
    )

    # §1.5 User context (who the user is)
    user_section = SectionLibrary.user_context()
    if user_section:
        builder.add_section(user_section)

    # §1.7 Geny platform awareness
    builder.add_section(SectionLibrary.geny_platform(session_id=session_id))

    # §2 Role behavior — always from prompts/{role}.md.
    # Cycle 20260422_6 PR4 dropped the prior "worker = no role_protocol"
    # special-case: prompts/worker.md now carries the Worker output
    # discipline (and the conditional "## When You Are a Paired
    # Sub-Worker" section that replaces the old hard-coded ## Paired
    # VTuber Agent block in agent_session_manager). VTuber's role file
    # carries the persona contract.
    builder.add_section(SectionLibrary.role_protocol(role))
    # env = single source: a per-environment stored system prompt (seeded from
    # prompts/{role}.md, editable in the env's Stage-3 editor) wins over the
    # on-disk file. The file is only the seed / fallback for envs without one.
    role_md = role_protocol_override or PromptTemplateLoader().load_role_template(role)
    if role_md:
        builder.override_section("role_protocol", role_md)

    # §2.5 Desktop control — only for sessions that actually carry the
    # connector capability tools (VTuber, or env opt-in).
    if computer_use_enabled:
        builder.add_section(SectionLibrary.computer_use())

    # §3 Workspace
    if working_dir:
        builder.add_section(SectionLibrary.workspace(working_dir))

    # §3.5 Files workspace — short manifest of the session's host-side file
    # space (uploads/drafts/outputs). Details via WorkspaceInfo (progressive
    # disclosure); the sandbox counterpart is covered by the GAPT section.
    if storage_path:
        # Where this space SITS in the cloud, not whether a link exists. The
        # old probe looked for a `workspace/cloud` symlink; agent spaces live
        # inside the cloud directly now, so that link is gone and the probe
        # would report "not shared" for every session that is.
        _where = ""
        try:
            from service.cloud import owning_storage

            # `owning_storage` reads the adoption symlink, so it answers both
            # "is this space in the cloud" and "where" without needing the
            # username threaded through the prompt builder. A session that
            # was never adopted returns an empty prefix and stays silent.
            _where = owning_storage(storage_path)[1]
        except Exception:  # noqa: BLE001 — prompt must build regardless
            _where = ""
        # The address the tools answer to, not the address on disk.
        workspace_addr = "/workspace" if in_gapt_workspace else f"{storage_path}/workspace"
        builder.add_section(SectionLibrary.files_workspace(workspace_addr, _where))

    # §4 DateTime (FULL only)
    if mode == PromptMode.FULL:
        builder.add_section(SectionLibrary.datetime_info())

    # §5 Bootstrap context files (e.g. AGENTS.md, CLAUDE.md)
    if context_files:
        for filename, content in context_files.items():
            builder.add_section(
                SectionLibrary.bootstrap_context(filename, content)
            )

    # -- Assemble base prompt --
    base_prompt = builder.build()

    # -- Build final prompt with clear separators --
    parts = [base_prompt]

    # Template prompt section (additional specialization from Prompt Template dropdown)
    if extra_system_prompt and extra_system_prompt.strip():
        parts.append("---")
        parts.append(extra_system_prompt.strip())

    # GAPT workspace section — the agent runs inside an isolated, persistent
    # sandbox container. Tell it where it works + how to make separate spaces.
    if in_gapt_workspace:
        wid = (gapt_workspace_id or "").strip()
        wid_line = (
            f"Your persistent, isolated GAPT workspace for this session is "
            f"`{wid}` (mounted at /workspace).\n"
            if wid
            else "You have a persistent, isolated GAPT workspace at /workspace.\n"
        )
        if gapt_cli_on_host:
            # claude_code_cli runs on the HOST (OAuth-safe); only the GAPT/forge
            # tools execute inside the workspace. Be explicit so the agent does
            # workspace work through those tools, not its host-side built-ins.
            where_line = (
                "IMPORTANT: your built-in Read/Write/Edit/Bash tools run on the "
                "HOST, not in this workspace. To create, edit, run, and persist "
                "code IN the workspace (the isolated sandbox), use the GAPT tools "
                "and forge_tool:\n"
                "- gapt_run_command — run a shell command inside the workspace\n"
                "- forge_tool — turn a script in the workspace into a callable tool\n"
                "- env(action=\"save_pack\") — save [workspace + tools + skills] as a reusable pack\n"
            )
        else:
            where_line = (
                "You run inside this workspace at /workspace — your file/shell "
                "tools operate there directly. Files persist for this session and "
                "are isolated from the host and other sessions. Use forge_tool to "
                "turn a script into a callable tool, and env(action=\"save_pack\") "
                "to save [workspace + tools + skills] as a reusable pack.\n"
            )
        # Tool names (gapt_*, forge_tool, …) are NOT listed — their schemas are
        # provided to the model. The prompt states only the non-discoverable facts:
        # where the workspace is, and that a separate persistent project space exists.
        gapt_section = (
            "---\n"
            + wid_line
            + where_line
            + "The sandbox is your FREE environment — install packages, run "
            "services, build whatever you need; it is isolated from the host. "
            "It is separate from your files workspace: bridge files between the "
            "two with SandboxPut / SandboxFetch (SandboxInfo shows sandbox "
            "state).\n"
            "For work that must persist across sessions or be deployed, a separate, "
            "fully-isolated GAPT project space is available via your project tools."
        )
        parts.append(gapt_section)

    return "\n\n".join(parts)
