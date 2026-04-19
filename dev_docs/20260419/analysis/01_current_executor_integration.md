# 01. Geny 의 현재 `geny-executor` 통합 지도

> **버전 고정**: `backend/pyproject.toml` → `geny-executor>=0.8.3`.
> 실제 import 되고 있는 공용 심볼은 5 개 모듈 / ~10 개 심볼로 국한된다.

## 1. 직접 호출 지점 (2 파일)

`grep ^(from|import) geny_executor` → **단 2 개 파일**:

### 1-A. `backend/service/langgraph/agent_session.py`

`AgentSession` — 세션 단위 파이프라인 래퍼. Geny 의 실질적 실행 진입점.

```python
# 파이프라인 구축시 (agent_session.py:635-640)
from geny_executor.memory import GenyPresets
from geny_executor.tools.registry import ToolRegistry
from geny_executor.tools.base import ToolContext
from geny_executor.tools.built_in import (
    ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool,
)

# 실행시 (agent_session.py:826, 954)
from geny_executor.core.state import PipelineState as _PipelineState
```

외부로 노출되는 async API:

| 메서드 | 시그니처 | 역할 |
|-------|--------|------|
| `AgentSession.create(...)` | `async classmethod` | 팩토리 — 파이프라인 빌드 + 메모리 매니저 초기화 |
| `initialize()` | `async` → `bool` | 지연 초기화 (vector memory 포함) |
| `invoke(input_text, thread_id, max_iterations)` | `async` → `Dict` | 1-회 실행 + JSON 결과 |
| `astream(input_text, thread_id, max_iterations)` | `async gen` | 토큰/스테이지 이벤트 스트림 |
| `revive()` | `async` → `bool` | 재기동 |
| `cleanup()` | `async` | 종료 |
| `is_alive()` | `bool` | 생존 검사 |

**파이프라인 구축 경로** (`_build_pipeline`, 626-736):

1. `ToolRegistry()` 생성.
2. 내장 툴 6 개 등록: `ReadTool/WriteTool/EditTool/BashTool/GlobTool/GrepTool`.
3. Geny 고유 툴 등록: `self._geny_tool_registry` 에서 이터레이트 (이미 `tool_bridge` 로 어댑트된 상태).
4. `ToolContext(session_id, working_dir, storage_path)`.
5. **분기**:
   - VTuber: `GenyPresets.vtuber(api_key, memory_manager, model, persona_prompt, curated_knowledge_manager, llm_reflect, tools, tool_context)`.
   - Worker: `GenyPresets.worker_adaptive(api_key, memory_manager, model, system_prompt, tools, tool_context, max_turns, easy_max_turns, curated_knowledge_manager, llm_reflect)`.
6. 결과 Pipeline 을 `self._pipeline` 에 저장.

**실행 경로** (`_invoke_pipeline`, `_astream_pipeline`):

```python
from geny_executor.core.state import PipelineState as _PipelineState
state = _PipelineState(session_id=...)
async for event in self._pipeline.run_stream(input_text, state):
    # event.type ∈ {
    #   "tool.execute_start", "tool.execute_complete",
    #   "stage.enter", "stage.exit",
    #   "text.delta",
    #   "pipeline.complete", "pipeline.error"
    # }
    # event.data: dict
```

### 1-B. `backend/service/langgraph/tool_bridge.py`

Geny 의 `ToolLoader` (Python 클래스 툴) → executor 의 `ToolRegistry` 어댑팅.

```python
from geny_executor.tools.registry import ToolRegistry
from geny_executor.tools.base import Tool, ToolResult
```

외부 공개:

- `build_geny_tool_registry(tool_loader, allowed_tool_names) → ToolRegistry`
- 내부 어댑터: `_GenyToolAdapter` — `Tool` 을 상속, `name/description/input_schema/to_api_format/execute` 구현.
  - `execute()` 가 auto-inject `context.session_id` 후 `tool.arun(**input)` 호출, 동기 툴은 `asyncio.to_thread()` 로 래핑.

## 2. 바깥 오케스트레이션 (executor 를 직접 부르지는 않지만 AgentSession 을 부름)

`service.langgraph` 패키지 를 import 하는 외부 호출자 (4 곳):

| 파일 | 사용 |
|------|------|
| `backend/main.py` | 부팅시 `agent_manager.set_*()` / `start_idle_monitor()` / 종료시 `cleanup` |
| `backend/controller/agent_controller.py` | REST — `/api/agents/*` |
| `backend/controller/chat_controller.py` | REST — `/api/chat/rooms/{id}/broadcast` |
| `backend/service/execution/agent_executor.py` | `execute_command()` — 공통 실행 통로 |

### 2-A. `AgentSessionManager` (singleton)

`backend/service/langgraph/agent_session_manager.py` — 세션/툴/MCP/공유폴더/아이들 모니터를 한 곳에서 관리하는 싱글턴.

- 의존성 주입: `set_app_db(app_db)`, `set_tool_loader(tool_loader)`, `set_global_mcp_config(mcp_config)`, `set_shared_folder_config(...)`.
- 핵심 생성 경로 `create_agent_session(request)`:
  1. 툴 프리셋 해석 (`ToolPresetStore`) → `allowed_tool_names`, `allowed_mcp_servers`.
  2. MCP 설정 머지: `build_session_mcp_config(global_config, allowed_mcp_servers, extra_mcp)`.
  3. 시스템 프롬프트 빌드 (`_build_system_prompt` + 모듈러 `PromptBuilder`).
  4. `build_geny_tool_registry(tool_loader, allowed_tool_names)` → Geny 툴 + MCP 툴을 executor 레지스트리로 변환.
  5. `AgentSession.create(...)` 호출.
  6. 메모리 DB 와이어, 공유 폴더 링크, VTuber auto-pair (VTuber 세션은 CLI 짝을 자동 생성).
- 백그라운드: `_idle_monitor_loop()` 가 60 초마다 STALE_IDLE 세션 전이.

### 2-B. REST/실행 흐름 요약

| 경로 | 메서드 | 주요 호출 |
|------|--------|-----------|
| REST `POST /api/agents` | `agent_controller.create_agent_session` | `agent_manager.create_agent_session(...)` |
| REST `POST /api/agents/{id}/invoke` | `agent_controller.invoke_agent` | `agent.invoke(...)` |
| REST `POST /api/agents/{id}/execute` | `agent_controller.execute_agent_prompt` | `execute_command(session_id, ...)` |
| REST `POST /api/chat/rooms/{id}/broadcast` | `chat_controller.broadcast_to_room` | 다중 `execute_command(...)` |
| WS `ws/execute_stream` | → | `execute_command(...)` |

모든 경로가 결국 `backend/service/execution/agent_executor.execute_command()` 로 수렴.

## 3. 부팅 순서 (main.py 관점)

`lifespan` 컨텍스트 매니저 기준 (약식):

1. AppDatabaseManager 연결.
2. ConfigManager 로드.
3. SessionStore / ChatStore 에 DB 주입.
4. Logging + 메모리 DB 와이어링: `agent_manager.set_app_db(app_db)`.
5. ToolLoader `load_all()`.
6. MCPLoader 로드 + `agent_manager.set_global_mcp_config()` + `set_tool_loader()`.
7. ToolPreset 시드.
8. SharedFolder 설정 + `agent_manager.set_shared_folder_config(...)`.
9. `agent_manager.start_idle_monitor()`.
10. VTuber 서비스 기동 + `ThinkingTriggerService.start()`.
11. `CurationScheduler.start()`.

## 4. 주목할 점 & 불확실성

- **GenyPresets 는 v0.20.0 에서도 여전히 존재**: `src/geny_executor/memory/presets.py:56` — 4 개 정적 메서드 (`worker_easy`, `worker_full`, `worker_adaptive`, `vtuber`) 가 그대로 있다. 즉 *import-path 호환성은 유지*되지만 내부 구현은 버전을 타고 바뀌었다 (다음 문서 §3 참조).
- **Pipeline.run_stream()** 은 항상 `PipelineEvent` 를 yield. 이벤트 스키마는 `geny_executor/events/types.py:PipelineEvent{type, stage, iteration, timestamp, data}` 로 0.8 → 0.20 간 동일.
- **`backend/service/langgraph/autonomous_graph.py.bak`** — 이전 LangGraph 구현 잔재. 본 마이그레이션에서는 참고 대상이 아님.
- **`workflows/` 디렉토리는 비어있음** — 현 시점 Geny 에 별도 워크플로 런타임 없음.

## 5. 오픈 퀘스천 (다음 문서 / 계획 단계에서 해소)

1. VTuber/Worker 프리셋 분기는 executor 의 `GenyPresets` 에 의존 중. 이를 유지하느냐 vs 신규 `PipelineBuilder` 로 재구축하느냐 — *plan/02* 에서 결정.
2. `ToolContext.stage_order / stage_name` (0.8.1 에서 추가, Geny 는 사용하지 않음) — 활용 여부.
3. `PipelineState` 의 신규 필드 (thinking, memory metadata 등) — Geny 가 미사용. 도입 필요성 여부.
4. VTuber-CLI 오토페어 로직이 executor `session` 모듈 (신규 `SessionManager`) 과 중복/경합하는지.
