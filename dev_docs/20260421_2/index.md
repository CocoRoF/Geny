# Cycle 20260421_2 — Special-tag display sanitization

**Date.** 2026-04-21
**Trigger.** User report: VTuber chat and sub-worker replies
regularly leak bracketed tags (`[joy]`, `[surprise]`, `[smirk]`,
`[SUB_WORKER_RESULT]`, `[THINKING_TRIGGER]`) into the rendered
chat — literal text instead of being consumed by avatar / routing
layers. Example payload:

```
[SUB_WORKER_RESULT] 워케에게서 답장이 왔어요! [joy]

워커가 정말 친근하게 인사해주네요~ [surprise]
```

Users see the brackets verbatim.

## Bug summary

`sanitize_tts_text` in `backend/controller/tts_controller.py` already
has the right regex set (routing prefixes + emotion tags +
`<think>` blocks) but it's wired only to the TTS endpoint. Every
chat-room write path stores `result.output.strip()` raw:

| # | Sink | File:line | Fires when |
|---|---|---|---|
| 1 | User-facing broadcast reply | `backend/controller/chat_controller.py:671` | User sends a message → VTuber replies |
| 2 | Sub-Worker → VTuber auto-report | `backend/service/execution/agent_executor.py:928` | Sub-worker finishes → VTuber narrates |
| 3 | Inbox drain result | `backend/service/execution/agent_executor.py:983` | VTuber was busy → reprocesses queued DM |
| 4 | Thinking-trigger output | `backend/service/vtuber/thinking_trigger.py:743` | Idle timer fires → VTuber speaks |
| 5 | Live streaming tokens | `backend/controller/chat_controller.py:607-609` | Accumulated `streaming_text` broadcast to SSE |

## Scope

- **In:** Central standalone sanitizer module. Wire into all 5
  display sinks. Refactor `sanitize_tts_text` to delegate. Unit
  tests + per-sink regression tests.
- **Out:** STM content (already role-classified correctly; tags
  inside stored turns don't hurt retrieval). Avatar emotion
  extraction (uses `EmotionExtractor` separately). Agent-to-agent
  DM body — not rendered user-visible anywhere.

## PR plan

| PR | Branch | Scope |
|---|---|---|
| PR-1 | `feat/display-text-sanitizer` | New `service/utils/text_sanitizer.py` with `sanitize_for_display()`; refactor `sanitize_tts_text` to delegate; unit tests |
| PR-2 | `feat/wire-sanitizer-into-display-sinks` | Call `sanitize_for_display` at the 5 sinks; regression tests per sink |
| PR-3 | `docs/cycle-20260421_2-sanitizer` | Analysis + plan + progress |

Merge order: PR-1 → PR-2 → PR-3. PR-2 depends on PR-1's helper.

## Documents

- [analysis/01_tag_leak_inventory.md](analysis/01_tag_leak_inventory.md) — full sink trace + root cause
- [plan/01_central_sanitizer_module.md](plan/01_central_sanitizer_module.md) — PR-1 design
- [plan/02_wire_sinks.md](plan/02_wire_sinks.md) — PR-2 design
- [progress/01_prs_opened.md](progress/01_prs_opened.md) — PR board (after open)
