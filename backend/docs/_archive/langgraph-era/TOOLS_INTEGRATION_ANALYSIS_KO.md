# GenY Tools 통합 심층 분석 보고서 (v4)

> **목적**: Agent 실행 시스템에 Tools 기능(built-in / custom 분류, Tool Preset, Session별 Tool 할당)을 체계적으로 통합하기 위한 아키텍처 분석
>
> **핵심 원칙**:
> - Claude CLI는 유지한다. LLM 호출 경로는 변경하지 않는다.
> - Python으로 정의된 모든 도구의 **실제 실행**은 메인 프로세스(FastAPI)에서 이루어진다.
> - MCP는 Claude CLI와 도구 사이의 **통신 프로토콜**로만 사용한다. 도구 실행 자체는 MCP subprocess가 아니라 메인 프로세스에서 직접 수행한다.

---

## 0. 핵심 문제 분석 — 왜 현재 구조가 잘못되었는가

### 0.1 현재 도구 실행 경로

```
LangGraph 노드
  └─ _resilient_invoke(messages)
      └─ ClaudeCLIChatModel.ainvoke()
          └─ ClaudeProcess.execute(prompt)
              └─ Claude CLI (node.exe → cli.js)     ← 유지 (변경 없음)
                  └─ .mcp.json 읽기
                      └─ _builtin_tools MCP 서버 (Python subprocess #2)
                          └─ geny_tools.py 실행     ← ❌ 문제 발생
                          └─ browser_tools.py 실행
                          └─ web_search_tools.py 실행
```

### 0.2 현재의 근본적 문제

**문제 1: 프로세스 격리로 인한 싱글턴 접근 실패**

```
Python 프로세스 #1 (FastAPI 메인)
  ├─ AgentSessionManager (싱글턴)     ← geny_tools가 접근해야 하는 대상
  ├─ ChatStore (싱글턴)
  └─ ClaudeProcess.execute()
       └─ Claude CLI (Node.js subprocess)
           └─ _builtin_tools (Python 프로세스 #2)   ← 별도 프로세스!
               └─ geny_tools._get_agent_manager()
                   → 프로세스 #2의 독립 인스턴스 반환  ← ❌ 프로세스 #1의 싱글턴이 아님!
```

`_mcp_server.py`는 별도 Python subprocess로 실행된다.
이 프로세스에서 `_get_agent_manager()`를 호출하면
메인 FastAPI 프로세스의 싱글턴이 아니라 MCP 프로세스 자체의 독립 인스턴스가 반환된다.
**즉, 현재 geny_tools는 사실상 제대로 동작하지 않는다.**

**문제 2: 모든 도구가 단일 MCP 서버에 혼재**

```
_builtin_tools MCP 서버:
  ├─ geny_session_list    (GenY 플랫폼 조작 — built-in)
  ├─ geny_send_message    (GenY 플랫폼 조작 — built-in)
  ├─ web_search           (범용 도구 — custom)
  ├─ browser_navigate     (범용 도구 — custom)
  └─ ... (구분 없이 전부 한 서버)
```

- built-in과 custom의 구분이 없음
- Session별 도구 선택/제한 불가 (all-or-nothing)
- ToolPolicyEngine이 존재하지만 실제 적용되지 않음

### 0.3 Claude CLI의 제약 조건

Claude CLI는 **반드시 MCP 프로토콜**을 통해서만 도구를 호출한다.
이것은 변경할 수 없는 제약이다.

- 도구 호출은 CLI 내부의 블랙박스에서 일어남
- `tool_use` 이벤트는 이미 실행된 후 stream-json으로 출력됨
- 실행 중간에 Python이 개입할 수 없음
- `--max-turns`로 루프 횟수만 제어 가능

**따라서**: MCP "프로토콜"은 유지하되, MCP 서버의 **실행 방식**을 바꿔야 한다.

---

## 1. 해결 아키텍처 — Proxy MCP 패턴

### 1.1 핵심 아이디어

```
현재:  MCP 서버(subprocess)가 도구를 직접 실행 → 싱글턴 접근 실패
해결:  MCP 서버(subprocess)는 얇은 프록시만 담당
       실제 실행은 메인 FastAPI 프로세스로 라우팅 → 싱글턴 정상 접근
```

MCP 서버 subprocess는 **도구 실행을 하지 않는다**.
Claude CLI로부터 도구 호출 요청을 받아서,
HTTP로 메인 FastAPI 프로세스에 전달하고,
메인 프로세스가 실제 Python 함수를 실행한 결과를 받아서
Claude CLI에게 돌려준다.

### 1.2 새로운 도구 실행 경로

```
LangGraph 노드
  └─ _resilient_invoke(messages)
      └─ ClaudeCLIChatModel.ainvoke()
          └─ ClaudeProcess.execute(prompt)
              └─ Claude CLI (node.exe)               ← 변경 없음
                  └─ .mcp.json 읽기
                      │
                      ├─ _python_tools MCP 서버 (Proxy — 얇은 subprocess)
                      │   └─ tool_call 수신 (MCP 프로토콜)
                      │       └─ HTTP POST → localhost:PORT/internal/tools/execute
                      │           └─ FastAPI 메인 프로세스에서 실행!
                      │               ├─ geny_tools → _get_agent_manager() ✅ 정상!
                      │               ├─ browser_tools → Playwright ✅
                      │               ├─ web_search_tools → DuckDuckGo ✅
                      │               └─ web_fetch_tools → httpx ✅
                      │           └─ 결과 반환 → MCP 응답 → Claude CLI
                      │
                      ├─ github (외부 MCP — 기존 방식 유지)
                      └─ filesystem (외부 MCP — 기존 방식 유지)
```

### 1.3 왜 이 구조가 올바른가

| 특성 | 현재 (잘못됨) | Proxy MCP (올바름) |
|------|-------------|-------------------|
| **geny_tools 싱글턴** | ❌ 별도 프로세스의 독립 인스턴스 | ✅ 메인 프로세스의 실제 싱글턴 |
| **Claude CLI 호환** | ✅ MCP 프로토콜 | ✅ MCP 프로토콜 (동일) |
| **도구 실행 위치** | MCP subprocess (프로세스 #2) | FastAPI 메인 (프로세스 #1) |
| **IPC 오버헤드** | stdio (MCP 프로토콜) | stdio + localhost HTTP (무시할 수준) |
| **도구 필터링** | 불가 (단일 서버) | ✅ Proxy가 허용된 도구만 등록 |
| **통합 로깅** | 분산 (두 프로세스) | ✅ 메인 프로세스에서 통합 |

### 1.4 Proxy MCP 서버 구조

```python
# tools/_proxy_mcp_server.py (자동 생성)
#
# 역할: Claude CLI ↔ FastAPI 메인 프로세스 사이의 얇은 프록시
# 실행: Claude CLI가 MCP 서버로 spawn (stdio 통신)
# 동작:
#   1. 기동 시: 도구 모듈 import → 스키마 추출 (함수 시그니처 보존)
#   2. 도구 호출 시: HTTP POST로 메인 프로세스에 전달 → 결과 반환

import sys
import asyncio
import functools
import httpx
from pathlib import Path
from mcp.server.fastmcp import FastMCP

BACKEND_URL = sys.argv[1]   # e.g., "http://localhost:8000"
SESSION_ID = sys.argv[2]    # 세션 식별자
ALLOWED_TOOLS = sys.argv[3].split(",") if len(sys.argv) > 3 else None

mcp = FastMCP("python-tools")

def _register_proxy_tool(tool_obj, mcp_server, backend_url, session_id):
    """도구의 스키마는 원본에서 가져오고, 실행은 메인 프로세스로 프록시."""
    name = getattr(tool_obj, 'name', None)
    if not name:
        return

    description = getattr(tool_obj, 'description', '') or f"Tool: {name}"

    # 원본 함수의 시그니처를 보존 (FastMCP가 올바른 input_schema 생성)
    source_fn = tool_obj.run if hasattr(tool_obj, 'run') else tool_obj

    @functools.wraps(source_fn)
    async def proxy_fn(*args, **kwargs):
        """메인 프로세스로 도구 실행 프록시."""
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{backend_url}/internal/tools/execute",
                json={
                    "tool_name": name,
                    "args": kwargs,
                    "session_id": session_id,
                },
            )
            data = resp.json()
            if data.get("error"):
                return f"Error: {data['error']}"
            return data.get("result", "")

    proxy_fn.__name__ = name
    proxy_fn.__doc__ = f"{description}"
    mcp_server.tool(name=name, description=description)(proxy_fn)


# 도구 모듈 import → 스키마 추출 (실행은 하지 않음)
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.built_in.geny_tools import TOOLS as builtin
from tools.custom.browser_tools import TOOLS as browser
from tools.custom.web_search_tools import TOOLS as web_search
from tools.custom.web_fetch_tools import TOOLS as web_fetch

all_tools = [*builtin, *browser, *web_search, *web_fetch]

for tool_obj in all_tools:
    tool_name = getattr(tool_obj, 'name', '')
    if ALLOWED_TOOLS and tool_name not in ALLOWED_TOOLS:
        continue  # Preset에 포함되지 않은 도구는 등록하지 않음
    _register_proxy_tool(tool_obj, mcp, BACKEND_URL, SESSION_ID)

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**핵심 설계 포인트:**

1. **`@functools.wraps(source_fn)`**: 원본 함수의 `__wrapped__`, `__annotations__` 등을 복사. FastMCP가 `inspect.signature()`를 호출할 때 원본 함수의 파라미터 스키마를 정확히 추출. Claude에게 올바른 `input_schema` 전달.

2. **실행 프록시**: `proxy_fn`은 도구를 직접 실행하지 않음. `httpx.post()`로 메인 프로세스의 `/internal/tools/execute` 엔드포인트에 요청. 메인 프로세스가 동일한 Python 함수를 **같은 프로세스에서** 실행.

3. **도구 필터링**: `ALLOWED_TOOLS` 인자로 Preset 기반 필터링. 허용되지 않은 도구는 MCP에 등록하지 않으므로 Claude에게 보이지 않음. Built-in 도구는 항상 `ALLOWED_TOOLS`에 포함.

### 1.5 메인 프로세스 — 내부 도구 실행 엔드포인트

```python
# controller/internal_tool_controller.py (신규)
# 내부 전용 — Proxy MCP 서버만 호출

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/internal/tools", tags=["internal"])

class ToolExecuteRequest(BaseModel):
    tool_name: str
    args: dict
    session_id: str

class ToolExecuteResponse(BaseModel):
    result: Optional[str] = None
    error: Optional[str] = None

@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(req: ToolExecuteRequest, request: Request):
    """Proxy MCP 서버의 도구 실행 요청을 처리.

    메인 프로세스에서 Python 도구를 직접 실행한다.
    같은 프로세스이므로 싱글턴 접근, DB 연결 등 모두 정상 동작.
    """
    tool_loader: ToolLoader = request.app.state.tool_loader

    tool = tool_loader.get_tool(req.tool_name)
    if not tool:
        return ToolExecuteResponse(error=f"Unknown tool: {req.tool_name}")

    try:
        if asyncio.iscoroutinefunction(tool.run):
            result = await tool.run(**req.args)
        else:
            result = tool.run(**req.args)
        return ToolExecuteResponse(result=str(result))
    except Exception as e:
        logger.error(f"Tool execution error [{req.tool_name}]: {e}")
        return ToolExecuteResponse(error=str(e))


@router.get("/schemas")
async def get_tool_schemas(request: Request, names: Optional[str] = None):
    """사용 가능한 도구 스키마 반환 (Proxy 서버 기동 시 호출)."""
    tool_loader: ToolLoader = request.app.state.tool_loader
    tools = tool_loader.get_all_tools()

    if names:
        allowed = set(names.split(","))
        tools = {k: v for k, v in tools.items() if k in allowed}

    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters or {},
        }
        for t in tools.values()
    ]
```

### 1.6 ToolLoader — 도구 로드 및 관리

```python
# service/tool_loader.py (신규)
# 메인 프로세스에서 모든 Python 도구를 로드하고 관리

class ToolLoader:
    """Python 도구 로더 — tools/built_in/, tools/custom/ 스캔.

    메인 프로세스에서 한 번 로드하고,
    /internal/tools/execute 요청 시 직접 실행.
    """

    def __init__(self, tools_dir: Path):
        self.tools_dir = tools_dir
        self.builtin_tools: Dict[str, BaseTool] = {}  # 항상 활성
        self.custom_tools: Dict[str, BaseTool] = {}    # Preset으로 제어

    def load_all(self):
        """모든 Python 도구 로드."""
        self._load_from_dir(self.tools_dir / "built_in", self.builtin_tools)
        self._load_from_dir(self.tools_dir / "custom", self.custom_tools)

    def _load_from_dir(self, dir_path: Path, target: Dict):
        for tool_file in dir_path.glob("*_tools.py"):
            tools = self._load_from_file(tool_file)
            for t in tools:
                target[t.name] = t

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self.builtin_tools.get(name) or self.custom_tools.get(name)

    def get_all_tools(self) -> Dict[str, BaseTool]:
        return {**self.builtin_tools, **self.custom_tools}

    def get_builtin_names(self) -> List[str]:
        return list(self.builtin_tools.keys())

    def get_custom_names(self) -> List[str]:
        return list(self.custom_tools.keys())

    def get_allowed_tools_for_preset(
        self, preset: ToolPresetDefinition
    ) -> List[str]:
        """Preset 기반으로 허용할 도구 이름 목록 반환. Built-in은 항상 포함."""
        allowed = list(self.builtin_tools.keys())  # built-in 항상 포함

        if "*" in preset.custom_tools:
            allowed.extend(self.custom_tools.keys())
        else:
            for name in preset.custom_tools:
                if name in self.custom_tools:
                    allowed.append(name)

        return allowed
```

---

## 2. 현행 시스템 분석 (AS-IS)

### 2.1 현재 Tools 구조

```
backend/tools/
├── __init__.py              # BaseTool, ToolWrapper, @tool 데코레이터 export
├── base.py                  # 툴 정의 프레임워크 (추상 클래스 + 데코레이터)
├── _mcp_server.py           # 자동 생성 — FastMCP 래퍼 (모든 툴을 하나의 MCP 서버로)  ⛔ 제거 대상
├── browser_tools.py         # Playwright 기반 브라우저 자동화 (7개 툴)
├── geny_tools.py            # GenY 플랫폼 조작 툴 (11개 툴)
├── web_fetch_tools.py       # HTTP 기반 웹 페이지 가져오기 (2개 툴)
├── web_search_tools.py      # DuckDuckGo 검색 (2개 툴)
└── README.md
```

### 2.2 현재 MCP 로딩 파이프라인

```
MCPLoader.load_all()
  ├─ (1) _load_mcp_configs()        → mcp/*.json → 외부 MCP 서버 등록
  ├─ (2) _load_tools()              → tools/*_tools.py → 모든 툴 수집
  └─ (3) _register_tools_as_mcp()   → 전체 → _mcp_server.py 자동 생성 → "_builtin_tools" 서버
                                       ⛔ 이 단계가 문제
```

### 2.3 현재 Session 생성 흐름

```
POST /api/agents
  └─ AgentSessionManager.create_agent_session()
      ├─ merge_mcp_configs(global_mcp, request.mcp_config)
      ├─ build_agent_prompt(role, mcp_servers, tools, ...)
      ├─ AgentSession.create() → ClaudeProcess 생성
      │   └─ _create_mcp_config() → .mcp.json 생성
      │       └─ Claude CLI 시작
      └─ ※ tool_preset 적용 없음
```

### 2.4 Workflow Preset 패턴 (Tool Preset의 참조 모델)

```
backend/service/workflow/
├── workflow_model.py       # WorkflowDefinition (Pydantic)
├── workflow_store.py       # JSON 파일 CRUD (singleton)
├── templates.py            # 팩토리 + install_templates()
└── workflow_executor.py    # 컴파일 + 실행
```

패턴: Pydantic 모델 → JSON Store → 팩토리 템플릿 → REST API → CRUD + clone

---

## 3. 목표 시스템 설계 (TO-BE)

### 3.1 핵심 요구사항

| # | 요구사항 | 해결 방법 |
|---|---------|----------|
| R1 | Claude CLI 유지 | ✅ 변경 없음. MCP 프로토콜 그대로 사용 |
| R2 | 모든 Python 도구 메인 프로세스 실행 | ✅ Proxy MCP → HTTP → 메인 프로세스 |
| R3 | Built-in / Custom 분류 | ✅ 디렉토리 분리 + ToolLoader |
| R4 | Built-in 항상 활성 | ✅ Preset 관계없이 항상 ALLOWED_TOOLS에 포함 |
| R5 | Tool Preset | ✅ Workflow Preset 패턴 복제 |
| R6 | Session별 Tool 할당 | ✅ Preset → ALLOWED_TOOLS → Proxy가 허용 도구만 등록 |
| R7 | 비허용 도구 차단 | ✅ Proxy가 미등록 → Claude에게 보이지 않음 |

### 3.2 새로운 Tools 디렉토리 구조

```
backend/tools/
├── __init__.py                    # BaseTool, @tool 데코레이터 export (기존 유지)
├── base.py                        # 툴 정의 프레임워크 (변경 없음)
├── _proxy_mcp_server.py           # ⭐ 신규 — Proxy MCP 서버 (자동 생성)
│
├── built_in/                      # GenY 플랫폼 자체 조작 (항상 활성)
│   ├── __init__.py
│   └── geny_tools.py              # 11개 툴 (기존 geny_tools.py 이동)
│
└── custom/                        # 범용 도구 (Preset으로 제어)
    ├── __init__.py
    ├── browser_tools.py           # 7개 툴 (기존 이동)
    ├── web_search_tools.py        # 2개 툴 (기존 이동)
    └── web_fetch_tools.py         # 2개 툴 (기존 이동)
```

**논리적 분류:**
- `built_in/`: GenY 플랫폼 자체를 조작하는 도구. Agent가 다른 Agent를 생성하거나 메시지를 보내는 등 **플랫폼 수준** 동작. 모든 Session에서 항상 사용 가능.
- `custom/`: 외부 세계와 상호작용하는 범용 도구. 웹 검색, 브라우저, HTTP 등 **작업 수준** 동작. Tool Preset으로 제어.

**실행 계층은 동일:** 둘 다 Proxy MCP → HTTP → 메인 프로세스에서 직접 실행.
차이는 **논리적 분류** (Preset에서 built-in은 항상 포함, custom은 선택)뿐이다.

### 3.3 전체 실행 흐름 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI 메인 프로세스                     │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ ToolLoader (app.state.tool_loader)                   │    │
│  │  ├─ builtin_tools:                                   │    │
│  │  │   ├─ geny_session_list → GenySessionListTool()   │    │
│  │  │   ├─ geny_send_message → GenySendRoomMsgTool()   │    │
│  │  │   └─ ... (11개)                                   │    │
│  │  └─ custom_tools:                                    │    │
│  │      ├─ web_search → WebSearchTool()                 │    │
│  │      ├─ browser_navigate → BrowserNavigateTool()     │    │
│  │      └─ ... (11개)                                   │    │
│  └──────────────────────────────────────────────────────┘    │
│                         │                                     │
│  ┌──────────────────────┼──────────────────────────────┐     │
│  │ POST /internal/tools/execute                        │     │
│  │  ├─ tool_name: "geny_send_message"                  │     │
│  │  ├─ args: {room_id: "...", content: "..."}          │     │
│  │  └─ → tool_loader.get_tool("geny_send_message")    │     │
│  │      → await tool.run(**args)   ← 같은 프로세스!     │     │
│  │      → _get_agent_manager() → ✅ 정확한 싱글턴!      │     │
│  │      → 결과 반환                                     │     │
│  └─────────────────────────────────────────────────────┘     │
│                         ▲                                     │
│              HTTP (localhost)                                  │
│                         │                                     │
│  ┌──────────────────────┴──────────────────────────────┐     │
│  │ AgentSessionManager.create_agent_session()          │     │
│  │  ├─ preset = tool_preset_store.load(preset_id)      │     │
│  │  ├─ allowed = tool_loader.get_allowed(preset)       │     │
│  │  ├─ .mcp.json 생성:                                 │     │
│  │  │   ├─ _python_tools: Proxy MCP (allowed 도구만)   │     │
│  │  │   ├─ github: 외부 MCP (preset에 따라)            │     │
│  │  │   └─ filesystem: 외부 MCP (preset에 따라)        │     │
│  │  └─ ClaudeProcess.execute()                         │     │
│  │      └─ Claude CLI                                  │     │
│  │          └─ _python_tools MCP (Proxy subprocess)    │     │
│  │              └─ HTTP POST → /internal/tools/execute │     │
│  └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 .mcp.json 생성 예시

```json
{
  "mcpServers": {
    "_python_tools": {
      "command": "python",
      "args": [
        "tools/_proxy_mcp_server.py",
        "http://localhost:8000",
        "session-abc-123",
        "geny_session_list,geny_send_message,geny_room_create,web_search,web_fetch"
      ]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-github"],
      "env": { "GITHUB_TOKEN": "..." }
    }
  }
}
```

- `_python_tools`: Proxy MCP 서버. 3번째 인자가 허용 도구 목록.
  Claude CLI가 이 서버에 연결하면, 허용된 도구의 스키마만 보임.
- `github`: 외부 MCP 서버. 기존 방식 그대로 유지.

---

## 4. Tool Preset 시스템

### 4.1 데이터 모델

```python
# service/tool_preset/models.py

class ToolPresetDefinition(BaseModel):
    """Tool Preset 정의 — WorkflowDefinition과 동일 패턴"""
    id: str                     # UUID 또는 "template-xxx"
    name: str                   # "Web Research"
    description: str            # 설명
    icon: Optional[str] = None

    # 포함할 custom 도구 이름 목록 (built-in은 항상 포함이므로 명시 불필요)
    custom_tools: List[str] = []    # ["web_search", "browser_navigate", ...]
                                     # ["*"] → 모든 custom 도구

    # 포함할 외부 MCP 서버 이름 목록
    mcp_servers: List[str] = []     # ["github", "filesystem"]
                                     # ["*"] → 모든 외부 MCP

    # 메타데이터
    created_at: str
    updated_at: str
    is_template: bool = False       # True → 수정 불가, clone만 가능
    template_name: Optional[str] = None
```

### 4.2 스토어 (WorkflowStore 패턴)

```python
# service/tool_preset/store.py

class ToolPresetStore:
    """JSON 파일 기반 Tool Preset CRUD. WorkflowStore와 동일 패턴."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, preset: ToolPresetDefinition) -> None: ...
    def load(self, preset_id: str) -> Optional[ToolPresetDefinition]: ...
    def delete(self, preset_id: str) -> bool: ...
    def list_all(self) -> List[ToolPresetDefinition]: ...
    def list_templates(self) -> List[ToolPresetDefinition]: ...
    def list_user_presets(self) -> List[ToolPresetDefinition]: ...
    def exists(self, preset_id: str) -> bool: ...
    def clone(self, preset_id: str, new_name: str) -> ToolPresetDefinition: ...
```

### 4.3 기본 프리셋 템플릿

```python
# service/tool_preset/templates.py

def create_minimal_preset() -> ToolPresetDefinition:
    """built-in만 (custom 없음, 외부 MCP 없음)"""
    return ToolPresetDefinition(
        id="template-minimal",
        name="Minimal",
        description="GenY 플랫폼 도구만 사용",
        custom_tools=[],
        mcp_servers=[],
        is_template=True,
        template_name="minimal",
    )

def create_web_research_preset() -> ToolPresetDefinition:
    """웹 리서치 전용"""
    return ToolPresetDefinition(
        id="template-web-research",
        name="Web Research",
        description="웹 검색, 페이지 가져오기, 브라우저 자동화",
        custom_tools=[
            "web_search", "news_search",
            "web_fetch", "web_fetch_multiple",
            "browser_navigate", "browser_click", "browser_fill",
            "browser_screenshot", "browser_evaluate",
            "browser_get_page_info", "browser_close",
        ],
        mcp_servers=[],
        is_template=True,
        template_name="web-research",
    )

def create_full_development_preset() -> ToolPresetDefinition:
    """개발 작업 — 모든 custom + 개발 MCP"""
    return ToolPresetDefinition(
        id="template-full-development",
        name="Full Development",
        description="모든 custom 툴 + 개발 관련 MCP 서버",
        custom_tools=["*"],
        mcp_servers=["filesystem", "github", "git"],
        is_template=True,
        template_name="full-development",
    )

def create_all_tools_preset() -> ToolPresetDefinition:
    """전부 활성"""
    return ToolPresetDefinition(
        id="template-all-tools",
        name="All Tools",
        description="모든 custom 툴과 MCP 서버 활성화",
        custom_tools=["*"],
        mcp_servers=["*"],
        is_template=True,
        template_name="all-tools",
    )

def install_templates(store: ToolPresetStore) -> None:
    for factory in [create_minimal_preset, create_web_research_preset,
                    create_full_development_preset, create_all_tools_preset]:
        preset = factory()
        if not store.exists(preset.id):
            store.save(preset)
```

### 4.4 ToolRegistry — 도구 카탈로그

```python
# service/tool_preset/registry.py

class ToolInfo(BaseModel):
    """개별 도구 메타 정보"""
    name: str               # "web_search"
    display_name: str        # "Web Search"
    description: str         # "Search the web..."
    category: str            # "built_in" | "custom"
    group: str               # 파일 기반 그룹명

class ToolRegistry:
    """현재 로드된 모든 도구의 카탈로그. Frontend UI용."""

    def __init__(self, tool_loader: ToolLoader, mcp_loader: MCPLoader):
        self._tool_loader = tool_loader
        self._mcp_loader = mcp_loader

    def get_all_tools(self) -> List[ToolInfo]: ...
    def get_builtin_tools(self) -> List[ToolInfo]: ...
    def get_custom_tools(self) -> List[ToolInfo]: ...
    def get_mcp_servers(self) -> List[dict]: ...
```

---

## 5. Session 생성 통합 흐름

### 5.1 CreateSessionRequest 확장

```python
# models.py

class CreateSessionRequest(BaseModel):
    # ... 기존 필드 ...
    tool_preset_id: Optional[str] = Field(
        default=None,
        description="Tool Preset ID. None이면 role 기반 기본 프리셋"
    )
```

### 5.2 기본 프리셋 매핑

```python
ROLE_DEFAULT_PRESET = {
    "worker":     "template-all-tools",
    "developer":  "template-full-development",
    "researcher": "template-web-research",
    "planner":    "template-all-tools",
}
```

### 5.3 Session 생성 시 도구 설정 흐름

```
AgentSessionManager.create_agent_session(request)
  │
  ├─ (1) Preset 결정
  │      preset_id = request.tool_preset_id or ROLE_DEFAULT_PRESET[role]
  │      preset = tool_preset_store.load(preset_id)
  │
  ├─ (2) Python 도구 목록 결정
  │      allowed_tools = tool_loader.get_allowed_tools_for_preset(preset)
  │      → built-in 전부 + preset.custom_tools 에 따른 custom
  │      → 예: ["geny_session_list", ..., "web_search", "web_fetch"]
  │
  ├─ (3) 외부 MCP 서버 필터링
  │      if "*" in preset.mcp_servers:
  │          mcp_servers = global_mcp_config.servers  # 전부
  │      else:
  │          mcp_servers = {name: cfg for name, cfg in global_mcp_config
  │                         if name in preset.mcp_servers}
  │
  ├─ (4) _python_tools Proxy MCP 서버 추가
  │      mcp_servers["_python_tools"] = MCPServerStdio(
  │          command=sys.executable,
  │          args=[
  │              "tools/_proxy_mcp_server.py",
  │              f"http://localhost:{port}",
  │              session_id,
  │              ",".join(allowed_tools),   ← Preset 기반 필터링
  │          ],
  │      )
  │
  ├─ (5) MCPConfig 조립 → .mcp.json 생성
  │      merged_config = MCPConfig(servers=mcp_servers)
  │      → ClaudeProcess._create_mcp_config()
  │
  └─ (6) ClaudeProcess.execute() → Claude CLI 시작
         → Claude가 _python_tools의 허용 도구만 인식
         → 도구 호출 → Proxy MCP → HTTP → 메인 프로세스 실행
```

---

## 6. REST API 설계

### 6.1 Tool Preset API

```
/api/tool-presets/
├── GET    /                     # 모든 프리셋 목록
├── POST   /                     # 새 프리셋 생성
├── GET    /{id}                 # 프리셋 상세
├── PUT    /{id}                 # 프리셋 수정 (템플릿 불가)
├── DELETE /{id}                 # 프리셋 삭제 (템플릿 불가)
├── POST   /{id}/clone           # 프리셋 복제
└── GET    /templates            # 템플릿만 조회
```

### 6.2 Tool 카탈로그 API

```
/api/tools/
├── GET    /catalog              # 모든 도구 (built-in + custom + MCP)
├── GET    /catalog/built-in     # built-in만
├── GET    /catalog/custom       # custom만
└── GET    /catalog/mcp-servers  # 외부 MCP 서버 목록
```

### 6.3 내부 API (Proxy MCP 전용)

```
/internal/tools/
├── POST   /execute              # 도구 실행 (Proxy MCP → 메인 프로세스)
└── GET    /schemas              # 도구 스키마 조회
```

---

## 7. 수정 필요 파일 매핑

### 7.1 Backend — 신규 생성

| 파일 | 설명 |
|------|------|
| `service/tool_loader.py` | ⭐ ToolLoader — Python 도구 로드/관리/실행 |
| `service/tool_preset/__init__.py` | 패키지 초기화 |
| `service/tool_preset/models.py` | ToolPresetDefinition 모델 |
| `service/tool_preset/store.py` | ToolPresetStore (JSON CRUD) |
| `service/tool_preset/templates.py` | 기본 프리셋 팩토리 |
| `service/tool_preset/registry.py` | ToolRegistry (카탈로그) |
| `controller/tool_preset_controller.py` | Preset REST API |
| `controller/tool_controller.py` | 카탈로그 REST API |
| `controller/internal_tool_controller.py` | ⭐ 내부 도구 실행 API |
| `tools/built_in/__init__.py` | built-in 패키지 |
| `tools/built_in/geny_tools.py` | geny_tools.py 이동 |
| `tools/custom/__init__.py` | custom 패키지 |
| `tools/custom/browser_tools.py` | browser_tools.py 이동 |
| `tools/custom/web_search_tools.py` | web_search_tools.py 이동 |
| `tools/custom/web_fetch_tools.py` | web_fetch_tools.py 이동 |

### 7.2 Backend — 수정 필요

| 파일 | 수정 내용 |
|------|----------|
| `service/mcp_loader.py` | ⭐ `_register_tools_as_mcp()` 교체 → Proxy MCP 서버 생성 |
| `service/claude_manager/models.py` | `CreateSessionRequest`에 `tool_preset_id` 추가 |
| `service/langgraph/agent_session_manager.py` | Preset 기반 도구/MCP 필터링 적용 |
| `controller/agent_controller.py` | `CreateAgentRequest`에 `tool_preset_id` 추가 |
| `main.py` | ToolLoader 초기화, install_templates(), internal API 등록 |
| `tools/__init__.py` | built-in/custom 구분 export |

### 7.3 Backend — 삭제

| 파일 | 이유 |
|------|------|
| `tools/_mcp_server.py` | 기존 MCP 래퍼 → `_proxy_mcp_server.py`로 대체 |

### 7.4 Frontend — 신규 생성

| 파일 | 설명 |
|------|------|
| `src/types/toolPreset.ts` | ToolPresetDefinition, ToolInfo 타입 |
| `src/lib/toolPresetApi.ts` | Tool Preset REST API 클라이언트 |
| `src/store/useToolPresetStore.ts` | Zustand 스토어 |
| `src/components/tabs/ToolPresetsTab.tsx` | Preset 관리 탭 |
| `src/components/tool-preset/ToolPresetEditor.tsx` | Preset 편집 UI |
| `src/components/tool-preset/ToolCatalog.tsx` | 도구 카탈로그 |
| `src/components/tool-preset/ToolPresetCard.tsx` | Preset 카드 |

### 7.5 Frontend — 수정 필요

| 파일 | 수정 내용 |
|------|----------|
| `src/components/modals/CreateSessionModal.tsx` | Tool Preset 선택 추가 |
| `src/types/index.ts` | `CreateAgentRequest`에 `tool_preset_id` 추가 |
| `src/store/useAppStore.ts` | createSession에 tool_preset_id 전달 |
| `src/components/TabNavigation.tsx` | "Tools" 탭 추가 |
| `src/components/TabContent.tsx` | ToolPresetsTab 라우팅 |

---

## 8. 구현 순서 (Phase Plan)

### Phase 1 — Proxy MCP + ToolLoader (핵심 아키텍처)
**목표**: 모든 Python 도구가 메인 프로세스에서 실행되는 구조 완성

1. `tools/built_in/`, `tools/custom/` 디렉토리 생성 및 파일 이동
2. `service/tool_loader.py` 구현 — 도구 로드/관리
3. `controller/internal_tool_controller.py` 구현 — `/internal/tools/execute`
4. `service/mcp_loader.py` 수정 — `_register_tools_as_mcp()` → Proxy MCP 생성
5. `tools/_proxy_mcp_server.py` 생성 (자동 생성 또는 정적)
6. `main.py` 수정 — ToolLoader 초기화, internal API 라우터 등록
7. 기존 `tools/_mcp_server.py` 삭제
8. 검증: Claude CLI가 Proxy를 통해 도구 호출 → 메인 프로세스 실행 확인

### Phase 2 — Tool Preset 백엔드
**목표**: Workflow Preset 패턴으로 도구 프리셋 CRUD

1. `service/tool_preset/` 패키지 생성 (models, store, templates, registry)
2. `tool_presets/` 디렉토리 생성
3. `controller/tool_preset_controller.py` REST API 구현
4. `controller/tool_controller.py` 카탈로그 API 구현
5. `main.py`에 install_templates() 호출 추가

### Phase 3 — Session 생성 통합
**목표**: Session 생성 시 Preset 기반 도구 필터링

1. `CreateSessionRequest`에 `tool_preset_id` 필드 추가
2. `AgentSessionManager.create_agent_session()` 수정:
   - Preset 조회 → 허용 도구 목록 추출
   - `_python_tools` Proxy MCP에 allowed_tools 전달
   - 외부 MCP 서버 preset 기반 필터링
3. `.mcp.json` 생성 시 Preset 반영 확인

### Phase 4 — Frontend 통합
**목표**: UI에서 Preset 관리 + Session 생성 시 선택

1. `types/toolPreset.ts` 타입 정의
2. `lib/toolPresetApi.ts` API 클라이언트
3. `store/useToolPresetStore.ts` Zustand 스토어
4. `CreateSessionModal.tsx` — Tool Preset 드롭다운 추가
5. `ToolPresetsTab.tsx` — 프리셋 관리 UI

### Phase 5 — 고도화
1. Tool Preset Editor (드래그 앤 드롭)
2. 도구 사용 통계
3. 세션 실행 중 동적 도구 전환

---

## 9. 변경 영향 및 호환성

### 9.1 Breaking Changes

| 변경 | 위험도 | 완화 |
|------|--------|------|
| `_builtin_tools` → `_python_tools` (Proxy) | 중간 | Claude CLI 입장에서는 MCP 서버 이름만 변경 |
| `tools/` 디렉토리 재구조화 | 중간 | 기존 경로에 import redirect 유지 |
| Session 요청 스키마 확장 | 낮음 | `tool_preset_id`는 Optional |

### 9.2 인터페이스 호환성

- **LangGraph 그래프**: 변경 없음. `ClaudeCLIChatModel.ainvoke()` 인터페이스 동일.
- **Claude CLI**: 변경 없음. `.mcp.json`의 서버 이름만 변경.
- **AutonomousGraph**: 변경 없음. `_resilient_invoke()` 동일.
- **Frontend API**: `tool_preset_id` 추가 (Optional, 하위 호환).

### 9.3 성능 영향

| 구간 | 오버헤드 |
|------|---------|
| Proxy → HTTP → 메인 프로세스 | < 1ms (localhost) |
| 도구 실행 자체 | 변경 없음 (동일 Python 코드) |
| Claude CLI ↔ Proxy MCP (stdio) | 기존과 동일 |

실제 도구 실행 시간(웹 검색 수초, 브라우저 수초)에 비해
localhost HTTP 왕복(< 1ms)은 무시할 수 있는 수준.

---

## 10. 핵심 결정 사항

### D1. Proxy MCP 서버 생성 방식

| 옵션 | 설명 | 권장 |
|------|------|------|
| **A. 정적 파일** | `_proxy_mcp_server.py`를 한 번 작성. 도구 목록은 CLI 인자로 전달 | ⭐ 권장 |
| **B. 동적 생성** | 기존처럼 MCPLoader가 매번 자동 생성 | 불필요한 복잡성 |

**권장: A.** Proxy 서버 코드는 바뀌지 않는다. 어떤 도구를 등록할지는 CLI 인자로 결정.

### D2. 내부 API 보안

| 옵션 | 설명 | 권장 |
|------|------|------|
| **A. localhost 바인딩만** | `/internal/` 경로는 localhost에서만 접근 가능 | ⭐ Phase 1 |
| **B. 세션 토큰** | Proxy에 세션 토큰 전달, API에서 검증 | Phase 5 |

**권장: A.** Docker 환경에서는 네트워크 격리로 충분. 추후 보안 강화.

### D3. 도구 필터링 단위

| 옵션 | 설명 | 권장 |
|------|------|------|
| **A. 개별 도구** | "web_search"만 허용, "news_search" 거부 | ⭐ 처음부터 지원 |
| **B. 파일 그룹** | "web_search_tools.py" 전체 ON/OFF | 대안 |

**권장: A.** Proxy MCP의 ALLOWED_TOOLS가 개별 도구명을 받으므로 자연스럽게 개별 필터링 지원.
Template preset은 편의상 그룹 단위로 정의하되, 실제 필터링은 개별 도구명 기준.
