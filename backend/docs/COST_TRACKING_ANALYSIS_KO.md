# Geny 플랫폼 — 비용 및 세션 로깅 흐름 레퍼런스

> 작성일 2026-03-21 · 비용 데이터 및 세션 로깅의 엔드투엔드 추적

---

## 1. 비용 데이터 원천

**궁극적 소스:** Claude CLI. `--output-format stream-json` 옵션으로 실행하면
Claude CLI가 최종 JSON 이벤트를 출력합니다:

```json
{"type": "result", "total_cost_usd": 0.003421, "duration_ms": 9234, ...}
```

호출당 비용은 CLI 자체에서 토큰 사용량과 모델 가격을 기반으로 계산됩니다.

---

## 2. StreamParser — 첫 번째 추출 지점

**파일:** `service/claude_manager/stream_parser.py`

### StreamEvent (dataclass)
```python
@dataclass
class StreamEvent:
    total_cost_usd: Optional[float] = None  # result 이벤트에서 추출
    ...
```

### ExecutionSummary (dataclass)
```python
@dataclass
class ExecutionSummary:
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    tool_calls: List[Dict] = field(default_factory=list)
    usage: Dict = field(default_factory=dict)
    model: str = ""
    final_output: str = ""
    ...
```

### 파싱 체인:
```
_parse_result(data) → StreamEvent(total_cost_usd=data["total_cost_usd"])
_update_summary(event) → self.summary.total_cost_usd = event.total_cost_usd
```

---

## 3. ProcessManager — 비용 전파 허브

**파일:** `service/claude_manager/process_manager.py`

### execute() 메서드
`stream_parser.get_summary()` 호출 후, 결과 딕셔너리를 반환합니다:

```python
return {
    "success": True,
    "output": summary.final_output,
    "cost_usd": summary.total_cost_usd,     # ← 여기
    "duration_ms": duration_ms,
    "tool_calls": summary.tool_calls,
    "num_turns": summary.num_turns,
    "usage": summary.usage,
    "model": summary.model,
    "execution_count": self._execution_count,
    ...
}
```

### execute()의 부수 효과:
1. **터미널에 비용 로그**: `Cost: ${summary.total_cost_usd:.6f}`
2. **WORK_LOG.md 기록:** `_append_work_log(cost_usd=summary.total_cost_usd)`
3. **결과 딕셔너리에 비용 반환** (호출자에게)

---

## 4. WORK_LOG.md — 파일 기반 비용 기록

**파일:** `{storage_path}/WORK_LOG.md`

`ProcessManager._append_work_log()`에 의해 작성됩니다. 형식:

```markdown
# Work Log - Session {session_id}
**Session Name:** {name}
**Created:** {ISO timestamp}
**Model:** {model}

---
## [✅] Execution #1 — 2026-03-21 10:51:51
**Duration:** 9234ms
**Cost:** $0.030541

### Prompt
```
{prompt_preview}
```

### Output
```
{output_preview}
```
```

**핵심 제약:** 비용이 마크다운 텍스트로 기록됩니다. 집계 기능 없음.
각 실행마다 새 항목이 추가되며, 파일은 무한히 커집니다.

---

## 5. 세 가지 실행 경로 — 비용 전파 분석

### 경로 1: Claude Controller (직접 CLI 실행)
**파일:** `controller/claude_controller.py`

```
사용자 → POST /api/claude/{id}/execute
       → ProcessManager.execute()
       → result["cost_usd"] = X.XX  ✅ 전파됨
       → ExecuteResponse(cost_usd=X.XX) → 프론트엔드  ✅
```

**상태:** 비용이 완전히 전파됨.

### 경로 2: Command Controller (배치/브로드캐스트)
**파일:** `controller/command_controller.py`

```
사용자 → POST /api/commands/batch
       → ProcessManager.execute()
       → result["cost_usd"] = X.XX  ✅
       → session_logger.log_response(cost_usd=X.XX)  ✅ 메타데이터에 기록
       → BatchCommandResult → 프론트엔드  ❌ 응답 모델에 비용 없음
```

**상태:** 비용이 로깅되지만 프론트엔드에 반환되지 않음.

### 경로 3: Agent Controller (그래프 실행) ⚠️ 결손
**파일:** `controller/agent_controller.py`

```
사용자 → POST /api/agents/{id}/execute/start
       → agent.invoke(input_text=prompt)
         → AgentSession.invoke()
           → graph.ainvoke(initial_state)
             → Node.execute() → context.resilient_invoke()
               → ClaudeCLIChatModel._agenerate()
                 → ProcessManager.execute() → cost_usd 사용 가능 ✅
                 → AIMessage(additional_kwargs={...})  ❌ 비용 미포함
               → Node가 상태 업데이트 반환 (비용 필드 없음)
             → 최종 상태 (AutonomousState) — 비용 필드 없음 ❌
           → 텍스트만 반환 (final_answer | answer | last_output) ❌
       → result_text (문자열, 비용 없음) ❌
       → session_logger.log_response(cost_usd=None) ❌
       → ExecuteResponse(cost_usd=None) → 프론트엔드 ❌
```

**상태:** 비용이 여러 지점에서 유실됨:
1. `ClaudeCLIChatModel._agenerate()`가 결과 딕셔너리에서 `cost_usd`를 누락
2. `AutonomousState`에 비용 관련 필드가 없음
3. `AgentSession.invoke()`가 텍스트만 반환
4. `agent_controller._run()`이 비용을 전달받지 못함

---

## 6. ClaudeCLIChatModel — 비용이 누락되는 지점

**파일:** `service/langgraph/claude_cli_model.py`

`_agenerate()` 메서드는 `self._process.execute()`를 호출하며 결과에
`cost_usd`가 포함됩니다. 하지만 AIMessage에는 다음 항목만 포함:

```python
additional_kwargs = {
    "execution_count": result.get("execution_count", 0),
    "duration_ms": result.get("duration_ms", 0),
    "session_id": self._process.session_id,
    "conversation_id": self._process._conversation_id,
    # ❌ "cost_usd" 미포함
    # ❌ "tool_calls" 미포함
    # ❌ "usage" 미포함
}
```

**수정 필요:** `additional_kwargs`에 `cost_usd`, `tool_calls`, `usage` 포함.

---

## 7. AutonomousState — 비용 추적 기능 없음

**파일:** `service/langgraph/state.py`

`AutonomousState` TypedDict에는 **비용 관련 필드가 전혀 없습니다**:
- `total_cost` 누적기 없음
- 반복당 비용 추적기 없음
- 비용 리듀서 함수 없음

그래프 실행 중 각 노드가 LLM을 호출하고 비용이 발생하지만,
상태 머신에서 비용은 보이지 않습니다.

---

## 8. SessionLogger — 메타데이터 내 비용

**파일:** `service/logging/session_logger.py`

### log_response()
RESPONSE 레벨 로그 항목의 메타데이터에 `cost_usd`를 기록합니다:
```python
metadata = {
    "type": "response",
    "cost_usd": cost_usd,      # ← 호출자로부터
    "duration_ms": duration_ms,
    ...
}
```

### log_iteration_complete()
`cost_usd` 파라미터가 있지만, 코드베이스 어디에서도 **호출되지 않음**.
데드 코드입니다.

### log_stream_event()
`event_type == "result"`인 경우:
```python
cost = data.get("total_cost_usd", 0)
preview = f"Duration: {duration}ms, Cost: ${cost:.6f}"
```
로그 내 표시 전용.

### 저장소:
- 인메모리 `_log_cache` (휘발성, 최대 1000개 항목)
- 파일: `logs/{session_id}.log`
- DB: `session_logs` 테이블 (`db_insert_log_entry` 통한 최선 노력)

---

## 9. Memory Manager — 비용 미기록
