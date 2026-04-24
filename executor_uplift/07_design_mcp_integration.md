# 07. Design — MCP Integration Uplift

**Status:** Draft
**Date:** 2026-04-24
**Priority:** P1 (runtime dynamism, resource/prompt, FSM) + P2 (transports, OAuth)

---

## 1. 목표

현재 MCP 레이어를 다음 방향으로 확장:

1. **Transport 다양화** — stdio / HTTP / SSE + WebSocket + SDK-managed + claudeai-proxy
2. **Connection FSM** — 5 상태 (Connected / Failed / NeedsAuth / Pending / Disabled) 로 상태 명시
3. **런타임 add/remove** — 프로세스 재시작 없이 서버 핫 플러그
4. **OAuth 자동 흐름** — callback port + credential 보관 (keychain 기반)
5. **Resource / Prompt 지원** — tool 만이 아니라 MCP 의 세 capability 전부
6. **Skill bridge** — MCP prompt 를 자동으로 skill 로 노출 (08 design 연동)

뼈대는 `geny-executor/src/geny_executor/tools/mcp/` 아래. Geny 측은 config 레이어 (`MCPLoader`, `tool_policy`) 만 변경.

---

## 2. Transport 추상화

```python
# geny_executor/tools/mcp/transports.py

from abc import ABC, abstractmethod
from typing import AsyncIterator

class MCPTransport(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def send(self, message: dict) -> None: ...

    @abstractmethod
    def receive(self) -> AsyncIterator[dict]: ...

    @abstractmethod
    async def close(self) -> None: ...

    @property
    @abstractmethod
    def is_alive(self) -> bool: ...


class StdioTransport(MCPTransport):
    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        ...
    # subprocess spawn + stdin/stdout JSON-RPC

class HttpTransport(MCPTransport):
    def __init__(self, url: str, headers: dict[str, str]):
        ...
    # httpx AsyncClient + request/response pairing

class SseTransport(MCPTransport):
    # Server-Sent Events — HTTP 스트리밍 수신

class WebSocketTransport(MCPTransport):
    # websockets 라이브러리

class SdkManagedTransport(MCPTransport):
    """Anthropic SDK 관리 (google-drive, github 등).

    실제 connection 은 Anthropic 측이 관리. 우리는 SDK proxy 를 통해 호출.
    """
    def __init__(self, sdk_server_name: str):
        ...

class ClaudeAIProxyTransport(MCPTransport):
    """claude.ai 가 호스트하는 MCP 서버로 프록시."""
    ...
```

설정 스키마 (`sessions/models.py` 수정):

```python
class MCPServerStdio(BaseModel):
    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str]
    env: Optional[dict[str, str]] = None

class MCPServerHttp(BaseModel):
    type: Literal["http"] = "http"
    url: str
    headers: Optional[dict[str, str]] = None

class MCPServerSse(BaseModel):
    type: Literal["sse"] = "sse"
    url: str
    headers: Optional[dict[str, str]] = None

class MCPServerWebSocket(BaseModel):
    type: Literal["ws"] = "ws"
    url: str
    headers: Optional[dict[str, str]] = None

class MCPServerSdk(BaseModel):
    type: Literal["sdk"] = "sdk"
    sdk_server_name: str   # "google-drive" | "github" | ...
    auth: Optional[dict] = None

class MCPServerClaudeaiProxy(BaseModel):
    type: Literal["claudeai-proxy"] = "claudeai-proxy"
    proxy_url: str
    proxy_token: str

MCPServerConfig = Union[
    MCPServerStdio, MCPServerHttp, MCPServerSse,
    MCPServerWebSocket, MCPServerSdk, MCPServerClaudeaiProxy,
]
```

---

## 3. Connection FSM

```python
# geny_executor/tools/mcp/connection.py

from enum import Enum
from dataclasses import dataclass

class MCPConnectionState(str, Enum):
    CONNECTED    = "connected"
    FAILED       = "failed"
    NEEDS_AUTH   = "needs_auth"
    PENDING      = "pending"     # 재연결 시도 중
    DISABLED     = "disabled"    # 사용자가 껐음

@dataclass
class MCPConnection:
    server_name: str
    config: MCPServerConfig
    state: MCPConnectionState
    transport: Optional[MCPTransport]   # CONNECTED 에서만 유효

    # CONNECTED 에서
    capabilities: Optional[dict] = None      # {tools: True, resources: True, prompts: True}
    instructions: Optional[str] = None       # 서버가 반환한 메타

    # FAILED / NEEDS_AUTH 에서
    last_error: Optional[str] = None

    # PENDING 에서
    reconnect_attempt: int = 0
    max_reconnect_attempts: int = 5

    # 공통 메타
    tools: list[Tool] = field(default_factory=list)
    resources: list[dict] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
```

상태 전이:

```
DISABLED ──▶ PENDING ──▶ CONNECTED ──▶ (정상 동작)
                 │            │
                 │            └──▶ FAILED   (exception)
                 └──▶ NEEDS_AUTH  (401/403)
                         │
                         └──▶ CONNECTED (auth 완료 후)

CONNECTED ──(재연결 필요)──▶ PENDING ──▶ CONNECTED
CONNECTED ──(사용자 disable)──▶ DISABLED
FAILED    ──(재시도)──▶ PENDING
```

---

## 4. MCPManager 2.0

```python
# geny_executor/tools/mcp/manager.py

class MCPManager:
    """Connection pool + lifecycle + runtime add/remove."""

    def __init__(self, event_bus: EventBus):
        self._connections: dict[str, MCPConnection] = {}
        self._bus = event_bus
        self._lock = asyncio.Lock()

    # ── Batch 초기화 ─────────────────────────────────
    async def connect_all(self, configs: dict[str, MCPServerConfig]) -> None:
        tasks = [self.register_server(name, cfg) for name, cfg in configs.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # 실패한 서버는 FAILED 상태로 남아있지만 나머지는 동작

    # ── 런타임 add ────────────────────────────────────
    async def register_server(self, name: str, config: MCPServerConfig) -> MCPConnection:
        async with self._lock:
            if name in self._connections:
                raise ValueError(f"server already registered: {name}")
            conn = MCPConnection(
                server_name=name, config=config,
                state=MCPConnectionState.PENDING,
                transport=None,
            )
            self._connections[name] = conn
        self._bus.emit("mcp.server.registered", {"server": name, "type": config.type})
        await self._try_connect(conn)
        return conn

    # ── 런타임 remove ─────────────────────────────────
    async def unregister_server(self, name: str, *, graceful: bool = True):
        async with self._lock:
            conn = self._connections.get(name)
            if not conn:
                return
            if graceful:
                await self._drain_pending_calls(conn)
            if conn.transport:
                await conn.transport.close()
            del self._connections[name]
        self._bus.emit("mcp.server.unregistered", {"server": name})

    # ── 토글 ──────────────────────────────────────────
    async def disable(self, name: str):
        async with self._lock:
            conn = self._connections.get(name)
            if not conn: return
            if conn.transport: await conn.transport.close()
            conn.state = MCPConnectionState.DISABLED
            conn.transport = None
        self._bus.emit("mcp.server.disabled", {"server": name})

    async def enable(self, name: str):
        async with self._lock:
            conn = self._connections.get(name)
            if not conn: return
            if conn.state != MCPConnectionState.DISABLED: return
            conn.state = MCPConnectionState.PENDING
        await self._try_connect(conn)

    # ── Tool discovery ─────────────────────────────────
    def list_tools(self) -> list[Tool]:
        """모든 CONNECTED 서버의 tool 을 평면 리스트로."""
        out = []
        for conn in self._connections.values():
            if conn.state == MCPConnectionState.CONNECTED:
                out.extend(conn.tools)
        return out

    # ── Resource / Prompt ─────────────────────────────
    def list_resources(self) -> list[dict]:
        return [r for c in self._connections.values() if c.state == CONNECTED for r in c.resources]

    def list_prompts(self) -> list[dict]:
        return [p for c in self._connections.values() if c.state == CONNECTED for p in c.prompts]

    async def read_resource(self, uri: str) -> str:
        # URI 에서 server 추출, 해당 transport 로 MCP resource/read 호출
        ...

    async def get_prompt(self, name: str, args: dict) -> list[dict]:
        # MCP prompt/get — skill bridge 가 이 걸 사용
        ...

    # ── 내부 ──────────────────────────────────────────
    async def _try_connect(self, conn: MCPConnection) -> None:
        transport = make_transport(conn.config)
        try:
            await transport.connect()
            # handshake
            init_result = await _send_initialize(transport)
            caps = init_result.get("capabilities", {})
            instructions = init_result.get("instructions")
            # discover
            tools = await _discover_tools(transport, conn.server_name) if caps.get("tools") else []
            resources = await _discover_resources(transport) if caps.get("resources") else []
            prompts = await _discover_prompts(transport) if caps.get("prompts") else []

            conn.state = MCPConnectionState.CONNECTED
            conn.transport = transport
            conn.capabilities = caps
            conn.instructions = instructions
            conn.tools = tools
            conn.resources = resources
            conn.prompts = prompts
            self._bus.emit("mcp.server.connected", {"server": conn.server_name, "tool_count": len(tools)})

        except AuthRequired as e:
            conn.state = MCPConnectionState.NEEDS_AUTH
            conn.last_error = str(e)
            self._bus.emit("mcp.server.needs_auth", {"server": conn.server_name})
        except Exception as e:
            conn.state = MCPConnectionState.FAILED
            conn.last_error = str(e)
            self._bus.emit("mcp.server.failed", {"server": conn.server_name, "error": str(e)})
```

### 관찰

- 모든 상태 변경이 EventBus 로 방출 → UI 대시보드가 실시간 표시 가능
- `disable`/`enable` 은 설정 편집 없이 런타임 토글
- tool 평면 리스트는 "CONNECTED 서버의 tool" 만 반환 → Stage 3 에서 그대로 레지스트리에 등록

---

## 5. MCP Tool Adapter — Tool ABC 에 맞춤

```python
# geny_executor/tools/mcp/adapter.py

class MCPToolAdapter(Tool):
    """MCP 서버의 tool 을 Tool ABC 로 래핑."""

    is_mcp = True

    def __init__(self, server_name: str, tool_def: dict, manager: MCPManager):
        self._server = server_name
        self._raw = tool_def
        self._manager = manager
        self.name = f"mcp__{server_name}__{tool_def['name']}"
        self.description = tool_def.get("description", "")
        self.mcp_info = {"serverName": server_name, "toolName": tool_def["name"]}
        self._schema = tool_def.get("inputSchema", {})

    def input_schema(self) -> dict:
        return self._schema

    def capabilities(self, input: dict) -> ToolCapabilities:
        # MCP 서버 자체가 annotation 으로 hint 주면 사용
        ann = self._raw.get("annotations", {})
        return ToolCapabilities(
            concurrency_safe = ann.get("readOnlyHint", False),
            read_only         = ann.get("readOnlyHint", False),
            destructive       = ann.get("destructiveHint", False),
            idempotent        = ann.get("idempotentHint", False),
            network_egress    = True,   # MCP 는 외부 I/O
        )

    async def check_permissions(self, input, ctx):
        # Geny ToolPolicyEngine 은 MCP 서버 단위에서 이미 필터링함.
        # 여기서는 input-pattern 체크만.
        return PermissionDecision(behavior="allow")

    async def execute(self, input, ctx, *, on_progress=None) -> ToolResult:
        conn = self._manager._connections.get(self._server)
        if not conn or conn.state != MCPConnectionState.CONNECTED:
            return ToolResult(
                data=None, is_error=True,
                display_text=f"MCP server '{self._server}' not available (state={conn.state if conn else 'unknown'})"
            )
        try:
            response = await _call_mcp_tool(
                conn.transport, self._raw["name"], input
            )
            content = response.get("content", [])
            text = _content_to_text(content)
            return ToolResult(
                data=response,
                display_text=text,
                mcp_meta={"structuredContent": response.get("structuredContent"), "_meta": response.get("_meta")},
            )
        except Exception as e:
            return ToolResult(data=None, is_error=True, display_text=str(e))
```

### MCP annotation 활용

MCP 1.0 spec 에 tool annotation 이 있음 (`readOnlyHint`, `destructiveHint`, `idempotentHint`). 이를 `ToolCapabilities` 로 자동 매핑 → concurrency partition 에 바로 반영됨. 이는 Tool ABC 가 없으면 불가능하던 것.

---

## 6. OAuth 흐름

MCP 서버가 OAuth 요구 (e.g. Google Drive) 시의 흐름:

```
1. register_server("gdrive", SdkConfig(sdk_server_name="google-drive"))
2. _try_connect → AuthRequired 예외
3. state = NEEDS_AUTH, emit "mcp.server.needs_auth"
4. 외부 (UI 또는 사용자) 가 URL 을 열고 OAuth consent
5. callback port (e.g. localhost:9876) 로 code 수신
6. token 을 exchange → credential 을 keychain 에 저장
7. 다시 _try_connect → CONNECTED
```

구현 스케치:

```python
# geny_executor/tools/mcp/oauth.py

class OAuthFlow:
    def __init__(self, callback_port: int, keychain):
        self._port = callback_port
        self._keychain = keychain

    async def authorize(self, server_name: str, auth_config: dict) -> str:
        # 1. 임시 HTTP server 시작 (on callback_port)
        # 2. 사용자에게 authorize URL 노출 (CLI: print, UI: pop modal)
        # 3. code 수신 대기
        # 4. exchange for token
        # 5. keychain.store(f"mcp:{server_name}", token_blob)
        # 6. return token
        ...

    def load_cached_token(self, server_name: str) -> Optional[str]:
        return self._keychain.get(f"mcp:{server_name}")
```

**보안**:
- 기본 callback port 는 `localhost` 바인딩만
- `state` 파라미터로 CSRF 방지
- token 은 OS keychain (macOS Keychain / gnome-keyring / Windows Credential Locker) 우선, 없으면 파일 (암호화).

---

## 7. Resource 지원

MCP resource 는 "LLM 이 읽을 수 있는 파일-유사 entity":

```
mcp://github/{owner}/{repo}/README.md
mcp://gdrive/document/{id}
```

Stage 2 (Context) 에서 활용:

```python
class MCPResourceRetriever(Strategy):
    """Stage 2 의 retriever slot 에 들어감. MCP resource 를 fetch 해 context 에 추가."""

    def __init__(self, manager: MCPManager):
        self._mgr = manager

    async def retrieve(self, query: RetrievalQuery, state) -> list[str]:
        # query.memory_refs 에 포함된 mcp:// URI 들을 읽어옴
        chunks = []
        for ref in state.memory_refs:
            if ref.startswith("mcp://"):
                content = await self._mgr.read_resource(ref)
                chunks.append(content)
        return chunks
```

---

## 8. Prompt 지원 + Skill bridge

MCP 서버가 prompt 를 노출하면 (`prompts/list` + `prompts/get`), 이걸 **Skill 로 자동 변환**.

```python
# geny_executor/skills/mcp_bridge.py (08 design 과 연동)

async def mcp_prompts_to_skills(manager: MCPManager) -> list[Skill]:
    skills = []
    for server_name, conn in manager._connections.items():
        if conn.state != MCPConnectionState.CONNECTED:
            continue
        for prompt_def in conn.prompts:
            skill = Skill(
                name=f"mcp__{server_name}__{prompt_def['name']}",
                description=prompt_def.get("description", ""),
                loaded_from="mcp",
                when_to_use=prompt_def.get("whenToUse"),
                argument_hint=prompt_def.get("argumentHint"),
                # Resolve 시 MCP prompt/get 호출
                get_prompt=lambda args, ctx: manager.get_prompt(prompt_def["name"], args),
            )
            skills.append(skill)
    return skills
```

상세는 08 design 참조.

---

## 9. Geny 측 변경

### 9.1 `service/mcp_loader.py` → 새 MCPManager 사용

```python
# 기존 build_session_mcp_config 는 유지 (설정 조합만 담당)
# 실제 manager 는 runtime 에서 주입

class MCPLoader:
    def __init__(self, mcp_dir: Path):
        ...
        # 1) JSON 로드 (변경 없음)

    async def build_manager(
        self, session_mcp_config: MCPConfig, event_bus: EventBus
    ) -> MCPManager:
        """세션 수준 MCPManager 반환."""
        mgr = MCPManager(event_bus)
        await mgr.connect_all(dict(session_mcp_config.servers))
        return mgr
```

### 9.2 `AgentSession` 가 manager 를 attach

```python
# service/executor/agent_session.py _build_pipeline

mcp_manager = await mcp_loader.build_manager(session_mcp_config, self._event_bus)
attach_kwargs["mcp_manager"] = mcp_manager

# Pipeline.attach_runtime 에 mcp_manager kwarg 추가 필요 (executor API 확장)
```

### 9.3 `Pipeline.attach_runtime` 시그니처 확장

```python
def attach_runtime(
    self,
    *,
    llm_client: Optional[BaseClient] = None,
    tools: Optional[list[Tool]] = None,
    tool_context: Optional[ToolContext] = None,
    system_builder: Optional[Callable] = None,
    memory_retriever: Optional[Retriever] = None,
    memory_strategy: Optional[MemoryStrategy] = None,
    memory_persistence: Optional[Persistence] = None,
    session_runtime: Optional[Any] = None,
    mcp_manager: Optional[MCPManager] = None,   # NEW
):
    self._mcp_manager = mcp_manager
    ...
```

Stage 3 (System) 의 tool 등록이 `mcp_manager.list_tools()` 로 MCP tool 을 자동 포함.

---

## 10. API 요약

```python
# geny_executor 공개
from geny_executor.tools.mcp import (
    MCPManager,
    MCPConnection,
    MCPConnectionState,
    MCPTransport,              # ABC
    StdioTransport, HttpTransport, SseTransport,
    WebSocketTransport, SdkManagedTransport, ClaudeAIProxyTransport,
    MCPToolAdapter,
    OAuthFlow,
)
```

## 11. 테스트 전략

| 테스트 | 목적 |
|---|---|
| Transport 별 connect/close | 각 transport 의 기본 흐름 |
| FSM 전이 | 5 상태 × 이벤트 조합 |
| Runtime add/remove | in-flight 요청 graceful 처리 |
| OAuth 흐름 | callback port mocking + token 저장 |
| Annotation → Capability | MCP annotation 별 ToolCapabilities 결과 |
| Resource fetch | mcp:// URI → content |
| Prompt → Skill 변환 | 메타 보존 확인 |
| 서버 실패 격리 | 한 서버 failure 가 다른 서버에 영향 없음 |

---

## 12. 다음 문서

- [`08_design_skills.md`](08_design_skills.md) — MCP prompt 를 skill 로 자동 노출하는 부분이 여기와 맞물림
- [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) — Stage 3 (tool 레지스트리) 와 Stage 2 (MCPResourceRetriever) 가 어떻게 엮이는지
