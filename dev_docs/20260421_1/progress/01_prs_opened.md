# Cycle 20260421_1 — Progress 01: DM continuity PRs opened

**Date.** 2026-04-21
**Status.** Analysis + plan written; 2 code PRs opened; awaiting merge.

## PR board

| Plan/PR | Repo | Branch | PR | Scope |
|---|---|---|---|---|
| 01 / PR-1 | Geny | `fix/classifier-inbox-drain-wrapper` | [#196](https://github.com/CocoRoF/Geny/pull/196) | classifier gains `[INBOX from` prefix |
| 02 / PR-2 | Geny | `feat/dm-sender-stm-record` | [#197](https://github.com/CocoRoF/Geny/pull/197) | `_record_dm_on_sender_stm` + both DM tools |
| docs / PR-3 | Geny | `docs/cycle-20260421_1-analysis-and-plan` | this PR | analysis + plan + progress |

## What each PR closes

- **#196 / Bug A.** `_drain_inbox` replays queued DMs as
  `[INBOX from {sender}]\n{body}`. Before this PR the outer wrapper
  wasn't in `_classify_input_role`'s prefix list, so every DM that
  arrived while the recipient was mid-turn (the common case — VTuber
  is always busy inside its own turn when the Sub-Worker finishes)
  landed in STM labelled `role=user`. Classifier now recognises the
  `[INBOX from` open-form prefix and routes to `assistant_dm`.

- **#197 / Bug B.** `send_direct_message_internal` and
  `send_direct_message_external` wrote only to the recipient inbox and
  fired `_trigger_dm_response`; the sender's own STM never saw the
  outgoing body because `record_message` only fires at the
  `execute_command` input/output layer inside `AgentSession.*_pipeline`.
  New helper `_record_dm_on_sender_stm` writes the body as
  `assistant_dm` on the sender side — symmetric with the recipient
  side's `[SYSTEM] You received a direct message ...` prompt, which
  cycle 20260420_8 already classifies as `assistant_dm`.

- **Bug C (read_inbox tool result not persisted to STM)** — no
  dedicated PR. Once #196 lands, the same message gets replayed via
  `_drain_inbox` after the current turn ends, so the body is written
  to STM at that point anyway. See
  `analysis/01_dm_continuity_regression.md` § 4.

## Merge order (proposed)

1. `#196` — classifier prefix. Self-contained, lowest risk.
2. `#197` — DM sender STM record. Independent at the file level but
   the verification smoke relies on both landing for full continuity.
3. This docs PR — last, matching the cycle 20260420_8 convention of
   landing analysis/plan/progress after the code PRs.

## Verification (post-merge)

The 5-step smoke from `analysis/01` § 7:

1. New VTuber session with Sub-Worker binding.
2. User asks VTuber: "흥미로운 사실 하나 찾아서 알려줘."
3. VTuber calls `send_direct_message_internal` → immediate
   acknowledgement response.
4. Wait ~2 min → `THINKING_TRIGGER:time_morning` fires automatically.
5. **Expected:** VTuber references the Sub-Worker's earlier reply as
   an established fact, not "아직 답이 없다". STM transcript should
   contain at minimum:
   - `role=assistant_dm` turn with body `[DM to Sub-Worker (internal)]: …`
     (from #197)
   - `role=assistant_dm` turn with body
     `[INBOX from Sub-Worker]\n[SUB_WORKER_RESULT] …` (from #196)
   - `role=user` turns should contain only the human user's text,
     never trigger / DM content.

## Non-scope reminders

- **LTM schema untouched.** `record_execution` continues to store
  full turns; no migration needed.
- **Retrieval layer untouched.** L0 recent-turns already handles
  `assistant_dm` correctly (cycle 20260420_8 PR-5); this cycle just
  feeds it the right data.
- **Non-DM tool results** (`web_search`, `Bash`, etc.) remain outside
  STM — scope is still DM/inbox-class messaging only.
