# Geny Executor Migration Report v2

> Date: 2026-04-14
> Status: Detailed Implementation Plan

---

## 1. Executive Summary

Geny의 에이전트 실행 시스템을 **geny-executor Pipeline 단일 엔진**으로 완전 전환한다.
구 CLI 기반(ClaudeProcess + LangGraph) 폴백을 **전부 제거**한다.

이를 위해 geny-executor 자체에 **현재 부족한 기능을 먼저 구현**해야 한다.

---

## 2. Gap Analysis: geny-executor vs Geny 요구사항

### 2.1 기능 대조표

| 기능 | Geny 현재 (CLI) | geny-executor 현재 | Gap |
|------|-----------------|-------------------|-----|
| LLM 호출 | Claude CLI 내부 | Anthropic API 직접 | **None** |
| 스트리밍 | stream-json 파싱 | EventBus 기반 | **None** |
| 도구 프레임워크 | BaseTool + ToolLoader | Tool ABC + ToolRegistry | **None** (tool_bridge 존재) |
| **빌트인 도구** | CLI 내장 (Read/Write/Edit/Bash/Glob/Grep) | **없음** | **Critical Gap** |
| **MCP 지원** | CLI가 .mcp.json 읽어서 연결 | 스켈레톤만 존재 (NotImplementedError) | **Critical Gap** |
| **세션 지속성** | `--resume` + conversation_id | 인메모리만 | **Critical Gap** |
| **파일 시스템 접근** | CLI의 Read/Write/Edit/Glob/Grep 도구 | **없음** | **Critical Gap** |
| **셸 실행** | CLI의 Bash 도구 | **없음** | **Critical Gap** |
| 메모리 시스템 | SessionMemoryManager | GenyMemoryStrategy (연동됨) | **None** |
| 비용 추적 | stream result 파싱 | TokenUsage + AnthropicPricing | **None** |
| Extended Thinking | CLI 지원 | s08_think 스테이지 | **None** |
| 프롬프트 캐싱 | CLI 내부 | s05_cache (Aggressive/Adaptive) | **None** |
| 도구 프리셋 | ToolPresetDefinition | 없음 (Geny 측에서 필터링) | **None** (Geny가 처리) |
| 환경변수 주입 | GITHUB_TOKEN 등 | ToolContext.metadata | **None** (패스 가능) |
| 아바타 상태 | EmotionExtractor | s14_emit VTuber 전략 | **None** |

### 2.2 Critical Gaps 상세

#### Gap 1: 빌트인 도구 부재

geny-executor에는 **단 하나의 빌트인 도구도 없다**.
Claude CLI가 기본 제공하는 다음 도구들이 필수:

| 도구 | 기능 | 우선순위 |
|------|------|---------|
| `Read` | 파일 읽기 (라인 범위, 이미지, PDF) | **P0** |
| `Write` | 파일 생성/덮어쓰기 | **P0** |
| `Edit` | 파일 부분 수정 (old_string → new_string) | **P0** |
| `Bash` | 셸 명령 실행 (타임아웃, 작업 디렉토리) | **P0** |
| `Glob` | 파일 패턴 매칭 검색 | **P1** |
| `Grep` | 파일 내용 정규식 검색 | **P1** |
| `WebFetch` | 웹 페이지 가져오기 | **P1** |
| `WebSearch` | 웹 검색 | **P1** |

이 도구들은 geny-executor 패키지 내부에 `tools/built_in/` 으로 구현되어야 한다.

#### Gap 2: MCP 미구현

현재 상태:
- `geny_executor/tools/mcp/manager.py` — `MCPManager` 클래스 존재
- `geny_executor/tools/mcp/adapter.py` — `MCPToolAdapter` 존재
- **그러나** `MCPServerConnection.call_tool()`이 `NotImplementedError`

필요한 구현:
- `mcp` SDK 패키지를 사용한 실제 서버 연결
- stdio transport (로컬 MCP 서버)
- HTTP/SSE transport (원격 MCP 서버)
- 도구 디스커버리 (서버에서 사용 가능한 도구 목록 조회)
- 도구 실행 (tool call → result 반환)
- Geny의 3-layer MCP 구조 지원:
  - built_in MCP (항상 포함)
  - custom MCP (프리셋 필터링)
  - proxy MCP (Python 도구를 MCP 서버로 노출)

#### Gap 3: 세션 지속성 미구현

현재: `SessionManager`가 인메모리 `Dict[str, Session]`만 관리
필요:
- 파일 기반 세션 상태 저장 (conversation history)
- 프로세스 재시작 후 세션 복원
- CLI의 `--resume` 대응: 이전 대화 컨텍스트 유지
- `.claude_session.json` 대체 메커니즘

#### Gap 4: 파일 시스템 도구

CLI는 `--dangerously-skip-permissions` 플래그로 파일 시스템에 자유롭게 접근.
geny-executor에서는 **명시적 도구**로 구현해야 함:
- 작업 디렉토리(working_dir) 기반 상대 경로 해석
- 보안 가드: 허용된 경로 외부 접근 차단
- 대용량 파일 처리 (offset/limit 파라미터)

---

## 3. Geny 커스텀 도구 현황

geny-executor의 tool_bridge가 이미 처리하는 도구들:

### 3.1 빌트인 (geny_tools.py) — 항상 포함

| 도구 | 기능 |
|------|------|
| `GenySessionListTool` | 팀 멤버/세션 목록 |
| `GenySessionInfoTool` | 세션 상세 정보 |
| `GenySessionCreateTool` | 새 에이전트 생성 |
| `GenyRoomListTool` | 채팅방 목록 |
| `GenyRoomCreateTool` | 채팅방 생성 |
| `GenyRoomInfoTool` | 채팅방 상세 |
| `GenyRoomAddMembersTool` | 멤버 초대 |
| `GenySendRoomMessageTool` | 채팅방 메시지 전송 |
| `GenySendDirectMessageTool` | 다이렉트 메시지 |
| `GenyReadRoomMessagesTool` | 채팅방 메시지 읽기 |
| `GenyReadInboxTool` | 받은 메시지함 |

### 3.2 메모리 도구 (memory_tools.py)

| 도구 | 기능 |
|------|------|
| `MemoryWriteTool` | 메모리 기록 |
| `MemoryReadTool` | 메모리 읽기 |
| `MemoryUpdateTool` | 메모리 수정 |
| `MemoryDeleteTool` | 메모리 삭제 |
| `MemorySearchTool` | 메모리 검색 |
| `MemoryListTool` | 메모리 목록 |
| `MemoryLinkTool` | 메모리 연결 |

### 3.3 커스텀 도구 (프리셋으로 필터링)

| 도구 | 기능 |
|------|------|
| `WebSearchTool` | 웹 검색 |
| `NewsSearchTool` | 뉴스 검색 |
| `WebFetchTool` | 웹 페이지 가져오기 |
| `WebFetchMultipleTool` | 다중 페이지 가져오기 |
| `BrowserNavigateTool` | 브라우저 네비게이션 |
| `BrowserClickTool` | 요소 클릭 |
| `BrowserFillTool` | 폼 입력 |
| `BrowserScreenshotTool` | 스크린샷 |
| `BrowserEvaluateTool` | JavaScript 실행 |
| `BrowserGetPageInfoTool` | 페이지 정보 |
| `BrowserCloseTool` | 브라우저 닫기 |
| `KnowledgeSearchTool` | 지식 베이스 검색 |
| `KnowledgeReadTool` | 지식 읽기 |
| `KnowledgeListTool` | 지식 목록 |
| `KnowledgePromoteTool` | 지식 승격 |

**이 도구들은 tool_bridge.py를 통해 이미 geny-executor에 연결됨.**
문제는 **파일 시스템/셸/MCP 도구**가 없다는 것.

---

## 4. 구체적 구현 계획

### Phase 0: geny-executor 기능 확장 (선행 작업)

> **작업 위치**: `/home/geny-workspace/geny-executor/`

#### Task 0-1: 코어 빌트인 도구 구현

`src/geny_executor/tools/built_in/` 디렉토리 생성 및 구현:

```
tools/built_in/
  __init__.py
  read_tool.py      # 파일 읽기 (라인 범위, 바이너리 감지)
  write_tool.py     # 파일 생성/덮어쓰기
  edit_tool.py      # 부분 수정 (old_string → new_string, replace_all)
  bash_tool.py      # 셸 명령 실행 (timeout, working_dir, env)
  glob_tool.py      # 파일 패턴 매칭
  grep_tool.py      # 파일 내용 검색 (regex, context lines)
```

**각 도구의 요구사항:**

**ReadTool:**
- 입력: `file_path` (절대경로), `offset?`, `limit?`
- 출력: 라인 번호 포함 텍스트 (`cat -n` 형식)
- 바이너리 파일 감지, 이미지 파일 base64 인코딩
- 보안: `working_dir` 기준 경로 검증

**WriteTool:**
- 입력: `file_path`, `content`
- 출력: 성공/실패 + 파일 크기
- 디렉토리 자동 생성
- 보안: `working_dir` 기준 경로 검증

**EditTool:**
- 입력: `file_path`, `old_string`, `new_string`, `replace_all?`
- 출력: 성공/실패 + 변경 라인 수
- `old_string`이 파일에서 유일해야 함 (아니면 에러)
- 보안: `working_dir` 기준 경로 검증

**BashTool:**
- 입력: `command`, `timeout?` (ms, 기본 120000), `working_dir?`
- 출력: stdout + stderr + exit_code
- `asyncio.create_subprocess_shell()` 사용
- 타임아웃 시 프로세스 kill
- 환경변수 주입 (GITHUB_TOKEN 등)

**GlobTool:**
- 입력: `pattern`, `path?` (기본: working_dir)
- 출력: 매칭된 파일 경로 목록
- `pathlib.Path.glob()` 또는 `glob.glob()` 사용
- 수정 시간 기준 정렬

**GrepTool:**
- 입력: `pattern` (regex), `path?`, `glob?`, `output_mode?`, `context?`
- 출력: 매칭 라인 + 파일명 + 라인 번호
- `re` 모듈 기반 구현
- 대용량 파일 스트리밍 처리

#### Task 0-2: MCP 완전 구현

`src/geny_executor/tools/mcp/` 수정:

```python
# manager.py — 실제 MCP 서버 연결 구현
class MCPManager:
    async def connect_server(self, name: str, config: MCPServerConfig) -> MCPServerConnection:
        """실제 MCP 서버에 연결"""
        if config.transport == "stdio":
            # subprocess로 MCP 서버 프로세스 시작
            # stdin/stdout으로 JSON-RPC 통신
            process = await asyncio.create_subprocess_exec(...)
            reader = McpStdioReader(process.stdout)
            writer = McpStdioWriter(process.stdin)
            
        elif config.transport == "http":
            # HTTP 기반 MCP 서버 연결
            session = aiohttp.ClientSession()
            
        elif config.transport == "sse":
            # SSE 기반 MCP 서버 연결 (레거시)
            
        # 도구 디스커버리
        tools = await connection.list_tools()
        # ToolRegistry에 자동 등록
        for tool in tools:
            adapted = MCPToolAdapter(connection, tool)
            self.registry.register(adapted)

# adapter.py — 실제 도구 실행
class MCPToolAdapter(Tool):
    async def execute(self, input_data: dict, context: ToolContext) -> ToolResult:
        """MCP 서버에 tool call 전달"""
        result = await self.connection.call_tool(
            name=self.mcp_tool_name,
            arguments=input_data,
        )
        return ToolResult(output=json.dumps(result))
```

**의존성 추가**: `mcp` SDK 패키지를 `pyproject.toml`에 추가

**지원해야 할 MCP 구조 (Geny 호환):**
1. `built_in` MCP — 항상 연결
2. `custom` MCP — 프리셋 기반 필터링 후 연결
3. `proxy` MCP — Geny의 Python 도구를 MCP 프로토콜로 노출 (기존 방식 유지 가능)

#### Task 0-3: 세션 지속성 구현

`src/geny_executor/session/` 확장:

```python
# persistence.py — 새 파일
class FileSessionPersistence:
    """파일 기반 세션 상태 저장"""
    
    def __init__(self, storage_root: Path):
        self.storage_root = storage_root
    
    def save_state(self, session_id: str, state: PipelineState):
        """세션 상태를 디스크에 저장"""
        path = self.storage_root / session_id / ".pipeline_state.json"
        # conversation history (messages array)
        # token usage stats
        # last execution timestamp
        # memory references
        
    def load_state(self, session_id: str) -> Optional[PipelineState]:
        """디스크에서 세션 상태 복원"""
        path = self.storage_root / session_id / ".pipeline_state.json"
        if not path.exists():
            return None
        # PipelineState 재구성
        
    def resume(self, session_id: str, pipeline: Pipeline) -> Session:
        """이전 대화를 이어서 새 세션 생성"""
        state = self.load_state(session_id)
        if state:
            session = Session(pipeline, state=state)
        else:
            session = Session(pipeline)
        return session
```

**CLI `--resume` 대응:**
- 이전 대화의 messages 배열을 PipelineState에 복원
- s02_context 스테이지가 복원된 messages를 로드
- 연속 대화 컨텍스트 유지

#### Task 0-4: ToolContext 확장

```python
@dataclass
class ToolContext:
    session_id: str
    working_dir: str                    # 기존
    metadata: Dict[str, Any]            # 기존
    storage_path: Optional[str] = None  # 추가: 세션 저장소 경로
    env_vars: Optional[Dict[str, str]] = None  # 추가: 환경변수
    allowed_paths: Optional[List[str]] = None  # 추가: 허용 경로 (보안)
```

---

### Phase 1: Geny 백엔드 통합 (geny-executor 확장 후)

> **작업 위치**: `/home/geny-workspace/Geny/backend/`

#### Task 1-1: agent_session.py — Pipeline-Only 전환

**제거할 코드:**
- `_build_graph()` 내 `GENY_FORCE_LANGGRAPH` 분기 (line 912-927)
- `_build_graph_langgraph()` 메서드 전체 (line 1113-1130)
- `invoke()` 내 `_graph.ainvoke()` 분기 (line 1480-1550)
- `astream()` 내 `_graph.astream()` 분기 (line 1636-1760)
- `_legacy_execute()` 메서드 (line 1794+)
- `ClaudeProcess` import 및 참조

**수정할 코드:**
```python
# _build_graph() → _build_pipeline()으로 단순화
def _build_execution_backend(self):
    """Build the geny-executor pipeline. No fallback."""
    self._load_workflow_definition()
    self._build_pipeline()
    # _build_pipeline() 실패 시 → 에러 발생 (폴백 없음)

# invoke() 단순화
async def invoke(self, input_text: str, **kwargs):
    assert self._pipeline is not None, "Pipeline not initialized"
    return await self._invoke_pipeline(input_text, ...)

# astream() 단순화
async def astream(self, input_text: str, **kwargs):
    assert self._pipeline is not None, "Pipeline not initialized"
    async for event in self._astream_pipeline(input_text, ...):
        yield event
```

#### Task 1-2: agent_session.py — CLI 프로세스 spawn 제거

**현재:** `AgentSession.create()` → `ClaudeCLIChatModel.initialize()` → ClaudeProcess spawn

**변경후:**
```python
@classmethod
async def create(cls, ...):
    session = cls(...)
    # ClaudeCLIChatModel 생성 제거
    # 대신 storage_path만 설정
    session._storage_path = storage_path
    session._build_pipeline()  # Pipeline만 빌드
    return session
```

#### Task 1-3: agent_session.py — revive() 수정

**현재:** 프로세스 죽으면 ClaudeProcess 재생성
**변경후:** Pipeline은 stateless API 호출이므로 revive 불필요. 세션 상태만 복원.

```python
async def revive(self):
    """Pipeline 모드에서는 상태 복원만 수행"""
    if self._pipeline is None:
        self._build_pipeline()
    self._status = SessionStatus.RUNNING
    return True
```

#### Task 1-4: agent_session_manager.py — 생성 흐름 정리

- `ClaudeProcess` 관련 코드 제거
- `_local_processes` dict 제거
- `from_process()`, `get_process()` 메서드 제거
- 빌트인 도구를 geny-executor ToolRegistry에 직접 등록

#### Task 1-5: _build_pipeline() 수정 — 코어 도구 포함

```python
def _build_pipeline(self):
    from geny_executor.memory import GenyPresets
    from geny_executor.tools.built_in import (
        ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool,
    )
    
    # 1. 코어 빌트인 도구 등록
    core_tools = ToolRegistry()
    core_tools.register(ReadTool(working_dir=self._storage_path))
    core_tools.register(WriteTool(working_dir=self._storage_path))
    core_tools.register(EditTool(working_dir=self._storage_path))
    core_tools.register(BashTool(working_dir=self._storage_path))
    core_tools.register(GlobTool(working_dir=self._storage_path))
    core_tools.register(GrepTool(working_dir=self._storage_path))
    
    # 2. Geny 커스텀 도구 등록 (기존 tool_bridge)
    if self._geny_tool_registry:
        core_tools.merge(self._geny_tool_registry)
    
    # 3. MCP 도구 연결
    if self._mcp_config:
        mcp_manager = MCPManager()
        await mcp_manager.connect_all(self._mcp_config)
        core_tools.merge(mcp_manager.registry)
    
    # 4. Preset 빌드
    self._pipeline = GenyPresets.worker_full(
        api_key=api_key,
        tools=core_tools,
        ...
    )
```

---

### Phase 2: CLI 의존성 완전 제거

> **작업 위치**: `/home/geny-workspace/Geny/backend/`

#### Task 2-1: 파일 삭제/보관

| 파일 | 조치 |
|------|------|
| `service/claude_manager/process_manager.py` | 삭제 (deprecated/ 폴더로 이동) |
| `service/claude_manager/session_manager.py` | ClaudeProcess 의존성 제거 |
| `service/langgraph/claude_cli_model.py` | 삭제 |
| `service/claude_manager/cli_discovery.py` | 삭제 |
| `service/claude_manager/stream_parser.py` | 삭제 (Pipeline은 자체 이벤트 사용) |

#### Task 2-2: Dockerfile 정리

```dockerfile
# 제거:
# npm install -g @anthropic-ai/claude-code
# Node.js 설치 관련 전체 블록

# 유지:
# Python 3.12-slim 기본 이미지
# pip install -r requirements.txt (geny-executor 포함)
```

#### Task 2-3: docker-compose 정리

- `GENY_FORCE_LANGGRAPH` 환경변수 참조 제거
- `ANTHROPIC_API_KEY` 필수 환경변수로 문서화

---

### Phase 3: 스트리밍 통합

> Pipeline 이벤트 → session_logger → WebSocket/SSE

#### Task 3-1: Pipeline 이벤트를 session_logger에 연동

```python
# _invoke_pipeline() 수정
async def _invoke_pipeline(self, input_text, start_time, session_logger, **kwargs):
    # 스트리밍 모드로 실행하여 이벤트를 session_logger에 기록
    async for event in self._pipeline.run_stream(input_text):
        if event.type == "tool.execute_start":
            session_logger.log_tool_use(
                tool_name=event.data.get("tool_name"),
                tool_input=event.data.get("input"),
            )
        elif event.type == "tool.execute_complete":
            session_logger.log(
                level=LogLevel.TOOL_RES,
                message=f"Tool result: {event.data.get('output', '')[:200]}",
                metadata={"tool_name": event.data.get("tool_name")},
            )
        elif event.type == "stage.enter":
            session_logger.log(
                level=LogLevel.GRAPH,
                message=f"Stage enter: {event.data.get('stage_name')}",
                metadata={"event_type": "node_enter", "node_name": event.data.get("stage_name")},
            )
        elif event.type == "stage.exit":
            session_logger.log(
                level=LogLevel.GRAPH,
                message=f"Stage exit: {event.data.get('stage_name')}",
                metadata={"event_type": "node_exit", "node_name": event.data.get("stage_name")},
            )
        elif event.type == "text.delta":
            # 텍스트 청크 — 최종 출력에 누적
            pass
        elif event.type == "pipeline.complete":
            # 완료
            break
```

이렇게 하면 기존 WebSocket/SSE 폴링 방식이 **그대로 동작**.
`session_logger.get_cache_entries_since()` → `ws/execute_stream.py` → 클라이언트.

#### Task 3-2: broadcast에서 thinking_preview 개선

```python
# chat_controller.py의 _poll_logs()
# Pipeline 이벤트가 session_logger에 GRAPH/TOOL 레벨로 기록되므로
# 기존 _extract_thinking_preview()가 그대로 동작
```

---

## 5. 구현 순서 및 의존성

```
Phase 0 (geny-executor 확장) ─────────────────────────────────
  │
  ├── Task 0-1: 빌트인 도구 (Read/Write/Edit/Bash/Glob/Grep)
  │     └── ToolContext 확장 (Task 0-4) 선행
  │
  ├── Task 0-2: MCP 완전 구현
  │     └── mcp SDK 의존성 추가
  │
  ├── Task 0-3: 세션 지속성
  │     └── FileSessionPersistence
  │
  └── Task 0-4: ToolContext 확장

Phase 1 (Geny 통합) ──────────── Phase 0 완료 후 ──────────────
  │
  ├── Task 1-1: agent_session.py Pipeline-Only
  ├── Task 1-2: CLI spawn 제거
  ├── Task 1-3: revive() 수정
  ├── Task 1-4: session_manager 정리
  └── Task 1-5: _build_pipeline() 코어 도구 포함

Phase 2 (정리) ──────────────── Phase 1 완료 후 ──────────────
  │
  ├── Task 2-1: 레거시 파일 삭제
  ├── Task 2-2: Dockerfile 정리
  └── Task 2-3: docker-compose 정리

Phase 3 (스트리밍) ──────────── Phase 1 완료 후 (병렬 가능) ───
  │
  ├── Task 3-1: Pipeline 이벤트 → session_logger
  └── Task 3-2: broadcast thinking_preview
```

---

## 6. 최종 아키텍처 (목표)

```
┌──────────────────────────────────────────────────────────────┐
│                   Agent Execution Flow (After)                │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  execute_command()                                             │
│       │                                                        │
│       ▼                                                        │
│  agent.invoke()                                                │
│       │                                                        │
│       ▼                                                        │
│  self._pipeline.run()         ← geny-executor Pipeline        │
│       │                                                        │
│       ├── s01: Input validation                                │
│       ├── s02: Context (memory retrieval)                      │
│       ├── s03: System prompt                                   │
│       ├── s04: Guard (budget, rate limit)                      │
│       ├── s05: Cache (prompt caching)                          │
│       ├── s06: API call  ──→  Anthropic API (직접)             │
│       ├── s07: Token tracking                                  │
│       ├── s08: Think (extended thinking)                       │
│       ├── s09: Parse response                                  │
│       ├── s10: Tool execution  ──→  도구 실행                  │
│       │    ├── ReadTool, WriteTool, EditTool    (빌트인)       │
│       │    ├── BashTool, GlobTool, GrepTool     (빌트인)       │
│       │    ├── GenySessionListTool, ...          (Geny 도구)   │
│       │    ├── MemoryWriteTool, ...              (메모리 도구) │
│       │    ├── WebSearchTool, BrowserTool        (커스텀 도구) │
│       │    └── MCP Tool (github, notion, ...)    (MCP 연동)   │
│       ├── s11: Agent orchestration                             │
│       ├── s12: Evaluate (completion check)                     │
│       ├── s13: Loop (continue or finish)                       │
│       ├── s14: Emit (output + avatar state)                    │
│       ├── s15: Memory (persist conversation)                   │
│       └── s16: Yield (final result)                            │
│                                                                │
│  ◆ ClaudeProcess      → 제거                                  │
│  ◆ LangGraph          → 제거                                  │
│  ◆ CLI subprocess     → 제거                                  │
│  ◆ GENY_FORCE_LANGGRAPH → 제거                                │
│  ◆ claude-code npm    → 제거                                  │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 7. 위험 관리

| 위험 | 대응 | 상태 |
|------|------|------|
| API key 필수화 | 시작 시 검증, 명확한 에러 메시지 | Phase 1에서 처리 |
| MCP 구현 복잡도 | `mcp` SDK 활용, 단계적 transport 지원 (stdio 우선) | Phase 0-2 |
| 세션 지속성 | FileSessionPersistence + PipelineState 직렬화 | Phase 0-3 |
| 기존 세션 호환 | 마이그레이션 스크립트로 기존 세션 데이터 변환 | Phase 2 |
| 파일 시스템 보안 | ToolContext.allowed_paths + working_dir 제한 | Phase 0-1 |
| 성능 차이 | CLI는 상주 프로세스, Pipeline은 stateless → 세션 캐시로 보완 | Phase 0-3 |
| 도구 호환성 | tool_bridge.py 유지, 기존 BaseTool 인터페이스 불변 | 영향 없음 |
