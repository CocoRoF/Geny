# Analysis 03 — Legacy `.process` attribute

## Symptom (LOG3)

```
File "/app/backend/controller/agent_controller.py", line 915,
in list_storage_files
    process = agent.process
AttributeError: 'AgentSession' object has no attribute 'process'
```

Identical traceback for `read_storage_file` and `download_folder`.
The error surfaces on file-related endpoints only.

## History

In the pre-manifest session shape, `AgentSession` wrapped a
subprocess-backed `ClaudeProcess` accessible as
`agent.process.*` — `agent.process.storage_path`,
`agent.process.system_prompt`, etc.

The manifest cutover (20260420_3 / 20260420_4) replaced
`ClaudeProcess` with a geny-executor `Pipeline` attached to the
`AgentSession` itself. `process` was removed; its functionality
moved to first-class properties:

- `agent.process.storage_path` → `agent.storage_path`
  (`agent_session.py:331-334`)
- `agent.process.system_prompt` → `agent._system_prompt`
  (internal; prompts flow through the composable system builder)

## Call-sites still referencing `.process`

From `grep -n "\.process\b" backend/controller/agent_controller.py`:

| Lines | Usage | Fix |
| --- | --- | --- |
| 307-308 | `if agent.process: agent.process.system_prompt = new_prompt` | **Delete** — the `_system_prompt` assignment on line 306 already persists to the session; writing to `agent.process.system_prompt` was forwarding it to the old subprocess and is a no-op today even when `.process` exists. Benign dead code. |
| 487-488 | Same pattern in session-restore path | **Delete** — same reason. |
| 525-528 | Same pattern in linked-session restore | **Delete** — same reason. |
| 915-917 | `process = agent.process; if not process: raise 400` then reads `process.storage_path` below | **Replace** — use `agent.storage_path` directly. The modern session always has it; no None-guard needed at the property level, but a "session not ready" 400 still makes sense if `agent.storage_path is None`. |
| 942-944 | Same pattern in `read_storage_file` | **Replace** — same. |
| 970-973 | `if agent and agent.process: folder = agent.process.storage_path` | **Replace** — `agent.storage_path`. |

Three of the six sites (307-308, 487-488, 525-528) are
*benign*: the attribute is guarded by `if agent.process:` which
evaluates to `None` (falsy) and the branch is skipped. The
remaining three actively throw because they dereference
`.process` directly.

## Why the benign three still deserve fixing

`agent.process` resolves via the default `__getattr__` path —
which isn't defined on `AgentSession`. Python raises
`AttributeError`, and `if agent.process:` **also raises** rather
than falling through. So even the "guarded" sites throw the
moment they're hit. LOG3 shows the hit is at line 915 because
that's the path the user exercised first; the other five would
fail on their respective endpoints.

All six must be fixed together to deliver a usable session-
controller surface.

## Scope boundary

Other controllers (session_controller, chat_controller, etc.)
don't reference `.process` — confirmed via
`grep -rn "\.process\b" backend/controller/`. Only
`agent_controller.py` has this legacy.

## Test that would have caught this

A simple controller-level test that calls each of the three file
endpoints against a manifest-built AgentSession. Such tests
don't exist today — the controller layer has integration tests
only for the primary `execute` endpoint. Plan/03 adds a minimal
one.
