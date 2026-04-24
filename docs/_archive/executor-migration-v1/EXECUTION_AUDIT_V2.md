# Geny 실행 로직 심층 검토 v2

> Date: 2026-04-14
> 대상: Phase A/B/C 수정 후 전체 실행 체인 재검증

---

## 1. 실행 체인 검증

### 1.1 session_id 전달 체인 — ✅ 정상

```
AgentSession._session_id
  → PipelineState(session_id=self._session_id)   [agent_session.py:834]
    → ToolStage.execute(): ToolContext(session_id=state.session_id)  [stage.py:69]
      → _GenyToolAdapter.execute(): input.setdefault("session_id", ctx.session_id)  [tool_bridge.py:116]
        → memory_search(session_id="abc-123")  ✅
```

### 1.2 working_dir 전달 체인 — ❌ 끊김

```
AgentSession._working_dir → working_dir 계산  [agent_session.py:666]
  → ToolContext(working_dir=working_dir) 생성  [agent_session.py:693]
    → self._tool_context = tool_context  [agent_session.py:737]
      → ❌ 여기서 끊김. Pipeline에 전달되지 않음.

ToolStage._context.working_dir = ""  (기본값)
  → ToolContext(working_dir="")  [stage.py:72]
    → ReadTool/BashTool: context.working_dir = ""  ❌ 상대경로 해석 불가
```

**원인**: 
1. `GenyPresets.worker_adaptive()`가 `tool_context` 파라미터를 받지 않음
2. `PipelineBuilder.with_tools()`가 `context` 파라미터를 ToolStage에 전달하지 않음
3. `self._tool_context`를 저장하지만 아무도 읽지 않음

---

## 2. 치명적 버그

### 2.1 tool_bridge.py asyncio.to_thread 문법 오류

**위치**: `tool_bridge.py` line 127

```python
result = await asyncio.to_thread(run_fn, **input)
```

`asyncio.to_thread()`는 `**kwargs`를 직접 받지 않음. 올바른 문법:

```python
result = await asyncio.to_thread(run_fn, **input)  # Python 3.9+에서 실제로 동작함
```

실제로는 Python 3.9+ `asyncio.to_thread(func, /, *args, **kwargs)` 시그니처에서 `**kwargs`를 지원하므로 **문법 자체는 정상**. 단, `run_fn`이 positional args를 기대하면 문제 될 수 있음.

→ **검증 결과: 대부분의 Geny 도구는 `run(**kwargs)`를 사용하므로 정상 동작**. 다만 안전성을 위해 lambda 래핑 권장.

### 2.2 working_dir 미전달 (1.2와 동일)

**심각도**: HIGH — 빌트인 도구(Read/Write/Edit/Bash/Glob/Grep)가 상대경로를 해석할 수 없음.

**수정 방법**: geny-executor의 `PipelineBuilder.with_tools()`가 `context` 파라미터를 받아서 `ToolStage`에 전달하도록 수정.

---

## 3. Dead Code / 미사용 필드

### agent_session.py

| 항목 | 위치 | 상태 |
|------|------|------|
| `from enum import Enum` | import | 미사용 |
| `enable_checkpointing` 파라미터 | __init__ | 받지만 저장/사용 안 함 |
| `graph_name` 파라미터 | __init__ | 받지만 저장/사용 안 함 |
| `self._execution_backend` | field | 설정만 하고 읽지 않음 |
| `self._current_thread_id` | field | "default" 고정, 의미 없음 |
| `self._needs_process_restart` | field | 설정만 하고 체크 안 함 |
| `self._tool_context` | field | 저장만 하고 사용 안 함 |
| `self._timeout` | field | 실행 시간 제한에 사용 안 함 |

### agent_session_manager.py

| 항목 | 상태 |
|------|------|
| `SessionManager` 상속 | CLI 기반 부모 클래스. `_local_processes` dict 등 레거시 |
| VTuber 채팅방 생성 실패 시 | 에러만 로깅, 복구 없음 |

---

## 4. 개선 계획

### P1: working_dir 전달 수정 (geny-executor + Geny)

geny-executor 변경:
- `PipelineBuilder.with_tools(registry, context=None)` → ToolStage에 context 전달
- `GenyPresets.worker_adaptive(tool_context=None)` → with_tools에 context 전달

Geny 변경:
- `_build_pipeline()`에서 `tool_context`를 preset 호출에 전달

### P2: Dead code 정리

- 미사용 import/필드/파라미터 제거
- `_check_freshness()`의 `_needs_process_restart` 로직 제거
- `enable_checkpointing`, `graph_name` 파라미터 제거

### P3: 안정성

- tool_bridge.py의 asyncio.to_thread를 lambda 래핑으로 안전하게 변경
- tool_bridge.py의 exception 로깅에 traceback 추가
