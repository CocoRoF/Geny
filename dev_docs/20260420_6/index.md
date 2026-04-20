# Cycle 20260420_6 — Tool bridge probe + arg-map correctness

**Status.** Open.
**Trigger.** Live error stream 2026-04-21 15:02 UTC, immediately after
20260420_5 merged:

```
tool_bridge: 'geny_send_direct_message' execution failed:
GenySendDirectMessageTool.run() got an unexpected keyword argument 'session_id'
```

The 20260420_5 cycle got the tool *registration* and *manifest roster*
right — the DM tool now reaches `pipeline.tool_registry`, the VTuber
sees it, Stage 10 dispatches to it. The failure surface has moved one
layer closer to the tool itself: the Geny→executor adapter
(`service.langgraph.tool_bridge._GenyToolAdapter`) injects
`session_id` into the tool's call kwargs when a probe decides the tool
"accepts" it — and the probe is wrong.

## Folder map

```
20260420_6/
├── index.md                                    — this file
├── analysis/
│   ├── 01_probe_misdirection.md                — root cause of the TypeError
│   └── 02_extensibility_review.md              — broader tool-interface review
├── plan/
│   └── 01_fix_probe_and_arg_map.md             — single-PR fix
└── progress/
    └── 01_tool_bridge_arg_plan.md              — written after PR merges
```

## Completion criteria

1. `geny_send_direct_message` dispatches without `TypeError` on a live
   VTuber → Sub-Worker DM.
2. Tools that declare `session_id` explicitly (`geny_session_info`,
   `memory_*`, `knowledge_*`) continue to receive it.
3. Tools that don't declare it (DM, room messages, web search, etc.)
   are never injected.
4. Regression tests in `backend/tests/service/langgraph/` cover the
   full shape matrix (BaseTool with/without session_id, ToolWrapper,
   tool with `**kwargs`).

## Relationship to 20260420_5

Cycle 5 fixed the *catalog* ("which tools does the pipeline know
about"). Cycle 6 fixes the *invocation* ("what do we actually pass
when we call them"). The same LOG2 DM flow is the integration test.
