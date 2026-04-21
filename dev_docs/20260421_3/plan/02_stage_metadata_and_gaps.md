# Plan 02 — Stage metadata enrichment + silent-path closure (PR-2)

**전제.** PR-1 merged. `LogLevel.STAGE`와 `log_stage_*` 헬퍼 준비됨,
`STAGE_ORDER` 상수 사용 가능.

**해결 대상.**
1. 지금까지 Geny가 버리고 있던 executor 이벤트(`stage.bypass`,
   `stage.error`, `pipeline.start`, `pipeline.error`)를 로그 패널에
   노출.
2. stage log의 metadata에 `iteration`, `stage_order`,
   `stage_display_name`이 실제로 실려서 전송되도록 변환부 완성.
3. `logger.info()`로만 나가던 실행 이벤트(auto-revival, inbox
   delivery, DLQ, drain)를 `session_logger` 엔트리로 승격.

## 1. 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/service/langgraph/agent_session.py` | `stage.bypass`/`stage.error` 변환부 추가, pipeline lifecycle 이벤트 추가 |
| `backend/service/execution/agent_executor.py` | silent path 5곳을 session_logger로 승격 |
| `backend/tests/service/logging/test_stage_event_coverage.py` | 신규 — 이벤트 커버리지 회귀 테스트 |
| `backend/tests/service/execution/test_execution_logging_gaps.py` | 신규 — 승격된 silent path들이 session_logger 엔트리를 남기는지 확인 |
| `Geny/frontend/src/components/execution/LogEntryCard.tsx` | `stage_bypass`/`stage_error` 아이콘/텍스트 |

## 2. 변환부 — bypass/error 핸들러

`agent_session.py`의 `_invoke_pipeline` 와 `_astream_pipeline`
(두 곳 동일 패턴). PR-1에서 리팩터한 분기 바로 다음에 추가:

```python
elif event_type == "stage.bypass":
    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
    iteration = event.iteration if hasattr(event, "iteration") else 0
    session_logger.log_stage_bypass(
        stage_name=stage_name,
        stage_order=STAGE_ORDER.get(stage_name),
        iteration=iteration,
    )
elif event_type == "stage.error":
    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
    iteration = event.iteration if hasattr(event, "iteration") else 0
    err = event_data.get("error") or "unknown error"
    session_logger.log_stage_error(
        stage_name=stage_name,
        stage_order=STAGE_ORDER.get(stage_name),
        iteration=iteration,
        error=err,
    )
elif event_type == "pipeline.start":
    session_logger.log_stage_execution_start(
        input_text=input_text,
        thread_id=getattr(_state, "pipeline_id", None),
        execution_mode="invoke",  # or "astream" in astream path
    )
elif event_type == "pipeline.error":
    err = event_data.get("error") or "unknown"
    session_logger.log(LogLevel.ERROR, f"Pipeline error: {err}", metadata={"source": "pipeline"})
```

`pipeline.complete`는 이미 `_invoke_pipeline` 쪽에서 수집·집계되므로
별도 추가 로그는 불필요 — 기존 `log_stage_execution_complete`를 필요
시 직접 호출.

PR-1에서 만든 헬퍼 signature (draft — PR-1에서 확정):

```python
def log_stage_bypass(self, stage_name, *, stage_order=None, iteration=0, reason=None) -> str:
    display = f"s{stage_order:02d}_{stage_name}" if stage_order else stage_name
    message = f"⊘ {display} (skipped)"
    return self.log_stage_event(
        event_type="stage_bypass",
        message=message,
        stage_name=stage_name,
        stage_order=stage_order,
        stage_display_name=display,
        iteration=iteration,
        data={"reason": reason} if reason else None,
    )

def log_stage_error(self, stage_name, error, *, stage_order=None, iteration=0) -> str:
    display = f"s{stage_order:02d}_{stage_name}" if stage_order else stage_name
    message = f"✗ {display}: {error[:200]}"
    return self.log_stage_event(
        event_type="stage_error",
        message=message,
        stage_name=stage_name,
        stage_order=stage_order,
        stage_display_name=display,
        iteration=iteration,
        data={"error": error},
    )
```

## 3. Silent path 승격

`backend/service/execution/agent_executor.py`에서 `logger.*`만
호출하던 지점을 `session_logger` 진입점으로 보강. **기존 logger
호출은 유지** (stderr 관측 유지) + **추가로 session_logger** — 두
경로 병행.

### 3.1. Auto-revival

L461-467 근처:

```python
if revived:
    logger.info("Auto-revived agent %s", session_id)
    # NEW — visible in log panel
    sl = _get_session_logger(session_id, create_if_missing=False)
    if sl is not None:
        sl.log(
            level=LogLevel.INFO,
            message=f"Agent auto-revived after inactivity",
            metadata={"event": "auto_revival", "session_id": session_id},
        )
```

### 3.2. Inbox delivery on busy VTuber

`_notify_linked_vtuber._trigger_vtuber` L205-240. `AlreadyExecutingError`
분기:

```python
except AlreadyExecutingError:
    try:
        from service.chat.inbox import get_inbox_manager
        inbox = get_inbox_manager()
        inbox.deliver(
            target_session_id=linked_id,
            content=content,
            sender_session_id=session_id,
            sender_name="Sub-Worker",
        )
        logger.info("VTuber %s busy — SUB_WORKER_RESULT stored in inbox", linked_id)
        # NEW — sender-side log entry so UI panel shows the reason for delay
        sender_sl = _get_session_logger(session_id, create_if_missing=False)
        if sender_sl:
            sender_sl.log(
                level=LogLevel.INFO,
                message="Recipient busy — message queued to inbox",
                metadata={
                    "event": "inbox.delivered",
                    "to_session_id": linked_id,
                    "tag": "[SUB_WORKER_RESULT]",
                },
            )
    except Exception as inbox_err:
        # ... existing DLQ fallback + logger.warning
        # NEW session_logger entry at WARNING level
```

동일 패턴으로 DLQ fallback (L226-240) 및 DLQ-failed 경로에도 추가.

### 3.3. Inbox drain

`_drain_inbox` L818-883에서:
- 시작 시: `log(INFO, "Draining inbox: N queued messages")`
- 각 item 처리 완료: `log(INFO, "Replayed inbox message from {sender}")`
- 실패: `log(WARNING, "Inbox drain item failed: {error}")`
- 종료: `log(INFO, "Drain complete: {n_ok} ok, {n_err} failed")`

## 4. 테스트

### 4.1. `test_stage_event_coverage.py`

```python
@pytest.mark.asyncio
async def test_stage_bypass_produces_log_entry():
    session, sl = _make_session_with_scripted_events([
        _FakeEvent("stage.bypass", {}, stage="cache", iteration=0),
        _FakeEvent("pipeline.complete", {"result": "", "total_cost_usd": 0, "iterations": 0}),
    ])
    session._session_logger = sl
    await session._invoke_pipeline("hi", start_time=0.0, session_logger=sl)
    bypass_entries = [e for e in sl.get_cache_entries_since(0) if e.metadata.get("event_type") == "stage_bypass"]
    assert len(bypass_entries) == 1
    assert bypass_entries[0].metadata["stage_name"] == "cache"
    assert bypass_entries[0].metadata["stage_order"] == 5


@pytest.mark.asyncio
async def test_stage_error_produces_log_entry():
    session, sl = _make_session_with_scripted_events([
        _FakeEvent("stage.error", {"error": "boom"}, stage="tool", iteration=2),
        ...
    ])
    ...
    assert entries[-1].metadata["stage_name"] == "tool"
    assert entries[-1].metadata["data"]["error"] == "boom"


@pytest.mark.asyncio
async def test_stage_enter_includes_order_and_iteration():
    session, sl = _make_session_with_scripted_events([
        _FakeEvent("stage.enter", {}, stage="yield", iteration=4),
        ...
    ])
    ...
    assert entries[-1].metadata["stage_order"] == 16
    assert entries[-1].metadata["stage_display_name"] == "s16_yield"
    assert entries[-1].metadata["iteration"] == 4
```

`_FakeEvent`는 기존 cycle 20260421_1 테스트 파일의 fake에 `stage`/
`iteration` 필드 추가.

### 4.2. `test_execution_logging_gaps.py`

```python
def test_auto_revival_emits_session_log_entry(monkeypatch):
    # Arrange: session that is not alive, _ensure_alive_or_revive
    # returns revived=True.
    # Act: _ensure_alive_or_revive(session_id)
    # Assert: session_logger has an entry with metadata.event == "auto_revival"

def test_inbox_delivery_on_busy_logs_sender_side_entry(monkeypatch):
    # Arrange: AlreadyExecutingError path in _notify_linked_vtuber
    # Assert: sender's session_logger has entry with event == "inbox.delivered"

def test_drain_start_and_complete_log_entries():
    # Arrange: 2 queued messages, scripted successful drain.
    # Act: _drain_inbox
    # Assert: entries include "Draining inbox: 2 queued" and "Drain complete: 2 ok, 0 failed"
```

## 5. Frontend (작은 추가)

`LogEntryCard.tsx` `getEntryDescription`에 PR-1에서 이미
stage_bypass/stage_error 분기를 넣음. 아이콘 선택만 개선:

```ts
// 이벤트 타입별 color override (optional)
// stage_bypass → muted grey text
// stage_error  → red text
```

`inbox.delivered`, `auto_revival`, `inbox.drain.*` 같은 INFO-level
이벤트는 메시지 그대로 렌더 (이미 line 127-129 분기가 INFO/DEBUG를
처리).

## 6. 검증

- `pytest backend/tests -q` — 신규 + 기존 green.
- 수동 smoke — analysis/01 § 8의 4-step scenario.

## 7. 롤아웃 리스크

- **로그 볼륨 증가.** Drain이 많이 일어나는 세션에서는 전보다
  10–30% 엔트리 증가 가능. 성능 영향 무시 가능 (session_logger는
  이미 batch/async write).
- **Bypass 노이즈.** `stage.bypass`는 항상 발생하는 slot-empty
  경우도 있어 패널이 지저분해질 수 있음. 경험상 15~16개 stage 중
  미등록 slot이 약 3~4개 (cache, think 등) — 세션당 평균 6~8
  bypass 엔트리. 필요 시 프론트엔드에서 `stage_bypass`만 접어두는
  토글 (follow-up).

## 8. 커밋 + PR

- 브랜치: `feat/stage-metadata-and-gap-closure`
- 커밋 제목: `feat(logging): surface stage metadata + bypass/error + silent paths`
- PR 제목: 동일
