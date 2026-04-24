# Geny Prompt System

Modular system prompt architecture for Geny Agent sessions.

---

## Design Principles

### Principle 1: MCP Provides Tool Knowledge — Prompts Do Not

Claude CLI receives full tool schemas (name, description, parameters) via MCP protocol.
**Listing tool names in the system prompt is redundant and wastes tokens.**

- Do NOT add tool names or tool descriptions to prompts
- Do NOT list MCP server names in prompts
- Only mention tools when giving **behavioral guidance** (e.g., "delegate via `send_direct_message_internal`")

### Principle 2: Single Source of Truth Per Layer

Each prompt layer has a distinct responsibility. Never duplicate content across layers.

```
Layer 1: identity()              ← WHO the agent is (1 line, role-specific)
Layer 2: geny_platform()         ← Platform awareness (categories only, no tool names)
Layer 3: prompts/{role}.md       ← Role behavior rules (what to do, how to behave)
Layer 4: templates/{persona}.md  ← Persona/tone (speaking style, emotional defaults)
Layer 5: characters/{model}.md   ← Live2D model-specific character traits (VTuber only)
```

Each layer **adds** to the previous — never repeats it.

### Principle 3: Token Budget Awareness

System prompt length directly reduces available conversation context.

| Role | Target | Rationale |
|------|--------|-----------|
| VTuber | < 1,500 tokens | Conversational — needs maximum dialog context |
| Sub-Worker | < 800 tokens | Task executor — minimal framing needed |
| Developer | < 1,200 tokens | bootstrap context files may be large |
| Researcher / Planner | < 1,200 tokens | same |

### Principle 4: Infrastructure Handles Infrastructure

| Concern | Handled By | NOT By Prompts |
|---------|-----------|----------------|
| Tool schemas & descriptions | MCP protocol | ~~capabilities section~~ |
| Safety guidelines | Claude CLI built-in | ~~safety section~~ |
| Tool usage patterns | Claude CLI built-in | ~~tool_style section~~ |
| Execution loops & retry | LangGraph | ~~execution_protocol~~ |
| Context window management | Claude CLI built-in | ~~context_efficiency section~~ |

---

## Architecture

### Prompt Assembly Flow

```
AgentSessionManager._build_system_prompt()
  └─ build_agent_prompt()
       └─ PromptBuilder (priority-sorted, mode-filtered)
            ├── §1   identity()           [P10] Role-specific identity line
            ├── §1.5 user_context()       [P12] Who the user is (from UserConfig)
            ├── §1.7 geny_platform()      [P13] Platform awareness (no tool names)
            ├── §2   role_protocol()      [P15] Role behavior (from prompts/{role}.md)
            ├── §3   workspace()          [P40] Working directory path
            ├── §4   datetime_info()      [P45] Current time (KST)
            └── §5   bootstrap_context()  [P90] AGENTS.md, CLAUDE.md, SOUL.md etc.
       + extra_system_prompt (persona template from dropdown)
       + shared_folder_path (if enabled)
  + memory_context (from SessionMemoryManager)
  + VTuber ↔ CLI session linking
  + Character injection (VTuber only, from vtuber_characters/)
```

### File Structure

```
backend/prompts/
├── README.md               ← This file (English)
├── README_KO.md            ← Korean version
├── worker.md               ← Worker role behavior
├── developer.md            ← Developer role behavior
├── researcher.md           ← Researcher role behavior
├── planner.md              ← Planner role behavior
├── vtuber.md               ← VTuber role behavior
├── templates/              ← Persona/specialization templates
│   ├── geny-default.md         (general-purpose)
│   ├── vtuber-default.md       (VTuber: warm/friendly tone)
│   ├── vtuber-cheerful.md      (VTuber: energetic/bright tone)
│   ├── vtuber-professional.md  (VTuber: calm/professional tone)
│   ├── sub-worker-default.md   (Sub-Worker: standard worker)
│   ├── sub-worker-detailed.md  (Sub-Worker: thorough reporting)
│   ├── developer-*.md          (Developer specializations)
│   └── researcher-*.md         (Researcher specializations)
└── vtuber_characters/      ← Live2D model-specific character files
    ├── README.md
    └── default.md
```

### Key Code Files

| File | Purpose |
|------|---------|
| `service/prompt/sections.py` | `SectionLibrary` (section factories) + `build_agent_prompt()` |
| `service/prompt/builder.py` | `PromptBuilder` engine + `PromptSection` / `PromptMode` |
| `service/prompt/template_loader.py` | Loads `prompts/{role}.md` files |
| `service/prompt/context_loader.py` | Loads bootstrap files (AGENTS.md, CLAUDE.md, etc.) |
| `service/executor/agent_session_manager.py` | Orchestrates prompt building + session linking |
| `controller/vtuber_controller.py` | Character prompt injection for Live2D models |

---

## Role Templates (`prompts/{role}.md`)

Each role has a dedicated Markdown file that defines **behavioral rules only**.

| File | Role | Content |
|------|------|---------|
| `worker.md` | worker | Minimal — general-purpose task execution |
| `developer.md` | developer | Code quality, conventions, verification |
| `researcher.md` | researcher | Research methodology, source diversity, idea synthesis |
| `planner.md` | planner | Critical evaluation, detailed specs, implementation guides |
| `vtuber.md` | vtuber | Conversational behavior, emotion tags, task delegation, triggers |

**Rules:**
- Focus on **what to do** and **how to behave**, not what tools exist
- Reference specific tools only for **behavioral guidance** (e.g., `send_direct_message_internal`)
- Keep under 500 words

---

## Persona Templates (`prompts/templates/`)

Optional specializations selected via the UI "Prompt Template" dropdown.
Appended after the base prompt with a `---` separator.

**For VTuber personas:**
- Only define **tone** (speaking style, formality) and **emotion defaults**
- Do NOT repeat behavior rules from `vtuber.md`

**For CLI personas:**
- Only define **reporting style** and **work approach**
- Do NOT repeat generic coding guidelines

**For other roles:**
- Domain specialization (e.g., `developer-backend.md` for backend focus)

---

## VTuber Character Files (`prompts/vtuber_characters/`)

Live2D model-specific character traits. Injected at runtime when a model is assigned.

- Filename must match the model name in `model_registry.json`
- Falls back to `default.md` if no model-specific file exists
- Uses `## Character Personality` marker to prevent duplicate injection
- Should only contain **character-specific** traits (personality, speech quirks)
- Do NOT repeat persona or role behavior content

---

## VTuber ↔ Sub-Worker Session Linking

When a VTuber session is created, a Sub-Worker session is
auto-created (see `dev_docs/20260420_3/plan/03_vtuber_worker_binding.md`).

**VTuber receives:**
```
## Sub-Worker Agent
You have a Worker agent bound to you. For complex tasks
(coding, research, multi-step execution), delegate to the Worker
via the `send_direct_message_internal` tool — pass only the
`content` argument; no target id. The Worker's reply arrives as
a `[SUB_WORKER_RESULT]` trigger; summarize for the user.
```

**Sub-Worker receives:**
```
## Paired VTuber Agent
You are the Worker bound to this VTuber persona.
Report results via `send_direct_message_internal` — no target id;
the runtime routes to your paired VTuber automatically.
```

---

## Unused Sections (Archived)

The following `SectionLibrary` methods exist but are **NOT called** by `build_agent_prompt()`:

| Section | Reason |
|---------|--------|
| `tool_style()` | Claude CLI handles tool usage natively |
| `safety()` | Claude CLI provides built-in safety |
| `context_efficiency()` | Response style handled by Claude CLI |
| `status_reporting()` | Can be defined per-role in .md files if needed |

These are retained for potential future use (e.g., stricter project-specific policies).

---

## Adding a New Role

1. Create `prompts/{role}.md` with behavioral rules
2. Add entry to `_ROLE_FILE_MAP` in `service/prompt/template_loader.py`
3. Add identity line to `SectionLibrary._ROLE_IDENTITY` in `service/prompt/sections.py`
4. Optionally create persona templates in `prompts/templates/{role}-*.md`

## Adding a New VTuber Character

1. Create `prompts/vtuber_characters/{model_name}.md`
2. Start with `## Character Personality` header
3. Define only model-specific traits (personality, speech quirks)
4. The model name must match the `name` field in `model_registry.json`

## Guidelines

- **Be concise** — every token in the system prompt reduces the context window for actual work
- **Don't repeat Claude CLI's defaults** — no tool usage guides, no safety rules
- **Don't repeat LangGraph's job** — no execution loop instructions (except self-manager)
- **Focus on behavior** — what makes this role different from default Claude?
