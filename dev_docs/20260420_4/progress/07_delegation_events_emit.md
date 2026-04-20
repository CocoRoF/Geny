# Progress/07 — Delegation events emit

**PR.** `obs/delegation-events` (Phase 2 · PR #7 of 9)
**Plan.** `plan/02_observability.md` §PR #7
**Date.** 2026-04-20

---

## What changed

Backend — emit structured `delegation.sent` / `delegation.received`
events whenever a tagged delegation message crosses sessions:

- `backend/service/logging/session_logger.py` — new
  `log_delegation_event(event, details)` method. Thin wrapper
  over `self.log(LogLevel.INFO, ...)`; builds a human-readable
  message like `DELEGATION → [TAG] <peer-8char>…` and stores the
  full `{tag, from_session_id, to_session_id, from_role, to_role,
  task_id}` in metadata. Keys with `None` are stripped.

- `backend/service/vtuber/delegation.py` — new
  `parse_delegation_headers(text)` helper. Extracts the tag and
  the optional `From:` / `Task:` headers from a formatted
  delegation message. Returns `None` for non-delegation prompts,
  so callers can use it as a single gate.

- `backend/service/execution/agent_executor.py`
  - `_notify_linked_vtuber`: once the `[SUB_WORKER_RESULT]`
    content is built and before the fire-and-forget trigger is
    queued, emit `delegation.sent` on the Sub-Worker's logger.
    Carries both session ids, both roles (`role.value`), and the
    tag. Wrapped in its own try/except so a logger failure never
    breaks the auto-report path.
  - `_execute_core`: right after `log_command`, call
    `parse_delegation_headers(prompt)`. If the prompt is a
    delegation message, emit `delegation.received` on the
    receiver's logger with the tag, the `from_session_id` parsed
    from the header (if present), the current `session_id` as
    `to_session_id`, and the executor's already-resolved
    `log_role` as `to_role`. This catches both the
    Sub-Worker→VTuber path (mirrors the sender emit above) and
    the VTuber→Sub-Worker path (MCP-tool-driven, no backend
    sender hook).

Frontend — render the new events as a distinguishable row:

- `frontend/src/components/execution/LogEntryCard.tsx` — extended
  `getEntryDescription` to detect `metadata.event ===
  'delegation.sent' | 'delegation.received'` and render
  `"[TAG] → <peer-short> (task …)"`. The existing INFO icon +
  color still apply — no new icon mapping needed.

- `frontend/src/types/index.ts` — added the new optional fields
  (`event`, `tag`, `from_session_id`, `to_session_id`,
  `from_role`, `to_role`, `task_id`) to `LogEntryMetadata`. The
  catch-all already tolerated them; the explicit declarations
  give the card code type-safe access without casting.

## Why

Delegation is the hottest cross-session event on the system and,
until now, left no visible trace on either side's log. Operators
had to correlate timestamps + inbox state + prompt content to
reconstruct a single delegation hop. These two events make every
hop a single pair of `.log` entries: one arrow out, one arrow in,
matched by `task_id` (when the tag carries one) or by
`from_session_id`/`to_session_id` otherwise.

Only one of the two hooks is structural:

- The sender emit lives where we actually own the Sub-Worker →
  VTuber auto-report path (`_notify_linked_vtuber`).
- The receiver emit lives at `_execute_core` entry because any
  delegation message — whether it was sent by the backend
  auto-report or by the VTuber via MCP DM — enters the executor
  the same way: as a tagged prompt.

This double-anchored approach avoids needing backend hooks into
the MCP DM tool and still guarantees `delegation.received` fires
on the receiver side.

## Verification

1. `python3 -m py_compile` on all three backend files → OK.
2. Logger method added with the same signature pattern as
   `log_session_event`, so the existing DB-backed log sink picks
   it up without further plumbing (INFO level goes through the
   normal path).
3. `parse_delegation_headers` tolerates the SUB_WORKER_RESULT
   format that skips `From:` / `Task:` lines — returns a dict
   with just `{"tag": "[SUB_WORKER_RESULT]"}` in that case, so
   `_execute_core` still emits a usable receiver marker.
4. TypeScript surface: only optional additions; the catch-all
   already accepted them, so no regression risk.
5. Runtime flow that will be visible after next session:
   - Sub-Worker finishes → Sub-Worker's `.log` gets
     `delegation.sent [SUB_WORKER_RESULT] → <vtuber-short>`
   - VTuber's `_execute_core` consumes it → VTuber's `.log` gets
     `delegation.received [SUB_WORKER_RESULT] ← <sub-short>`
   - LogsTab renders both rows with the arrow + short peer id.

## Out of scope

- OpenTelemetry span bridging (noted in plan PR #7 "useful
  follow-ups").
- Persistent cross-session delegation index (same).
- Per-event icon (reusing INFO icon; distinguishable by the
  arrow in the rendered description is enough for now).
- Inbox-delivered delegation messages — they flow back through
  `execute_command` → `_execute_core`, so the receiver emit
  still fires.

## Rollback

Revert the three backend files and the two frontend files. The
events stop appearing on new logs; existing entries are
untouched. No consumer breaks because every new field and every
new event kind is additive.
