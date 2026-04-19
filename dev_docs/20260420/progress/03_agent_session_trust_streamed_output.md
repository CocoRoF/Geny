# 03 — VTuber chat truncation: trust streamed accumulation

**Plan ref:** `dev_docs/20260420/plan.md` §3 (Issue 3, Fix B).
**Companion PR:** [`CocoRoF/geny-executor#20`](https://github.com/CocoRoF/geny-executor/pull/20) (Fix A).
**Branch:** `fix/agent-session-trust-streamed-output`.

## Outcome

VTuber Chat (and any other consumer of `AgentSession`) now displays the
full model output once the stream ends, instead of being clipped to
~500 chars. Two-sided fix:

- **Upstream (geny-executor 0.20.1)**: removes the `EVENT_DATA_TRUNCATE`
  slice from `pipeline.complete.result`. That field is the canonical
  final text — preview caps no longer apply.
- **Downstream (this PR)**: `agent_session.py` now treats its
  `text.delta` accumulation as the source of truth and only adopts the
  `pipeline.complete.result` value when it is *at least as long* as
  what we already streamed. Older executor builds that still send a
  truncated `result` no longer overwrite a complete buffer.

## Changes

| File | Change |
|------|--------|
| `backend/pyproject.toml` | `geny-executor>=0.20.0` → `>=0.20.1`. |
| `backend/requirements.txt` | Same pin update for environments that install via pip. |
| `backend/service/langgraph/agent_session.py` | `_invoke_pipeline` (line ~894) and `_astream_pipeline` (line ~1049) now compare lengths before letting `pipeline.complete.result` overwrite the streamed text. Comment explains why preview-truncated `result` would otherwise silently drop characters. |

## Why two layers

Even with the executor fix, Geny still deploys against arbitrary
executor versions in dev environments. The defensive `len(...)` check
costs nothing and prevents a regression if anyone reverts the executor
patch or pins an older release.

## Verification

- Upstream regression covered by
  `tests/unit/test_phase1_pipeline.py::test_streaming_pipeline_complete_carries_full_result`
  in geny-executor (1500-char body round-trips through
  `pipeline.complete.result`).
- Manual: VTuber chat with a prompt that produces > 1000 char output —
  full text remains visible after stream end; DB
  `chat_message.content` length matches the streamed length.

## Skipped / out of scope

- No backend test added in Geny — there is no existing pytest harness
  for `agent_session.py` and adding the scaffolding for one regression
  is disproportionate. The geny-executor side already has the
  authoritative test.
