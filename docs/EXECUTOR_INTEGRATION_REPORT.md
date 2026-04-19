# Geny Executor Integration — 현행 심층 분석 리포트

> Date: 2026-04-14
> Status: Phase 1 Migration Complete, Phase 2 최적화 필요

---

## 1. 현재 상태 요약

geny-executor Pipeline이 유일한 실행 엔진으로 동작 중.
**기본 실행은 성공하지만, 기존 Geny 아키텍처의 잔재가 광범위하게 남아있음.**

### 동작하는 것
- Pipeline 빌드 + 실행 (invoke/astream)
- 빌트인 도구 6종 (Read/Write/Edit/Bash/Glob/Grep)
- Geny 커스텀 도구 35종 (tool_bridge 경유)
- 메모리 시스템 연동 (GenyPresets → SessionMemoryManager)
- WebSocket/SSE 스트리밍 (Pipeline 이벤트 → session_logger)

### 문제/미완성 영역
- 워크플로우 시스템이 **사실상 사용되지 않음** (로드만 하고 내용은 무시)
- MCP가 **이중 경로** (Proxy HTTP vs Pipeline 내장) 
- 레거시 코드가 대량으로 잔존
- 도구 실행 시 ToolContext 미전달

---

## 2. 워크플로우 시스템: 현재 vs 실제 사용

### 2.1 구조

```
service/workflow/
├── workflow_model.py       # WorkflowDefinition (노드/엣지 그래프)
├── workflow_store.py       # JSON 파일 저장소
├── workflow_executor.py    # WorkflowDefinition → LangGraph CompiledStateGraph 컴파일러
├── workflow_state.py       # AutonomousState 필드 26개 정의
├── workflow_inspector.py   # 그래프 시각화/디버깅
├── templates.py            # 5개 템플릿 팩토리
└── nodes/                  # 30+ 노드 구현체
    ├── model/              # classify, answer, review, llm_call, direct_answer
    ├── task/               # create_todos, execute_todo, final_answer
    ├── logic/              # check_progress, iteration_gate, conditional_router
    ├── resilience/         # context_guard, post_model
    ├── memory/             # memory_inject, memory_reflect, transcript_record
    └── vtuber/             # vtuber_classify, vtuber_respond, vtuber_delegate
```

### 2.2 5개 워크플로우 템플릿

| Template | 노드 수 | 구조 | 용도 |
|----------|---------|------|------|
| `template-autonomous` | 28 | 4경로 (easy/medium/hard + 리뷰 루프) | 범용 자율 에이전트 |
| `template-simple` | 6 | 단일 LLM 호출 | 간단한 Q&A |
| `template-optimized-autonomous` | 9 | 2경로 (easy/not_easy) | 비용 최적화 |
| `template-ultra-light` | 21 | 5난이도 분기 | 극단적 비용 절감 |
| `template-vtuber` | 8 | 3분기 (respond/delegate/think) | VTuber 대화 |

### 2.3 실제 사용 현황: **거의 사용되지 않음**

```python
# agent_session.py _build_graph()
self._workflow = self._load_workflow_definition()  # 로드만 함
self._build_pipeline()  # 워크플로우 내용 무시

# _build_pipeline()에서의 실제 사용
template_id = getattr(self._workflow, "id", "") or self._workflow_id or ""
is_vtuber = "vtuber" in template_id.lower()      # ← template_id 문자열만 확인
is_simple = "simple" in template_id.lower()       # ← 노드/엣지 구조는 사용 안 함
```

**WorkflowDefinition의 28개 노드, 엣지 구조, 분기 로직이 전부 무시되고 있음.**
template_id 문자열만으로 GenyPresets 메서드를 선택.

### 2.4 Dead Code 규모

| 컴포넌트 | 파일 수 | 라인 수 (추정) | 상태 |
|----------|---------|--------------|------|
| WorkflowExecutor (LangGraph 컴파일러) | 1 | ~420 | **Dead** — 실행에서 미사용 |
| workflow_state.py (26 필드 정의) | 1 | ~690 | **Dead** — Pipeline 미사용 |
| nodes/ (30+ 노드 구현체) | 25+ | ~3,000+ | **Dead** — Pipeline 미사용 |
| autonomous_graph.py | 1 | ~500 | **Dead** — 하드코딩 그래프 |
| workflow_inspector.py | 1 | ~790 | Semi-dead (REST API만) |
| AutonomousState (state.py) | 1 | ~280 | **Dead** — Pipeline 미사용 |

**추정 Dead Code: ~5,600+ 줄**

---

## 3. 도구 시스템 현황

### 3.1 도구 인벤토리 (총 35종)

**빌트인 (24종) — 항상 포함:**

| 그룹 | 도구 | 설명 |
|------|------|------|
| Session (11) | geny_session_list/info/create | 에이전트 관리 |
| | geny_room_list/create/info/add_members | 채팅방 관리 |
| | geny_send_room_message/direct_message | 메시지 전송 |
| | geny_read_room_messages/inbox | 메시지 읽기 |
| Knowledge (6) | knowledge_search/read/list/promote | 지식 베이스 |
| | opsidian_browse/read | Obsidian 연동 |
| Memory (7) | memory_write/read/update/delete | 메모리 CRUD |
| | memory_search/list/link | 메모리 검색/연결 |

**커스텀 (11종) — 프리셋으로 필터링:**

| 그룹 | 도구 | 설명 |
|------|------|------|
| Web (4) | web_search, news_search | DDGS 검색 |
| | web_fetch, web_fetch_multiple | HTTP 페이지 가져오기 |
| Browser (7) | browser_navigate/click/fill | Playwright 자동화 |
| | browser_screenshot/evaluate | 스크린샷/JS 실행 |
| | browser_page_info/close | 페이지 정보/닫기 |

**geny-executor 빌트인 (6종) — 파이프라인에 직접 등록:**

| 도구 | 설명 |
|------|------|
| Read | 파일 읽기 |
| Write | 파일 쓰기 |
| Edit | 파일 수정 |
| Bash | 셸 명령 |
| Glob | 파일 검색 |
| Grep | 내용 검색 |

### 3.2 도구 등록 경로

```
_build_pipeline()
  │
  ├── 1. geny-executor 빌트인 (6종)
  │     ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool
  │     → ToolRegistry에 직접 register()
  │
  ├── 2. Geny 커스텀 도구 (35종)
  │     tool_loader.get_tool() → _GenyToolAdapter → ToolRegistry.register()
  │     (tool_bridge.py 경유)
  │
  └── 3. MCP 도구 (현재 미연동)
        → Pipeline에서 MCP 도구 미등록 (아래 4번 참조)
```

### 3.3 ToolContext 전달 문제

현재 `_GenyToolAdapter.execute()`는 `context: Any = None`을 받지만, **Pipeline의 ToolStage가 전달하는 ToolContext를 Geny 도구에 전달하지 않습니다.**

```python
# _GenyToolAdapter.execute() — context를 무시하고 있음
async def execute(self, input: Dict[str, Any], context: Any = None) -> Any:
    result = await self._tool.arun(**input)  # ← context 미전달
```

문제: Geny 빌트인 도구 (memory_*, knowledge_* 등)는 `session_id`를 파라미터로 직접 받지만,
이것이 Pipeline의 ToolContext.session_id와 연동되지 않음.

---

## 4. MCP 시스템: 이중 경로 문제

### 4.1 현재 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                     MCP 경로 1 (Proxy)               │
│                                                       │
│  Claude CLI → .mcp.json → _proxy_mcp_server.py       │
│       ↓                        ↓                      │
│  MCP 프로토콜 (stdio)    HTTP POST /internal/tools/   │
│       ↓                        ↓                      │
│  tool_name → proxy_fn    → tool_loader.get_tool()     │
│                                ↓                      │
│                           tool.run(**args)             │
│                                                       │
│  ⚠ CLI가 없으므로 이 경로는 완전히 Dead              │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                   MCP 경로 2 (Pipeline 직접)         │
│                                                       │
│  Pipeline → s10_tool → ToolRegistry                   │
│       ↓                    ↓                          │
│  tool_call            → _GenyToolAdapter.execute()    │
│       ↓                    ↓                          │
│  ToolResult           ← tool.arun(**input)            │
│                                                       │
│  ✅ 현재 사용 중인 경로                               │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│               MCP 경로 3 (외부 MCP 서버)             │
│                                                       │
│  geny-executor MCPManager → stdio/HTTP MCP server     │
│       ↓                        ↓                      │
│  MCPToolAdapter          → server.call_tool()         │
│       ↓                        ↓                      │
│  ToolResult              ← MCP 응답                   │
│                                                       │
│  ⚠ _build_pipeline()에서 MCP 도구 등록 안 함         │
└─────────────────────────────────────────────────────┘
```

### 4.2 문제점

1. **Proxy MCP 서버 (경로 1)**: CLI 제거로 완전히 Dead. `_proxy_mcp_server.py`, `/internal/tools/execute` 엔드포인트, `.mcp.json` 생성 코드 전부 불필요.

2. **외부 MCP 서버 (경로 3)**: `_build_pipeline()`에서 `MCPManager`를 사용하지 않음. GitHub MCP, Notion MCP 등 외부 서버 연결 불가.

3. **MCP config 생성** (`build_session_mcp_config`): CLI용 `.mcp.json` 생성 로직. Pipeline에 불필요.

---

## 5. 레거시 잔재 목록

### 5.1 agent_session.py 내 레거시

| 항목 | 라인 | 상태 |
|------|------|------|
| `from langgraph.graph.state import CompiledStateGraph` | L49 | **Dead import** |
| `from service.langgraph.claude_cli_model import ClaudeCLIChatModel` | L60 | **Dead import** |
| `self._model: Optional[ClaudeCLIChatModel] = None` | L157 | **Dead 필드** |
| `self._graph: Optional[CompiledStateGraph] = None` | L158 | **Dead 필드** |
| `from_process()` classmethod | L275-290 | **Dead 메서드** |
| `from_model()` classmethod | L292-330 | **Dead 메서드** |
| `process` property | L415-420 | **Dead 속성** |
| `model` property | L414 | **Dead 속성** |
| `graph` property | L409-411 | **Dead 속성** |
| `get_state()`, `get_state_history()` | L1637-1662 | **Dead** (그래프 없음) |
| `visualize()`, `get_mermaid_diagram()` | L1674-1693 | **Dead** (그래프 없음) |

### 5.2 agent_session_manager.py 내 레거시

| 항목 | 상태 |
|------|------|
| `from service.claude_manager.process_manager import ClaudeProcess` | Dead import |
| `from service.claude_manager.session_manager import SessionManager` | 상속 관계 |
| `_local_processes` dict | 미사용 |
| `build_session_mcp_config()` 호출 | CLI용 MCP config (Pipeline 불필요) |

### 5.3 독립 파일 레거시

| 파일 | 상태 |
|------|------|
| `service/claude_manager/process_manager.py` | **Dead** — ClaudeProcess |
| `service/claude_manager/cli_discovery.py` | **Dead** — CLI 경로 탐색 |
| `service/claude_manager/stream_parser.py` | **Dead** — CLI 출력 파싱 |
| `service/langgraph/claude_cli_model.py` | **Dead** — CLI 래퍼 |
| `service/langgraph/autonomous_graph.py` | **Dead** — 하드코딩 그래프 |
| `tools/_proxy_mcp_server.py` | **Dead** — CLI MCP 프록시 |
| `tools/_mcp_server.py` | **Dead** — CLI MCP 서버 |
| `controller/internal_tool_controller.py` | **Dead** — 프록시 도구 실행 |

---

## 6. 핵심 구조적 문제

### 6.1 워크플로우 ↔ Pipeline 단절

현재 워크플로우 시스템과 Pipeline은 **완전히 분리**되어 있습니다:

```
WorkflowDefinition (28 노드, 엣지, 분기 로직)
       ↓
  template_id 문자열만 추출
       ↓
  GenyPresets.worker_full() ← 워크플로우 구조 무시
       ↓
  16-stage Pipeline (고정 구조)
```

**워크플로우의 난이도 분류(easy/medium/hard), 리뷰 루프, TODO 시스템이 전부 무시됨.**
Pipeline은 항상 동일한 16-stage 구조로 실행.

### 6.2 두 가지 선택지

**Option A: 워크플로우 → Pipeline 매핑**
- WorkflowDefinition의 노드/엣지 구조를 읽어서 Pipeline의 스테이지 구성을 동적으로 변경
- 예: `classify_node` → s12_evaluate 전략 변경, `review_node` → s13_loop 전략 변경
- 장점: 기존 워크플로우 에디터 UI 유지
- 단점: 두 시스템 간 추상화 불일치 해결 필요

**Option B: 워크플로우 시스템 폐기**
- GenyPresets가 모든 실행 로직을 담당
- 템플릿은 Preset 이름으로만 관리 (vtuber, worker_easy, worker_full)
- 기존 워크플로우 에디터 UI 제거 또는 Pipeline 시각화로 대체
- 장점: 아키텍처 단순화, 대규모 코드 제거
- 단점: 워크플로우 커스터마이징 능력 상실

**Option C: geny-executor에 워크플로우 개념 통합**
- geny-executor의 PipelineBuilder를 확장하여 WorkflowDefinition을 소비
- 노드 타입 → Stage strategy 매핑 테이블
- Pipeline의 dual-abstraction (stage swap + strategy swap)을 활용
- 장점: 깔끔한 단일 아키텍처
- 단점: geny-executor 대규모 확장 필요

### 6.3 MCP 통합 방향

**현재**: Proxy MCP (Dead) + Pipeline 직접 도구 실행 (동작) + 외부 MCP (미연동)

**목표**: Pipeline이 외부 MCP 서버에 직접 연결

```python
# _build_pipeline()에 추가 필요
from geny_executor.tools.mcp.manager import MCPManager

mcp_manager = MCPManager.from_config_file(mcp_config_path)
await mcp_manager.connect_from_loaded_configs()
mcp_registry = await mcp_manager.build_registry()
tools.merge(mcp_registry)  # Pipeline ToolRegistry에 MCP 도구 추가
```

---

## 7. 도구 시스템 개선 포인트

### 7.1 ToolContext 활용

현재 `_GenyToolAdapter`가 ToolContext를 무시합니다. 개선 필요:

```python
async def execute(self, input: Dict[str, Any], context: ToolContext) -> ToolResult:
    # session_id를 자동 주입 (Geny 도구가 필요로 함)
    if context and context.session_id:
        input.setdefault("session_id", context.session_id)
    
    result = await self._tool.arun(**input)
```

### 7.2 도구 파라미터 스키마

Geny 도구의 `parameters`는 자동 생성되지만, geny-executor의 `input_schema`와 호환되지 않을 수 있음:
- Geny: `_generate_parameters_schema()` → Python 타입 힌트 기반
- geny-executor: JSON Schema (Anthropic API 형식)

검증 필요: 모든 35개 도구의 스키마가 Anthropic API와 호환되는지.

### 7.3 비동기 도구 실행

일부 Geny 도구는 `arun()` 메서드가 있고, 일부는 `run()`만 있음.
`_GenyToolAdapter`는 이미 처리하지만, `asyncio.to_thread()`로 sync → async 변환 시
GIL 이슈나 이벤트 루프 문제 가능성.

---

## 8. 향후 작업 제안

### Tier 1: 즉시 필요 (안정성)
1. ToolContext.session_id → Geny 도구에 자동 주입
2. 외부 MCP 서버 연동 (MCPManager → Pipeline ToolRegistry)
3. Dead import/필드 정리 (agent_session.py)

### Tier 2: 아키텍처 결정 필요
4. 워크플로우 시스템 방향 결정 (Option A/B/C)
5. Proxy MCP 경로 완전 제거
6. CLI 관련 Dead code 전체 제거 (~5,600줄)

### Tier 3: 완성도
7. Pipeline 이벤트 ↔ session_logger 매핑 검증
8. 에러 핸들링 강화 (Pipeline 이벤트 파싱)
9. 도구 스키마 호환성 검증 (35종 전수 테스트)
10. 워크플로우 에디터 UI 업데이트 (현재 LangGraph 기반)
