# Geny 현행 심층 검토 리포트

> Date: 2026-04-14
> 대상: geny-executor 통합 후 전체 실행 로직
> 방향: vtuber(간소화) + default(geny-executor 전체) 두 가지만 사용

---

## 1. 치명적 버그 (CRITICAL)

### 1.1 session_id가 Pipeline에 전달되지 않음

**위치**: `agent_session.py` `_invoke_pipeline()` / `_astream_pipeline()`

```python
# 현재 코드
async for event in self._pipeline.run_stream(input_text):
```

`pipeline.run_stream(input_text)`에 `PipelineState`를 전달하지 않아서
`PipelineState.session_id`가 빈 문자열 `""`으로 남음.

**결과**: `s10_tool` → `ToolContext(session_id="")` → `_GenyToolAdapter`가
`input.setdefault("session_id", "")` 주입 → **memory/knowledge 도구가 빈 session_id로 호출됨**

**수정**:
```python
from geny_executor.core.state import PipelineState
state = PipelineState(session_id=self._session_id)
async for event in self._pipeline.run_stream(input_text, state):
```

### 1.2 astream()에 finally 블록 없음

**위치**: `agent_session.py` `astream()`

스트림이 정상 완료되면 `_is_executing = True`가 해제되지 않음.
except 경로에서만 해제됨. invoke()에는 finally가 있는데 astream()에는 없음.

**결과**: 세션이 영원히 "실행 중" 상태 → idle 모니터가 정리 불가, 다음 실행 차단

### 1.3 Proxy MCP 서버가 삭제된 파일을 참조

**위치**: `mcp_loader.py` `build_proxy_mcp_server()` line 136

```python
proxy_script = str(PROJECT_ROOT / "tools" / "_proxy_mcp_server.py")
```

`_proxy_mcp_server.py`가 삭제되었지만 `build_session_mcp_config()`에서
여전히 프록시 서버를 생성하려 함. geny-executor에서는 이 경로를 사용하지 않지만,
`merged_mcp_config`에 dead 엔트리가 포함됨.

---

## 2. 구조적 문제 (HIGH)

### 2.1 working_dir가 Pipeline에 전달되지 않음

**위치**: `agent_session.py` `_build_pipeline()` line 666, 777

```python
working_dir = self._working_dir or self.storage_path or ""
# ... 계산하지만
self._pipeline_working_dir = working_dir  # 저장만 하고 사용 안 함
```

GenyPresets 호출 시 `working_dir`가 전달되지 않음.
→ 빌트인 도구 (Read/Write/Edit/Bash/Glob/Grep)의 `ToolContext.working_dir`가 빈 문자열.
→ 상대 경로 해석 불가.

### 2.2 agent.process 참조 (Dead code가 실행됨)

**위치**: `agent_session_manager.py` line 543-544, 728-729

```python
if agent.process:  # AgentSession에 process 속성 없음
    agent.process.system_prompt = ...
```

`AgentSession`에서 `process` 프로퍼티를 삭제했으므로 AttributeError 발생 가능.
현재는 `hasattr` 체크가 없어서 런타임에 터질 수 있음.

### 2.3 upgrade_to_agent() 메서드가 from_process() 호출

**위치**: `agent_session_manager.py` line 865

```python
agent = AgentSession.from_process(process, ...)  # 메서드 삭제됨
```

이 메서드가 호출되면 AttributeError. 사용되는 경로가 있으면 치명적.

### 2.4 워크플로우 관련 잔재

- `agent_session.py`: `_workflow_id`, `_graph_name` 필드가 여전히 존재
- `agent_session_manager.py`: `build_session_mcp_config()` 호출, `_local_processes` dict
- `SessionManager` 상속 관계: CLI 기반의 `SessionManager`를 상속 중

---

## 3. Preset 구조 단순화 필요

### 현재: 3종 preset (+ 복잡한 분기)
```python
if is_vtuber:
    GenyPresets.vtuber(...)
elif is_simple:
    GenyPresets.worker_easy(...)
else:
    GenyPresets.worker_adaptive(...)
```

### 목표: 2종만 사용
```
vtuber → GenyPresets.vtuber()       # 간소화된 대화형
default → GenyPresets.worker_adaptive()  # 전체 geny-executor
```

`worker_easy`는 제거. 모든 비-vtuber 세션은 `worker_adaptive` 사용.
`template-simple`, `template-autonomous`, `template-optimized-autonomous` 등의
워크플로우 ID 분기도 불필요.

---

## 4. 메모리 시스템 검증

### 4.1 정상 동작 확인

| 컴포넌트 | 상태 |
|----------|------|
| SessionMemoryManager 초기화 | ✅ |
| DB 백엔드 연동 (set_database) | ✅ |
| Vector memory 초기화 | ✅ |
| GenyMemoryRetriever 6-layer 검색 | ✅ |
| GenyMemoryStrategy 트랜스크립트 기록 | ✅ |
| GenyPersistence JSONL 저장 | ✅ |
| CuratedKnowledgeManager 연동 | ✅ |
| LLM reflection 콜백 | ✅ |

### 4.2 Obsidian 연동

| 컴포넌트 | 상태 |
|----------|------|
| UserOpsidianManager 초기화 | ✅ |
| opsidian_browse 도구 | ✅ (LTMConfig 게이트) |
| opsidian_read 도구 | ✅ (LTMConfig 게이트) |
| Pipeline 내에서 접근 | ✅ (knowledge_tools가 직접 매니저 참조) |

### 4.3 문제점

- `StructuredMemoryWriter` 초기화 시 `session_id` 미전달 (manager.py line 150)
- `PipelineState.session_id`가 빈 문자열 → 도구의 session_id 주입 실패 (1.1과 동일)

---

## 5. MCP 시스템 검증

### 5.1 외부 MCP 서버 (GitHub 등)

`_build_pipeline()`에 MCPManager 코드를 추가했지만, `build_session_mcp_config()`가
여전히 dead proxy 서버를 생성하고 있음.

**필요한 변경**:
- `build_session_mcp_config()`에서 proxy 서버 생성 로직 제거
- 외부 MCP 서버(built_in + custom)만 반환하도록 단순화
- `_build_pipeline()`에서 MCPManager로 연결

### 5.2 Proxy MCP 패턴

완전히 Dead. `_proxy_mcp_server.py` 삭제됨. `build_proxy_mcp_server()` 함수와
관련 코드 전부 제거 필요.

---

## 6. 개선 계획

### Phase A: 치명적 버그 수정 (즉시)

| # | 작업 | 파일 |
|---|------|------|
| A1 | PipelineState에 session_id 전달 | agent_session.py |
| A2 | astream() finally 블록 추가 | agent_session.py |
| A3 | working_dir를 ToolContext에 전달 | agent_session.py, geny-executor ToolStage |

### Phase B: 구조 단순화

| # | 작업 | 파일 |
|---|------|------|
| B1 | Preset을 vtuber/default 2종으로 단순화 | agent_session.py |
| B2 | worker_easy 분기 제거, 모든 비-vtuber → worker_adaptive | agent_session.py |
| B3 | _workflow_id/_graph_name 필드 제거 → preset_name 필드로 교체 | agent_session.py |
| B4 | build_session_mcp_config()에서 proxy 서버 제거 | mcp_loader.py |
| B5 | agent.process 참조 제거, upgrade_to_agent() 제거 | agent_session_manager.py |
| B6 | SessionManager 상속 정리 | agent_session_manager.py |

### Phase C: 정합성

| # | 작업 | 파일 |
|---|------|------|
| C1 | StructuredMemoryWriter에 session_id 전달 | service/memory/manager.py |
| C2 | 미사용 변수 정리 (event_count, last_event, _pipeline_working_dir) | agent_session.py |
| C3 | 프론트엔드 CreateSessionModal에서 워크플로우 선택 UI 완전 제거 → 역할 선택만 | CreateSessionModal.tsx |
