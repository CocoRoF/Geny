"""
프롬프트 섹션 라이브러리

OpenClaw의 25+ 섹션 설계를 참고하여
Geny Agent에 적합한 15개 핵심 섹션을 정의합니다.

각 섹션은 PromptSection 객체로 생성되며,
PromptBuilder에 등록하여 조건부로 조립됩니다.
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
    """프롬프트 섹션 생성 팩토리.

    각 메서드는 PromptSection 객체를 생성하여 반환합니다.
    PromptBuilder에 add_section()으로 등록하세요.
    """

    # ========================================================================
    # §1 Identity — 에이전트 정체성
    # ========================================================================

    @staticmethod
    def identity(
        agent_name: str = "Geny Agent",
        role: str = "worker",
        agent_id: Optional[str] = None,
    ) -> PromptSection:
        """에이전트 정체성 섹션 (간결)."""
        parts = [f"You are {agent_name} (role: {role})."]
        if agent_id:
            parts.append(f"Agent ID: {agent_id}")

        return PromptSection(
            name="identity",
            content=" ".join(parts),
            priority=10,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §2 Role Protocol — 역할별 행동 지침
    # ========================================================================

    @staticmethod
    def role_protocol(role: str = "worker") -> PromptSection:
        """역할별 상세 행동 지침 섹션."""

        # Lean fallback protocols — only used when no prompts/*.md file exists
        protocols = {
            "worker": "Complete assigned tasks autonomously. Break complex work into steps, resolve issues yourself, and produce quality results.",
            "developer": "Write clean, production-quality code. Read existing code before changing it, follow project conventions, handle edge cases, and test your changes.",
            "manager": "Plan, delegate, and coordinate — never do implementation work yourself. Use `list_workers`, `delegate_task`, `get_worker_status`, and `broadcast_task` to manage workers.",
            "researcher": "Gather comprehensive information, analyze critically, and present structured findings. Note limitations and suggest further investigation.",
            "self-manager": "You are fully autonomous. Plan, execute, verify, and iterate until the task is completely finished. Never ask for guidance. End every non-final response with `[CONTINUE: {next_action}]`. When all work is verified: `[TASK_COMPLETE]`.",
        }

        content = protocols.get(role, protocols["worker"])

        return PromptSection(
            name="role_protocol",
            content=content,
            priority=15,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §3 Capabilities — 사용 가능 도구 목록
    # ========================================================================

    @staticmethod
    def capabilities(
        tools: Optional[List[str]] = None,
        mcp_servers: Optional[List[str]] = None,
    ) -> PromptSection:
        """사용 가능한 도구/MCP 서버 목록 섹션.

        Claude CLI 기본 도구는 이미 내장되어 있으므로,
        추가 MCP 서버나 커스텀 도구만 명시합니다.
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
    # §4 Tool Style — 도구 사용 스타일 가이드
    # ========================================================================

    @staticmethod
    def tool_style() -> PromptSection:
        """도구 호출 형식 및 결과 처리 가이드."""
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
    # §5 Safety — 안전 가이드라인
    # ========================================================================

    @staticmethod
    def safety() -> PromptSection:
        """안전 가이드라인 섹션."""
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
    # §6 Workspace — 작업 환경 정보
    # ========================================================================

    @staticmethod
    def workspace(
        working_dir: str,
        project_name: Optional[str] = None,
        file_tree: Optional[str] = None,
    ) -> PromptSection:
        """작업 디렉토리 정보 섹션 (간결)."""
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
    # §7 DateTime — 현재 시각 정보
    # ========================================================================

    @staticmethod
    def datetime_info() -> PromptSection:
        """현재 시각 정보 (1-line). 빌드 시점의 시각을 캡처."""
        now_kst = datetime.now(timezone.utc).astimezone(KST)

        return PromptSection(
            name="datetime",
            content=f"Current time: {now_kst.strftime('%Y-%m-%d %H:%M:%S KST')}",
            priority=45,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §8 Context Efficiency — 토큰 효율 가이드
    # ========================================================================

    @staticmethod
    def context_efficiency() -> PromptSection:
        """토큰 효율적 응답 가이드."""
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
    # §9 Delegation — Manager 전용 위임 프로토콜
    # ========================================================================

    @staticmethod
    def delegation(worker_tools: Optional[List[str]] = None) -> PromptSection:
        """Manager 전용 위임 프로토콜 섹션."""
        tools_list = worker_tools or ["list_workers", "delegate_task", "get_worker_status", "broadcast_task"]

        content = f"""## Delegation Protocol

### Available Management Tools
{chr(10).join(f'- `{t}`' for t in tools_list)}

### Delegation Best Practices
- **Be specific**: Include enough detail in task descriptions for Workers to act independently
- **Check availability**: Always `list_workers` before delegating
- **Match capabilities**: Assign tasks to Workers with relevant expertise
- **Clear success criteria**: Define what "done" looks like for each delegated task
- **Parallel where possible**: Use `broadcast_task` when tasks are independent"""

        return PromptSection(
            name="delegation",
            content=content,
            priority=55,
            modes={PromptMode.FULL},
        )

    # ========================================================================
    # §10 Status Reporting — Worker 진행 상태 보고
    # ========================================================================

    @staticmethod
    def status_reporting() -> PromptSection:
        """Worker 진행 상태 보고 형식."""
        content = """## Status Reporting

When reporting progress to the Manager or system, use this format:

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
    # §11 Bootstrap Context — 프로젝트 컨텍스트 파일
    # ========================================================================

    @staticmethod
    def bootstrap_context(
        file_name: str,
        file_content: str,
        tag: Optional[str] = None,
    ) -> PromptSection:
        """부트스트랩 파일 내용을 프롬프트에 주입.

        OpenClaw의 <project-context> / <persona> 패턴 참고.
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
    # §12 Runtime Line — 런타임 메타 정보
    # ========================================================================

    @staticmethod
    def runtime_line(
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        role: Optional[str] = None,
        version: str = "1.0.0",
    ) -> PromptSection:
        """런타임 메타 정보 (1-line)."""
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
        """
        return (
            "You are {agent_name} (role: {role}).\n"
            "A group chat message was sent to all agents.\n\n"
            "Message: {message}\n\n"
            "Should you respond to this message? Consider:\n"
            "- Is it directed at you by name or role?\n"
            "- Is it relevant to your expertise/responsibilities?\n"
            "- Is it a general question that you should answer?\n\n"
            "Reply ONLY with: YES or NO"
        )


def build_agent_prompt(
    agent_name: str = "Geny Agent",
    role: str = "worker",
    agent_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    tools: Optional[List[str]] = None,
    mcp_servers: Optional[List[str]] = None,
    mode: PromptMode = PromptMode.FULL,
    context_files: Optional[Dict[str, str]] = None,
    extra_system_prompt: Optional[str] = None,
) -> str:
    """Build the agent system prompt via the modular prompt builder.

    Design philosophy:
    - Claude CLI already provides tool knowledge, safety, and error handling.
    - LangGraph graph controls execution loop, retry, and completion.
    - The system prompt only needs: Identity + Role Behavior + Context.

    Sections removed (handled by infrastructure):
    - tool_style: Claude CLI knows its own tools
    - safety: Claude CLI has built-in safety
    - context_efficiency: ContextWindowGuard handles budget
    - execution_protocol: LangGraph graph controls the loop
    - error_recovery: _resilient_invoke + Claude's natural debugging
    - completion_signals: Only self-manager needs signals (in .md file)
    - delegation: Merged into manager.md template
    - status_reporting: Graph nodes track status
    - safety_wrap: Claude CLI has its own guardrails

    Args:
        agent_name: Display name for the agent.
        role: Role (worker/manager/developer/researcher/self-manager).
        agent_id: Agent identifier.
        working_dir: Working directory path.
        model: Model name.
        session_id: Session identifier.
        tools: List of available tool names.
        mcp_servers: List of MCP server names.
        mode: Prompt detail level.
        context_files: Bootstrap file dict ``{filename: content}``.
        extra_system_prompt: Additional system prompt appended at end.

    Returns:
        Assembled system prompt string.
    """
    from service.prompt.template_loader import PromptTemplateLoader

    builder = PromptBuilder(mode=mode)

    # §1 Identity (1 line)
    builder.add_section(SectionLibrary.identity(agent_name, role, agent_id))

    # §2 Role behavior (from prompts/*.md, or lean fallback)
    builder.add_section(SectionLibrary.role_protocol(role))
    loader = PromptTemplateLoader()
    md_template = loader.load_role_template(role)
    if md_template:
        builder.override_section("role_protocol", md_template)

    # §3 Capabilities — only when non-default MCP/tools are configured
    if tools or mcp_servers:
        builder.add_section(SectionLibrary.capabilities(tools, mcp_servers))

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

    # §7 Runtime metadata
    builder.add_section(
        SectionLibrary.runtime_line(model, session_id, role)
    )

    # §8 Extra system prompt (user-provided)
    if extra_system_prompt:
        builder.add_extra_context(extra_system_prompt)

    return builder.build()
