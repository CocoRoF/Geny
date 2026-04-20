# Plan/01 — Single PR: fix probe, defend against ToolWrapper

**Branch.** `fix/tool-bridge-probe-arg-map`
**Depends on.** 20260420_5 (merged).

## Code change — `backend/service/langgraph/tool_bridge.py`

Replace `_probe_session_id_support` with a version that inspects the
signature the kwargs actually reach:

```python
@staticmethod
def _probe_session_id_support(tool: Any) -> bool:
    """True iff injecting `session_id` into this tool's kwargs is safe.

    The adapter's kwargs flow through `arun(**input)` → `run(**input)`
    via :meth:`BaseTool.arun`'s inherited `**kwargs` forwarder, so the
    signature that actually *accepts* the kwargs is `run`'s, not
    `arun`'s. For a ``@tool``-decorated function wrapped in
    ``ToolWrapper``, the kwargs reach ``func`` through
    ``ToolWrapper.run``'s fixed `**kwargs` forwarder — probe ``func``.

    Resolution order:
      1. ``tool.func`` — wrapped function inside a ToolWrapper.
      2. ``tool.run`` — concrete override on a BaseTool subclass.
      3. ``tool.arun`` — last-resort probe for duck-typed objects.

    A target accepts session_id if it declares the parameter
    explicitly OR accepts `**kwargs`. If inspection fails
    (C-implemented callables, partials with unreadable sigs), return
    False — safer to omit the injection than to crash.
    """
    probe_order = (
        getattr(tool, "func", None),   # ToolWrapper
        getattr(tool, "run", None),    # BaseTool subclass
        getattr(tool, "arun", None),   # fallback
    )
    for fn in probe_order:
        if fn is None:
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        for param in sig.parameters.values():
            if param.name == "session_id":
                return True
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                return True
        return False  # first inspectable target is authoritative
    return False
```

Minor hardening in `execute`:

```python
async def execute(self, input, context=None):
    ...
    call_input = dict(input)  # don't mutate caller's dict
    if self._accepts_session_id and context and getattr(context, "session_id", None):
        call_input.setdefault("session_id", context.session_id)
    ...
```

Net diff ~25 LoC.

## Regression tests — `backend/tests/service/langgraph/test_tool_bridge.py` (new)

Matrix:

| Case | Expectation |
|---|---|
| BaseTool subclass without `session_id` in `run` | probe=False; execute passes no `session_id`; tool completes |
| BaseTool subclass with `session_id` in `run` | probe=True; execute injects `session_id`; tool completes |
| BaseTool subclass whose `run` has `**kwargs` | probe=True; tool completes |
| ToolWrapper around function without `session_id` | probe=False; execute passes no `session_id`; func completes |
| ToolWrapper around function with `session_id` | probe=True; func receives it |
| Pure duck-typed object with `arun(session_id, ...)` | probe=True |
| Inspection failure (object with C-implemented callable) | probe=False (safe) |
| `execute` does not mutate the caller's `input` dict | `input` unchanged after call |

Plus an end-to-end micro-integration: wrap
`GenySendDirectMessageTool` (real class, not a stub) via
`_GenyToolAdapter`, call `execute({...}, ctx)`, assert
`ToolResult.is_error is False` and no `TypeError`. Uses monkeypatching
to stub `_resolve_session` so the DM doesn't need a live SessionStore.

## No changes to

- `geny_executor` (the executor's Tool ABC / ToolContext are correct;
  this is a Geny-side adapter bug).
- `BaseTool` / `ToolWrapper` interfaces.
- `GenyToolProvider` (the provider's shape is right; the adapter it
  returns is the problem).
- Any manifest / seed env / role default (20260420_5 territory).

## Verification

1. `python -m pytest tests/service/langgraph/test_tool_bridge.py -q`
   → all matrix rows green.
2. Full suite `python -m pytest tests/ -q` → no regressions.
3. Live smoke: restart backend, open a VTuber session, issue
   "Sub-Worker에게 DM 보내줘". Logs show no `TypeError` on
   `geny_send_direct_message`; DM lands in Sub-Worker inbox.

## Rollback

Revert the commit. The probe reverts to its previous over-eager
behaviour and every DM/room-message tool fails with `TypeError`
again — identical to the pre-PR baseline.

## Progress doc

`progress/01_tool_bridge_arg_plan.md`, mapping the fix to the
analysis, listing the test matrix, and noting the deferred items
(context-as-side-channel, LangChain adapter) from `analysis/02` for
future cycles.
