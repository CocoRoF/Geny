# Analysis/01 — `_probe_session_id_support` misdirection

## Symptom

```
tool_bridge: 'geny_send_direct_message' execution failed:
GenySendDirectMessageTool.run() got an unexpected keyword argument 'session_id'
```

Not just DM — this fires on every `BaseTool` subclass whose concrete
`run()` signature does not declare `session_id` or accept `**kwargs`.
Which is most of them.

## The probe

`service/langgraph/tool_bridge.py:45-73`:

```python
def _probe_session_id_support(tool):
    fn = getattr(tool, "arun", None) or getattr(tool, "run", None)
    sig = inspect.signature(fn)
    for param in sig.parameters.values():
        if param.name == "session_id":
            return True
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return False
```

Two bugs, one surfaced:

1. **`arun` is always tried first.** Every `BaseTool` subclass inherits
   `BaseTool.arun(self, **kwargs)` — a universal forwarder that calls
   `self.run(**kwargs)`. The probe sees `VAR_KEYWORD` → returns `True`.
   Cached on `self._accepts_session_id`.
2. **Downstream, `execute` injects `session_id`:** `input.setdefault("session_id", ctx.session_id)`,
   then calls `arun(**input)`. The inherited forwarder has `**kwargs`
   so it accepts it; it then calls `self.run(session_id=...)` which
   raises `TypeError` because the concrete `run`'s signature does not
   include `session_id`.

**Root cause**: the probe inspects the *wrong signature*. The kwargs
the adapter actually sends don't land in `arun` — they pass through
`arun`'s `**kwargs` catchall into `run`, whose signature is the
authoritative one.

## Audit of current tool set

Reproduced with
`backend/tools/built_in/{geny,memory,knowledge}_tools.py`:

| Tool | `run` signature | Probe on `arun` | Probe on `run` | Should inject? |
|---|---|---|---|---|
| `geny_send_direct_message` | `(target_session_id, content, sender_session_id='', sender_name='')` | **True (wrong)** | False | No |
| `geny_send_room_message` | `(room_id, content, sender_session_id='', sender_name='')` | **True (wrong)** | False | No |
| `geny_session_list` | `()` | **True (wrong)** | False | No |
| `geny_session_info` | `(session_id)` | True | True | Yes |
| `memory_read` | `(session_id, filename)` | True | True | Yes |
| `memory_write` | `(session_id, filename, content)` | True | True | Yes |
| `knowledge_read` | `(session_id, filename)` | True | True | Yes |
| `web_search`, `news_search`, `web_fetch` (custom) | depends | **True (wrong)** if `**kwargs` in `arun` | False | No |

The probe-on-`run` column matches the "should inject?" column exactly.
The probe-on-`arun` column is `True` for every row — the inherited
forwarder swallows all signature information.

## Why the bug escaped 20260420_5

The 20260420_5 harness (`test_vtuber_dm_delegation.py`) used a stub
`_RecordingDMTool` that inherited `geny_executor.tools.base.Tool`
directly — not Geny's `BaseTool`. So the stub's `execute` received
`input` dict cleanly, no Geny-shaped `arun`/`run` forwarding. The
probe/inject code path in `_GenyToolAdapter` was never exercised.

The integration test proved *Stage 10 dispatches to the registered
tool*. It did not prove *the Geny tool's `run()` receives kwargs its
signature accepts*. That's the gap this cycle closes.

## Scope of the fix

The probe needs to inspect the signature that actually receives the
kwargs:

- For a `BaseTool` subclass that does not override `arun`: that's the
  concrete `run` override (abstract in the base, so a concrete class
  must supply it).
- For a `BaseTool` subclass that *does* override `arun` with a non-trivial
  implementation: that's `arun` itself.
- For a `ToolWrapper` (created by `@tool` decorator): `ToolWrapper.run`
  is a fixed `(**kwargs)` forwarder to `self.func` — probe `func`
  instead.
- For anything else that looks like a tool (duck-typed): fall back to
  `arun` → `run`.

Additionally, the current `input.setdefault("session_id", ...)`
mutates the caller's `input` dict — benign because the caller in
`Stage 10` creates a fresh dict per call, but a latent foot-gun if
the adapter is ever reused. Worth tightening to a local copy.

## Out of scope

- `BaseTool`'s top-level interface. Rewriting `run(**kwargs)` →
  `run(input, context)` would break every user-authored custom tool
  in `tools/custom/`. The adapter is the right place to absorb the
  impedance mismatch.
- `@tool` decorator ergonomics. `ToolWrapper` is fine; only the probe
  needs to know to look at `func`.
- MCP tool shape. MCP tools never go through `_GenyToolAdapter` —
  they're registered by `mcp_manager` against a separate adapter.
