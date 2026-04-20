# Progress/01 — Probe fix + caller-input isolation

**PR.** `fix/tool-bridge-probe-arg-map` (cycle 20260420_6, PR #1)
**Date.** 2026-04-21

---

## Symptom (from live logs 2026-04-21 15:02 UTC)

```
tool_bridge: 'geny_send_direct_message' execution failed:
GenySendDirectMessageTool.run() got an unexpected keyword argument 'session_id'
```

Repeats on every tool whose concrete `run()` lacks `session_id` and
lacks `**kwargs` — every tool in the geny/room/custom families except
the handful that explicitly declare it.

## Root cause

See `analysis/01_probe_misdirection.md`. Summary: the probe read
`arun`'s signature first, saw the inherited `**kwargs` forwarder, and
returned `True` for every `BaseTool` subclass. Injection then landed
in `run` via the forwarder and triggered `TypeError`.

## The change (`backend/service/langgraph/tool_bridge.py`)

### `_probe_session_id_support`

Rewrote the probe to inspect the authoritative callable — the one
that actually receives the kwargs:

```python
for fn in (
    getattr(tool, "func", None),   # ToolWrapper (@tool decorator)
    getattr(tool, "run", None),    # concrete BaseTool override
    getattr(tool, "arun", None),   # duck-typed fallback
):
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
    return False
return False
```

Key decision: the *first inspectable* target is authoritative. If
the tool exposes `.func`, we don't fall through to `.run` — because
the kwargs will reach `func` via `ToolWrapper.run`'s `**kwargs`
forwarder, identical to the BaseTool case but for decorator-style
tools.

### `execute`

Stopped mutating the caller's `input` dict:

```python
call_input = dict(input)
if self._accepts_session_id and context and ctx.session_id:
    call_input.setdefault("session_id", context.session_id)
# ... everything downstream uses call_input, not input
```

The caller (Stage 10) constructs a fresh dict per call today, so
this was latent — but adapters are cached in `GenyToolProvider` and
retries at the stage layer could have observed the mutation.

## Regression tests
(`backend/tests/service/langgraph/test_tool_bridge.py`)

14 tests, 8 shapes covered:

| Shape | Probe | Injection behaviour |
|---|---|---|
| `BaseTool` subclass, `run(target, content)` | False | not injected |
| `BaseTool` subclass, `run(session_id, key)` | True | injected from context |
| `BaseTool` subclass, `run(**kwargs)` | True | injected (safe) |
| `BaseTool` subclass, explicit input `session_id` | True | respects `setdefault` |
| `@tool` decorator, `fn(target, content)` | False | not injected |
| `@tool` decorator, `fn(session_id, key)` | True | injected from context |
| Duck-typed `arun` only, explicit `session_id` | True | injected |
| Uninspectable callable (ValueError from `signature`) | False | not injected, no crash |

Plus:
- `test_execute_does_not_mutate_caller_input` — the input-isolation
  regression.
- `test_geny_send_direct_message_adapter_no_type_error` —
  end-to-end smoke against the *real* `GenySendDirectMessageTool`
  class (monkey-patched `_resolve_session` / inbox / trigger) to
  prove the production bug is dead.

Full suite: `56 passed` (42 pre-existing + 14 new).

## Verification

```
$ python -m pytest tests/service/langgraph/test_tool_bridge.py -q
..............                                                           [100%]
14 passed in 0.25s

$ python -m pytest tests/ -q
........................................................                 [100%]
56 passed in 0.38s
```

Live smoke (post-merge / deploy): restart backend, open a VTuber
session, issue "Sub-Worker에게 DM 보내줘". Expect: no `TypeError`
in `tool_bridge` logs; `geny_send_direct_message` returns success
JSON; the Sub-Worker inbox picks up the message.

## Deferred (from `analysis/02_extensibility_review.md`)

Not in this PR — recorded as next investments if a consumer needs
them:

1. **Context-as-side-channel**: migrate Geny's platform tools to
   receive `ToolContext` via a dedicated parameter (e.g.
   `run(**input, *, ctx=None)`) so `session_id` stops appearing in
   LLM-visible schemas. Touches every platform tool; scope for a
   dedicated cycle if the kwargs-coupling continues to cause churn.
2. **LangChain adapter**: `LangChainToolProvider` implementing
   `AdhocToolProvider`, wrapping each `langchain.tools.BaseTool`
   into a geny-executor `Tool`. One file; add when the first
   consumer arrives.
3. **Schema fidelity**: `BaseTool._generate_parameters_schema`
   degrades `Optional`/`Union`/`List[X]` to `"string"`. Tools that
   care override `parameters = {...}` manually; if LLM-side
   hallucinations start creeping in, revisit.

## Rollback

Revert the commit. Probe reverts to the over-eager behaviour, every
tool whose `run()` lacks `session_id`/`**kwargs` raises `TypeError`
again, identical to the pre-PR baseline.
