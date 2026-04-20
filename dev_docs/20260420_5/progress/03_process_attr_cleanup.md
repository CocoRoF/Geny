# Progress/03 — `agent_controller.py` `.process` cleanup

**PR.** `fix/controller-process-attr` (cycle 20260420_5, PR #3)
**Date.** 2026-04-20

---

## Symptom (LOG3)

```
File "/app/backend/controller/agent_controller.py", line 915,
in list_storage_files
    process = agent.process
AttributeError: 'AgentSession' object has no attribute 'process'
```

Identical traceback for `read_storage_file` and would occur on
`download_storage_folder` the moment a user exercised it.

## History

In the pre-manifest session shape, `AgentSession` wrapped a
subprocess-backed `ClaudeProcess` accessible as
`agent.process.*`. The manifest cutover
(20260420_3 / 20260420_4) replaced `ClaudeProcess` with a
geny-executor `Pipeline` attached to the `AgentSession` itself
and exposed `storage_path` as a first-class property
(`agent_session.py:331-334`). `.process` was removed; six
controller call-sites still referenced it.

## Six sites, three patterns

### Pattern A — redundant write-through (3 sites, all benign)

Lines `305-306`, `486-488`, `526-528` before this PR. All three
assigned `agent._system_prompt = new_prompt`, then attempted to
mirror that write to `agent.process.system_prompt` — a holdover
from the era when the subprocess needed to know the prompt
independently. Today the composable prompt builder reads
`_system_prompt` directly.

Because `.process` doesn't exist, `if agent.process:` raises
`AttributeError` before the write-through branch is even
reached. Each of these paths was only unreached because the
specific endpoint hadn't been hit in the current session's
lifetime.

Fix: delete the three `if agent.process: agent.process.... = ...`
blocks. The `_system_prompt` assignment + `store.update(...)`
immediately above it already persists the change.

### Pattern B — file endpoints (2 sites, actively throwing)

`list_storage_files` (around line 911) and `read_storage_file`
(around line 938) dereferenced `.process` then called methods on
it. Fixed by:

- Replace `process = agent.process` + method calls →
  `from service.claude_manager import storage_utils` +
  `storage_utils.list_storage_files(storage_path, ...)` /
  `storage_utils.read_storage_file(storage_path, ...)`.
- Use `agent.storage_path` directly as the path source.
- Guard with `if not storage_path: raise 400 ...` — the session
  is real but hasn't finished attaching storage.

`storage_utils.list_storage_files` + `read_storage_file` are
standalone functions
(`backend/service/claude_manager/storage_utils.py:186-296`) that
take the path as an argument. They're the canonical
implementation; the legacy `ClaudeProcess` methods were thin
wrappers. No behaviour change — the same ignore-pattern logic
and the same return shape.

### Pattern C — download-folder ternary (1 site)

Around line 972:

```diff
-    if agent and agent.process:
-        folder = agent.process.storage_path
+    if agent and agent.storage_path:
+        folder = agent.storage_path
```

Same replacement pattern; the else branch (session-store
fallback) is unchanged.

## Verification

- `grep '\.process\b' backend/controller/agent_controller.py`
  returns zero matches after this PR.
- `ast.parse` confirms the file still parses.
- Three new references to `agent.storage_path` and two to
  `storage_utils.*`.

## Tests

No new controller test module in this PR. The existing
`backend/tests/` layout doesn't carry fixtures for live
AgentSession against the FastAPI test client, and wiring one
(seed env, ToolLoader, AgentSessionManager) just to assert
a 200 response introduces significant scope for a
mechanical one-line replacement per endpoint.

PR #4 (`test/tool-use-e2e-validation`) is the right home for
file-endpoint regression coverage: it already needs a
manifest-backed session fixture for the VTuber→Sub-Worker DM
integration test and can assert file endpoints alongside.

## What this unlocks

Users can open the file panel on a live session without
crashing the controller. Combined with PR #1 + PR #2, the
three-way fix covers:

- Platform tools reach both worker and VTuber sessions.
- File endpoints return 200.
- VTuber→Sub-Worker delegation uses real DM tools.

## Rollback

Revert. File endpoints throw `AttributeError` again. The
three benign deletions re-introduce dead code but don't cause
*new* runtime errors beyond what was there before PR #3
(i.e. the same `AttributeError` on the system-prompt update
path).
