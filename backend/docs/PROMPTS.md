# Prompt System

> Modular prompt engine that assembles role-based system prompts from sections

## Architecture Overview

```
AgentSessionManager._build_prompt_for_session()
        │
        ├── ContextLoader         ── Auto-discover project files (AGENTS.md, CLAUDE.md, …)
        ├── PromptTemplateLoader  ── Load role-specific .md files (prompts/*.md)
        ├── SectionLibrary        ── Section factory (identity, capabilities, workspace, …)
        ├── PromptBuilder         ── Builder pattern for final prompt assembly
        └── AutonomousPrompts     ── Format string templates for workflow nodes
```

---

## PromptBuilder — Builder Pattern

### PromptMode

| Mode | Description |
|------|-------------|
| `FULL` | Include all sections (default) |
| `MINIMAL` | Core sections only (for lightweight sub-agents) |
| `NONE` | No system prompt (use extra context only) |

### PromptSection

```python
@dataclass
class PromptSection:
    name: str                                    # Section identifier
    content: str                                 # Body text
    priority: int = 50                           # Sort priority (lower = earlier)
    condition: Optional[Callable[[], bool]]       # Condition function
    modes: Set[PromptMode] = {PromptMode.FULL}   # Inclusion modes
    tag: Optional[str] = None                    # XML wrapping tag
```

- `should_include(mode)` — Check mode + condition
- `render()` — If `tag` is set, wrap as `<tag>...</tag>`

### Builder Methods

All methods return `self` for **chaining**:

```python
prompt = (
    PromptBuilder(mode=PromptMode.FULL)
    .add_section(SectionLibrary.identity(...))
    .add_section(SectionLibrary.capabilities(...))
    .override_section("role_protocol", custom_content)
    .add_extra_context("Additional info...")
    .build()
)
```

| Method | Description |
|--------|-------------|
| `add_section(section)` | Add/replace section |
| `remove_section(name)` | Remove section |
| `override_section(name, content)` | Replace content only (preserve tag/priority) |
| `add_extra_context(context)` | Append extra context at end |
| `build()` | Assemble final prompt |
| `build_with_safety_wrap()` | `build()` + add anti-override instructions |

### build() Algorithm

1. If `NONE` mode → return `extra_context` only
2. Filter by `should_include(mode)`
3. Sort by `priority` ascending
4. Apply `_overrides` (content replacement)
5. `render()` each section
6. Append `_extra_context`
7. Join with `"\n\n"` separator

---

## SectionLibrary — Section Factory

All methods are `@staticmethod` and return `PromptSection`.

| Priority | Section Name | Method | Modes | Description |
|----------|-------------|--------|-------|-------------|
| 10 | `identity` | `identity(agent_name, role, agent_id, session_name)` | FULL, MINIMAL | Agent identity one-liner |
| 12 | `user_context` | `user_context()` | FULL, MINIMAL | User persona (UserConfig) |
| 13 | `geny_platform` | `geny_platform(session_id)` | FULL, MINIMAL | Geny platform built-in tool list |
| 15 | `role_protocol` | `role_protocol(role)` | FULL | Role-specific behavior guidelines (hardcoded fallback) |
| 20 | `capabilities` | `capabilities(tools, mcp_servers)` | FULL, MINIMAL | MCP servers + additional tool list |
| 25 | `tool_style` | `tool_style()` | FULL | Tool usage guidelines |
| 30 | `safety` | `safety()` | FULL, MINIMAL | Safety guidelines |
| 40 | `workspace` | `workspace(working_dir, project_name, file_tree)` | FULL, MINIMAL | Working directory info |
| 45 | `datetime` | `datetime_info()` | FULL | Current KST time |
| 50 | `context_efficiency` | `context_efficiency()` | FULL | Token efficiency guide |
| 60 | `status_reporting` | `status_reporting()` | FULL | Worker progress report format |
| 90 | `bootstrap_{file}` | `bootstrap_context(file, content, tag)` | FULL, MINIMAL | Project context files (XML wrapped) |
| 99 | `runtime_line` | `runtime_line(model, session_id, role, version)` | FULL, MINIMAL | Runtime meta one-liner |

### Role-Specific Hardcoded Fallback (role_protocol)

| Role | Content |
|------|---------|
| `worker` | Empty string (general purpose) |
| `developer` | Understand → Implement → Verify 3-phase |
| `researcher` | Information gathering → Exploration → Idea generation |
| `planner` | Idea evaluation → Architecture → Documentation |

---

## PromptTemplateLoader — Role Template Files

Loads role-specific Markdown files from the `prompts/` directory.

### Role → File Mapping

```python
_ROLE_FILE_MAP = {
    "worker":     "worker.md",
    "developer":  "developer.md",
    "researcher": "researcher.md",
    "planner":    "planner.md",
}
```

When the file exists, it **overrides** the `SectionLibrary.role_protocol()` hardcoded fallback.

### Methods

| Method | Description |
|--------|-------------|
| `load_role_template(role)` | Load .md file (cached) |
| `list_available_roles()` | List roles with existing files |
| `load_all()` | All roles → content dictionary |
| `clear_cache()` | Clear cache |

### Role Templates (prompts/*.md)

| File | Role | Content |
|------|------|---------|
| `worker.md` | worker | Code reading, rule compliance, error handling, testing |
| `developer.md` | developer | Understand→Implement→Verify 3 responsibilities, code quality guidelines |
| `researcher.md` | researcher | Information gathering→Experimentation→Ideas 3 responsibilities, output format |
| `planner.md` | planner | Evaluation→Architecture→Documentation, deliverable standards (master plan, etc.) |

### Specialized Templates (prompts/templates/*.md)

Not auto-loaded by `PromptTemplateLoader`; selected via UI "Prompt Template" dropdown and passed as `extra_system_prompt`.

| File | Title | Specialty |
|------|-------|-----------|
| `developer-ai-engineer.md` | AI/ML Engineer | PyTorch, TF, HuggingFace, LangChain, MLOps |
| `developer-backend.md` | Backend Expert | FastAPI, Django, PostgreSQL, Docker |
| `developer-frontend.md` | Frontend Expert | React, Next.js, Tailwind, accessibility |
| `developer-fullstack.md` | Fullstack Expert | E2E type safety, API-first |
| `researcher-market-analysis.md` | Market/Business Analysis | TAM/SAM/SOM, competitive analysis |
| `researcher-tech-trends.md` | Tech Trends | arXiv, GitHub trending, technology maturity |

---

## ContextLoader — Project Context File Discovery

Auto-discovers project context files in `working_dir` and injects them as Bootstrap sections.

### Discovery Files

**Default files (always searched):**

| Filename | XML Tag | Max Size |
|----------|---------|----------|
| `AGENTS.md` | `project-context` | 50,000 B |
| `CLAUDE.md` | `ai-instructions` | 50,000 B |
| `.claude` | `ai-instructions` | 50,000 B |
| `.cursorrules` | `ai-instructions` | 30,000 B |
| `.windsurfrules` | `ai-instructions` | 30,000 B |
| `SOUL.md` | `persona` | 20,000 B |

**Optional files (when `include_readme=True`):**

| Filename | XML Tag | Max Size |
|----------|---------|----------|
| `README.md` | `project-readme` | 30,000 B |
| `CONTRIBUTING.md` | `project-contributing` | 20,000 B |

### Discovery Behavior

1. Search in `working_dir` first
2. If not found, search in `working_dir.parent` (monorepo support)
3. Skip empty files and oversized files
4. Total budget: `max_total_size` (default 100,000 B)

### Constructor

```python
ContextLoader(
    working_dir: str,
    max_total_size: int = 100_000,
    include_readme: bool = False,
    custom_files: Optional[List[str]] = None,  # Additional custom files
)
```

---

## AutonomousPrompts — Workflow Node Templates

Format string templates used by each node in the workflow graph.

| Method | Placeholders | Used By | Description |
|--------|-------------|---------|-------------|
| `classify_difficulty()` | `{memory_context}`, `{input}` | classify_node | Classify as easy/medium/hard |
| `review()` | `{question}`, `{answer}` | review_node | Quality review, VERDICT: approved/rejected |
| `create_todos()` | `{memory_context}`, `{input}` | create_todos_node | Decompose hard task into TODOs |
| `execute_todo()` | `{goal}`, `{title}`, `{description}`, `{previous_results}` | execute_todo_node | Execute individual TODO |
| `final_review()` | `{input}`, `{todo_results}` | final_review_node | Review all TODO completion |
| `final_answer()` | `{input}`, `{todo_results}`, `{review_feedback}` | final_answer_node | Final comprehensive answer |
| `retry_with_feedback()` | `{previous_feedback}`, `{input_text}` | answer_node | Retry after review rejection |
| `check_relevance()` | `{agent_name}`, `{role}`, `{message}` | relevance_gate_node | Determine broadcast relevance |

Per-node custom prompts: Overridable from workflow config via `config.get("prompt_template", AutonomousPrompts.xxx())` pattern.

---

## Protocols — Extension Protocol Sections

Not included by default in `build_agent_prompt()`; for manual insertion.

### ExecutionProtocol

| Method | Priority | Mode | Content |
|--------|----------|------|---------|
| `autonomous_execution()` | 35 | FULL | CPEV cycle: Check→Plan→Execute→Verify |
| `multi_turn_execution()` | 36 | FULL | Turn budget, state continuity, progress tracking |

### CompletionProtocol

| Signal | Meaning |
|--------|---------|
| `[CONTINUE: {action}]` | Additional work needed |
| `[TASK_COMPLETE]` | All tasks complete |
| `[BLOCKED: {reason}]` | Blocked by external dependency |
| `[ERROR: {description}]` | Unrecoverable error |

### ErrorRecoveryProtocol

4-level escalation: Immediate retry → Diagnostic analysis → Strategy switch → Graceful degradation

---

## Full Assembly Flow

```
User session creation (role, model, working_dir, system_prompt, ...)
    │
    └── AgentSessionManager._build_prompt_for_session()
          │
          ├── ContextLoader.load_context_files()
          │     └── Auto-discover AGENTS.md, CLAUDE.md, etc.
          │
          └── build_agent_prompt(
                agent_name, role, working_dir, model,
                session_id, session_name, tools, mcp_servers,
                mode=FULL, context_files, extra_system_prompt,
                shared_folder_path
              )
                │
                ├── Create PromptBuilder(FULL)
                ├── §1  identity       (p=10)  — always
                ├── §1.5 user_context  (p=12)  — if UserConfig exists
                ├── §1.7 geny_platform (p=13)  — always
                ├── §2  role_protocol  (p=15)  — if role ≠ "worker"
                │     └── PromptTemplateLoader → override if prompts/{role}.md exists
                ├── §3  capabilities   (p=20)  — if tools/mcp_servers present
                ├── §6  workspace      (p=40)  — if working_dir present
                ├── §7  datetime       (p=45)  — if FULL mode
                ├── §11 bootstrap_*    (p=90)  — each context_file
                │
                ├── builder.build() → sort by priority, filter, render
                │
                ├── + "---" + extra_system_prompt (specialized template)
                └── + "---" + shared_folder_info (if shared folder active)
```

### Final Prompt Layout

```
You are a Great Agent (role: developer). Your name is "MySession".

[User persona] (if configured)

## Geny Platform Tools
- Session/Room/Messaging/Read tool list...

[Role protocol] (prompts/developer.md content)

[MCP servers + additional tool list]

Working directory: /path/to/project

Current time: 2026-03-21 15:30:00 KST

<project-context file="AGENTS.md">
  Project context...
</project-context>

---

(extra_system_prompt: specialized template content)

---

Shared Folder: ./_shared/
A shared directory accessible by ALL sessions...
```

---

## Related Files

```
service/prompt/
├── __init__.py              # Public API exports
├── builder.py               # PromptBuilder, PromptMode, PromptSection
├── sections.py              # SectionLibrary, AutonomousPrompts, build_agent_prompt()
├── protocols.py             # ExecutionProtocol, CompletionProtocol, ErrorRecoveryProtocol
├── context_loader.py        # ContextLoader (project file discovery)
└── template_loader.py       # PromptTemplateLoader (role .md loader)

prompts/
├── worker.md                # worker role template
├── developer.md             # developer role template
├── researcher.md            # researcher role template
├── planner.md               # planner role template
└── templates/
    ├── developer-ai-engineer.md
    ├── developer-backend.md
    ├── developer-frontend.md
    ├── developer-fullstack.md
    ├── researcher-market-analysis.md
    └── researcher-tech-trends.md
```
