# Analysis 01 — Tag leak inventory & root cause

## 1. Symptom

VTuber chat renders bracketed control-text verbatim. Real user
report (sub-worker → VTuber reply rendered in the chat panel):

```
[SUB_WORKER_RESULT] 워케에게서 답장이 왔어요! [joy]

워커가 정말 친근하게 인사해주네요~ [surprise]

워케가 오늘 제가 어떤 일정이나 작업이 있는지 궁금해하네요. [smirk]
```

User also reports the same leak happening in the main VTuber chat
(direct user-message → VTuber-reply flow), not only the sub-worker
auto-report path. Inventory below confirms both.

## 2. Tag taxonomy (what should be stripped)

Two disjoint categories of tags appear inside VTuber LLM output and
must never reach the rendered chat:

### 2.1. Routing / system prefixes

Already enumerated in `backend/controller/tts_controller.py:42-54`
(`_SYSTEM_TAG_PATTERN`):

- `[THINKING_TRIGGER]`, `[THINKING_TRIGGER:<name>]`
- `[ACTIVITY_TRIGGER]`, `[ACTIVITY_TRIGGER:<name>]`
- `[SUB_WORKER_RESULT]`, `[CLI_RESULT]` (legacy alias)
- `[DELEGATION_REQUEST]`, `[DELEGATION_RESULT]`
- `[autonomous_signal:<payload>]`
- `[SILENT]`

These enter VTuber input as protocol tags; the LLM often echoes
them into its own output. That echo leaks to display.

### 2.2. Emotion tags

Enumerated at `tts_controller.py:56-61` (`_EMOTION_TAGS`, 21
labels): `neutral`, `joy`, `anger`, `disgust`, `fear`, `smirk`,
`sadness`, `surprise`, `warmth`, `curious`, `calm`, `excited`,
`shy`, `proud`, `grateful`, `playful`, `confident`, `thoughtful`,
`concerned`, `amused`, `tender`.

Deliberately emitted by the VTuber LLM per
`backend/prompts/vtuber.md:5`. Consumed by the avatar layer
(`agent_executor.py:109-130` `_emit_avatar_state`) via
`EmotionExtractor.resolve_emotion(...)`. **But** the emotion-
extraction step does not mutate the chat-room payload; it reads
the output string and pushes an avatar update. The string itself
— with tags still inside — continues on to the chat-room store.

### 2.3. `<think>...</think>` blocks

Some reasoning models emit these; `sanitize_tts_text` already
strips them for TTS (`_THINK_BLOCK_PATTERN`, `_THINK_OPEN_PATTERN`
at lines 67-68). Same treatment needed for chat display.

## 3. Sink inventory

Every place where raw agent output reaches a user-visible surface.
The first four are persistent chat-room writes; the fifth is a
live SSE stream of tokens-in-flight.

### 3.1. Sink #1 — user-message broadcast reply

`backend/controller/chat_controller.py:668-684` in the broadcast
loop of `POST /chat/rooms/{room_id}/broadcast`:

```python
if result.success and result.output and result.output.strip():
    msg_data: Dict[str, Any] = {
        "type": "agent",
        "content": result.output.strip(),   # ← raw
        ...
    }
    store.add_message(room_id, msg_data)
    _notify_room(room_id)
```

This is the **primary** path the user flagged. When a human user
sends a message to a VTuber in a chat room, the VTuber's reply
goes through here. If the reply starts with `[joy] 안녕하세요` the
frontend sees `[joy] 안녕하세요` literally.

### 3.2. Sink #2 — sub-worker reply auto-broadcast

`backend/service/execution/agent_executor.py:926-935` in
`_save_subworker_reply_to_chat_room`, invoked from
`_notify_linked_vtuber` after the VTuber responds to a
`[SUB_WORKER_RESULT]` trigger (see agent_executor.py:254). Stores
`result.output.strip()` raw. This is the path that produced the
exact payload quoted in § 1.

### 3.3. Sink #3 — inbox drain result

`backend/service/execution/agent_executor.py:981-989` in
`_save_drain_to_chat_room`. Fires when a DM queued while the
VTuber was busy is finally drained (cycle 20260421_1 PR-1 made
sure STM classification works; display sanitization is orthogonal
and was not in that cycle's scope). Same raw-write pattern.

### 3.4. Sink #4 — thinking-trigger output

`backend/service/vtuber/thinking_trigger.py:741-749` in
`ThinkingTriggerService._save_to_chat_room`. Idle timer fires →
VTuber speaks spontaneously → response lands here with tags
intact.

### 3.5. Sink #5 — live streaming tokens (`agent_progress` event)

`backend/controller/chat_controller.py:606-612`:

```python
if level == "STREAM":
    agent_state.streaming_text = (
        (agent_state.streaming_text or "") + (entry.message or "")
    )
```

The accumulated `streaming_text` is pushed to the frontend in the
`agent_progress` SSE event (via `_build_agent_progress_data`,
line 154). Tokens flow token-by-token, so a tag like `[joy]` may
arrive across two token boundaries (`[j` + `oy]`). A naive
per-token strip is incorrect; the right move is to sanitize the
**accumulated** string on each emission — the regex `sub` over
the whole string correctly strips complete tags and leaves a
partial tag in place until the next token completes it. Brief
mid-token flicker is acceptable and invisible in practice.

## 4. Why it was missed

Cycle 20260420_8 addressed STM role classification (input side) —
ensuring that internal triggers / sub-worker results land under
the right STM role. Cycle 20260421_1 fixed DM continuity gaps
(drain classifier + sender-side STM record). Neither cycle
touched **output-side display sanitization** because the bugs
reported at the time were about memory/continuity, not
rendering. The TTS sanitizer was quietly doing the same work for
the audio output but was never lifted into the display pipeline.

## 5. Non-scope / confirmed safe

- **STM content.** Tags inside stored turns don't impair role
  classification (role is decided at write-time from the *input*
  prefix) and retrieval layers treat the body as opaque.
  Stripping inside STM would risk losing debugging context and
  doesn't fix any user-visible issue.
- **Agent-to-agent DM body.** `_record_dm_on_sender_stm` and the
  recipient-side `[SYSTEM] You received a direct message` prompt
  both live in STM, not in the chat room. No display leak here.
- **Avatar emission path.** `_emit_avatar_state` runs on
  `result.output` directly via `EmotionExtractor`; it needs the
  raw text to extract emotions. This path must stay untouched.

## 6. Verification plan (post-merge)

1. Start a VTuber session bound to a Sub-Worker.
2. Send "안녕!" from the user. Confirm the rendered reply shows
   no `[joy]`/`[surprise]` and no `<think>` residue.
3. Send a DM-inducing request so the Sub-Worker replies. Confirm
   the auto-report broadcast shows **neither** `[SUB_WORKER_RESULT]`
   **nor** embedded emotion tags.
4. Wait ~2 min for `THINKING_TRIGGER:*` to fire. Confirm the
   spontaneous response is likewise clean.
5. During any of steps 2-4, watch the live streaming progress
   panel: no full `[joy]` should linger on screen (partial
   mid-token bracket briefly visible is OK).
