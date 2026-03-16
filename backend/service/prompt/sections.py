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

# KST timezone
KST = timezone(timedelta(hours=9))


class SectionLibrary:
    """Prompt section factory.

    Each static method creates and returns a PromptSection object.
    Register via PromptBuilder.add_section().
    """

    # ========================================================================
    # §1 Identity — Agent identity
    # ========================================================================

    @staticmethod
    def identity(
        agent_name: str = "Great Agent",
        role: str = "worker",
        agent_id: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> PromptSection:
        """Agent identity section (concise one-liner)."""
        parts = [f"You are a Great Agent (role: {role})."]
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
    # §2 Role Protocol — Per-role behavior instructions
    # ========================================================================

    @staticmethod
    def role_protocol(role: str = "worker") -> PromptSection:
        """Per-role behavior protocol section.

        Worker has no role-specific prompt — it operates as a
        general-purpose agent with only the base identity.
        """

        # Lean fallback protocols — only used when no prompts/*.md file exists
        protocols = {
            "worker": "",  # No role-specific behavior — general purpose agent
            "developer": "Execute implementation tasks with precision. Read existing code before changing it, follow project conventions, handle edge cases, and test your changes.",
            "researcher": "Discover cutting-edge information, explore emerging technologies, and generate actionable product ideas. Explore diverse sources broadly, try things hands-on, and synthesize findings into concise idea summaries.",
            "planner": "Evaluate ideas critically and transform promising ones into comprehensive, production-ready plans. Produce detailed specifications, architecture designs, and implementation guides that developers can build from directly.",
        }

        content = protocols.get(role, "")

        return PromptSection(
            name="role_protocol",
            content=content,
            priority=15,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §3 Capabilities — Available tools
    # ========================================================================

    @staticmethod
    def capabilities(
        tools: Optional[List[str]] = None,
        mcp_servers: Optional[List[str]] = None,
    ) -> PromptSection:
        """Available tools/MCP server list section.

        Claude CLI built-in tools are already known, so only
        additional MCP servers or custom tools are listed.
        """
        parts: List[str] = []

        if mcp_servers:
            parts.append("MCP servers: " + ", ".join(mcp_servers))

        if tools:
            parts.append("Additional tools: " + ", ".join(tools))

        if not parts:
            # No extra capabilities beyond Claude CLI defaults — skip section
            return PromptSection(
                name="capabilities",
                content="",
                priority=20,
                modes={PromptMode.FULL, PromptMode.MINIMAL},
            )

        return PromptSection(
            name="capabilities",
            content="\n".join(parts),
            priority=20,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §4 Tool Style — Tool usage guidelines
    # ========================================================================

    @staticmethod
    def tool_style() -> PromptSection:
        """Tool invocation format and result handling guide."""
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
    # §5 Safety — Safety guidelines
    # ========================================================================

    @staticmethod
    def safety() -> PromptSection:
        """Safety guidelines section."""
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
        now_kst = datetime.now(timezone.utc).astimezone(KST)

        return PromptSection(
            name="datetime",
            content=f"Current time: {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}",
            priority=45,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §8 Context Efficiency — Token-efficient response guidelines
    # ========================================================================

    @staticmethod
    def context_efficiency() -> PromptSection:
        """Token-efficient response guide."""
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
    # §10 Status Reporting — Worker progress reporting
    # ========================================================================

    @staticmethod
    def status_reporting() -> PromptSection:
        """Worker progress reporting format."""
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
    # §11.5 Tool Search — Dynamic tool discovery instructions
    # ========================================================================

    @staticmethod
    def tool_search_instructions() -> PromptSection:
        """Instructions for tool-search mode where agent discovers and executes tools dynamically."""
        content = """## Tool Discovery & Execution Mode

You are operating in **tool search mode**. You do NOT have direct access to all tools upfront. Instead, you have 5 discovery and execution tools:

### Available Tools
1. **tool_search(query)** — Search for tools by describing what you need (e.g., "read a file", "search git history")
2. **tool_schema(tool_name)** — Get the full parameter schema for a specific tool before calling it
3. **tool_execute(tool_name, parameters)** — Execute a discovered tool with the given parameters
4. **tool_browse()** — Browse all available tools organized by category
5. **tool_workflow(tool_name)** — Get the recommended execution sequence for a tool

### Workflow
1. When you need to perform an action, first use `tool_search` to find relevant tools
2. Use `tool_schema` to get the exact parameters needed
3. Use `tool_execute` to run the tool with the correct parameters
4. For multi-step operations, use `tool_workflow` to understand the typical tool chain

### Important
- Always search before assuming a tool exists
- Always get the schema before calling an unfamiliar tool
- Execute tools through `tool_execute` — do NOT try to call discovered tools directly
- Use `tool_browse` to get an overview of all available tool categories"""

        return PromptSection(
            name="tool_search_instructions",
            content=content,
            priority=22,  # right after capabilities (20)
            modes={PromptMode.FULL, PromptMode.MINIMAL},
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
        """Prompt for difficulty classification (easy / medium / hard)."""
        return (
            "You are a task difficulty classifier. "
            "Analyze the given input and classify its difficulty level.\n\n"
            "Classification criteria:\n"
            "- EASY: Simple questions, factual lookups, basic calculations, straightforward requests\n"
            "  Examples: \"What is 2+2?\", \"What is the capital of France?\", \"Hello, how are you?\"\n\n"
            "- MEDIUM: Moderate complexity, requires some reasoning or multi-step thinking, "
            "but can be done in one response\n"
            "  Examples: \"Explain how photosynthesis works\", \"Compare Python and JavaScript\", "
            "\"Write a simple function\"\n\n"
            "- HARD: Complex tasks requiring multiple steps, research, planning, or iterative execution\n"
            "  Examples: \"Build a web application\", \"Debug this complex codebase\", "
            "\"Design a system architecture\"\n\n"
            "IMPORTANT: Respond with ONLY one of these exact words: easy, medium, hard\n\n"
            "{memory_context}\n\n"
            "Input to classify:\n{input}"
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
    tools: Optional[List[str]] = None,
    mcp_servers: Optional[List[str]] = None,
    mode: PromptMode = PromptMode.FULL,
    context_files: Optional[Dict[str, str]] = None,
    extra_system_prompt: Optional[str] = None,
    shared_folder_path: Optional[str] = None,
    tool_search_mode: bool = False,
) -> str:
    """Build the agent system prompt via the modular prompt builder.

    Final prompt layout::

        [Base prompt]          identity + role_protocol + capabilities
                               + workspace + datetime + context_files
        ---
        [Template prompt]      additional specialization (from prompt template)
        ---
        [Shared folder info]   shared folder instructions (if enabled)

    Layers:
        1. Role prompt — auto-loaded from ``prompts/{role}.md``.
           Worker has none.  Fallback: hardcoded one-liner.
        2. Template prompt — optional specialization from ``extra_system_prompt``.
           Selected independently via the Prompt Template dropdown.
        3. Shared folder — auto-appended when enabled.

    Design philosophy:
    - Claude CLI already provides tool knowledge, safety, and error handling.
    - LangGraph graph controls execution loop, retry, and completion.
    - The system prompt only needs: Identity + Role Behavior + Context.

    Sections handled by infrastructure (not included here):
    - tool_style, safety, context_efficiency, execution_protocol,
      error_recovery, completion_signals, status_reporting,
      safety_wrap — all handled by Claude CLI, LangGraph, or role .md files.

    Args:
        agent_name: Display name for the agent.
        role: Role (worker/developer/researcher/planner).
        agent_id: Agent identifier.
        working_dir: Working directory path.
        model: Model name.
        session_id: Session identifier.
        session_name: Session display name — the agent recognizes it as its own name.
        tools: List of available tool names.
        mcp_servers: List of MCP server names.
        mode: Prompt detail level.
        context_files: Bootstrap file dict ``{filename: content}``.
        extra_system_prompt: Additional specialization prompt (from template or manual input).
        shared_folder_path: Relative path to the shared folder (e.g. ``_shared``).
        tool_search_mode: If True, inject tool-search discovery instructions.

    Returns:
        Assembled system prompt string.
    """
    from service.prompt.template_loader import PromptTemplateLoader

    builder = PromptBuilder(mode=mode)

    # §1 Identity (1 line)
    builder.add_section(SectionLibrary.identity(agent_name, role, agent_id, session_name))

    # §2 Role behavior — always from prompts/{role}.md (worker = none)
    if role != "worker":
        builder.add_section(SectionLibrary.role_protocol(role))
        loader = PromptTemplateLoader()
        md_template = loader.load_role_template(role)
        if md_template:
            builder.override_section("role_protocol", md_template)

    # §3 Capabilities — only when non-default MCP/tools are configured
    if tools or mcp_servers:
        builder.add_section(SectionLibrary.capabilities(tools, mcp_servers))

    # §3.5 Tool Search Instructions — when tool_search_mode is active
    if tool_search_mode:
        builder.add_section(SectionLibrary.tool_search_instructions())

    # §4 Workspace
    if working_dir:
        builder.add_section(SectionLibrary.workspace(working_dir))

    # §5 DateTime (FULL only)
    if mode == PromptMode.FULL:
        builder.add_section(SectionLibrary.datetime_info())

    # §6 Bootstrap context files (e.g. AGENTS.md, CLAUDE.md)
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
