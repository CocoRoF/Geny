# Plan 01 — LogLevel.STAGE rename (PR-1)

**해결 대상.** `LogLevel.GRAPH` 및 관련 helper/frontend label을
`STAGE`로 정비. 데이터 손실 없이 전환 — 과거 DB의 `GRAPH` 행은
프론트엔드에서 동일한 시각처리로 계속 렌더된다.

## 1. 변경/신규 파일

| 파일 | 변경 종류 |
|---|---|
| `backend/service/logging/session_logger.py` | `LogLevel.STAGE` 추가, `log_stage_*` 헬퍼 추가, 기존 `log_graph_*`는 deprecated wrapper |
| `backend/service/langgraph/agent_session.py` | 변환부가 `log_stage_event` 호출 (2개 경로) |
| `backend/controller/chat_controller.py` | `_extract_thinking_preview`에 `STAGE` level 분기 추가 (`GRAPH` 분기도 유지) |
| `backend/tests/service/logging/test_stage_logging.py` | 신규 — LogLevel.STAGE 및 새 helper pin tests |
| `Geny/frontend/src/components/execution/LogEntryCard.tsx` | `LEVEL_CONFIG.STAGE` 추가, `getEntryDescription`에 STAGE 분기, `hasDetail` 배열에 `STAGE` 포함 |
| `Geny/frontend/src/lib/i18n/en.ts` | "Graph" → "Stage" 유저 대면 문자열 |
| `Geny/frontend/src/components/tabs/LogsTab.tsx` | 필터/라벨 |
| `Geny/frontend/src/components/execution/ExecutionTimeline.tsx` | 마커 |
| `Geny/frontend/src/components/execution/StepDetailPanel.tsx` | 상세 텍스트 |
| 프론트엔드 파일의 CSS/나머지 | 동일 패턴 |

## 2. 백엔드 설계

### 2.1. LogLevel enum

```python
class LogLevel(str, Enum):
    ...
    STAGE = "STAGE"   # geny-executor Stage transitions (preferred)
    GRAPH = "GRAPH"   # legacy alias — old DB rows still read this
    ...
```

- `STAGE`가 쓰기 표준. `GRAPH`는 **읽기만** 지원 (DB에 과거 값이
  남아 있을 때 deserialization 실패 방지용).
- 상단 docstring에 두 값의 역할 명시.

### 2.2. 신규 helper — `log_stage_*`

`log_graph_*`와 signature 동일. 내부에서 `LogLevel.STAGE`로 기록.

```python
def log_stage_event(
    self,
    event_type: str,
    message: str,
    stage_name: Optional[str] = None,
    stage_order: Optional[int] = None,
    stage_display_name: Optional[str] = None,
    iteration: Optional[int] = None,
    state_snapshot: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> str:
    event_id = str(uuid.uuid4())[:8]
    metadata = {
        "event_id": event_id,
        "event_type": event_type,
        "stage_name": stage_name,
        "stage_order": stage_order,
        "stage_display_name": stage_display_name,
        "iteration": iteration,
        # Back-compat — old DB rows and frontend expect node_name
        "node_name": stage_name,
        "state_snapshot": state_snapshot,
        "data": data,
    }
    metadata = {k: v for k, v in metadata.items() if v is not None}
    self.log(LogLevel.STAGE, message, metadata)
    return event_id


def log_stage_enter(
    self,
    stage_name: str,
    *,
    stage_order: Optional[int] = None,
    iteration: int = 0,
    state_summary: Optional[Dict[str, Any]] = None,
) -> str:
    display = f"s{stage_order:02d}_{stage_name}" if stage_order else stage_name
    message = f"→ {display} (iter {iteration})" if iteration else f"→ {display}"
    return self.log_stage_event(
        event_type="stage_enter",
        message=message,
        stage_name=stage_name,
        stage_order=stage_order,
        stage_display_name=display,
        iteration=iteration,
        state_snapshot=state_summary,
    )


def log_stage_exit(...)
def log_stage_bypass(...)   # new — for stage.bypass events
def log_stage_error(...)    # new — for stage.error events
def log_stage_execution_start(...)
def log_stage_execution_complete(...)
```

note: `event_type`이 `"node_enter"` → `"stage_enter"`로 바뀐다.
frontend에서 둘 다 허용하도록 수정 (다음 섹션).

### 2.3. 기존 `log_graph_*` 유지 (deprecated wrappers)

```python
def log_graph_event(self, *args, **kwargs):
    """DEPRECATED — use log_stage_event. Kept for outside callers."""
    return self.log_stage_event(*args, **kwargs)
```

외부 호출자가 있다면 계속 동작. 반환값도 동일. 단, 이 wrapper도
`LogLevel.STAGE`로 기록된다 — 새 UI 라벨을 따라가게 됨. 과거 DB
로딩 시 `"GRAPH"` 값은 `LogLevel("GRAPH")`로 읽히고 프론트엔드가
동등하게 렌더.

### 2.4. agent_session.py 변환부

```python
# Before (L1001-1014)
elif event_type == "stage.enter":
    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
    session_logger.log_graph_event(
        event_type="node_enter",
        message=f"→ {stage_name}",
        node_name=stage_name,
    )
elif event_type == "stage.exit":
    ...

# After (both _invoke_pipeline and _astream_pipeline)
elif event_type == "stage.enter":
    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
    iteration = event.iteration if hasattr(event, "iteration") else 0
    session_logger.log_stage_enter(
        stage_name=stage_name,
        stage_order=STAGE_ORDER.get(stage_name),
        iteration=iteration,
    )
elif event_type == "stage.exit":
    stage_name = event.stage if hasattr(event, "stage") else event_data.get("stage", "unknown")
    iteration = event.iteration if hasattr(event, "iteration") else 0
    session_logger.log_stage_exit(
        stage_name=stage_name,
        stage_order=STAGE_ORDER.get(stage_name),
        iteration=iteration,
    )
```

- `stage.bypass`와 `stage.error` 처리는 PR-2의 subject.
- `STAGE_ORDER` 상수는 session_logger 쪽에 정의하고 여기서 import.

### 2.5. `STAGE_ORDER` 상수

`backend/service/logging/session_logger.py` 상단:

```python
# Mirror of geny_executor.core.pipeline._DEFAULT_STAGE_NAMES.
# Duplicated because the executor treats the table as private;
# if the executor renames a stage the version bump will surface
# here via a failing test. Update in lockstep.
STAGE_ORDER: Dict[str, int] = {
    "input": 1, "context": 2, "system": 3, "guard": 4,
    "cache": 5, "api": 6, "token": 7, "think": 8,
    "parse": 9, "tool": 10, "agent": 11, "evaluate": 12,
    "loop": 13, "emit": 14, "memory": 15, "yield": 16,
}
```

공개 상수이므로 외부에서 import 가능 (e.g., agent_session.py).

### 2.6. chat_controller.py `_extract_thinking_preview`

`entry.level.value`는 `"STAGE"` 또는 `"GRAPH"`. 둘 다 지원:

```python
if level in ("STAGE", "GRAPH"):
    event_type = meta.get("event_type", "")
    display = meta.get("stage_display_name") or meta.get("node_name", "")
    iteration = meta.get("iteration")
    iter_suffix = f" (iter {iteration})" if iteration else ""
    if event_type in ("stage_enter", "node_enter") and display:
        return f"→ {display}{iter_suffix}"
    if event_type in ("stage_exit", "node_exit") and display:
        preview = meta.get("output_preview", "")[:60]
        if preview:
            return f"✓ {display}: {preview}"
        return f"✓ {display}{iter_suffix}"
    if event_type == "edge_decision":
        decision = meta.get("decision", "")
        return f"⋯ {decision}" if decision else None
    return None
```

## 3. 프론트엔드 설계

### 3.1. `LogEntryCard.tsx` (핵심)

```ts
// LEVEL_CONFIG
STAGE:     { icon: Zap, color: '#8b5cf6', bgColor: 'rgba(139,92,246,0.08)', label: 'Stage' },
GRAPH:     { icon: Zap, color: '#8b5cf6', bgColor: 'rgba(139,92,246,0.08)', label: 'Stage' },  // legacy rows → same visual
```

- 두 레벨이 동일 시각처리. 라벨 문자열만 `"Stage"`로 통일.

```ts
// getEntryDescription
if ((entry.level === 'STAGE' || entry.level === 'GRAPH') && meta?.event_type) {
    const display = meta.stage_display_name || meta.node_name || '';
    const iter = meta.iteration ? ` (iter ${meta.iteration})` : '';
    // new event_types (stage_*) + legacy (node_*)
    if (meta.event_type === 'stage_enter' || meta.event_type === 'node_enter')
        return `→ ${display}${iter}`;
    if (meta.event_type === 'stage_exit' || meta.event_type === 'node_exit')
        return `✓ ${display}${iter}`;
    if (meta.event_type === 'stage_bypass') return `⊘ ${display} (skipped)`;
    if (meta.event_type === 'stage_error') return `✗ ${display}: error`;
    return `${meta.event_type}${display ? `: ${display}` : ''}`;
}
```

```ts
// hasDetail
const hasDetail = [..., 'STAGE', 'GRAPH', ...].includes(entry.level);
```

### 3.2. 타입 정의

`LogEntryMetadata`(`frontend/src/lib/logs.ts` 또는 유사 위치)에
새 필드 선언:

```ts
interface LogEntryMetadata {
  ...
  stage_name?: string;
  stage_order?: number;
  stage_display_name?: string;
  iteration?: number;
  // legacy — still present on old rows
  node_name?: string;
  event_type?: string;
}
```

### 3.3. i18n / LogsTab / ExecutionTimeline / StepDetailPanel

- `en.ts`: "Graph events" 등 문구 → "Stage events" (있다면)
- `LogsTab.tsx`, `ExecutionTimeline.tsx`: 필터 옵션에 `STAGE`를 포함
  하고 legacy `GRAPH`는 같은 bucket으로 묶음
- `StepDetailPanel.tsx`: step 표시에 `stage_display_name` 우선 사용

## 4. 테스트

### 4.1. 백엔드 — `test_stage_logging.py`

```python
def test_loglevel_stage_and_graph_both_present():
    assert LogLevel.STAGE.value == "STAGE"
    assert LogLevel.GRAPH.value == "GRAPH"

def test_log_stage_enter_writes_stage_level():
    sl = SessionLogger("test-sid")
    sl.log_stage_enter(stage_name="yield", stage_order=16, iteration=3)
    entries = sl.get_cache_entries_since(0)
    assert entries[-1].level == LogLevel.STAGE
    assert entries[-1].metadata["stage_display_name"] == "s16_yield"
    assert entries[-1].metadata["iteration"] == 3

def test_legacy_log_graph_event_delegates_to_stage():
    # The old method name still works and writes at LogLevel.STAGE
    sl = SessionLogger("test-sid")
    sl.log_graph_event(event_type="node_enter", message="→ yield", node_name="yield")
    entries = sl.get_cache_entries_since(0)
    assert entries[-1].level == LogLevel.STAGE

def test_stage_order_table_matches_executor_names():
    from geny_executor.core.pipeline import Pipeline
    # Guardrail: if executor ever renames a stage this test fails
    # and forces an explicit lockstep update.
    assert set(STAGE_ORDER.keys()) == set(Pipeline._DEFAULT_STAGE_NAMES.values())
    for order, name in Pipeline._DEFAULT_STAGE_NAMES.items():
        assert STAGE_ORDER[name] == order
```

`test_stage_order_table_matches_executor_names`는 "private 이름
table에 의존"이라는 약점이 있으나, executor가 rename 하면 이
테스트가 명시적으로 깨지므로 drift가 소리 없이 일어날 수 없게 된다.

### 4.2. 프론트엔드 — 단위 테스트

`LogEntryCard.test.tsx` (혹은 기존 테스트 파일에 추가):

```tsx
test('renders STAGE level with Stage label', () => {
    const entry = { level: 'STAGE', metadata: { event_type: 'stage_enter', stage_display_name: 's16_yield' }, ... };
    render(<LogEntryCard entry={entry} />);
    expect(screen.getByText('Stage')).toBeInTheDocument();
    expect(screen.getByText(/s16_yield/)).toBeInTheDocument();
});

test('renders legacy GRAPH level with same Stage treatment', () => {
    const entry = { level: 'GRAPH', metadata: { event_type: 'node_enter', node_name: 'yield' }, ... };
    render(<LogEntryCard entry={entry} />);
    expect(screen.getByText('Stage')).toBeInTheDocument();
});
```

## 5. 롤아웃 리스크

- **DB 호환.** 과거 행은 `level = "GRAPH"`. `LogLevel("GRAPH")`
  enum lookup이 성공하므로 deserialization 문제 없음. 프론트엔드가
  두 값 모두 렌더.
- **외부 호출자.** Geny backend 외부(예: 테스트/스크립트)에서
  `LogLevel.GRAPH`를 쓰는 코드가 있으면 그대로 유효. `log_graph_*`
  메서드도 살아 있음 — 새 레벨로만 라우팅됨.
- **시각 변경.** 라벨이 "Graph"→"Stage"로 바뀌는 건 사용자 가시
  변경이지만 의도된 목표.

## 6. 커밋 + PR

- 브랜치: `feat/loglevel-stage-rename`
- 커밋 제목: `feat(logging): rename LogLevel.GRAPH → LogLevel.STAGE`
- PR 제목: 동일
