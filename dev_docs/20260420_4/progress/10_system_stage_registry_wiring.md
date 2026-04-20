# Progress/10 — SystemStage tool registry wiring fix

**PR.** `fix/system-stage-tool-registry-bump` (Phase 3 · post-hoc fix)
**Upstream PR.** `CocoRoF/geny-executor#33` — merged as v0.26.1
**Plan.** Regression caught after completing the 20260420_4 nine-PR
cycle. Originating symptom: VTuber output contained literal
`<function_calls><invoke name="geny_send_direct_message">…` XML
instead of structured tool use. No `s10_tool` logs in the session
trail — the LLM was hallucinating XML because it had never been
told any tools existed.
**Date.** 2026-04-20

---

## Symptom

After PRs #1–#9 landed, a VTuber session asked to delegate to
its Sub-Worker responded with plain text of the form:

```
네! 워커에게 인사 전해드릴게요!

<function_calls>
<invoke name="geny_send_direct_message">
<parameter name="target_session_id">…</parameter>
…
```

The XML was *user-visible content*, not a `tool_use` block. The
session log showed the API call but no `s10_tool` events — no
tool was ever executed. This is the canonical signature of a
training-era fallback: the model, given `tools=None`, reaches
for the XML format it was trained with rather than refusing.

## Root cause

Race between stage construction and tool-registry population in
`geny_executor.core.pipeline.Pipeline.from_manifest`:

1. Stages are instantiated from `manifest.stage_entries()` via
   `create_stage(entry.name, entry.artifact, **kwargs)` at
   `pipeline.py:287`.
2. `_stage_kwargs_for_entry` returns only `{api_key}` for stages
   that want it — nothing else. SystemStage's `__init__` takes
   an optional `tool_registry`; without a kwarg passed in, the
   stage instance stores `self._tool_registry = None`.
3. *Then*, at `pipeline.py:317`,
   `_register_external_tools(manifest, registry, adhoc_providers)`
   populates the *shared* registry object, and
   `pipeline._tool_registry = registry` attaches it to the
   pipeline.
4. SystemStage's reference is never rebound. At execute time,
   `s03_system/.../stage.py:116-117` gates on
   `if self._tool_registry and not state.tools:` — falsy `None`
   → `state.tools` stays `[]`.
5. APIStage later sends `tools=state.tools`, i.e. `tools=[]`
   (or absent), to Anthropic. With no tool schema to bind to,
   the model emits the XML fallback in assistant text.

The integration tests never caught this because the tests that
exercised external-provider registration read from
`pipeline.tool_registry` directly — the pipeline's own handle
was correct. Only the stage's stale handle was wrong, and no
test asserted stage-level identity.

## Fix

Upstream (`geny-executor@v0.26.1`, PR #33): after
`_register_external_tools` runs, walk `pipeline._stages.values()`
once and, for any stage whose `_tool_registry` is still `None`,
rebind it to the populated registry. Stages that were
constructed with an explicit registry (tests, callers wiring
manually) are left alone.

Added regression test
`test_system_stage_sees_populated_registry_after_from_manifest`
in `tests/unit/test_adhoc_providers.py`: builds an `s03_system`
manifest with `external=["alpha"]`, constructs the pipeline,
and asserts the SystemStage's `_tool_registry` is the same
object as `pipeline.tool_registry` and that `alpha` is
registered on it. Fails without the patch; passes with it.

This PR (Geny side): bumps the floor pin from `>=0.26.0` to
`>=0.26.1` in both `backend/pyproject.toml` and
`backend/requirements.txt` so any fresh install picks up the
fix.

## Why bump the pin, not just rely on the range

The existing range `>=0.26.0,<0.27.0` would pick up 0.26.1 on a
fresh install. But already-provisioned environments that
resolved against the 0.26.0 floor have no trigger to upgrade.
Moving the floor makes the dependency-upgrade explicit for any
reproducible build.

## Verification

1. `pip show geny-executor` in a freshly resolved env → 0.26.1.
2. Walked the failure signature end-to-end:
   - `Pipeline.from_manifest(manifest, adhoc_providers=[…])`
     for an env that declares `external=["geny_send_direct_message"]`.
   - `pipeline.get_stage(3)._tool_registry` is the populated
     registry (not `None`). ✓
   - First state after s03 has `state.tools` non-empty with the
     tool's JSON schema. ✓
   - s06 sends `tools=state.tools` to Anthropic. ✓
   - Model returns a `tool_use` block rather than XML. s09
     parses it into `state.pending_tool_calls`; s10 executes it
     and the `delegation.sent` log entry appears. ✓
3. Regression test on the upstream side locks in the contract.

## Out of scope

- Richer schema-validation at manifest-load time to surface
  "declared external tools with no providers" before runtime.
  The existing WARNING log is enough for now.
- Similar audit of the other stages that *might* hold stale
  references to shared pipeline state. Only SystemStage
  currently opts into a `tool_registry` kwarg; no other stage
  is affected.

## Rollback

Revert this commit. The pin returns to `>=0.26.0`, which still
resolves to 0.26.1 on a fresh install — so the fix remains in
effect for any new environment. Only already-locked envs that
pre-date the fix would need a manual `pip install -U
geny-executor` to recover.
