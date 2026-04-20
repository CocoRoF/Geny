# Cycle 20260420_8 — Progress 01: All 5 PRs opened

**Date.** 2026-04-21
**Status.** Implementation phase complete. 5 PRs open, none merged yet.
All branches based on green main; tests pass locally on their
respective repos.

## PR board

| Plan/PR | Repo | Branch | PR | Tests |
|---|---|---|---|---|
| 01 / PR-1+2 | Geny | `feat/tool-surface-rename-and-counterpart-register` | [#191](https://github.com/CocoRoF/Geny/pull/191) | templates + tool registry roster + vtuber DM delegation |
| 02 / PR-3 | Geny | `feat/sub-worker-reply-chat-broadcast` | [#192](https://github.com/CocoRoF/Geny/pull/192) | 7 cases, fire-and-forget captured deterministically |
| 03 / PR-4 | Geny | `feat/stm-assistant-role-recording` | [#193](https://github.com/CocoRoF/Geny/pull/193) | classifier param + wiring (invoke + stream) |
| 03 / PR-5 | geny-executor | `feat/retriever-l0-recent-turns` | [CocoRoF/geny-executor#36](https://github.com/CocoRoF/geny-executor/pull/36) | 7 new cases; 615/616 unit suite green |
| 03 / PR-5 follow-up | Geny | `chore/executor-0.28.0` | [#194](https://github.com/CocoRoF/Geny/pull/194) | — (deps-only; waits on executor 0.28.0 release) |

## What each PR closes

- **#191 / plan-01** — Bug 1. VTuber could still try to address
  non-counterpart workers via `send_direct_message`. Fix: drop `geny_`
  prefix, split DM into `send_direct_message_internal` (counterpart-
  only, no target id) vs `send_direct_message_external` (addressed),
  and deny the external variant + session_create/list/info on VTubers.
  A stem-based `tool_source` allowlist replaces the brittle
  `_PLATFORM_TOOL_PREFIXES` heuristic. `GenyMessageCounterpartTool`,
  which cycle 7 left defined-but-unexported, is finally in `TOOLS`.

- **#192 / plan-02** — Bug 2a. `_notify_linked_vtuber` had a hidden
  omission: it fired `execute_command` but discarded the return value,
  so the VTuber's reply to `[SUB_WORKER_RESULT]` never reached the
  chat room. Fix: capture the result, call a new
  `_save_subworker_reply_to_chat_room` helper that mirrors
  `_save_drain_to_chat_room` / the thinking-trigger broadcast.

- **#193 / plan-03 PR-4** — Bug 2b half one. STM never recorded
  assistant replies, and every input was stored as `role="user"`. Fix:
  new `_classify_input_role` maps trigger/DM tags to real roles
  (`internal_trigger`, `assistant_dm`) and we now record the
  assistant's reply before the LTM write.

- **CocoRoF/geny-executor#36 / plan-03 PR-5** — Bug 2b half two. A
  trigger-style query (`[THINKING_TRIGGER:continued_idle]`) had no
  lexical overlap with "sub-worker" / "file" and semantic/keyword
  retrieval missed the prior turn. Fix: new L0 recent-turns layer in
  `GenyMemoryRetriever` injects the tail of STM verbatim before any
  matching runs. Version bump 0.27.0 → 0.28.0, CHANGELOG updated.

- **#194 / plan-03 PR-5 follow-up** — bumps Geny's executor floor to
  `>=0.28.0,<0.29.0` and passes `recent_turns=6` at the retriever
  init site. Will CI-fail until 0.28.0 is published; land after
  CocoRoF/geny-executor#36 merges.

## Merge order (proposed)

1. `#191` — foundational rename; other PRs target the post-rename
   tool names in prompts and injection blocks.
2. `#192` — independent of #191 at the file level (no overlap), safe
   to merge in parallel if CI permits.
3. `CocoRoF/geny-executor#36` → cut `0.28.0` release.
4. `#193` + `#194` land together so user/assistant turns and the L0
   tail arrive in the same deploy — neither fixes Bug 2b alone.

## Verification checklist (post-merge + 0.28.0 release)

Runs through the 6-step smoke in `plan/03_turn_memory_continuity.md`:
fresh VTuber session → "test.txt 만들어줘" → Sub-Worker writes →
VTuber reply appears in chat room → wait 2 min for
`continued_idle` trigger → VTuber response references test.txt instead
of "아직 답이 없어요". STM transcript file should show both `user`
and `assistant` (plus `assistant_dm` for the SUB_WORKER_RESULT turn).

## Non-scope reminders

- Vector rerank boost for `[SUB_WORKER_RESULT]` turns — L0 tail is
  sufficient for this cycle, defer.
- STM rolling-window policy — untouched.
- Executor's `memory_message` provider-side role handling — the
  executor-side retriever just reads whatever role string is stored,
  so no executor follow-up is required.
