# Progress 11 — VTuber auto-pair block reshape

| Field | Value |
|-------|-------|
| Plan ref | `plan/03_vtuber_worker_binding.md` → **PR B** |
| Master ref | `plan/00_overview.md` → **Phase 3 / PR 20** |
| Geny PR | [#162](https://github.com/CocoRoF/Geny/pull/162) |
| Geny merge commit | `db64c00` on `main` |
| Status | **Merged** |

---

## Why this is Phase 3's load-bearing PR

PR 18 renamed the schema; PR 20 changes the behavior. The VTuber
auto-pair block (the recursive `create_agent_session` call that
spawns the bound Worker) was the last site still driving the
Worker down a pre-manifest path via hardcoded `workflow_id` /
`graph_name` / `tool_preset_id`. That worked as a leftover from
the 20260420_2 cycle but lost its semantic coherence after Phase 2
made every other session go through `resolve_env_id → manifest`.

With this PR merged, the statement "every session in Geny flows
through `resolve_env_id`" is finally true without qualification.

## What changed

### Auto-pair block (`agent_session_manager.py`)

**Before** (post-PR 18):

```python
worker_request = CreateSessionRequest(
    session_name=worker_name,
    working_dir=shared_dir,
    model=request.bound_worker_model or None,
    ...
    role=SessionRole.WORKER,
    system_prompt=request.bound_worker_system_prompt,
    workflow_id="template-optimized-autonomous",
    graph_name="Optimized Autonomous",
    tool_preset_id=None,
    linked_session_id=session_id,
    session_type="bound",
    env_vars=request.env_vars,
)
```

**After**:

```python
worker_request = CreateSessionRequest(
    session_name=worker_name,
    working_dir=shared_dir,
    model=request.bound_worker_model or None,
    ...
    role=SessionRole.WORKER,
    system_prompt=request.bound_worker_system_prompt,
    env_id=request.bound_worker_env_id,
    linked_session_id=session_id,
    session_type="bound",
    env_vars=request.env_vars,
)
```

- **`env_id=request.bound_worker_env_id`** — when the VTuber's
  creation request specifies `bound_worker_env_id`, the bound
  Worker uses that env. Otherwise `resolve_env_id(WORKER, None)`
  picks the default `template-worker-env`. The resolver was the
  load-bearing abstraction from PR 15 — this PR just lets the
  VTuber auto-pair participate.
- **`workflow_id` / `graph_name` / `tool_preset_id` gone.** The
  Pydantic defaults (None) take over. Under plan/02, envs own
  stage layout and `manifest.tools.built_in` / `.external`
  carry tool selection. A per-session override is still possible
  through the top-level `CreateSessionRequest` fields, but the
  auto-pair path doesn't need it — the bound Worker should run
  vanilla `template-worker-env` unless the caller says otherwise.

### Explicit recursion guard

**Before**:

```python
if (
    request.role == SessionRole.VTUBER
    and not request.linked_session_id  # Avoid recursion
):
```

**After**:

```python
if (
    request.role == SessionRole.VTUBER
    and request.session_type != "bound"
    and not request.linked_session_id
):
```

The old guard worked because the recursive spawn carries
`linked_session_id`. It piggybacked on an adjacent invariant. The
new guard states the actual rule — *don't spawn a bound Worker
from a request that is already a bound Worker* — in the form
`request.session_type != "bound"`. The `linked_session_id` check
stays as a belt-and-braces second predicate because it catches
*any* request that already has a linked session (including
hypothetical future non-bound link types).

### Prompt injection rewrite

Two injection sites — the post-spawn direct injection on
`agent._system_prompt` (auto-pair block) and the
`_build_system_prompt` restoration branch (`role == "vtuber" and
request.linked_session_id`) — now emit the same block:

```text
## Bound Worker Agent

You have a Worker agent bound to you: session_id=`<W1>`.
For complex tasks (coding, research, multi-step execution),
delegate to the Worker via the `geny_send_direct_message` tool
with target_session_id=`<W1>`. The Worker's reply will arrive in
your inbox; read it with `geny_read_inbox` and summarize for
the user.
```

Wording choices:

- **`target_session_id` is named explicitly**, because
  `geny_send_direct_message` takes several params and the VTuber
  will get this argument wrong often without the cue.
- **`geny_read_inbox` is named**. In practice Geny's agent loop
  auto-drains the inbox between turns, but the VTuber still
  benefits from the mental model "reply arrives in inbox → I
  read it → I summarize." Naming both tools pushes the model
  toward a clearer mental model of the async hand-off.
- **"Summarize for the user"** is spelled out because VTubers
  otherwise tend to forward the Worker's verbose output
  verbatim, breaking the persona layer.

The exact text will be reviewed again in plan PR 22 when
`prompts/vtuber.md` gets rewritten — it's likely the injected
block and the persona base prompt will share wording, or the
injected block will be pruned to avoid duplication once the
persona file carries a stronger delegation section.

### Local variable renames

`cli_name` → `worker_name`, `cli_request` → `worker_request`,
`cli_agent` → `worker_agent`, `cli_id` → `worker_session_id`.
Aligned with PR 18's schema rename. No behavioral impact;
improves readability.

### Log messages

- `"🔗 Paired CLI session created: <id> (<name>)"` → `"🔗 Bound
  Worker created: <id> (<name>)"`
- `"Failed to create paired CLI session"` → `"Failed to create
  bound Worker"`

Operators grepping logs for session lifecycle events need the
wording to match the user-facing model.

## Smoke test

Written as `/tmp/test_pr20_reshape.py` (not checked in). 6 groups,
all passing:

| Group | Checks |
|:-----:|:-------|
| A | Hardcoded `workflow_id` / `graph_name` / `tool_preset_id=None` removed from the auto-pair block; `env_id=request.bound_worker_env_id` added |
| B | Explicit `session_type != "bound"` recursion guard present |
| C | `## Bound Worker Agent` header appears ≥ 2 times; "Paired CLI Agent" / "when the CLI agent finishes" legacy wording gone |
| D | VTuber delegation prompt references `geny_read_inbox` |
| E | Log messages updated: "Failed to create bound Worker" / "Bound Worker created" |
| F | Local vars renamed: no `cli_request` remains; `worker_request = CreateSessionRequest(` present |

A full end-to-end integration test on `create_agent_session` would
require standing up global MCP config, the shared-folder manager,
the memory registry, and `IdleMonitor` — essentially reproducing
`main.py` — so it's deferred to manual verification (next section).

## Manual verification

- [ ] Create a VTuber session through the UI. Confirm:
  - bound Worker is spawned with `env_id == "template-worker-env"`
    in the session store
  - VTuber's live system prompt contains the `## Bound Worker
    Agent` block with the correct `session_id=` / `target_session_id=`
  - the logger emits `🔗 Bound Worker created: <id>`
- [ ] Create a VTuber session with an explicit
      `bound_worker_env_id="template-developer-env"` (or some
      other seeded env). Confirm the bound Worker uses that env,
      not `template-worker-env`.
- [ ] Call `geny_send_direct_message` from the VTuber targeting
      the bound Worker's `session_id`. Confirm the Worker
      processes and its reply lands in the VTuber's inbox.
- [ ] Sanity: a plain Worker / Developer / Researcher / Planner
      session (no role=VTUBER) still creates normally, without
      any auto-pair attempt or log line.

## Phase 3 status

| # | Title | PR | Status |
|---|-------|----|--------|
| 18 | Geny: rename `cli_*` → `bound_worker_*` | #160 | Done |
| 19 | Progress doc for PR 18 | #161 | Done |
| 20 | Geny: reshape VTuber auto-pair block | #162 | **Done** |
| 21 | Progress doc for PR 20 | *this doc* | Done |
| 22 | Geny: rewrite `prompts/vtuber.md` delegation paragraph | — | Next |
| 23 | Progress doc for PR 22 | — | Pending |
| 24 | Geny: document BoundWorker contract | — | Pending |
| 25 | Progress doc for PR 24 | — | Pending |

## Next

Master-plan PR 22 — rewrite `backend/prompts/vtuber.md`. The
VTuber persona base prompt still refers to "CLI" in at least one
paragraph. With the auto-injected `## Bound Worker Agent` block
now wording things clearly, `vtuber.md` should be aligned so the
VTuber reads a coherent instruction set when the injected block
is appended. Scope: text-only edits in one markdown file.
