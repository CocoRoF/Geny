# Plan/01 — Unblock tool execution (Phase 1)

Three PRs. Covers `analysis/01_missing_stages_tool_execution.md`.
The order is **strict**: PR #2 depends on #1, PR #3 depends on
both.

---

## PR #1 — `default_manifest.py`: include stages 10 / 11 / 14

**Branch.** `fix/manifest-tool-stages`

**Files.**
- `backend/service/langgraph/default_manifest.py` (edit)
- `backend/tests/service/langgraph/test_default_manifest.py`
  (new or extended)

**Change.**

Extend both `_worker_adaptive_stage_entries` and
`_vtuber_stage_entries` to emit `StageManifestEntry` rows for
orders 10, 11, and 14. Place them in the correct numeric slots
between the existing entries.

Concrete entries (verified against executor source):

```python
StageManifestEntry(
    order=10,
    name="tool",
    strategies={"executor": "sequential", "router": "registry"},
),
StageManifestEntry(
    order=11,
    name="agent",
    strategies={"orchestrator": "single_agent"},
    config={"max_delegations": 4},
),
StageManifestEntry(
    order=14,
    name="emit",
    strategies={},  # EmitStage uses a chain, no default strategies
    chain_order={"emitters": []},  # empty chain → no-op via should_bypass
),
```

Rationale:

- Stage 10 `sequential` / `registry` — matches the stage's
  default constructor
  (`geny-executor/.../s10_tool/artifact/default/stage.py:36–55`).
- Stage 11 `single_agent` — the no-op orchestrator; multi-agent
  delegation in Geny happens via the DM tool, not this stage.
  `max_delegations=4` matches the default in the stage schema
  (`s11_agent/artifact/default/stage.py:70–78`).
- Stage 14 empty chain — `EmitStage.should_bypass` returns True
  when the chain is empty, so the stage exists for future use
  (TTS, callbacks) but is inert today.

**Both presets should be updated.** VTuber and worker_adaptive
identically need tools. Do not skip VTuber — `web_search` /
`news_search` / `web_fetch` on the VTuber depend on Stage 10.

**Remove stale comment.** The docstring block at
`default_manifest.py:77–80` ("Stage 10 is left off … session-level
code decides") is now wrong. Rewrite it to explain that all tool
stages are declared unconditionally and rely on `should_bypass`
for the no-tools path.

**Tests.**

1. `test_worker_adaptive_has_tool_stage` — build the manifest,
   assert entries include orders `{10, 11, 14}`.
2. `test_vtuber_has_tool_stage` — same assertion for the VTuber
   preset.
3. `test_manifest_instantiates_into_full_pipeline` — call
   `Pipeline.from_manifest_async(manifest)`, inspect
   `pipeline._stages`, assert `{10, 11, 14}` are registered.

**Verification.**

- `python3 -m pytest backend/tests/service/langgraph/test_default_manifest.py -v`
- `python3 -m py_compile backend/service/langgraph/default_manifest.py`

**Out of scope for this PR.**

- Migrating existing on-disk seed envs (deferred to PR #2).
- End-to-end smoke (deferred to PR #3).

---

## PR #2 — Seed-env overwrite on boot

**Branch.** `fix/seed-env-overwrite`

**Files.**
- `backend/service/environment/templates.py` (edit
  `install_environment_templates`)
- Tests.

**Context.**

Zero users, no legacy envs in the wild. We do not need a
preservation-safe migration — on boot we simply overwrite the
two seed envs unconditionally with the canonical output of PR
#1's builder.

**Change.**

`install_environment_templates` today only writes a seed env if
it is missing on disk (`if service.load(env_id) is None:`).
Remove the guard for the two seeded IDs and always overwrite:

```python
for env_id, preset in (
    (WORKER_ENV_ID, "worker_adaptive"),
    (VTUBER_ENV_ID, "vtuber"),
):
    manifest = build_default_manifest(preset=preset, ...)
    service.save(env_id, manifest)  # overwrite unconditionally
```

Custom envs (other IDs) are untouched — only the two template
seeds are rewritten on boot.

**Tests.**

1. `test_seed_env_overwrites_existing_on_boot` — write a stale
   manifest to disk (missing orders 10/11/14), call
   `install_environment_templates`, assert the saved manifest
   now has the full stage set.
2. `test_custom_env_is_not_touched` — an env with a non-template
   ID is left alone.

**Out of scope.**

- Preserving user edits to seed envs (none exist).
- Migration framework.

---

## PR #3 — Integration smoke: end-to-end delegation round-trip test

**Branch.** `test/delegation-round-trip`

**Files.**
- `backend/tests/integration/test_delegation_round_trip.py`
  (new)
- Possibly a shared fixture in `backend/tests/conftest.py` for
  `AgentSessionManager` with a mocked LLM.

**Change.**

Add an integration test that:

1. Spawns an `AgentSessionManager` with a stub LLM that returns
   a fixed tool-call response (LLM emits
   `geny_send_direct_message(target_session_id=<sub_id>,
   content="please do X")`).
2. Creates a VTuber session; asserts a Sub-Worker is auto-created
   and back-linked.
3. Calls `execute_command()` on the VTuber with a trivial user
   prompt.
4. Asserts the Sub-Worker's inbox received the DM with the
   expected content.
5. Stubs the Sub-Worker's LLM to return a "done" response.
6. Triggers Sub-Worker execution; asserts VTuber's inbox now has
   a `[SUB_WORKER_RESULT]`-tagged reply (or the VTuber received
   it directly if idle).

**Why this is a proper test, not a duplicate of PR #1/#2 unit
tests.** Unit tests assert the manifest has the right shape.
This test asserts the shape actually causes tool calls to run
end-to-end. Without this, a future manifest change that drops
Stage 10 by accident could again silently disable tools and
unit tests would still pass.

**LLM stub strategy.** Don't hit the real Anthropic API. Use
the existing test harness for mocked `ClaudeCLIChatModel` (if
it exists) or patch `service/claude_manager/` to return
pre-canned responses. If no harness exists, write a minimal
stub in this PR — keep it local to the test file.

**Out of scope.**

- Property-based testing of all tool-call shapes.
- Testing other tools (`Read`, `Write`, etc.) beyond one
  representative (`geny_send_direct_message`).

---

## Verification at the end of Phase 1

Manual smoke (add to `progress/03_*.md` checklist):

- [ ] Restart the backend; confirm logs show the seed-env
      migration fired and the on-disk manifests now include
      orders 10, 11, 14.
- [ ] Open the env editor UI; confirm `template-worker-env`
      visibly shows a "tool" stage entry.
- [ ] Create a fresh VTuber session through the UI; ask the
      VTuber to run a simple delegation ("worker, read this
      file"); confirm the Sub-Worker actually executes and
      replies.
- [ ] Spin up a solo Worker session; ask it to
      `Read backend/README.md`; confirm the tool call executes
      and contents come back.

Each PR's progress doc documents its own verification; this
section is the phase-level gate.

---

## Rollback plan

If a regression appears after Phase 1 merge:

- PR #1 and #2 are safely revertable — the manifest format is
  back-compatible both ways (`EmitStage` with empty chain is
  inert; `ToolStage` with `pending_tool_calls == []` is a
  no-op).
- On revert, the on-disk seed envs remain upgraded (PR #2 is
  not self-reverting). This is acceptable — the upgraded shape
  is valid for both old and new code.
