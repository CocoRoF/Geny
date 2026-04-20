# Analysis 02 — Delegation target resolution

## Symptom (from LOG2)

```
VTuber → geny_send_direct_message
   target_session_id: "Sub-Worker Agent"   # display name, not UUID
   content: "안녕! 워커야..."
```

The user flagged this as "worker's id가 제대로 입력되지 않음".

## Is this actually broken?

`backend/tools/built_in/geny_tools.py:71-77`

```python
def _resolve_session(name_or_id: str):
    """Resolve a session by ID or name."""
    manager = _get_agent_manager()
    agent = manager.resolve_session(name_or_id)
    if agent:
        return agent, agent.session_id
    return None, None
```

`manager.resolve_session` accepts **either** a UUID or a display
name. So `"Sub-Worker Agent"` is a valid input as long as a
session with that exact display name exists.

## Two sub-cases

### Case A — display name resolves → fine

If the user's Sub-Worker is literally named `"Sub-Worker Agent"`,
this call works end-to-end once tool registration (analysis 01)
is fixed. The VTuber's prompt context already tells it the
worker's display name, so this is the expected path.

### Case B — display name does not resolve → silent `{"error":…}`

`_resolve_session` returns `(None, None)`; the tool returns
`{"error": "Target session not found: Sub-Worker Agent"}`. No
exception is raised. The frontend's `ERROR (0ms)` visual does
*not* come from this path — it comes from analysis 01 (routing
refuses the call entirely before execution). So case B would
manifest as a successful *tool call* with an error JSON payload
in the output, not as a 0ms ghost.

**Once analysis 01 is fixed, case B becomes the fallback failure
mode**: the user will see the JSON error string in the tool
result, the LLM will correct itself (try a UUID, or re-list
sessions with `geny_session_list`), and the conversation
proceeds. That is the correct design — no code change needed.

## Supporting evidence — prompt context

VTuber sessions are built via `AgentSessionManager.create_session`
which configures the persona to reference the linked sub-worker
by *name* (see `service.langgraph.prompts.*`). So the LLM
emitting `target_session_id="Sub-Worker Agent"` is behaviourally
correct given the prompt. The real question is whether the
manager guarantees the sub-worker has that exact display name.

`backend/service/langgraph/agent_session_manager.py` constructs
the linked session with whatever display name the request
supplied (via `request.session_name`). The VTuber + Sub-Worker
pair is created together, and the linking code stores each
other's `session_name` field in the prompt context.

## Verdict — out of scope for this cycle

The delegation resolution path is correct as written. The
apparent failure in LOG2 is a **downstream** consequence of the
tool not being registered — the LLM saw `ERROR (0ms)` and filled
in an excuse ("I don't have that tool"), not a genuine resolution
failure.

After fixing analysis 01, if the user still sees a genuine
resolution miss, that becomes a separate follow-on:

- Possibly: the Sub-Worker display name in the VTuber's prompt
  drifts from the *actual* stored name (e.g. prompt says
  "Sub-Worker Agent" but the session was saved as "Worker-1").
- Possibly: session cleanup leaves stale name→id mappings that
  `resolve_session` doesn't flush.

Neither is in scope for the tool-registration fix. Document the
test: after PR #2 ships, run a VTuber → Sub-Worker delegation
turn and confirm:

1. `geny_send_direct_message(target="Sub-Worker Agent", ...)` →
   succeeds with `delivered_to_name: "Sub-Worker Agent"`.
2. If it fails with `target not found`, capture the actual
   `session_list` output at that moment and open a focused
   issue against the session-manager linking layer.
