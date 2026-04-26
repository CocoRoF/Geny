# 04 — Workspace abstraction (executor 1.3.0)

**Phase:** 5 (executor minor bump — independent of Geny work)
**PRs:** 3
**Risk:** medium — design exercise; first executor minor since 1.2.

---

## Why deferred from cycles A+B

Cycles A+B shipped Worktree tools (PR-A.3.4) + LSP tool (PR-A.3.5)
+ sandbox (already in 1.0). They work but don't compose — a sub-
agent spawned via AgentTool inherits the parent's sandbox cwd
even when the parent just `EnterWorktree`'d into a fresh branch.
The user has to manually thread the worktree path through.

Cycle C audit didn't surface this as a regression (existing tools
work standalone) but it's the next sensible composition layer.

---

## Design

A `Workspace` is a value object that bundles three currently-
independent concepts:

```
geny_executor.workspace.Workspace
├── cwd: Path                      (sandbox-rooted)
├── git_branch: Optional[str]      (worktree-aware)
├── lsp_session: Optional[LSPSession]
├── env_vars: Dict[str, str]       (workspace-scoped overrides)
└── metadata: Dict[str, Any]
```

`ToolContext.workspace` becomes the canonical accessor (replaces
direct reads of `working_dir` for any tool that wants to be
workspace-aware). Old tools keep working — `workspace` defaults to
a Workspace whose cwd == working_dir.

When `EnterWorktreeTool` runs, it pushes a new Workspace onto the
stack instead of mutating extras. AgentTool spawning a sub-agent
gives the sub a fresh ToolContext seeded with the parent's current
Workspace (so the sub starts in the same git branch by default).

---

## PR-D.4.1 — feat(workspace): Workspace value object + stack

### Files

- `src/geny_executor/workspace/__init__.py` (new)
- `src/geny_executor/workspace/types.py` (new — Workspace dataclass)
- `src/geny_executor/workspace/stack.py` (new — push/pop/current)
- `tests/unit/test_workspace_stack.py` (new)

### Workspace shape

```python
@dataclass(frozen=True)
class Workspace:
    cwd: Path
    git_branch: Optional[str] = None
    lsp_session_id: Optional[str] = None
    env_vars: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_cwd(self, new_cwd: Path) -> "Workspace": ...
    def with_branch(self, branch: str) -> "Workspace": ...
```

### Stack

`WorkspaceStack` is a per-session structure. Pushed Workspaces
compose (a sub-agent inheriting parent's stack sees the full
chain). Pop returns the popped Workspace so cleanup hooks can
fire (worktree removal, LSP session close).

### Tests

- push then current returns latest
- pop reverses
- empty pop raises
- `with_*` returns new Workspace (immutable)

---

## PR-D.4.2 — feat(tools): Worktree + LSP tools use Workspace

### Files

- `src/geny_executor/tools/built_in/worktree_tools.py` (modify)
- `src/geny_executor/tools/built_in/dev_tools.py` (modify — LSPTool)
- `src/geny_executor/tools/base.py` (modify — ToolContext gains
  `.workspace` property)

### Change

EnterWorktreeTool builds a Workspace with the new branch's path
and pushes it onto `ctx.workspace_stack`. ExitWorktreeTool pops.

LSPTool now reads `ctx.workspace.cwd` instead of `ctx.working_dir`
when present.

`ToolContext.workspace` defaults to a Workspace seeded from
`working_dir`, `env_vars`, etc. — so old tools that don't know
about Workspace still work.

### Tests

- EnterWorktree pushes Workspace with the right cwd + branch
- ExitWorktree pops + returns it
- LSPTool reads workspace.cwd when set
- old tools (Bash, Read) still get the right cwd via the default
  Workspace

---

## PR-D.4.3 — feat(stages): SubagentTypeOrchestrator threads workspace

### Files

- `src/geny_executor/stages/s12_agent/subagent_type.py` (modify)
- `tests/unit/test_subagent_workspace_propagation.py` (new)

### Change

When AgentTool spawns a sub-pipeline, the sub's initial
ToolContext is seeded with a copy of the parent's current
Workspace. The sub can call `EnterWorktree` to add its own; on
exit, the parent's Workspace is what's left.

### Tests

- spawn → sub sees parent's workspace.cwd
- sub Enter → sub's workspace differs
- sub Exit → sub's stack returns to parent's
- sub crash → no parent workspace mutation

---

## Combined acceptance criteria

- [ ] Workspace + stack land
- [ ] Worktree + LSP tools workspace-aware
- [ ] SubagentTypeOrchestrator threads workspace
- [ ] cross-import audit (cycle C style) extended to cover Workspace
- [ ] full executor suite green
- [ ] CHANGELOG entry for 1.3.0

### Geny adoption follow-on (not in this folder)

After 1.3.0 lands:

- bump pyproject pin to `>=1.3.0,<1.4.0`
- code-coder subagent type (researcher / worker / vtuber-narrator
  + a new "code-coder" with Workspace per spawn)
- frontend Workspace badge in TasksTab when a task is associated
  with a non-default workspace

These are 2-3 small Geny PRs and belong in a separate plan file once
1.3.0 is out.
