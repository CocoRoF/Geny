# Tools & MCP System

> Python 도구 정의 → MCP 프록시 패턴으로 Claude CLI에 노출 → FastAPI 메인 프로세스에서 실행하는 도구 시스템

## 아키텍처 개요

```
Claude CLI ←stdio→ _proxy_mcp_server.py ←HTTP→ FastAPI (main.py)
                    (스키마만 등록)              (실제 실행)
```

**핵심 설계**: 도구는 `AgentSessionManager`, `ChatStore` 등 FastAPI 메인 프로세스의 싱글톤에 접근해야 한다. 프록시 서브프로세스는 MCP 스키마만 Claude CLI에 등록하고, 실제 실행은 `POST /internal/tools/execute`로 위임한다.

### 계층 구조

```
정의 계층 ─── BaseTool / ToolWrapper / @tool 데코레이터
     │
발견 계층 ─── ToolLoader: built_in/ + custom/ 스캔
     │
MCP 노출 ─── _proxy_mcp_server.py: FastMCP stdio 서버 등록
     │
실행 계층 ─── InternalToolController: 메인 프로세스 내 실행
     │
정책 계층 ─── ToolPolicyEngine: 역할/프로필별 필터링
     │
프리셋 ───── ToolPresetDefinition: 세션별 도구 세트 정의
     │
설정 계층 ─── MCPLoader: 외부 MCP JSON 설정 로드
```

---

## BaseTool

모든 도구의 추상 기반 클래스.

```python
class BaseTool(ABC):
    name: str              # 고유 도구 이름 (클래스명에서 자동 추론)
    description: str       # Claude에게 보여줄 설명 (docstring에서 추론)
    parameters: Dict       # JSON Schema (run() 시그니처에서 자동 생성)

    @abstractmethod
    def run(self, **kwargs) -> str: ...

    async def arun(self, **kwargs) -> str: ...  # 비동기 오버라이드 가능
```

### 파라미터 자동 생성

`run()` 메서드의 시그니처 + 타입 힌트 + Google-style docstring `Args:` 섹션에서 JSON Schema를 자동 생성:

```python
class MyTool(BaseTool):
    def run(self, query: str, limit: int = 5) -> str:
        """Search for items.

        Args:
            query: The search query string
            limit: Maximum results to return
        """
        ...
```

→ 자동 생성되는 JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "The search query string"},
    "limit": {"type": "integer", "description": "Maximum results to return"}
  },
  "required": ["query"]
}
```

### @tool 데코레이터

일반 함수를 도구로 래핑:

```python
@tool
def my_function(param: str) -> str:
    """Description here."""
    return result

@tool(name="custom_name", description="Custom description")
def another_function(param: str) -> str: ...
```

`ToolWrapper` 인스턴스를 반환하며, `BaseTool`과 동일한 인터페이스 제공.

---

## 내장 도구 (Built-in)

항상 모든 세션에서 사용 가능. Geny 플랫폼을 가상 회사로 모델링 (세션 = 직원).

### 세션 관리

| 도구 | 설명 | 파라미터 |
|------|------|----------|
| `geny_session_list` | 모든 세션 목록 조회 | 없음 |
| `geny_session_info` | 특정 세션 상세 조회 | `session_id` |
| `geny_session_create` | 새 세션 생성 | `session_name`, `role`, `model` |

### 채팅방 관리

| 도구 | 설명 | 파라미터 |
|------|------|----------|
| `geny_room_list` | 모든 채팅방 목록 | 없음 |
| `geny_room_create` | 채팅방 생성 | `room_name`, `session_ids` (콤마 구분) |
| `geny_room_info` | 채팅방 상세 | `room_id` |
| `geny_room_add_members` | 멤버 추가 | `room_id`, `session_ids` |

### 메시징

| 도구 | 설명 | 파라미터 |
|------|------|----------|
| `geny_send_room_message` | 채팅방 메시지 전송 | `room_id`, `content`, `sender_session_id`, `sender_name` |
| `geny_send_direct_message` | DM 전송 | `target_session_id`, `content`, `sender_session_id`, `sender_name` |
| `geny_read_room_messages` | 채팅방 메시지 읽기 | `room_id`, `limit` |
| `geny_read_inbox` | 수신함 읽기 | `session_id`, `limit`, `unread_only`, `mark_read` |

---

## 커스텀 도구 (Custom)

Tool Preset을 통해 세션별로 제어 가능.

### Browser Tools (Playwright)

Headless Chromium 브라우저 자동화. `_BrowserManager` 싱글톤으로 쿠키/세션 유지.

| 도구 | 설명 |
|------|------|
| `browser_navigate` | URL 탐색 (페이지 텍스트 반환) |
| `browser_click` | CSS 선택자 클릭 |
| `browser_fill` | 폼 필드 입력 |
| `browser_screenshot` | 스크린샷 캡처 |
| `browser_evaluate` | JavaScript 실행 |
| `browser_page_info` | 현재 페이지 정보 + DOM 요소 |
| `browser_close` | 브라우저 닫기 |

### Web Search Tools (DuckDuckGo)

| 도구 | 설명 |
|------|------|
| `web_search` | 웹 검색 (ddgs 라이브러리) |
| `news_search` | 뉴스 검색 |

### Web Fetch Tools (httpx)

| 도구 | 설명 |
|------|------|
| `web_fetch` | URL 내용 가져오기 (HTML→텍스트 변환) |
| `web_fetch_multiple` | 여러 URL 병렬 가져오기 |

---

## MCP 서버 통합

### Proxy MCP Server (`_proxy_mcp_server.py`)

Claude CLI와 FastAPI 메인 프로세스 사이의 경량 stdio 프록시.

```bash
python _proxy_mcp_server.py <backend_url> <session_id> [allowed_tools]
```

**동작 방식:**
1. ToolLoader에서 도구 객체 로드
2. 각 도구의 `name`, `description`, `run()` 시그니처 추출
3. FastMCP에 프록시 함수 등록 (스키마만 동일하게 유지)
4. 실제 호출 시 `POST {backend_url}/internal/tools/execute`로 HTTP 위임
5. 페이로드: `{"tool_name": name, "args": kwargs, "session_id": session_id}`

`ALLOWED_TOOLS`가 설정되면 해당 도구만 등록.

### Internal Tool Controller

프록시 MCP 서버의 HTTP 실행 엔드포인트. localhost 전용.

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/internal/tools/execute` | 도구 실행 (`arun()` 우선, `run()` 폴백) |
| `GET` | `/internal/tools/schemas` | 도구 스키마 조회 (선택적 이름 필터) |

---

## MCPLoader

외부 MCP 서버 설정을 JSON 파일에서 로드.

### 설정 파일 형식

`mcp/` 디렉토리의 `*.json` 파일:

```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["@modelcontextprotocol/server-filesystem", "/workspace"],
  "env": {"HOME": "${HOME}"},
  "description": "Filesystem access"
}
```

```json
{
  "type": "http",
  "url": "https://api.example.com/mcp/",
  "headers": {"Authorization": "Bearer ${API_KEY}"},
  "description": "Remote API server"
}
```

지원 타입: `stdio`, `http`, `sse`

환경 변수 확장: `${VAR}`, `${VAR:-default}` 패턴 지원.

### 세션별 MCP 설정 조립

```python
build_session_mcp_config(
    global_config,        # MCPLoader가 로드한 외부 서버
    allowed_tools,        # 프리셋에서 허용된 Python 도구 이름
    session_id,
    backend_port,
    allowed_mcp_servers,  # 프리셋에서 허용된 외부 MCP 서버
    extra_mcp,            # 세션별 추가 MCP
)
```

결과:
1. **`_python_tools`** 서버: Proxy MCP (허용된 Python 도구이름 포함)
2. **외부 MCP 서버**: `allowed_mcp_servers`로 필터링
3. **추가 MCP**: 요청별 오버라이드

---

## ToolLoader

`tools/built_in/` + `tools/custom/` 디렉토리 자동 스캔.

### 발견 메커니즘

1. `*_tools.py` 파일 글로빙
2. `importlib.util.spec_from_file_location()`으로 동적 임포트
3. 모듈에 `TOOLS` 속성이 있으면 사용
4. 없으면 모듈 내 `BaseTool`/`ToolWrapper` 인스턴스 자동 수집

### 프리셋 기반 필터링

```python
get_allowed_tools_for_preset(preset: ToolPresetDefinition) -> List[str]
```

- 내장 도구: **항상 포함**
- 커스텀 도구: `preset.custom_tools`로 필터링
  - `["*"]` → 모든 커스텀 도구
  - `[]` → 커스텀 없음
  - `["web_search", "browser_navigate"]` → 명시적 허용

---

## Tool Policy 시스템

역할 기반 MCP 서버 접근 제어.

### 프로필

| 프로필 | 허용 서버 |
|--------|----------|
| `MINIMAL` | 내장 도구 서버만 |
| `CODING` | + filesystem, git, github, code, lint, docker, terminal |
| `MESSAGING` | + slack, email, discord, teams, notion, jira, linear |
| `RESEARCH` | + web, search, brave, perplexity, google, bing, arxiv, wikipedia, fetch, browser |
| `FULL` | 무제한 (모든 서버) |

### 역할 → 기본 프로필

| 역할 | 기본 프로필 |
|------|------------|
| `worker` | CODING |
| `developer` | CODING |
| `researcher` | RESEARCH |
| `planner` | FULL |

### ToolPolicyEngine

```python
engine = ToolPolicyEngine.for_role("developer")
filtered_mcp = engine.filter_mcp_config(mcp_config)    # 허용 서버만 필터
filtered_tools = engine.filter_tool_names(tool_names)   # 허용 도구만 필터
```

서버 이름은 프로필의 접두사(prefix) 집합과 대소문자 무시 매칭. Deny list가 Allow list보다 우선.

---

## Tool Preset 시스템

세션별 도구 세트를 정의하는 프리셋.

### ToolPresetDefinition

```python
class ToolPresetDefinition(BaseModel):
    id: str                         # UUID (템플릿은 "template-xxx")
    name: str                       # "All Tools"
    description: str
    custom_tools: List[str]         # ["*"] = 전체, [] = 없음
    mcp_servers: List[str]          # ["*"] = 전체, [] = 없음
    is_template: bool               # 읽기 전용 여부
```

### 내장 템플릿

| ID | 이름 | custom_tools | mcp_servers |
|----|------|-------------|-------------|
| `template-all-tools` | All Tools | `["*"]` | `["*"]` |

모든 역할의 기본 프리셋은 `template-all-tools`.

### ToolPresetStore

`tool_presets/` 디렉토리에 JSON 파일로 저장.

| 메서드 | 설명 |
|--------|------|
| `save(preset)` | 저장/갱신 |
| `load(preset_id)` | ID로 로드 |
| `delete(preset_id)` | 삭제 |
| `list_all()` | 전체 목록 |
| `clone(preset_id, new_name)` | 복제 |

---

## 도구 → 세션 연결 흐름

```
CreateSessionRequest
  ├── tool_preset_id (또는 역할 기본값)
  ├── role
  └── mcp_config (추가)
        │
        ▼
┌───────────────────┐      ┌──────────────────┐
│  ToolPresetStore  │─────►│ ToolPresetDef    │
│  (JSON 파일)      │      │ .custom_tools    │
└───────────────────┘      │ .mcp_servers     │
                           └────────┬─────────┘
                                    │
                   ┌────────────────┼────────────────┐
                   ▼                ▼                ▼
         ToolLoader.              MCPLoader.       외부 MCP
         get_allowed_tools_      global config    서버 필터링
         for_preset()
                   │                │                │
                   ▼                ▼                ▼
             build_session_mcp_config()
                   │
                   ▼
             MCPConfig {
               "_python_tools": Proxy MCP Server,
               "github": MCPServerHTTP,
               ...
             }
                   │
                   ▼
             세션의 .mcp.json에 기록
             → Claude CLI가 읽음
             → _proxy_mcp_server.py 서브프로세스 스폰
             → 도구 호출 → POST /internal/tools/execute
             → 메인 프로세스에서 싱글톤 접근하여 실행
```

---

## API 엔드포인트

### Tool Catalog (`/api/tools`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/tools/catalog` | 전체 카탈로그 (내장 + 커스텀 + MCP) |
| `GET` | `/api/tools/catalog/built-in` | 내장 도구만 |
| `GET` | `/api/tools/catalog/custom` | 커스텀 도구만 |
| `GET` | `/api/tools/catalog/mcp-servers` | 외부 MCP 서버만 |

### Tool Presets (`/api/tool-presets`)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/api/tool-presets/` | 전체 프리셋 목록 |
| `GET` | `/api/tool-presets/templates` | 템플릿만 |
| `POST` | `/api/tool-presets/` | 프리셋 생성 |
| `GET` | `/api/tool-presets/{id}` | 프리셋 조회 |
| `PUT` | `/api/tool-presets/{id}` | 프리셋 수정 (템플릿 불가) |
| `DELETE` | `/api/tool-presets/{id}` | 프리셋 삭제 (템플릿 불가) |
| `POST` | `/api/tool-presets/{id}/clone` | 프리셋 복제 |

---

## 관련 파일

```
tools/
├── __init__.py                # 공개 API: BaseTool, ToolWrapper, tool, is_tool
├── base.py                    # BaseTool ABC, ToolWrapper, @tool 데코레이터
├── _mcp_server.py             # 직접 MCP 서버 (레거시)
├── _proxy_mcp_server.py       # 프록시 MCP 서버 (현재 사용)
├── built_in/
│   └── geny_tools.py          # 11개 내장 도구
└── custom/
    ├── browser_tools.py       # 7개 브라우저 도구 (Playwright)
    ├── web_search_tools.py    # 2개 검색 도구 (DuckDuckGo)
    └── web_fetch_tools.py     # 2개 웹 가져오기 도구 (httpx)

service/
├── mcp_loader.py              # 외부 MCP 설정 로드, 세션별 MCP 조립
├── tool_loader.py             # Python 도구 발견 및 등록
├── tool_policy/
│   └── policy.py              # ToolPolicyEngine, ToolProfile
└── tool_preset/
    ├── models.py              # ToolPresetDefinition
    ├── store.py               # ToolPresetStore (JSON 파일 저장)
    └── templates.py           # 내장 프리셋 템플릿

controller/
├── tool_controller.py         # /api/tools — 카탈로그 API
├── tool_preset_controller.py  # /api/tool-presets — 프리셋 CRUD
└── internal_tool_controller.py # /internal/tools — 프록시 실행 엔드포인트

mcp/
├── README.md                  # MCP 설정 가이드
├── example_filesystem.json.template
└── example_github.json.template
```
