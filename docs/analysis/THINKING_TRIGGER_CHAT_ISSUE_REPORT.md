# ThinkingTrigger → Chat Room Message Delivery Issue Report

**Date**: 2026-03-31
**Status**: Root Cause Identified — Fix Required

---

## 1. Problem Statement

The VTuber session's ThinkingTrigger fires every ~2 minutes when idle, sending
`[THINKING_TRIGGER]` prompts to the agent. The agent responds (visible in
**Session Logs** as `[neutral] *...*` with duration ~10–14s), but these responses
**never appear** in:

- The **VTuber tab chat panel** (`VTuberChatPanel`)
- The **Messenger chat room** (Geny Chat → "tata Chat")

---

## 2. Architecture Overview

```
ThinkingTrigger._loop()
    │
    ▼
_fire_trigger(session_id)
    │
    ├─ execute_command(session_id, prompt)   ← agent runs, returns ExecutionResult
    │       │
    │       ├─ _execute_core()               ← logs to SessionLogger (shows in Logs tab)
    │       ├─ _emit_avatar_state()          ← updates Live2D emotion (read-only)
    │       └─ _notify_linked_vtuber()       ← only for CLI sessions (N/A here)
    │
    └─ _save_to_chat_room(session_id, result)  ← NEW CODE (should save to DB + SSE)
            │
            ├─ store.add_message()           ← persist to Chat Room DB
            └─ _notify_room()               ← signal SSE listeners
```

**The working broadcast flow** (Messenger → user sends message):
```
POST /api/chat/rooms/{room_id}/broadcast
    │
    └─ _run_broadcast → _invoke_one(session_id)
            │
            ├─ execute_command(session_id, prompt, is_chat_message=True)
            └─ store.add_message(room_id, {...})   ← EXPLICIT save (same pattern)
                └─ _notify_room(room_id)
```

Both flows use the identical save pattern:
`execute_command() → check result.success → store.add_message() → _notify_room()`

---

## 3. Root Cause Analysis

### Primary Cause: Backend Not Restarted After Code Changes

The `_save_to_chat_room()` method and the modified `_fire_trigger()` logic were
added to `thinking_trigger.py` **but the backend process was never restarted**.

**Evidence**:
- Session Logs show ThinkingTrigger responses accumulating (old code is running)
- No `[ThinkingTrigger]` prefixed WARNING/INFO logs appear anywhere (new logging
  format was added but not loaded)
- Chat room DB has only the initial user interaction (3 messages), confirming
  `store.add_message()` was never called for trigger responses

### Secondary Risk: `_chat_room_id` May Be `None` on Restored Sessions

When the backend restarts and sessions are restored, `_chat_room_id` is restored
from the session store in `agent_controller.py:405-407`:

```python
stored_chat_room_id = params.get("chat_room_id")
if stored_chat_room_id:
    agent._chat_room_id = stored_chat_room_id
```

However, the `ThinkingTriggerService.record_activity()` is only called:
1. During initial VTuber session creation (`agent_session_manager.py:593`)
2. Inside `execute_command()` when `_session_type == 'vtuber'` (`agent_executor.py:505`)

**After a backend restart**, if the restored session doesn't trigger any user
interaction, the ThinkingTrigger won't fire at all because `record_activity()`
is never called → the session is not in `self._activity` dict.

This is actually a **separate issue** but worth noting.

### Tertiary Risk: Error Silencing at `debug` Level

The original `_save_to_chat_room` used `logger.debug()` for all failures. If any
exception occurred (e.g., circular import, missing store), it would be invisible
in standard log output. This has been upgraded to `logger.warning()` in the
latest code changes.

---

## 4. Data Flow Verification

| Step | Component | Status |
|------|-----------|--------|
| 1. Idle detection | `ThinkingTriggerService._loop()` | ✅ Working (fires every ~2min) |
| 2. Prompt selection | `_build_trigger_prompt()` | ✅ Working (varied prompts visible in logs) |
| 3. Agent execution | `execute_command()` | ✅ Working (responses in Session Logs with durations) |
| 4. Result check | `result.success and result.output.strip()` | ⚠️ Likely True (output = `[neutral] *...*`) |
| 5. Chat room save | `_save_to_chat_room()` | ❌ **Never called** (old code loaded) |
| 6. SSE notification | `_notify_room()` | ❌ Never reached |
| 7. Frontend SSE | `VTuberChatPanel` EventSource | ✅ Connected (shows initial messages) |
| 8. Messenger SSE | Chat room EventSource | ✅ Connected (shows initial messages) |

---

## 5. Resolution Plan

### Step 1: Restart Backend (Immediate — Required)

The most critical action. The new `_save_to_chat_room()` code and upgraded
logging are already written but not loaded by the running process.

```bash
# Restart the backend server
# (docker-compose restart backend, or kill & re-run uvicorn)
```

After restart, verify in logs:
- `Thinking trigger fired for <id> (output=XX chars, saved to chat)` → Working
- `[ThinkingTrigger] No chat_room_id on agent <id>` → Need Step 2
- `[ThinkingTrigger] Failed to save trigger response` → Exception details visible

### Step 2: Ensure `_chat_room_id` Survives Restart

If logs show "No chat_room_id", the ThinkingTrigger needs to register the
session AND the session needs its `_chat_room_id` restored.

**Current code already handles this** in `agent_controller.py:405-407`, but we
should verify the session store actually has `chat_room_id` persisted.

### Step 3: Re-register ThinkingTrigger on Session Restore

After backend restart, restored VTuber sessions may not be registered with
ThinkingTrigger. The `record_activity()` is called inside `execute_command()`,
so the first user interaction will register it. But if no user interaction
happens, the trigger won't fire.

**Recommended fix**: Add ThinkingTrigger re-registration during session restore
in `agent_controller.py`'s restore endpoint:

```python
# After restoring _chat_room_id
if agent._session_type == 'vtuber':
    try:
        from service.vtuber.thinking_trigger import get_thinking_trigger_service
        get_thinking_trigger_service().record_activity(session_id)
    except Exception:
        pass
```

### Step 4: Verify End-to-End

1. Restart backend
2. Create new VTuber session (or restore existing one + send a message)
3. Wait 2+ minutes for ThinkingTrigger to fire
4. Check logs for `[ThinkingTrigger] Saved response to chat room`
5. Check VTuber chat panel — new message should appear
6. Check Messenger chat room — same message should appear

---

## 6. Code Status

| File | Change | Status |
|------|--------|--------|
| `backend/service/vtuber/thinking_trigger.py` | `_save_to_chat_room()` method | ✅ Written, not loaded |
| `backend/service/vtuber/thinking_trigger.py` | Enhanced logging (WARNING level) | ✅ Written, not loaded |
| `backend/service/vtuber/thinking_trigger.py` | `_fire_trigger()` result-aware logging | ✅ Written, not loaded |

**No additional code changes needed** for the primary fix. The code is correct
and mirrors the working broadcast pattern exactly. Only a backend restart is
required.

---

## 7. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Backend not restarted | **HIGH** | Full feature broken | Restart immediately |
| `_chat_room_id` None after restore | MEDIUM | Trigger fires but doesn't save | Step 3 fix |
| Circular import from controller | LOW | `_notify_room` import fails | Already wrapped in try/except |
| `result.output` empty/whitespace | LOW | Skipped by condition check | Logged at INFO level |
| SSE event not received by frontend | LOW | Delay until next poll/reconnect | Auto-reconnect in 3s |
