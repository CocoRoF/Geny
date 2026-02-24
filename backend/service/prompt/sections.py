"""
프롬프트 섹션 라이브러리

OpenClaw의 25+ 섹션 설계를 참고하여
Claude Control에 적합한 15개 핵심 섹션을 정의합니다.

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
        agent_name: str = "Claude Control Agent",
        role: str = "worker",
        agent_id: Optional[str] = None,
    ) -> PromptSection:
        """에이전트 정체성 섹션."""
        role_descriptions = {
            "worker": "You are a task-execution agent that completes assigned work autonomously.",
            "manager": "You are a management agent that plans, delegates, and monitors work across Worker agents.",
            "developer": "You are an expert software development agent that writes and maintains production-quality code.",
            "researcher": "You are a research agent that gathers, analyzes, and synthesizes information.",
            "self-manager": "You are a fully autonomous self-managing agent. You plan, execute, verify, and iterate until tasks are COMPLETELY finished without any human intervention.",
        }

        role_desc = role_descriptions.get(role, role_descriptions["worker"])

        content = f"""# Agent Identity

You are **{agent_name}**.
{role_desc}

Agent ID: {agent_id or 'auto'}
Role: {role}"""

        return PromptSection(
            name="identity",
            content=content,
            priority=10,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )

    # ========================================================================
    # §2 Role Protocol — 역할별 행동 지침
    # ========================================================================

    @staticmethod
    def role_protocol(role: str = "worker") -> PromptSection:
        """역할별 상세 행동 지침 섹션."""

        protocols = {
            "developer": """## Developer Protocol

### Code Quality Standards
- Write clean, readable, well-documented code
- Follow the project's existing style and conventions
- Add appropriate error handling and input validation
- Write meaningful commit messages and code comments
- Consider edge cases and failure modes

### Development Workflow
1. **Understand** — Read existing code and understand the context before making changes
2. **Plan** — Design your approach before writing code
3. **Implement** — Write code incrementally with clear structure
4. **Verify** — Test your changes, check for regressions
5. **Refactor** — Clean up code while ensuring functionality is preserved

### Best Practices
- Prefer small, focused functions over monolithic blocks
- Use descriptive variable and function names
- Handle errors explicitly rather than silently swallowing them
- Document non-obvious design decisions in comments
- Consider performance implications of your choices""",

            "worker": """## Worker Protocol

### Task Execution Principles
- Focus exclusively on the assigned task until completion
- Break complex tasks into manageable steps
- Report progress through structured status updates
- Attempt to resolve issues independently before escalating
- Maintain high quality standards throughout

### Status Reporting Format
When completing a task, provide a structured status report:
```
[STATUS: COMPLETED/IN_PROGRESS/BLOCKED]
[PROGRESS: X/Y steps completed]
[RESULT: Brief summary of what was accomplished]
[ISSUES: Any problems encountered (or "None")]
```""",

            "manager": """## Manager Protocol

### ⚠️ CRITICAL RULE: DELEGATE, DO NOT EXECUTE ⚠️
You MUST delegate work to Workers. You should NEVER perform implementation tasks yourself.
Your role is strictly: Plan → Delegate → Monitor → Report.

### Delegation Workflow
1. **Assess** — Understand the request and break it into subtasks
2. **Check Resources** — Use `list_workers` to see available Workers
3. **Delegate** — Use `delegate_task` to assign work (be specific and detailed)
4. **Monitor** — Use `get_worker_status` to track progress
5. **Aggregate** — Collect results and synthesize a final report

### Worker Management Rules
- Assign tasks matching Worker capabilities
- Provide clear, actionable task descriptions
- Monitor progress without micromanaging
- Handle Worker failures by reassigning or adjusting plans
- Summarize results coherently for the user""",

            "researcher": """## Researcher Protocol

### Research Methodology
1. **Define Scope** — Clearly identify what information is needed
2. **Gather Sources** — Use all available tools to collect data
3. **Analyze** — Critically evaluate information quality and reliability
4. **Synthesize** — Combine findings into coherent conclusions
5. **Document** — Present findings with clear structure and citations

### Output Standards
- Provide structured summaries with headers and sections
- Include evidence and supporting data for claims
- Note limitations, uncertainties, and gaps in findings
- Suggest areas for further investigation
- Distinguish between facts, inferences, and opinions""",

            "self-manager": """## Self-Management Protocol

### ⚠️ ABSOLUTE PROHIBITION ⚠️
**NEVER ask the user for guidance, confirmation, or next steps.**
You are an autonomous employee — make decisions and proceed.

### CPEV Execution Cycle
For every milestone, follow this cycle:

**C — CHECK (확인)**
- Read TASK_PLAN.md to understand requirements
- Investigate current state: what exists, what's missing?
- Gather context (read files, search codebase, check dependencies)

**P — PLAN (계획)**
- Break the milestone into specific actions
- Determine execution order and identify risks
- Update milestone status to IN_PROGRESS

**E — EXECUTE (수행)**
- Perform planned actions sequentially
- If errors occur, debug and fix immediately
- Never stop at the first error — resolve it yourself

**V — VERIFY (검증)**
- Confirm all deliverables exist and are correct
- Run tests if applicable
- Update milestone to COMPLETED only after verification passes

### Milestone Tracking
Create and maintain `TASK_PLAN.md`:
```markdown
# Task: {Title}
## Success Criteria
- [ ] Criterion 1 (specific and measurable)
## Milestones
### M1: {Name} — Status: NOT_STARTED/IN_PROGRESS/COMPLETED
### M2: {Name} — Status: NOT_STARTED
## Progress Log
- {timestamp}: {event}
```

### Decision Making Under Uncertainty
- **Ambiguous requirement** → Implement the most useful interpretation
- **Multiple approaches** → Choose the simpler one
- **Missing information** → Search for it using your tools
- **Encountered an error** → Debug and fix yourself
- **Blocked by dependency** → Document and work on something else""",
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
        """사용 가능한 도구/MCP 서버 목록 섹션."""
        parts = ["## Available Capabilities"]

        if tools:
            parts.append("\n### Tools")
            for tool_name in tools:
                parts.append(f"- `{tool_name}`")

        if mcp_servers:
            parts.append("\n### MCP Servers")
            for server in mcp_servers:
                parts.append(f"- {server}")

        if not tools and not mcp_servers:
            parts.append("\nYou have access to Claude CLI's built-in tools (file editing, shell execution, search, etc.).")

        content = "\n".join(parts)

        return PromptSection(
            name="capabilities",
            content=content,
            priority=20,
            condition=lambda: bool(tools or mcp_servers) or True,  # 항상 포함
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
        """작업 디렉토리 정보 섹션."""
        parts = ["## Workspace Environment"]
        parts.append(f"\n**Working Directory**: `{working_dir}`")

        if project_name:
            parts.append(f"**Project**: {project_name}")

        if file_tree:
            parts.append(f"\n### Project Structure\n```\n{file_tree}\n```")

        content = "\n".join(parts)

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
        """현재 시각 정보 섹션. 빌드 시점의 시각을 캡처."""
        now_utc = datetime.now(timezone.utc)
        now_kst = now_utc.astimezone(KST)

        content = f"""## Current Time
- UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}
- KST: {now_kst.strftime('%Y-%m-%d %H:%M:%S %Z')}"""

        return PromptSection(
            name="datetime",
            content=content,
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
        """런타임 정보 한 줄 메타.

        OpenClaw의 "Runtime: OpenClaw v1.2.3 | claude-opus-4-6 | agent:main | telegram | 2024-12-15T09:30:00Z"
        패턴 참고.
        """
        now = datetime.now(timezone.utc)
        parts = [f"Claude Control v{version}"]

        if model:
            parts.append(model)
        if session_id:
            parts.append(f"session:{session_id[:8]}")
        if role:
            parts.append(f"role:{role}")
        parts.append(now.strftime('%Y-%m-%dT%H:%M:%SZ'))

        content = f"---\nRuntime: {' | '.join(parts)}"

        return PromptSection(
            name="runtime_line",
            content=content,
            priority=99,  # 항상 마지막
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


def build_agent_prompt(
    agent_name: str = "Claude Control Agent",
    role: str = "worker",
    agent_id: Optional[str] = None,
    working_dir: Optional[str] = None,
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    tools: Optional[List[str]] = None,
    mcp_servers: Optional[List[str]] = None,
    autonomous: bool = True,
    mode: PromptMode = PromptMode.FULL,
    context_files: Optional[Dict[str, str]] = None,
    extra_system_prompt: Optional[str] = None,
) -> str:
    """Build the agent system prompt via the modular prompt builder.

    Assembles all sections automatically and returns the final prompt string.
    When a role-specific Markdown template exists in ``prompts/``, it is used
    as the ``role_protocol`` section content (overriding the hardcoded default).

    Args:
        agent_name: Display name for the agent.
        role: Role (worker/manager/developer/researcher/self-manager).
        agent_id: Agent identifier.
        working_dir: Working directory path.
        model: Model name.
        session_id: Session identifier.
        tools: List of available tool names.
        mcp_servers: List of MCP server names.
        autonomous: Whether autonomous mode is on.
        mode: Prompt detail level.
        context_files: Bootstrap file dict ``{filename: content}``.
        extra_system_prompt: Additional system prompt appended at end.

    Returns:
        Assembled system prompt string.
    """
    from service.prompt.protocols import (
        ExecutionProtocol,
        CompletionProtocol,
        ErrorRecoveryProtocol,
    )
    from service.prompt.template_loader import PromptTemplateLoader

    builder = PromptBuilder(mode=mode)

    # Required sections
    builder.add_section(SectionLibrary.identity(agent_name, role, agent_id))
    builder.add_section(SectionLibrary.role_protocol(role))
    builder.add_section(SectionLibrary.capabilities(tools, mcp_servers))
    builder.add_section(SectionLibrary.safety())

    # Override role_protocol with Markdown template if available on disk
    loader = PromptTemplateLoader()
    md_template = loader.load_role_template(role)
    if md_template:
        builder.override_section("role_protocol", md_template)

    # Conditional sections
    if mode == PromptMode.FULL:
        builder.add_section(SectionLibrary.tool_style())
        builder.add_section(SectionLibrary.datetime_info())
        builder.add_section(SectionLibrary.context_efficiency())

        # Execution protocol (when autonomous)
        if autonomous:
            builder.add_section(ExecutionProtocol.autonomous_execution())
            builder.add_section(ErrorRecoveryProtocol.self_recovery())

        # Completion protocol (always in FULL mode)
        builder.add_section(CompletionProtocol.completion_signals())

        # Role-specific additional sections
        if role == "manager":
            builder.add_section(SectionLibrary.delegation())
        if role in ("worker", "self-manager"):
            builder.add_section(SectionLibrary.status_reporting())

    # Workspace environment
    if working_dir:
        builder.add_section(SectionLibrary.workspace(working_dir))

    # Bootstrap context files
    if context_files:
        for filename, content in context_files.items():
            builder.add_section(
                SectionLibrary.bootstrap_context(filename, content)
            )

    # Runtime metadata line
    builder.add_section(
        SectionLibrary.runtime_line(model, session_id, role)
    )

    # Extra system prompt
    if extra_system_prompt:
        builder.add_extra_context(extra_system_prompt)

    return builder.build_with_safety_wrap()
