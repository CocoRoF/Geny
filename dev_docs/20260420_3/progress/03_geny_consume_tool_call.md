# Progress 03 — Geny consumes `tool.call_*` + pin to 0.23.0

| Field | Value |
|-------|-------|
| Plan ref | `plan/01_immediate_fixes.md` → **PR III** |
| Master ref | `plan/00_overview.md` → **Phase 1 / PR #5** |
| PR | [#146](https://github.com/CocoRoF/Geny/pull/146) |
| Branch | `feat/consume-tool-call-events` (squashed + deleted) |
| Merge commit | `b74b595` on `main` |
| Status | **Merged** — **Phase 1 complete** |

---

## What shipped

Three files, 28 insertions / 6 deletions:

### `backend/service/langgraph/agent_session.py`

Replaced the four-branch event handler with a five-branch one:

| Event | Before | After |
|-------|--------|-------|
| `tool.call_start` | *(didn't exist in 0.22.1)* | `log_tool_use(name, input_dict, tool_use_id)` |
| `tool.call_complete` | *(didn't exist in 0.22.1)* | TOOL_RESULT line **only** on `is_error=True`; happy path silent |
| `tool.execute_start` | `log_tool_use(tools[0], str(count))` ← **the bug** | `INFO` summary `"Tool turn starting: N call(s)"` |
| `tool.execute_complete` | TOOL_RESULT `"…N calls, M errors"` | unchanged |

The "only log errors on `call_complete`" choice is deliberate: the
per-call input already landed via `call_start`, and the
`execute_complete` summary already reports the total error count
for observability. Emitting a per-call success line would double
up the output. An error line is worth it because the user needs
to know *which* of N parallel calls failed, not just "M errors
total".

### Pin bumps

- `backend/pyproject.toml`: `geny-executor>=0.22.1,<0.23.0` →
  `>=0.23.0,<0.24.0`
- `backend/requirements.txt`: same range

Both files now line up with the executor tag `v0.23.0` that's
live on PyPI (verified via
`curl https://pypi.org/pypi/geny-executor/json` → `latest: 0.23.0`).

## Verification done

### Compile

```
$ python3 -m py_compile backend/service/langgraph/agent_session.py
# exit 0
```

### 14-assertion smoke test

Ran against the dispatch logic with realistic event shapes (using
an extracted function matching the merged code byte-for-byte):

| # | Scenario | Expected | Observed |
|---|----------|----------|----------|
| 1 | `call_start` with `news_search` shape | name propagates | OK |
| 2 | `call_start` input dict | dict passed to `log_tool_use`, not `count` string | OK |
| 3 | `call_start` tool_use_id | propagates as `tool_id` | OK |
| 4 | `call_start` with no `input` key | falls back to `{}` | OK |
| 5 | `call_complete` `is_error=False` | silent (no log emitted) | OK |
| 6 | `call_complete` `is_error=True` | one log produced | OK |
| 7 | `call_complete` error level | `TOOL_RESULT` | OK |
| 8 | `call_complete` error message | contains tool name + duration | OK |
| 9 | `call_complete` error metadata | `is_error=True` | OK |
| 10 | `execute_start` | one log produced | OK |
| 11 | `execute_start` method | generic `log`, **not** `log_tool_use` | OK |
| 12 | `execute_start` level | `INFO` | OK |
| 13 | `execute_complete` | message unchanged from pre-0.23.0 | OK |
| 14 | **Regression guard**: `execute_start` never calls `log_tool_use` | verified | OK |

Assertion #14 is the bug guard: the exact path that produced the
`detail='2'` symptom is now actively asserted *not* to happen.

### Not yet verified (requires deploy)

- **End-to-end VTuber session without `env_id`**. With Phase 1
  complete, expected behavior on next deploy:
  1. `news_search`, `web_search`, `web_fetch` *actually execute*
     (was: `TypeError` on `session_id` kwarg → PR #143).
  2. Log UI renders the call input dict per call (e.g.,
     `query=\`…\``), paired with duration on completion (was:
     `detail='2'` → this PR).
  3. Failed calls surface a TOOL_RESULT line with the tool name
     and duration (was: silent — subsumed into summary only).

This validation happens once the user deploys from `main`.

## Phase 1 — exit criteria

The 20260420_3 master plan defines Phase 1 as "VTuber flow unblocked
for real use." That requires:

1. ✅ Tool calls don't `TypeError` on `session_id`. *(PR #143)*
2. ✅ Per-call input available in event stream.
   *(upstream `CocoRoF/geny-executor` PR #29, v0.23.0)*
3. ✅ Geny consumes the per-call event. *(this PR)*

**All three conditions met.** Phase 1 is now a sealed unit; any
follow-up adjustment lives in a new cycle rather than as a
retro-commit here.

## Summary of Phase 1 artifacts

| # | Scope | PR | Status |
|---|-------|----|--------|
| 1 | Geny — `_GenyToolAdapter` introspection | [#143](https://github.com/CocoRoF/Geny/pull/143) | merged |
| 2 | Geny — progress 01 | [#144](https://github.com/CocoRoF/Geny/pull/144) | merged |
| 3 | executor — `tool.call_*` events (v0.23.0) | [CocoRoF/geny-executor#29](https://github.com/CocoRoF/geny-executor/pull/29) | merged + released + on PyPI |
| 4 | Geny — progress 02 | [#145](https://github.com/CocoRoF/Geny/pull/145) | merged |
| 5 | Geny — pin + consumer swap | [#146](https://github.com/CocoRoF/Geny/pull/146) | merged |
| 6 | Geny — progress 03 | *(this PR)* | in flight |

## Next phase

**Phase 2**: environment-only session creation. Per the user's
directive:

> Geny의 모든 sessions 생성은 이제 전부 ENVIRONMENT 기반으로 바꿀거야
> (하위 호환성 신경쓰지 않아도 됨).

Kickoff work is **P2-PR7** — executor `v0.24.0` with the
`Pipeline.attach_runtime(memory_retriever, memory_strategy,
memory_persistence, llm_reflect, llm_gate,
curated_knowledge_manager)` helper. Without this helper, manifest-built
pipelines can't attach Geny's runtime (memory + reflection +
curation) consistently with the current `GenyPresets` flow, and
the Phase 2 cutover loses one of its two endpoints.

Plan: `dev_docs/20260420_3/plan/02_default_env_per_role.md`.
