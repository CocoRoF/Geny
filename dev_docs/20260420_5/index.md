# 20260420_5 — Tool-Use Architectural Repair

**Date.** 2026-04-20
**Follow-on to.** 20260420_4 (SystemStage/ToolStage registry wiring,
v0.26.1 + v0.26.2 — both merged). Those fixes unblocked the
*mechanics* of tool dispatch. This cycle fixes the *content* of
what reaches the registry in the first place.

## Trigger

Even after v0.26.1 + v0.26.2, the user's VTuber → Sub-Worker
delegation trace still shows:

1. **LOG1** — `geny_send_direct_message` returns `ERROR (0ms)` with
   no execution trail. But now it's not a routing bug: the router
   refuses the call because the tool was never registered.
2. **LOG2** — both VTuber and Sub-Worker explicitly tell the user
   *"I only have web tools, not file / DM tools"*. The LLM is
   reporting its `state.tools` faithfully; the problem is that the
   manifest published a tool roster that excludes every platform
   tool.
3. **LOG3** — `AttributeError: 'AgentSession' object has no
   attribute 'process'` at `agent_controller.py:915` during a file-
   list request. Dead legacy attribute from the pre-manifest
   session shape.

## Root cause (single sentence)

`Pipeline.from_manifest` **only consumes `manifest.tools.external`**
when populating the `ToolRegistry` — `manifest.tools.built_in` is
declarative metadata that nothing reads — and the seed env
templates (`create_worker_env` / `create_vtuber_env`) put only a
*subset of custom tools* into `.external`, never the Geny
platform-layer builtins (`geny_*`, `memory_*`, `knowledge_*`).
So the agents never see DM, inbox, memory, or knowledge tools.

## Folder map

```
analysis/
  01_tool_registration_gap.md   — the manifest.tools.built_in dead-
                                   metadata defect + seed env
                                   roster omission
  02_delegation_target_resolution.md — why Sub-Worker session ids
                                         stay wrong even once DM
                                         works (prompt/context gap)
  03_legacy_process_attr.md     — the 6 `.process` call-sites in
                                   agent_controller.py
plan/
  00_overview.md                — PR sequence + cadence
  01_register_all_manifest_tools.md  — PR #1
  02_role_default_tool_rosters.md    — PR #2
  03_process_attr_cleanup.md         — PR #3
  04_end_to_end_validation.md        — PR #4
progress/
  (populated as each PR merges)
```

## Completion criteria

- VTuber can call `geny_send_direct_message`, `geny_read_inbox`,
  `memory_*`, `knowledge_search` against its Sub-Worker.
- Worker sessions get the full Geny platform toolset + their
  preset-selected custom tools.
- `/sessions/{id}/files` no longer throws `AttributeError`.
- Regression test asserts `pipeline.tool_registry` contains every
  platform tool after `from_manifest_async` returns — so a future
  refactor cannot silently regress the roster again.
