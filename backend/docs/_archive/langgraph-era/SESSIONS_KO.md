# Session Management

> Claude CLI 서브프로세스 → LangChain 모델 → LangGraph StateGraph 기반의 에이전트 세션 생명주기 관리

## 아키텍처 개요

```
AgentSessionManager (최상위 관리자)
        │
        ├── AgentSession (세션별 인스턴스)
        │     ├── ClaudeCLIChatModel (LangChain BaseChatModel)
        │     │     └── ClaudeProcess (CLI 서브프로세스)
        │     ├── CompiledStateGraph (LangGraph 그래프)
        │     │     └── WorkflowDefinition → WorkflowExecutor
        │     ├── SessionMemoryManager (장기 + 단기 메모리)
        │     └── SessionFreshness (유휴 감지 / 자동 부활)
        │
        ├── SessionStore (영속 메타데이터 — PostgreSQL + JSON)
        ├── SessionLogger (로깅)
        └── Idle Monitor (백그라운드 유휴 스캔)
```

---

## 세션 상태 머신

```
STARTING → RUNNING → IDLE → RUNNING (자동 부활)
    │          │         │
    ↓          ↓         ↓
  ERROR      ERROR    STOPPED
```

| 상태 | 설명 |
|------|------|
| `STARTING` | 초기화 중 |
| `RUNNING` | 활성 — 명령 수신/실행 가능 |
| `IDLE` | 유휴 — 다음 호출 시 자동 부활 |
| `STOPPED` | 정상 종료 |
| `ERROR` | 오류 발생 |

유휴 모니터는 60초 간격으로 실행되며, `RUNNING` 상태이면서 실행 중이 아닌 세션을 `IDLE`로 전환. `IDLE` 세션은 다음 `invoke()` 호출 시 자동 부활.

---

## ClaudeProcess

개별 Claude CLI 서브프로세스 관리자.

### 초기화

```python
process = ClaudeProcess(
    session_id="abc123",
    session_name="Developer Session",
    working_dir="/workspace/project",
    model="claude-sonnet-4-20250514",
    max_turns=100,
    timeout=21600.0,
    mcp_config=mcp_config,
    system_prompt="You are a developer...",
    role="developer"
)
await process.initialize()
```

초기화 시:
1. 저장소 디렉토리 생성 (`{STORAGE_ROOT}/{session_id}`)
2. 세션 정보 파일 작성
3. `.mcp.json` 생성 (MCP 서버 설정)
4. Claude CLI 발견 (node.exe + cli.js 경로)
5. 상태를 `RUNNING`으로 전환

### 실행

```python
result = await process.execute(
    prompt="파이썬 웹 서버 만들어줘",
    timeout=300,
    skip_permissions=True,
    resume=True  # 이전 대화 이어가기
)
```

**실행 흐름:**
1. `_execution_lock` 획득 (동시 실행 방지)
2. 환경 변수 빌드 (OS + Claude + Git 인증)
3. CLI 인수 구성: `--print --verbose --output-format stream-json`
4. 자동 이어가기: `_execution_count > 0`이면 `--resume {conversation_id}` 추가
5. 보안 플래그: `--dangerously-skip-permissions`
6. 노드 직접 명령 빌드: `[node.exe, cli.js, ...args]`
7. 서브프로세스 시작 → stdin에 프롬프트 기록
8. stdout/stderr 동시 읽기 (타임아웃 적용)
9. `StreamParser`로 각 줄 파싱
10. `WORK_LOG.md`에 기록
11. 결과 반환

### 결과 형식

```python
{
    "success": True,
    "output": "최종 출력 텍스트",
    "error": None,
    "duration_ms": 3500,
    "cost_usd": 0.0234,
    "tool_calls": [{"id": "...", "name": "Write", "input": {...}}],
    "num_turns": 3,
    "model": "claude-sonnet-4-20250514",
    "stop_reason": "end_turn"
}
```

### Git 인증

`_setup_git_auth_env()` — `GITHUB_TOKEN` 환경 변수를 감지하여:
- `GH_TOKEN` 설정
- `GIT_TERMINAL_PROMPT=0`
- `GIT_CONFIG_*`로 `https://x-access-token:<PAT>@github.com/` URL 리라이트 주입

---

## StreamParser

Claude CLI의 `--output-format stream-json` 출력을 한 줄씩 파싱.

### 이벤트 타입

| 이벤트 | 설명 |
|--------|------|
| `SYSTEM_INIT` | 초기화 (모델, 도구, MCP 서버 정보) |
| `ASSISTANT_MESSAGE` | 어시스턴트 메시지 (텍스트, 도구 사용 블록) |
| `TOOL_USE` | 도구 호출 시작 |
| `TOOL_RESULT` | 도구 실행 결과 |
| `CONTENT_BLOCK_START` / `DELTA` / `STOP` | 스트리밍 텍스트 |
| `RESULT` | 실행 완료 (소요 시간, 비용, 턴 수) |
| `ERROR` | 오류 |

### ExecutionSummary

```python
@dataclass
class ExecutionSummary:
    model: str
    available_tools: List[str]
    mcp_servers: List[str]
    tool_calls: List[Dict]
    assistant_messages: List[str]
    final_output: str
    success: bool
    is_error: bool
    error_message: str
    duration_ms: int
    total_cost_usd: float
    num_turns: int
    usage: Dict
    stop_reason: str
```

---

## ClaudeCLIChatModel

`ClaudeProcess`를 LangChain `BaseChatModel`로 래핑.

```
LangGraph StateGraph
    │
    ▼
ClaudeCLIChatModel._agenerate(messages)
    │
    ▼
ClaudeProcess.execute(prompt)
    │
    ▼
Claude CLI 서브프로세스
```

- `_agenerate(messages)`: 메시지를 프롬프트로 변환 → `process.execute()` → `AIMessage`로 래핑
- `cost_usd`는 `AIMessage.additional_kwargs`에 포함
- `_llm_type = "claude-cli"`

---

## AgentSession

`CompiledStateGraph` 기반 세션. ClaudeProcess + LangGraph + Memory 통합.

### 생성

```python
agent = await AgentSession.create(
    session_id="abc123",
    session_name="Dev Session",
    working_dir="/workspace",
    model_name="claude-sonnet-4-20250514",
    workflow_id="template-autonomous",
    role="developer",
    max_iterations=50,
    mcp_config=mcp_config,
    system_prompt="..."
)
```

### 그래프 빌드

`_build_graph()` → `_load_workflow_definition()`:

| 우선순위 | 소스 | 설명 |
|---------|------|------|
| 1 | `workflow_id` | WorkflowStore에서 명시적 ID로 로드 |
| 2 | `graph_name` | 이름 추론: "optimized" → `template-optimized-autonomous` 등 |
| 3 | 기본값 | `template-simple` |

`WorkflowExecutor(workflow, ExecutionContext).compile()` → `CompiledStateGraph`

### 실행 (invoke)

```python
result = await agent.invoke(
    input_text="Python 웹 서버 만들어줘",
    max_iterations=50
)
# result = {"output": "...", "total_cost": 0.0234}
```

**invoke 흐름:**
1. Freshness 체크 → 유휴면 자동 부활, 한계 초과면 ERROR
2. 프로세스 생존 확인 → 비동기 부활
3. `_is_executing = True` (유휴 모니터 차단)
4. `make_initial_autonomous_state(input_text)` 생성
5. 입력을 단기 메모리에 기록
6. `await self._graph.ainvoke(initial_state, config)`
7. `final_answer` / `answer` / `last_output` 추출
8. 실행 결과를 장기 메모리에 기록
9. 결과 반환

### 스트리밍 (astream)

```python
async for chunk in agent.astream(input_text="..."):
    # 노드별 실행 청크 수신
    ...
```

### 부활 (revive)

프로세스가 죽었을 때 자동 복구:
1. 죽은 모델 정리
2. 모델 재생성 (새 ClaudeProcess)
3. 그래프 재빌드
4. 상태를 `RUNNING`으로 복원

---

## AgentSessionManager

`AgentSession` + `SessionStore` + 유휴 모니터 통합 관리.

### 세션 생성 흐름

```python
agent = await manager.create_agent_session(CreateSessionRequest(
    session_name="My Developer",
    role="developer",
    model="claude-sonnet-4-20250514",
    workflow_id="template-autonomous",
    tool_preset_id="template-all-tools"
))
```

**생성 순서:**
1. Tool Preset 해석 → 허용 Python 도구 + MCP 서버 계산
2. 세션 MCP 설정 조립 (`build_session_mcp_config`)
3. 시스템 프롬프트 빌드 (역할 + 컨텍스트 + 메모리 + 공유 폴더)
4. `AgentSession.create()` — ClaudeProcess 스폰 + 그래프 컴파일
5. `_local_agents`와 `_local_processes`에 등록
6. DB를 메모리 관리자에 연결
7. 공유 폴더 심볼릭 링크 생성
8. SessionLogger 생성 + SessionStore 등록

### 주요 메서드

| 메서드 | 설명 |
|--------|------|
| `create_agent_session(request)` | 풀 생성 흐름 |
| `get_agent(session_id)` | 에이전트 조회 |
| `delete_session(session_id)` | 정리 + 소프트 삭제 |
| `cleanup_dead_sessions()` | 부활 시도 → 실패 시 삭제 |
| `start_idle_monitor()` | 백그라운드 유휴 스캔 시작 |
| `stop_idle_monitor()` | 유휴 스캔 중지 |

---

## SessionStore

영속 세션 메타데이터 레지스트리.

### 이중 저장소

- **주**: PostgreSQL `sessions` 테이블
- **백업**: `sessions.json` 파일
- 모든 쓰기는 양쪽에, 읽기는 DB 우선

### 소프트 삭제 패턴

```python
store.soft_delete(session_id)    # is_deleted=True, status=stopped
store.restore(session_id)        # is_deleted=False
store.permanent_delete(session_id)  # 완전 삭제
```

### 비용 추적

```python
store.increment_cost(session_id, 0.0234)
# SQL: UPDATE sessions SET total_cost = COALESCE(total_cost, 0) + 0.0234
```

원자적 증가 — 동시 실행 안전.

---

## CLI 발견 (cli_discovery)

Claude CLI의 `node.exe` + `cli.js` 경로를 자동 발견.

### Windows

`claude.cmd` 찾기 → `node.exe` + `node_modules/@anthropic-ai/claude-code/cli.js` 경로 추론

### Unix

`claude` 바이너리 → 심볼릭 링크 해석 → `cli.js` 경로 추론

결과: `ClaudeNodeConfig(node_path, cli_js_path, base_dir)`

**핵심**: `cmd.exe`/PowerShell을 우회하여 `node.exe`로 직접 실행 — 신뢰성 향상.

---

## 플랫폼 유틸리티

| 유틸리티 | 설명 |
|---------|------|
| `IS_WINDOWS` / `IS_MACOS` / `IS_LINUX` | 플랫폼 감지 |
| `DEFAULT_STORAGE_ROOT` | 플랫폼별 세션 저장 경로 |
| `get_claude_env_vars()` | Claude 관련 환경 변수 수집 |
| `WindowsProcessWrapper` | Windows `SelectorEventLoop` 문제 우회 |
| `create_subprocess_cross_platform()` | 크로스 플랫폼 서브프로세스 생성 |

---

## API 엔드포인트

### Agent Sessions (`/api/agents`) — 주요 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/agents` | AgentSession 생성 |
| `GET` | `/api/agents` | 전체 에이전트 목록 |
| `GET` | `/api/agents/{id}` | 에이전트 조회 |
| `PUT` | `/api/agents/{id}/system-prompt` | 시스템 프롬프트 변경 |
| `DELETE` | `/api/agents/{id}` | 소프트 삭제 |
| `DELETE` | `/api/agents/{id}/permanent` | 영구 삭제 |
| `POST` | `/api/agents/{id}/restore` | 복원 |
| `POST` | `/api/agents/{id}/invoke` | LangGraph 상태 기반 실행 |
| `POST` | `/api/agents/{id}/execute` | 그래프 실행 (블로킹) |
| `POST` | `/api/agents/{id}/execute/start` | 백그라운드 실행 시작 |
| `GET` | `/api/agents/{id}/execute/events` | 실행 SSE 로그 스트림 |
| `POST` | `/api/agents/{id}/execute/stream` | 실행 + SSE 결합 |

### 저장소 조회

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/agents/store/deleted` | 소프트 삭제된 세션 |
| `GET` | `/api/agents/store/all` | 전체 저장 세션 |
| `GET` | `/api/agents/store/{id}` | 저장된 세션 메타데이터 |

### Legacy Sessions (`/api/sessions`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/sessions` | 세션 생성 |
| `GET` | `/api/sessions` | 세션 목록 |
| `GET` | `/api/sessions/{id}` | 세션 조회 |
| `DELETE` | `/api/sessions/{id}` | 세션 삭제 |
| `POST` | `/api/sessions/{id}/execute` | 실행 (블로킹) |
| `POST` | `/api/sessions/{id}/execute/stream` | 실행 (SSE) |
| `GET` | `/api/sessions/{id}/storage` | 저장소 파일 목록 |
| `GET` | `/api/sessions/{id}/storage/{path}` | 파일 읽기 |

### SSE 이벤트 타입

| 이벤트 | 설명 |
|--------|------|
| `log` | SessionLogger 로그 항목 |
| `status` | 상태 변경 (running/completed/error) |
| `result` | 실행 결과 |
| `done` | 스트림 종료 |
| `error` | 오류 |

자동 부활: 모든 실행 엔드포인트에서 `agent.is_alive()` 확인 → 필요 시 `agent.revive()` 호출.

---

## 관련 파일

```
service/claude_manager/
├── __init__.py
├── models.py               # SessionStatus, CreateSessionRequest, ExecuteResponse, MCPConfig
├── session_manager.py       # SessionManager (기본 세션 관리)
├── session_store.py         # SessionStore (영속 메타데이터 — PostgreSQL + JSON)
├── process_manager.py       # ClaudeProcess (CLI 서브프로세스)
├── stream_parser.py         # StreamParser (stream-json 파싱)
├── cli_discovery.py         # Claude CLI 자동 발견 (node.exe + cli.js)
├── platform_utils.py        # 크로스 플랫폼 유틸리티
├── storage_utils.py         # 저장소 파일 유틸리티
└── constants.py             # 상수 정의

service/executor/
├── agent_session.py          # AgentSession (LangGraph 기반 세션)
├── agent_session_manager.py  # AgentSessionManager (통합 관리)
├── claude_cli_model.py       # ClaudeCLIChatModel (LangChain 래퍼)
├── state.py                  # AutonomousState TypedDict
├── autonomous_graph.py       # 레거시 하드코딩 그래프 (대체됨)
├── context_guard.py          # ContextWindowGuard (토큰 제한)
├── model_fallback.py         # ModelFallbackRunner (모델 전환)
└── resilience_nodes.py       # 완료 시그널 파싱
```
