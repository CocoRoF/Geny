# Analysis 03 — State-shape design space

**Date.** 2026-04-21
**Scope.** The "per-stage state" and "global state" interfaces the
user asked for in this cycle. This document argues the chosen
shape and enumerates rejected alternatives so the plan for PR-1
has no undocumented trade-offs.

## 1. What the user actually asked for

Two complementary capabilities:

1. **Per-stage state.** A stage can stash its own bookkeeping
   between iterations without colliding with other stages.
   *Every* stage, not just the ones that run the main LLM.
   Example uses: the s02 summarizer remembering which message
   indices have already been summarized; the s15 reflector
   remembering which insights were emitted this session to
   avoid duplicates.

2. **Global / shared state.** A first-class bucket every stage
   can read and write during one run, separate from the
   pipeline's own typed fields. Example uses: a retriever stage
   caching memory manager handles for the strategy stage to
   reuse; a summarizer publishing "this turn's context summary"
   for the API stage to append to the system prompt.

The user's words: *"개별 STAGE가 STAGE에서 사용하는 일종의
State(상태)를 담을 수 있는 그러한 인터페이스 ... 전체 STAGE가
공유하는 GLOBAL_STATE도 어딘가에서 사용할 수 있으면 좋겠어."*

Must be **ergonomic** (low boilerplate per call site),
**composable** (a stage shouldn't have to know other stages'
names to collaborate), and **non-breaking** (the 16 shipped
stages and all tests must keep working without edits).

## 2. What exists today

From analysis 01 §4 — `PipelineState` (186 lines) already has a
`metadata: Dict[str, Any]` field (L133). Stages use it for a
grab-bag of things:

- `metadata["needs_reflection"]` — written by s15 strategy when
  no `llm_reflect` callback exists (memory/strategy.py L183).
- `metadata["L0_tail"]` / `metadata["L0_enabled"]` — written by
  s02 context injection path.
- `metadata["cost_breakdown"]` — written by s06 api for
  per-turn cost attribution.

So today there is **one** shared dict, no per-stage namespace,
and no convention for who owns which key. The pattern is already
being used (correctly, for coarse cross-stage signalling) but
it is collision-prone.

Relevant existing fields in `PipelineState` that we can re-read
to calibrate design choices:

- `messages`, `system` — typed, pipeline-owned (payload).
- `model`, `max_tokens`, `temperature`, `tools`, `token_usage`,
  `total_cost_usd` — typed, pipeline-owned (runtime config +
  accounting).
- `memory_refs`, `pending_tool_calls`, `tool_results`,
  `delegate_requests`, `agent_results` — typed, pipeline-owned
  (payload handoffs between specific stage pairs).
- `metadata: Dict[str, Any]` — untyped, shared, no convention.
- `events: List[Dict[str, Any]]` — append-only, read by the
  streaming listener.

Any design must slot alongside these without reshuffling the
dataclass layout (external callers of `PipelineState(...)` would
break).

## 3. Design axes

Four orthogonal choices:

1. **Storage container.** Where does the new state live?
2. **Ownership boundary.** How do we scope "per-stage" — by
   stage name, stage order, or stage identity?
3. **Access ergonomics.** Getter-only, get-with-default, typed
   dataclass, property access?
4. **Lifetime.** Per run, per iteration, or per stage instance?

## 4. Options considered

### Option A — Reuse `metadata` with naming convention

**Shape.** Keep `metadata` as the only container. Document the
convention that per-stage state lives under `metadata[stage.name]`
and shared state lives under `metadata["shared"]`.

**Pros.**
- Zero core-dataclass changes. Nothing in `PipelineState`
  signature moves.
- Existing uses of `metadata` (which already mix "pipeline
  signals" and "ad-hoc scratch") continue to work unchanged.

**Cons.**
- The namespace `"shared"` is still just a string in a shared
  dict. Collision between a stage whose name is `"shared"` (no
  such stage today, but a plugin stage could call itself that)
  and the shared bucket.
- No type signal — readers see `state.metadata["x"]` and have
  to know whether `x` is a stage name or the global bucket.
- Static analyzers can't warn about missing slots.
- Convention-only means the convention won't be followed by
  one-off contributions; convention-only is how `metadata`
  became untyped in the first place.

**Verdict.** Reject. The whole point of this cycle is to
formalize state structure; keeping `metadata` as sole container
re-enacts the current problem.

### Option B — `shared: Dict[str, Any]` as a new first-class field

**Shape.** Add `shared: Dict[str, Any] = field(default_factory=dict)`
directly to `PipelineState`. Keep per-stage state as a helper
over `metadata.setdefault(stage.name, {})`.

**Pros.**
- Zero migration cost for `metadata` — existing uses stay put.
- `state.shared` is discoverable via `PipelineState.__dataclass_fields__`.
- Global reads/writes get their own bucket without collision
  risk (can't overlap with any stage name).
- Per-stage helper is a one-liner and still backed by
  `metadata`, so existing metadata-based per-stage writes keep
  working without rewrite.

**Cons.**
- One new top-level field (minor dataclass surface growth).
- Two storage locations (`shared` vs `metadata`) requires users
  to know which to use. Mitigated by: shared is for cross-stage
  communication; `metadata[stage.name]` (via helper) is for
  per-stage only; `metadata["..."]` without the helper is
  legacy and discouraged but unbroken.

**Verdict.** **Chosen.** Minimal surface, clear semantics, no
migration. Full design in §6.

### Option C — Typed `SharedContext` dataclass

**Shape.** Add `shared: SharedContext = field(default_factory=SharedContext)`
where `SharedContext` is a typed dataclass with known fields
(e.g. `memory_manager: Optional[Any]`, `llm_client: Optional[BaseClient]`,
`context_summary: Optional[str]`, `custom: Dict[str, Any]`).

**Pros.**
- Static typing on the fields we know about up front.
- Editor autocomplete.

**Cons.**
- Forces us to enumerate cross-stage keys at design time, which
  defeats the "stages can share without knowing each other"
  requirement.
- Every new shared field is a PR against the typed dataclass —
  downstream plugins can't use `shared` without upstreaming.
- Mixed shape (`custom: Dict` escape hatch) undoes the typing
  benefit.
- `state.llm_client: Optional[BaseClient]` (separate top-level
  field, added in PR-3 from the unified
  `geny_executor/llm_client/` package) is the right place for
  the *one* known cross-stage handle; the rest should stay a
  free-form bucket for unknown future uses.

**Verdict.** Reject. Over-structures a freeform concept; kills
extensibility; mixed shape is worse than fully freeform.

### Option D — `StageScratchpad` wrapper on every stage

**Shape.** Give every `Stage` an automatic `self.scratchpad:
Dict[str, Any]` field that lives on the stage instance, not on
state. Global state moves to pipeline (`pipeline.shared`).

**Pros.**
- Per-stage state has no naming collision possible — it's
  literally on `self`.
- Strong scope separation: state goes on state, per-stage goes
  on stage.

**Cons.**
- Stages are instantiated once per pipeline (L202 of
  pipeline.py — `self._stages: Dict[str, Stage] = {}`) and
  survive across runs of the same pipeline instance. Scratchpad
  on the instance would **leak across sessions**. We'd need
  per-session instance cloning (disruptive) or explicit reset
  hooks every run (error-prone).
- `PipelineState.metadata` *is* per-run (new state per run).
  Putting per-stage state on state keeps the per-run lifetime
  automatically.
- Global state on `pipeline.shared` faces the same
  cross-session-leak problem.

**Verdict.** Reject. Wrong lifetime — per-session data must
live on the per-session object, which is `PipelineState`.

### Option E — Context-var stack

**Shape.** Use Python `contextvars.ContextVar` to expose
`shared` and per-stage state during stage execution, pop on
exit.

**Pros.**
- No `PipelineState` change.
- Natural async behavior (context-var inherits across tasks).

**Cons.**
- Invisible in the dataclass. `state.shared` is the explicit
  interface the user asked for; hiding it behind a context-var
  is a worse match for the ask.
- Stages already receive `state` as argument — there's no
  ambient-context need.
- Testing requires setting up the context-var per test; dict
  on a dataclass is a plain assignment.

**Verdict.** Reject. Solves a problem we don't have.

## 5. Options × requirements matrix

| Option | Ergonomic | Composable | Non-breaking | Per-run lifetime | Chosen? |
|--------|-----------|-----------|--------------|------------------|---------|
| A — metadata-only | medium | medium | yes | yes (via state) | no |
| B — `shared` dict + helper | high | high | yes | yes (via state) | **yes** |
| C — typed SharedContext | low | low | yes | yes (via state) | no |
| D — scratchpad on Stage | high | high | yes | **no** (instance) | no |
| E — contextvars | low | medium | yes | yes | no |

## 6. Chosen design — details

### 6.1 Global state

Add one field to `PipelineState` (`core/state.py`):

```python
# ── Shared (cross-stage) ──
shared: Dict[str, Any] = field(default_factory=dict)
```

Placed next to `metadata` in the dataclass (conceptually
adjacent, same storage shape). Zero existing callers break —
constructing `PipelineState()` with no args still works
(`default_factory=dict`).

**Semantic contract.**
- `shared` is intended for cross-stage communication within
  one run.
- Keys are free-form strings. No key prefix is reserved; readers
  and writers cooperate by convention.
- Anything in `shared` is reset to `{}` at the start of every
  new run (this is automatic: callers either pass a fresh
  `PipelineState()` or `run()` creates one).
- `shared` is a plain dict, not a typed object. Stages may
  store any value: primitives, dataclasses, handles, callables.
- `shared` is not an event channel. Writes don't notify
  listeners. Stages that need event semantics should
  `state.add_event(...)` instead.

**Concurrency.** Stages run sequentially within a loop turn
(pipeline.py orchestration), so `shared` access is single-writer
within a turn. Documented in the plan and the dataclass
docstring. If a future cycle introduces parallel sub-stages,
this becomes a real concern — called out in risks but not
solved here.

### 6.2 Per-stage state

Add a helper **on `Stage`** (`core/stage.py`), not a new state
field:

```python
def local_state(self, state: PipelineState) -> Dict[str, Any]:
    """Return this stage's private scratchpad, creating it on first access.

    The scratchpad lives under ``state.metadata[self.name]`` — using
    ``metadata`` (not ``shared``) avoids polluting the cross-stage
    namespace with per-stage internals. Keys inside the dict are
    owned entirely by the stage; other stages should not reach in.
    """
    return state.metadata.setdefault(self.name, {})
```

**Why `state.metadata` and not `state.shared`?** Because
`shared` is semantically for *cross-stage* communication;
per-stage internals are by definition not that. Keeping them
separate makes the intent visible at the call site: a read of
`state.shared["context_summary"]` says "I'm consuming something
another stage published," whereas `self.local_state(state)` says
"I'm using my own bookkeeping."

**Why stage name as the key?** Because `stage.name` is stable,
unique within a pipeline, matches what the log panel and
mutation API use (cycle 20260421_3 pinned this vocabulary), and
survives artifact swaps (the artifact name changes, the stage
name doesn't).

**What if two stages share a name?** They can't — pipeline.py
uses `_stages: Dict[str, Stage]` keyed by name, so a collision
raises at registration. No runtime check needed.

### 6.3 Interaction with existing `metadata`

`metadata` stays. It retains its current semantics for
"miscellaneous per-run signals" (`"needs_reflection"`,
`"L0_tail"`, `"cost_breakdown"`, etc.). New contributors should
prefer `shared` for named cross-stage data and `local_state` for
per-stage data — but nothing *requires* the migration, because
the existing metadata keys don't collide with any stage name
(`"needs_reflection"` is a signal name, not a stage name).

If a future cycle wants to strip `metadata` down to only
pipeline-owned signals, that's a separate refactor. Out of
scope here.

### 6.4 Lifetime summary

| Bucket | Lives on | Reset when | Visible to |
|--------|---------|-----------|-----------|
| `state.shared` | per-run `PipelineState` | each `run()` creates fresh state | all stages in the run |
| `state.metadata[stage.name]` (via `local_state`) | per-run `PipelineState` | same | the owning stage only (by convention) |
| `state.metadata[<other keys>]` | per-run `PipelineState` | same | free-form (legacy pattern) |

All three reset together automatically — nothing leaks across
runs because they all live on the per-run state object.

## 7. Rejected micro-decisions (worth recording)

Some ideas were suggested during design review and rejected.
Recorded here so they don't come back without understanding why:

- **"Make `local_state` typed via `TypeVar[T]`."** Rejected —
  the escape hatch of `Dict[str, Any]` is the point; typed
  scratchpads push schema management into every stage for no
  cross-stage benefit.
- **"Put `llm_client` inside `shared` instead of as a separate
  field."** Rejected — `shared` is optional/free-form;
  `llm_client` is a typed handle with a concrete abstract
  (`BaseClient` from the new `geny_executor/llm_client/`
  package). PR-3 gives it a dedicated typed slot
  (`state.llm_client: Optional[BaseClient]`, defaulting to
  `None` because not every pipeline runs an LLM — the slot
  exists for extensibility, not as a requirement).
- **"Move `memory_refs` / `pending_tool_calls` / etc. into
  `shared`."** Rejected — those are typed pipeline-owned
  payload fields between specific stage pairs (s02→s03,
  s09→s10). They have their own readers and writers; moving
  them into a free-form dict loses type signal for no gain.
- **"Add `stage_state: Dict[str, Dict[str, Any]]` as a separate
  top-level field instead of using metadata."** Rejected — it
  duplicates what `metadata.setdefault(stage.name, {})` already
  gives you, adds a second untyped dict, and would need
  migration for existing metadata-based per-stage writes.

## 8. Testability

The chosen design passes the minimal-test checklist:

- `PipelineState().shared == {}` — trivial assertion.
- `stage.local_state(state)["foo"] = 1; stage.local_state(state)` —
  returns `{"foo": 1}`; idempotent.
- `stage_a.local_state(state)` and `stage_b.local_state(state)` —
  return disjoint dicts; mutation of one doesn't affect the
  other.
- Two runs of the same pipeline produce fresh `shared` each run
  when `PipelineState()` is constructed per run (the
  default — `pipeline.run()` constructs one if none supplied).

Plan/01 lists the concrete tests.

## 9. Out of scope

- **Persisting `shared` across runs.** If a pipeline wants to
  carry state between sessions, it uses the memory layer, not
  `shared`. The lifetime contract is per-run.
- **Typed schema for specific `shared` keys.** None of the
  expected consumers (PR-5 summarizer, PR-5 reflector, PR-3
  llm_client stash) need schema enforcement. Future cycles
  that pin a specific key's shape can do so at the reader,
  not at the container.
- **Concurrent writes to `shared` from parallel sub-stages.**
  Documented as a future risk; no sub-stage parallelism exists
  today, so no synchronization primitive is worth adding
  preemptively.
