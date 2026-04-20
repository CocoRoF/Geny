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
    ) -> PromptSection:
        """Agent identity section (concise one-liner)."""
        identity_line = SectionLibrary._ROLE_IDENTITY.get(role, f"You are a Geny agent (role: {role}).")
        parts = [identity_line]
        if session_name:
            parts.append(f"Your name is \"{session_name}\".")
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
        parts = [
            "## Geny Platform",
            "",
            "You are running inside the Geny multi-agent platform.",
            "You have platform tools (provided via MCP) for:",
            "- Managing agent sessions (list, create, inspect)",
            "- Messaging (send/read messages to rooms or directly to other agents)",
            "- Room collaboration (create rooms, add members)",
        ]
        if session_id:
            parts.append("")
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
    # §4 Tool Style — NOT IN USE
    # ========================================================================
    # Claude CLI handles tool invocation guidelines natively.
    # Kept for potential future use (e.g. role-specific tool policies).

    @staticmethod
    def tool_style() -> PromptSection:
        """Tool invocation guidelines. NOT IN USE — Claude CLI handles this."""
        content = """## Tool Usage Guidelines

### Efficiency Principles
- **Batch operations**: When multiple files need reading, read them in sequence rather than one at a time
- **Targeted searches**: Use specific search queries; avoid overly broad searches
- **Minimal writes**: Write files only when necessary; avoid creating unnecessary files
- **Verify before modify**: Always read a file before editing it to understand current state

### Error Handling in Tool Use
- If a tool call fails, analyze the error and retry with corrected parameters
- If a file doesn't exist, create it (don't ask)
- If a command fails, check the output and debug
- Never repeat the exact same failing tool call without modifying your approach

### Output Processing
- Extract relevant information from tool results
- Don't dump raw tool output in your response unless specifically asked
- Summarize large outputs to preserve context window space"""

        return PromptSection(
            name="tool_style",
            content=content,
            priority=25,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §5 Safety — NOT IN USE
    # ========================================================================
    # Claude CLI provides built-in safety guidelines.
    # Kept for potential future use (e.g. stricter project-specific policies).

    @staticmethod
    def safety() -> PromptSection:
        """Safety guidelines. NOT IN USE — Claude CLI handles this."""
        content = """## Safety Guidelines

### Data Protection
- Never expose API keys, tokens, passwords, or other secrets in your output
- If you encounter credentials in code, note their presence but don't display them
- Treat file contents as potentially sensitive

### Destructive Operations
- Before deleting files or directories, verify the path is correct
- When modifying critical system files, create a backup first
- Avoid running commands that could damage the system (rm -rf /, format, etc.)

### Scope Boundaries
- Stay within the assigned working directory
- Do not access files outside the project scope unless explicitly instructed
- Do not make network requests to unknown external services
- Do not modify system configuration files"""

        return PromptSection(
            name="safety",
            content=content,
            priority=30,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

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

    # ========================================================================
    # §7 DateTime — Current time
    # ========================================================================

    @staticmethod
    def datetime_info() -> PromptSection:
        """Current time (1-line). Captures the time at prompt build."""
        tz = _get_tz()
        now_local = datetime.now(timezone.utc).astimezone(tz)
        abbr = now_local.strftime("%Z")

        return PromptSection(
            name="datetime",
            content=f"Current time: {now_local.strftime('%Y-%m-%d %H:%M:%S')} {abbr}",
            priority=45,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §8 Context Efficiency — NOT IN USE
    # ========================================================================
    # Claude CLI and role .md files handle response style.
    # Kept for potential future use.

    @staticmethod
    def context_efficiency() -> PromptSection:
        """Token-efficient response guide. NOT IN USE."""
        content = """## Context Efficiency

Be mindful of context window limits. Follow these guidelines:
- **Concise responses**: Don't repeat the question or task description in your answer
- **Summarize large outputs**: If a tool returns extensive output, summarize key findings
- **Avoid redundancy**: Don't explain what you're about to do AND then do it — just do it
- **Progressive detail**: Start with a summary, add detail only when necessary
- **Truncate tool results**: When tool output exceeds ~500 lines, extract only the relevant parts"""

        return PromptSection(
            name="context_efficiency",
            content=content,
            priority=50,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §10 Status Reporting — NOT IN USE
    # ========================================================================
    # Role .md files can define their own reporting format.
    # Kept for potential future use.

    @staticmethod
    def status_reporting() -> PromptSection:
        """Worker progress reporting format. NOT IN USE."""
        content = """## Status Reporting

When reporting progress, use this format:

```
## Task Status Report
- **Status**: COMPLETED | IN_PROGRESS | BLOCKED | FAILED
- **Progress**: X/Y steps completed
- **Summary**: Brief description of what was accomplished
- **Output**: Key results or deliverables
- **Issues**: Problems encountered (or "None")
- **Next Steps**: What remains to be done (if IN_PROGRESS)
```

Always provide actionable information. If blocked, explain what's needed to unblock."""

        return PromptSection(
            name="status_reporting",
            content=content,
            priority=60,
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
    mode: PromptMode = PromptMode.FULL,
    context_files: Optional[Dict[str, str]] = None,
    extra_system_prompt: Optional[str] = None,
    shared_folder_path: Optional[str] = None,
) -> str:
    """Build the agent system prompt via the modular prompt builder.

    Final prompt layout::

        [Base prompt]          identity + geny_platform + role_protocol
                               + workspace + datetime + context_files
        ---
        [Template prompt]      additional specialization (from prompt template)
        ---
        [Shared folder info]   shared folder instructions (if enabled)

    Layers:
        1. Role prompt — auto-loaded from ``prompts/{role}.md``.
           Worker has none.  Fallback: empty.
        2. Template prompt — optional specialization from ``extra_system_prompt``.
           Selected independently via the Prompt Template dropdown.
        3. Shared folder — auto-appended when enabled.

    Design philosophy:
    - Claude CLI receives full tool schemas via MCP — no tool listing needed.
    - LangGraph graph controls execution loop, retry, and completion.
    - The system prompt only needs: Identity + Role Behavior + Context.

    Sections NOT included (handled by infrastructure):
    - capabilities — removed; MCP provides tool schemas directly to Claude CLI.
    - tool_style, safety, context_efficiency, status_reporting — handled by
      Claude CLI natively or by role .md files when needed.

    Args:
        agent_name: Display name for the agent.
        role: Role (worker/developer/researcher/planner/vtuber).
        agent_id: Agent identifier.
        working_dir: Working directory path.
        model: Model name.
        session_id: Session identifier.
        session_name: Session display name — the agent recognizes it as its own name.
        mode: Prompt detail level.
        context_files: Bootstrap file dict ``{filename: content}``.
        extra_system_prompt: Additional specialization prompt (from template or manual input).
        shared_folder_path: Relative path to the shared folder (e.g. ``_shared``).

    Returns:
        Assembled system prompt string.
    """
    from service.prompt.template_loader import PromptTemplateLoader

    builder = PromptBuilder(mode=mode)

    # §1 Identity (1 line)
    builder.add_section(SectionLibrary.identity(agent_name, role, agent_id, session_name))

    # §1.5 User context (who the user is)
    user_section = SectionLibrary.user_context()
    if user_section:
        builder.add_section(user_section)

    # §1.7 Geny platform awareness
    builder.add_section(SectionLibrary.geny_platform(session_id=session_id))

    # §2 Role behavior — always from prompts/{role}.md (worker = none)
    if role != "worker":
        builder.add_section(SectionLibrary.role_protocol(role))
        loader = PromptTemplateLoader()
        md_template = loader.load_role_template(role)
        if md_template:
            builder.override_section("role_protocol", md_template)

    # §3 Workspace
    if working_dir:
        builder.add_section(SectionLibrary.workspace(working_dir))

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

    # Shared folder section
    if shared_folder_path:
        shared_section = (
            "---\n"
            f"Shared Folder: ./{shared_folder_path}/\n"
            f"A shared directory accessible by ALL sessions. "
            f"Use it to exchange files, data, and artifacts between sessions."
        )
        parts.append(shared_section)

    return "\n\n".join(parts)
