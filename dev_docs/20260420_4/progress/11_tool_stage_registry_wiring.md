# Progress/11 — ToolStage tool registry wiring fix

**PR.** `fix/tool-stage-registry-bump` (Phase 3 · post-hoc fix #2)
**Upstream PR.** `CocoRoF/geny-executor#34` — merged as v0.26.2
**Companion to.** `progress/10_system_stage_registry_wiring.md`
(v0.26.1). This PR closes the same class of bug on the sibling
stage that v0.26.1 missed.
**Date.** 2026-04-20

---

## Symptom after v0.26.1

VTuber delegation now emits a **structured** `tool_use` block
(the XML fallback is gone — confirmation the v0.26.1 SystemStage
fix reached the runtime). But the tool call then fails at
execution:

```
Tool Call: geny_send_direct_message
Input: {"target_session_id": "Sub-Worker Agent",
        "message": "안녕! 워커야~ …"}
Tool execution complete: 1 calls, 1 errors
geny_send_direct_message: ERROR (0ms)
No output
```

Backend logs show no tool-execution event, no warning, no
exception — just three API round-trips with nothing between
them:

```
13:31:50  POST /v1/messages  → 200
13:31:53  POST /v1/messages  → 200
13:31:59  POST /v1/messages  → 200
```

The 0 ms duration + no error trail is the canonical signature
of a routing-layer short-circuit: the router decided the tool
doesn't exist, returned an error result, and the stage reported
"1 call, 1 error" without ever invoking the tool.

## Root cause

The same construction-order bug that bit SystemStage in v0.26.1
also bites **ToolStage**, but on a different attribute:

1. `Pipeline.from_manifest` creates stages at `pipeline.py:287`
   with the kwargs returned by `_stage_kwargs_for_entry`. That
   helper only returns `{api_key}` for API stages and `{}` for
   everyone else.
2. `ToolStage.__init__` sees `registry=None` and does
   `self._registry = registry or ToolRegistry()` — allocating a
   **freshly empty** registry as a private attribute.
3. Later, at `pipeline.py:317`,
   `_register_external_tools(manifest, registry, …)` populates
   the **shared** `registry` object.
4. v0.26.1 rebinds `SystemStage._tool_registry = registry`, so
   SystemStage now publishes `state.tools` correctly and the
   LLM sees the schema.
5. But `ToolStage._registry` is *still* the empty one from
   step 2. When `RegistryRouter.route(...)` looks up the tool,
   it asks ToolStage's private registry — which is empty — and
   returns `ToolError.unknown_tool(name, known=[])` immediately.
6. The frontend shows `ERROR (0ms)` with "No output" because
   the structured error was swallowed by the lean log path and
   the tool never actually ran.

The `message` vs. `content` param-name mismatch visible in the
frontend is a **red herring**: the tool was never executed, so
the schema-level validation never ran, so the LLM never got
corrective feedback on the arg name. Once routing works, a
wrong param name will surface as `invalid_input` with a clear
"`content` is a required property" message and the LLM's retry
loop will pick the correct name.

## Fix

Upstream (`geny-executor@v0.26.2`, PR #34): extend the v0.26.1
post-hoc rebind loop to cover ToolStage as well.

```python
for stage in pipeline._stages.values():
    # SystemStage — v0.26.1
    if hasattr(stage, "_tool_registry") and getattr(stage, "_tool_registry", None) is None:
        stage._tool_registry = registry
    # ToolStage — v0.26.2
    if getattr(stage, "name", None) == "tool" and hasattr(stage, "_registry"):
        if getattr(stage, "_registry") is not registry:
            stage._registry = registry
```

`ToolStage.execute` already calls
`router.bind_registry(self._registry)` on every run, so the
`RegistryRouter` picks up the rebinding automatically — no
further plumbing needed.

Added regression test
`test_tool_stage_sees_populated_registry_after_from_manifest`
in `tests/unit/test_adhoc_providers.py` parallel to the v0.26.1
SystemStage test.

This PR (Geny side): bumps the floor pin from `>=0.26.1` to
`>=0.26.2` in both `backend/pyproject.toml` and
`backend/requirements.txt` so reproducible installs pick up the
fix.

## Why it wasn't caught in v0.26.1

The v0.26.1 investigation focused on the XML-output symptom,
which is a **pre-LLM-request** problem — the schema never
reached Anthropic because `state.tools` was empty. Fixing
SystemStage was sufficient to make the LLM emit structured
`tool_use` blocks. The post-LLM-request path (routing tools
through ToolStage) had the *same* defect but was never the
focus of the trace, so it slipped through.

The regression test in v0.26.1 asserted SystemStage identity
only. The corresponding ToolStage assertion would have caught
this in isolation; v0.26.2 adds that assertion now, so the
next time someone touches `from_manifest` they will not be
able to regress either stage silently.

## Verification

1. Inline reproduction using `_DictProvider` + `_NamedTool`:
   `ToolStage._registry is pipeline.tool_registry` → True
   after the patch; False before.
2. Walked through a VTuber → Sub-Worker delegation turn end
   to end under the patched runtime (mental model):
   - s03 publishes `state.tools` with `geny_send_direct_message`
     schema. ✓
   - LLM returns `tool_use` block with the canonical args. ✓
   - s10 router looks up the tool in the *shared* registry,
     finds the `_GenyToolAdapter` wrapping
     `GenySendDirectMessageTool`. ✓
   - `validate_input` passes; `adapter.execute(...)` runs;
     `inbox.deliver` + `_trigger_dm_response` fire. ✓
   - `tool.execute_complete` event reports `errors=0`. ✓

## Out of scope

- The `Sub-Worker Agent` vs. real session-id issue visible in
  the user's trace (VTuber prompted its Sub-Worker by display
  name, not session id). The tool *does* accept either via
  `_resolve_session`; this is a prompt/context concern, not a
  registry concern.
- Richer frontend rendering of tool-call errors. The router's
  `ToolError` is already structured; surfacing it in the
  LogsTab is a separate UX task.
- A full sweep of stages that might hold stale references to
  pipeline-level shared objects. ToolStage and SystemStage are
  the only two today; if another stage is later added with the
  same pattern, a parallel rebind hook should be added.

## Rollback

Revert this commit. The pin returns to `>=0.26.1`, which still
resolves to 0.26.2 under the `<0.27.0` ceiling — so fresh
environments keep the fix. Only already-locked envs that
pre-date the fix would need `pip install -U geny-executor` to
recover.
