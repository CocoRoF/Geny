# Cycle 20260421_2 — PR board

**Date.** 2026-04-21

Three-PR sequence for the display sanitizer. Merge in order
(PR-1 → PR-2 → PR-3); PR-2 stacks on PR-1's branch because the sink
wiring imports the module PR-1 creates.

| PR | Branch | Status | Scope |
|---|---|---|---|
| [#199](https://github.com/CocoRoF/Geny/pull/199) | `feat/display-text-sanitizer` | open | New `service/utils/text_sanitizer.py` + `sanitize_for_display()`; `sanitize_tts_text` becomes a delegation shim; ~60 parametrized pytest cases |
| [#200](https://github.com/CocoRoF/Geny/pull/200) | `feat/wire-sanitizer-into-display-sinks` | open (base = #199) | Wire sanitizer into all 5 display sinks + regression tests per sink + token-boundary streaming test |
| #201 (this PR) | `docs/cycle-20260421_2-sanitizer` | open | Analysis, plans, this progress note |

## Sinks covered in PR-2

1. `chat_controller` broadcast reply — final user-facing agent turn
2. `agent_executor._save_subworker_reply_to_chat_room` — sub-worker → VTuber auto-report
3. `agent_executor._save_drain_to_chat_room` — inbox drain replay
4. `thinking_trigger._save_to_chat_room` — idle-trigger responses
5. `chat_controller._poll_logs` STREAM branch — live streaming accumulator (uses raw + sanitized view so partial tags across chunks survive)

## Follow-ups (out of scope for this cycle)

- Frontend toggle to collapse `stage_bypass` noise (tracked under cycle 20260421_3 rollout risks).
- Optional `(empty)` placeholder when sanitization collapses an entire turn — currently just dropped. Cycle can revisit if users report "agent went silent" without cause.

## Verification plan

- `pytest backend/tests/service/utils/test_text_sanitizer.py -q` (PR-1)
- `pytest backend/tests/controller/test_chat_broadcast_sanitize.py backend/tests/service/execution/test_agent_executor_sanitize.py backend/tests/service/vtuber/test_thinking_trigger_sanitize.py -q` (PR-2)
- Manual smoke: broadcast a message that triggers an emotion-tagged reply; confirm chat renders cleaned text, avatar still reacts, TTS still strips identically.
