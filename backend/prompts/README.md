# Role Prompt Templates

Role-specific behavior templates for Geny Agent sessions.

## Design Philosophy

These templates are appended to Claude CLI's **existing** system prompt via `--append-system-prompt`.
Claude CLI already provides tool knowledge, safety guidelines, and error handling — so templates
should only specify **role identity** and **behavioral directives**. Keep them concise.

LangGraph controls the execution loop, retry logic, and completion detection.
The `AutonomousPrompts` class (in `service/prompt/sections.py`) provides per-node prompts
for the difficulty-based graph. Only `self-manager.md` includes execution signals
(`[CONTINUE]`, `[TASK_COMPLETE]`) because the graph's iteration gate reads them.

## Files

| File | Role | Chars | Purpose |
|------|------|-------|---------|
| `worker.md` | worker | ~150 | Task completion, autonomous work |
| `developer.md` | developer | ~300 | Code quality, conventions, incremental changes |
| `researcher.md` | researcher | ~250 | Research methodology |
| `self-manager.md` | self-manager | ~800 | Full autonomy + execution signals |

## How It Works

1. `build_agent_prompt()` in `service/prompt/sections.py` assembles the system prompt
2. `PromptTemplateLoader` checks this directory for a matching `{role}.md` file
3. If found, it overrides the hardcoded fallback in `SectionLibrary.role_protocol()`
4. The final prompt = Identity (1 line) + Role Template + Context (workspace, datetime, MCP)

## Guidelines

- **Be concise** — every token in the system prompt reduces the context window for actual work
- **Don't repeat Claude CLI's defaults** — no tool usage guides, no safety rules
- **Don't repeat LangGraph's job** — no execution loop instructions (except self-manager)
- **Focus on behavior** — what makes this role different from default Claude?
