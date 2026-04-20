# Plan 01 — Immediate fixes (Bug A + Bug B)

Unblocks the VTuber flow. Three PRs, split across Geny and the
executor. The executor side requires a **v0.23.0 release** because
the event vocabulary needed to render tool-call details does not
exist in v0.22.1 (verified by reading
`geny-executor/src/geny_executor/stages/s10_tool/artifact/default/stage.py`
— only `tool.execute_start` / `tool.execute_complete` are emitted,
neither carrying per-call input).

Everything here is additive on the executor side: existing consumers
that still listen only to `tool.execute_*` keep working unchanged.

---

## Executor vocabulary audit — result

Full inventory of tool-related events emitted by executor 0.22.1:

| Event | Emitted at | Payload |
|-------|-----------|---------|
| `tool.execute_start` | `s10_tool/.../stage.py:100` | `{count: int, tools: list[str]}` — summary only |
| `tool.execute_complete` | `s10_tool/.../stage.py:130` | `{count: int, errors: int}` — summary only |

**Neither event carries per-call `input` or per-call `output`.** The
executor's router (`s10_tool/.../routers.py`) dispatches directly to
`tool.execute(input, context)` with no event bracket. Any
"detail-per-call" view on the host side must be either:

- reconstructed from `pending_tool_calls` state snapshots (brittle —
  the state is a pipeline-internal field, not an event contract), or
- re-derived from the Anthropic response parsing in `s09_parse` (the
  input dicts live there momentarily before being handed to s10).

Neither is stable. **The executor must emit per-call events.** This
is Plan/01 PR II.

---

## PR I — Signature-introspected `session_id` injection (Geny only)

**Fixes**: Bug A from `analysis/01_vtuber_tool_failure.md`.

**Surface**: `backend/service/langgraph/tool_bridge.py` + one test
file. No executor involvement, no version bump.

### Change

In `_GenyToolAdapter.__init__`, probe the wrapped tool's signature
once. Use the cached answer to decide whether `session_id` should be
injected on each call.

```python
# tool_bridge.py (proposed)

class _GenyToolAdapter:
    def __init__(self, geny_tool: Any):
        self._tool = geny_tool
        self._name = getattr(geny_tool, "name", "unknown_tool")
        self._description = getattr(geny_tool, "description", "")
        self._parameters = getattr(geny_tool, "parameters", None) or {
            "type": "object",
            "properties": {},
        }
        self._accepts_session_id = self._probe_session_id_support(geny_tool)

    @staticmethod
    def _probe_session_id_support(tool: Any) -> bool:
        """True iff run/arun can accept a `session_id` kwarg."""
        fn = getattr(tool, "arun", None) or getattr(tool, "run", None)
        if fn is None:
            return False
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            return False
        for p in sig.parameters.values():
            if p.name == "session_id":
                return True
            if p.kind is inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    async def execute(self, input, context=None):
        from geny_executor.tools.base import ToolResult

        if (
            self._accepts_session_id
            and context
            and getattr(context, "session_id", None)
        ):
            input.setdefault("session_id", context.session_id)
        # … rest unchanged
```

### Tests (`backend/tests/service/langgraph/test_tool_bridge_session_id.py`)

- Tool with `session_id` kwarg → injected.
- Tool with `**kwargs` → injected.
- Tool without either (`news_search` shape) → **not** injected,
  call succeeds.
- ToolContext has no session_id → nothing injected (regression
  guard).
- Input already contains `session_id` → value preserved
  (`setdefault` semantics unchanged).

### Why this is safe to ship first

It is the only fix that makes `news_search` / `web_search` /
`web_fetch` actually run. PR II and III fix *display* only — the
tool calls themselves keep failing until PR I lands. Shipping PR I
immediately unblocks the user for real usage while the executor
change goes through review.

---

## PR II — Executor v0.23.0: per-call tool events (additive)

**Fixes**: the executor half of Bug B from
`analysis/01_vtuber_tool_failure.md`.

**Surface**: `geny-executor`:
- `src/geny_executor/stages/s10_tool/artifact/default/stage.py`
- `src/geny_executor/stages/s10_tool/artifact/default/executors.py`
- new tests for the new events
- `CHANGELOG.md`, `pyproject.toml`, `__init__.py.__version__`

**No breaking changes.** Existing `tool.execute_start` /
`tool.execute_complete` emissions are preserved byte-for-byte;
additional per-call events are inserted **between** them. Consumers
that ignore the new event types observe no change.

### Event additions

Two events per tool call, bracketing the `router.route(...)` dispatch:

```python
# proposed payloads

PipelineEvent(
    type="tool.call_start",
    data={
        "tool_use_id": tc["tool_use_id"],   # Anthropic's call id
        "name": tc["tool_name"],
        "input": tc.get("tool_input", {}),  # full input dict
    },
)

PipelineEvent(
    type="tool.call_complete",
    data={
        "tool_use_id": tc["tool_use_id"],
        "name": tc["tool_name"],
        "is_error": bool(result.is_error),
        "duration_ms": int((t1 - t0) * 1000),
        # NOTE: no full `output` — tool results can be huge. Host-side
        # log consumers read `content` from the tool_result message
        # that s10 appends to state. The event is a *signal*, not a
        # transport.
    },
)
```

Rationale for the split:

- **`tool.call_start`** carries input. Host loggers render a
  per-call detail the moment dispatch begins — even if the tool
  hangs, the UI has the right detail.
- **`tool.call_complete`** carries outcome + timing. Host loggers
  render error state and latency without needing to match against
  a later message.
- Pairing is done via `tool_use_id` (Anthropic-provided, stable per
  call). Host code doesn't need to track ordering.

### Where to emit

Both `SequentialExecutor.execute_all` and
`ParallelExecutor.execute_all` live in
`stages/s10_tool/artifact/default/executors.py`. Today they call
`router.route(...)` with no event brackets. The events must be
emitted from the same scope that has access to `state`.

The cleanest option: pass a `state.add_event`-shaped callback down
to the executors. Implementation sketch:

```python
# stage.py (only the changed branch)

async def execute(self, input, state):
    ...
    results = await self._executor.execute_all(
        tool_calls,
        router,
        ctx,
        on_event=state.add_event,  # new kwarg
    )
    ...

# executors.py (Sequential branch, Parallel is analogous)

async def execute_all(
    self,
    tool_calls: List[Dict[str, Any]],
    router: ToolRouter,
    context: ToolContext,
    *,
    on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    results = []
    for tc in tool_calls:
        t0 = time.monotonic()
        if on_event:
            on_event("tool.call_start", {
                "tool_use_id": tc["tool_use_id"],
                "name": tc["tool_name"],
                "input": tc.get("tool_input", {}),
            })
        result = await router.route(
            tc["tool_name"], tc.get("tool_input", {}), context
        )
        t1 = time.monotonic()
        if on_event:
            on_event("tool.call_complete", {
                "tool_use_id": tc["tool_use_id"],
                "name": tc["tool_name"],
                "is_error": bool(result.is_error),
                "duration_ms": int((t1 - t0) * 1000),
            })
        results.append(result.to_api_format(tc["tool_use_id"]))
    return results
```

The `on_event` parameter is optional; when omitted (e.g., in unit
tests that construct an executor directly), no events are emitted
and behavior matches 0.22.1. Third-party executors implementing
the `ToolExecutor` protocol won't break — they simply miss out on
the new emissions, which was their existing reality anyway.

### Tests

`tests/unit/stages/s10_tool/test_tool_call_events.py` (new):

- Sequential executor fires `call_start` / `call_complete` in order
  for each of N tool calls, `execute_start` before the first
  `call_start`, `execute_complete` after the last `call_complete`.
- `call_start` carries the full input dict (unmasked); `call_complete`
  carries `is_error` and a non-negative `duration_ms`.
- Parallel executor: `N` `call_start` events and `N` `call_complete`
  events arrive, each pair sharing a `tool_use_id`. Ordering between
  pairs is not asserted (parallelism).
- Omitting `on_event` is a no-op — nothing raised, nothing emitted.
- Existing `test_stage_tool.py` still passes (ensures back-compat).

### Release

- `pyproject.toml`: `0.22.1` → `0.23.0` (minor — new public
  contract in the event stream).
- `src/geny_executor/__init__.py`: `__version__ = "0.23.0"`.
- `CHANGELOG.md`: new `[0.23.0] — 20260420` section, **Added**
  only, no Changed/Removed. Reference `#NN` for the PR.
- Git tag `v0.23.0` + GitHub release.

### Risk

Low. The change is purely additive and tested independently. The
only consumer of `on_event` will be s10's default stage; third-party
executors that subclass `ToolExecutor` continue to work because the
new kwarg is keyword-only and optional.

---

## PR III — Geny consumes `tool.call_start` (pin bump + handler swap)

**Fixes**: the Geny half of Bug B.

**Surface**: `backend/service/langgraph/agent_session.py`,
`backend/pyproject.toml`, `backend/requirements.txt`, new test.

### Change

Bump pin and replace the misused `tool.execute_start` branch with a
`tool.call_start` branch.

```python
# agent_session.py (proposed, lines 855-870 area)

if session_logger:
    if event_type == "tool.call_start":
        session_logger.log_tool_use(
            tool_name=event_data.get("name", "unknown"),
            tool_input=event_data.get("input") or {},
        )
    elif event_type == "tool.call_complete":
        # Per-call outcome signal. Optional: log only on error to
        # avoid doubling up with tool.execute_complete's summary.
        if event_data.get("is_error"):
            session_logger.log(
                level=LogLevel.TOOL_RESULT,
                message=(
                    f"Tool {event_data.get('name', 'unknown')} "
                    f"failed ({event_data.get('duration_ms', 0)}ms)"
                ),
                metadata={
                    "tool_name": event_data.get("name"),
                    "is_error": True,
                    "duration_ms": event_data.get("duration_ms"),
                },
            )
    elif event_type == "tool.execute_start":
        # Summary — drop the old log_tool_use call entirely. The
        # UI renders per-call detail from tool.call_start now;
        # execute_start stays in the event stream only for
        # observability tooling that wants turn-level aggregates.
        count = event_data.get("count", 0)
        tools = event_data.get("tools", [])
        session_logger.log(
            level=LogLevel.INFO,
            message=f"Tool turn starting: {count} call(s)",
            metadata={"tool_count": count, "tools": tools},
        )
    elif event_type == "tool.execute_complete":
        # Unchanged from today.
        errors = event_data.get("errors", 0)
        count = event_data.get("count", 0)
        session_logger.log(
            level=LogLevel.TOOL_RESULT,
            message=f"Tool execution complete: {count} calls, {errors} errors",
            metadata={"tool_count": count, "error_count": errors},
        )
```

### Pin bumps

- `backend/pyproject.toml`: `"geny-executor>=0.22.1,<0.23.0"` →
  `"geny-executor>=0.23.0,<0.24.0"`.
- `backend/requirements.txt`: same.

### Tests (`backend/tests/service/langgraph/test_agent_session_tool_logging.py`)

- Fake `tool.call_start` with `{"name": "news_search", "input":
  {"query": "hi"}}` → `session_logger.log_tool_use` called with the
  dict; formatter renders `query=\`hi\``.
- Fake `tool.call_complete` with `is_error=True` → logger emits
  TOOL_RESULT-level error line.
- Fake `tool.execute_start` alone → does **not** produce a
  `log_tool_use` call (regression guard — the exact bug this
  plan exists to fix).
- Fake `tool.execute_complete` → existing summary line emitted
  unchanged.

---

## Sequencing & merge cadence

Per the standing directive (one PR per step, merge before next):

1. **PR I** (Geny, session_id introspection). Smallest, most
   urgent, unblocks tools. Merge + squash + delete branch. Progress
   doc `dev_docs/20260420_3/progress/01_adapter_session_id_fix.md`.
2. **PR II** (executor, `tool.call_*` events + 0.23.0 release).
   Merge, tag, release. Progress doc
   `dev_docs/20260420_3/progress/02_executor_tool_call_events.md`.
3. **PR III** (Geny pin + handler swap). Requires PR II published.
   Progress doc `dev_docs/20260420_3/progress/03_geny_consume_tool_call.md`.
4. User reproduces the VTuber flow end-to-end. If clean, move to
   Plan/02. If not, adjust here rather than opening a new
   `dev_docs/20260420_4/`.

Each PR ships with the reproduction snippet in its description: the
failing call + the passing call after merge.

---

## Interaction with Plan/02

Plan/01 fixes are **independent** of the environment-only cutover
in Plan/02. The executor 0.23.0 event additions are compatible
with the attach-helper that Plan/02's executor work will add
(different modules, different tests). Plan/02's executor release
will be **0.24.0** on top of 0.23.0.

If Plan/02's scope changes, Plan/01 still lands as-is — no code in
Plan/01 is speculative about future architecture.

---

## Non-goals

- **No changes to `tool_detail_formatter.py`.** The formatter is
  correct given valid input; the bug was the caller.
- **No output-payload events.** `tool.call_complete` carries
  `is_error` and `duration_ms` only; full output stays on the
  message bus (state). Event streams should not transport
  unbounded-size payloads.
- **No tracing IDs / spans.** The `tool_use_id` + `duration_ms`
  pair is the minimum needed for the UI. A proper tracing layer
  is out of scope.
