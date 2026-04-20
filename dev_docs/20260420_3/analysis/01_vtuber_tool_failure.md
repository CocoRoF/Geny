# Analysis 01 — VTuber `news_search` failure root cause

Two *independent* defects combine in the session log. Fixing either
one does not mask the other — each needs its own patch.

---

## Bug A (primary) — `_GenyToolAdapter.execute` blindly injects `session_id`

### Evidence

File: `backend/service/langgraph/tool_bridge.py`, lines 104-149.

```python
async def execute(
    self, input: Dict[str, Any], context: Any = None
) -> Any:
    """Execute the Geny tool and wrap result as ToolResult.

    Automatically injects session_id from ToolContext into the input
    dict if the tool expects it (many Geny built-in tools require it).
    """
    from geny_executor.tools.base import ToolResult

    # Auto-inject session_id from Pipeline ToolContext
    if context and hasattr(context, "session_id") and context.session_id:
        input.setdefault("session_id", context.session_id)

    try:
        # Try async first (arun), fall back to sync (run)
        if hasattr(self._tool, "arun"):
            result = await self._tool.arun(**input)
        elif hasattr(self._tool, "run"):
            run_fn = self._tool.run
            if asyncio.iscoroutinefunction(run_fn):
                result = await run_fn(**input)
            else:
                result = await asyncio.to_thread(lambda: run_fn(**input))
        ...
    except Exception as exc:
        logger.warning("tool_bridge: '%s' execution failed: %s", self._name, exc, exc_info=True)
        return ToolResult(
            content=f"Error executing {self._name}: {exc}",
            is_error=True,
        )
```

The docstring claims the injection happens "if the tool expects it" —
the code does **not** check. `input.setdefault(...)` adds the key
unconditionally whenever a `ToolContext` with a truthy `session_id`
is present, and the ToolContext created in `agent_session.py:709-713`
always carries `self._session_id`.

### Target tool's signature

File: `backend/tools/custom/web_search_tools.py`, lines 101-130.

```python
class NewsSearchTool(BaseTool):
    name = "news_search"
    ...
    def run(
        self,
        query: str,
        max_results: int = 5,
        region: str = "us-en",
        timelimit: Optional[str] = None,
    ) -> str:
        ...
```

`NewsSearchTool.run` accepts exactly four kwargs and **does not**
declare `**kwargs`. Passing `session_id=...` raises
`TypeError: run() got an unexpected keyword argument 'session_id'`
on the very first call.

The same applies to `WebSearchTool.run` and `WebFetchTool.run` (all
three tools in the VTuber preset whitelist — see
`backend/service/tool_preset/templates.py:38-42`). The VTuber has
**no** tool whose signature will accept the forced kwarg.

### Why both calls fail the same way

The caught exception becomes `ToolResult(is_error=True)` with
`content="Error executing news_search: run() got an unexpected …"`.
Stage s10_tool treats the result as a normal tool_result block and
the loop returns to stage s05/s06 for the next model turn. The
Anthropic model sees the error, retries with a slightly different
query, and hits the *same* signature mismatch — two identical
failures, not a transient network problem.

So the log's "2 calls, 2 errors" is a deterministic consequence of
Bug A: every future call will fail until the kwarg injection is
fixed.

### Why this did not explode earlier

Two reasons the bug survived prior test cycles:

1. **Built-in Geny tools *do* accept `session_id`.** Tools like
   `mcp_tools`, `sub_agent`, `list_files` were authored assuming
   the adapter would inject it, so the assumption in the
   adapter's docstring is correct *for them*. The adapter was
   originally written to service those specific tools and grew to
   cover custom tools later without revisiting the assumption.
2. **The pre-0.22.0 error surface used plain strings.** Previously
   a tool exception was rendered as `Error: ...` in the content
   string and did not mark the result as an error. The model was
   more tolerant of the malformed response and would sometimes
   "recover" by pivoting to a different tool. Since 0.22.0's
   structured `ToolResult(is_error=True)` bridge, the error is now
   visibly an error every time, which also made the bug
   reproducible.

### Fix direction (detail in plan/01)

Introspect the wrapped tool's `run`/`arun` signature once (at
adapter construction) and inject `session_id` only when the
signature accepts it — either by naming it explicitly or by
declaring `**kwargs`. Cache the introspection result on the
adapter; do not re-run `inspect.signature` per call.

---

## Bug B (secondary) — session logger passes the *count*, not the *input*

### Evidence

File: `backend/service/langgraph/agent_session.py`, lines 855-862.

```python
if session_logger:
    if event_type == "tool.execute_start":
        tool_name = event_data.get("tools", ["unknown"])[0] if event_data.get("tools") else "unknown"
        session_logger.log_tool_use(
            tool_name=tool_name,
            tool_input=str(event_data.get("count", "")),
        )
```

`tool.execute_start` is emitted by the executor's s10_tool stage
(see `geny-executor/src/geny_executor/stages/s10_tool/artifact/default/stage.py:101`)
with a payload shaped like:

```python
{"tools": ["news_search"], "count": 1, "iteration": 3}
```

The `count` field is **the number of tool calls in the current
iteration**, not a per-call detail. The current code stringifies
that integer and hands it to `session_logger.log_tool_use` as the
`tool_input` positional. When two tools fire in one turn, the count
is `2`, so every subsequent detail render sees the string `"2"`.

### How that becomes `'2'` in the UI

File: `backend/service/logging/tool_detail_formatter.py`, lines 80-96
and 196-203.

```python
def format_tool_detail(tool_name, tool_input):
    if not tool_input:
        return "(no input)"
    try:
        return _format_tool_detail_inner(tool_name, tool_input)
    except Exception:
        logger.exception("tool detail formatting crashed; tool=%s", tool_name)
        try:
            fallback = repr(tool_input)
        except Exception as exc:
            return f"<unrepresentable input: {type(exc).__name__}>"
        return _truncate(fallback, _REPR_FALLBACK_LIMIT)
```

`tool_input` is the string `"2"`. The inner formatter falls through
to the default branch:

```python
for key, value in tool_input.items():
    ...
```

`str.items()` does not exist → `AttributeError` → caught by the
top-level `except Exception` at line 85 → `logger.exception` dumps
a traceback → `repr("2")` returns the six-character string
``"'2'"`` (the two quote marks *are* visible). That is exactly
what the user sees in the UI.

So the formatter is behaving **correctly given the wrong input**.
The formatter's new "no swallower" policy (PR #137 from 20260420_2)
is what surfaced this as a log exception — previously the legacy
swallower silently returned `"(parse error)"` and nobody noticed.

### Fix direction (detail in plan/01)

`tool.execute_start` does not currently carry the per-call `input`
payload. The fix is one of:

1. Short term: emit a richer per-tool detail from `agent_session.py`
   by listening to `tool.call` (per-call) events, which already
   carry `input`. Stop consuming `event_data["count"]` as a detail.
2. Medium term: add `inputs: list[dict]` to the `execute_start`
   event data in the executor, so the detail survives without
   changing event ordering.

Option 1 is Geny-side only — no executor release needed. Plan 01
picks option 1; option 2 is noted as a future executor change if
the per-call events turn out to be noisy.

---

## Interaction between the two bugs

The two bugs are stacked but independent:

- **Fix only Bug A**: tool runs succeed, but the UI still shows
  `'2'` as the detail, because `tool_input` is still the stringified
  count. Observability remains broken.
- **Fix only Bug B**: UI shows the right query, but every call
  still `is_error=True` with the same `TypeError`. Usability
  remains broken.

Both fixes are required to land the VTuber flow in a working state.
Neither fix is a rollback of a 20260420_2 change — these are pre-
existing bugs that the 0.22.0 error-surface hardening made visible.

---

## Scope boundary: this is *not* an env_id bug

Both bugs reproduce with **or without** env_id:

- Non-env_id VTuber: `_build_pipeline` registers the adapted
  `news_search` directly into a fresh `ToolRegistry` at
  `agent_session.py:699-702` ("Geny application tools (via
  tool_bridge adapter)"). Same `_GenyToolAdapter`, same bug.
- env_id VTuber: the env path funnels through
  `EnvironmentService.instantiate_pipeline` with `adhoc_providers =
  [GenyToolProvider(tool_loader)]` (PR #139). `GenyToolProvider.get`
  ultimately wraps the same `BaseTool` with the same
  `_GenyToolAdapter`. Same bug.

The env_id dimension — covered in `analysis/02` — is a separate
design gap. It does not cause the failure reported here.
