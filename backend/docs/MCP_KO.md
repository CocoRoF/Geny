# MCP (Model Context Protocol) 시스템

> 외부 MCP 서버 관리 — 2단계 디렉토리 로딩 (built_in / custom), 프록시 패턴, 세션별 조립

## 아키텍처 개요

```
Claude CLI ←stdio→ _builtin_tools 프록시   ←HTTP→ FastAPI (메인 프로세스)
           ←stdio→ _custom_tools 프록시     ←HTTP→ FastAPI (메인 프로세스)
           ←stdio/http/sse→ 외부 MCP 서버 (GitHub, Notion 등)
```

**핵심 설계**: Python 도구는 Proxy MCP 패턴을 사용합니다 ([TOOLS_KO.md](TOOLS_KO.md) 참조). 외부 MCP 서버는 `mcp/` 디렉토리의 JSON 설정 파일에서 로드되어 Claude CLI에 stdio/http/sse 전송 방식으로 직접 연결됩니다.

---

## 디렉토리 구조

```
mcp/
├── built_in/          ← 항상 포함 (프리셋 필터링 우회)
│   └── github.json    ← GitHub API — Settings에서 자동 구성
├── custom/            ← 사용자 추가 서버 (프리셋 필터링 대상)
│   └── (JSON 파일 추가)
├── *.json.template    ← 예제 템플릿 (로드되지 않음)
└── README.md
```

### 2단계 로딩

| 단계 | 폴더 | 프리셋 필터링 | 환경변수 스킵 | 저장 위치 | 용도 |
|------|------|-------------|-------------|----------|------|
| 1 | `mcp/built_in/` | **아니오** — 항상 포함 | 예 | `builtin_servers` | 시스템 레벨 서버 (GitHub) |
| 2 | `mcp/custom/` | **예** | 예 | `servers` | 사용자 추가 서버 |

**주요 차이점:**
- **built_in/** 서버는 Tool Sets에서 제외할 수 없음 — 모든 세션에 포함
- **custom/** 서버는 환경변수가 미해결이면 로딩 스킵 (선택적 통합에 유용)

---

## JSON 설정 스키마

각 `.json` 파일은 하나의 MCP 서버를 정의합니다. 파일명(확장자 제외)이 서버 이름이 됩니다.

```json
{
  "type": "stdio | http | sse",
  "command": "명령어 (stdio 전용)",
  "args": ["arg1", "arg2"],
  "env": {"KEY": "값 또는 ${ENV_VAR}"},
  "url": "서버 URL (http/sse 전용)",
  "headers": {"Header": "값"},
  "description": "Tool Sets & Session Tools UI에 표시"
}
```

### 전송 타입

| 타입 | 필수 필드 | 설명 |
|------|----------|------|
| `stdio` | `command`, `args` (선택) | 서브프로세스를 실행하고 stdin/stdout으로 통신 |
| `http` | `url` | HTTP 엔드포인트에 연결 |
| `sse` | `url` | Server-Sent Events로 연결 |

### 설정 모델 (Python)

```python
# service/sessions/models.py
MCPServerStdio(command, args, env)
MCPServerHTTP(url, headers)
MCPServerSSE(url, headers)
MCPConfig(servers: Dict[str, MCPServerConfig])
```

---

## MCPLoader

**파일**: `service/mcp_loader.py`

JSON 설정을 로드하고 글로벌 MCP 구성을 관리하는 핵심 컴포넌트입니다.

### 싱글톤 패턴

```python
_global_mcp_config: Optional[MCPConfig] = None   # 커스텀 서버 (프리셋 필터링)
_builtin_mcp_config: Optional[MCPConfig] = None   # 빌트인 서버 (항상 포함)
_mcp_loader_instance: Optional[MCPLoader] = None  # 리로드용 싱글톤
```

### 초기화 및 로딩

```python
# main.py — 시작 시
loader = MCPLoader()
config = loader.load_all()
app.state.mcp_loader = loader
```

`load_all()`은 두 단계를 순서대로 실행합니다:

1. **`_load_builtin_configs()`** — `mcp/built_in/*.json` 스캔
   - `${VAR}` 환경변수 확장
   - 미해결 환경변수가 있는 서버 스킵 (`_has_unresolved_env()`)
   - `self.builtin_servers`에 저장 + `self.builtin_server_names`에 추적

2. **`_load_custom_configs()`** — `mcp/custom/*.json` 스캔
   - 동일한 환경변수 확장 + 미해결 스킵 동작
   - `self.servers`에 저장 + `self.custom_server_names`에 추적

### 상태 추적

```python
self.servers: Dict[str, MCPServerConfig]           # 커스텀 서버
self.builtin_servers: Dict[str, MCPServerConfig]    # 빌트인 서버
self.server_descriptions: Dict[str, str]            # 이름 → 설명 (전체)
self.builtin_server_names: set                      # mcp/built_in/ 이름 목록
self.custom_server_names: set                       # mcp/custom/ 이름 목록
```

### 리로드 메커니즘

빌트인 MCP 서버에 영향을 주는 설정 값이 변경되면 (예: Settings에서 GitHub 토큰 업데이트) 리로드 체인이 동작합니다:

```
Settings UI → ConfigField.apply_change → _github_token_sync()
  → env_sync("GITHUB_TOKEN") + env_sync("GH_TOKEN")
  → reload_builtin_mcp()
    → MCPLoader.reload_builtins()
      → builtin_servers / builtin_server_names 초기화
      → _load_builtin_configs() 재실행
      → set_builtin_mcp_config(새 설정)
```

이를 통해 `mcp/built_in/github.json`의 `${GITHUB_TOKEN}`이 새 값으로 재확장됩니다.

---

## 환경변수 확장

### 문법

| 패턴 | 동작 |
|------|------|
| `${VAR}` | `os.environ["VAR"]`로 대체, 없으면 원본 유지 |
| `${VAR:-fallback}` | `os.environ["VAR"]`로 대체, 없으면 `fallback` 사용 |

### 구현

```python
def _expand_env_vars(self, data: Any) -> Any:
    # 패턴: ${VAR} 또는 ${VAR:-default}
    # 빈 문자열("")은 미설정으로 처리 (None과 동일)
```

### 미해결 검사

`_has_unresolved_env(data)`는 확장 후에도 `${...}` 패턴이 남아있으면 `True`를 반환합니다. `built_in/`과 `custom/` 로더가 불완전한 설정을 스킵하는 데 사용됩니다.

---

## 세션별 MCP 조립

**함수**: `build_session_mcp_config()`

5개 레이어를 결합하여 세션의 완전한 MCP 설정을 구성합니다:

```
레이어 1: _builtin_tools    ← 내장 Python 도구용 프록시 MCP (항상)
레이어 2: _custom_tools     ← 커스텀 Python 도구용 프록시 MCP (허용 시)
레이어 3: Built-in MCP      ← mcp/built_in/ 서버 (항상, 필터링 없음)
레이어 4: Custom MCP        ← mcp/custom/ 서버 (프리셋 필터링)
레이어 5: Extra per-session ← 세션 생성 시 추가 MCP
```

### 프리셋 필터링 (레이어 4)

```python
allowed_mcp_servers: Optional[List[str]]
# None 또는 ["*"] → 모든 커스텀 MCP 서버 포함
# ["notion", "filesystem"] → 이것만 포함
# [] → 없음 (빌트인만 유지)
```

### 매개변수

```python
build_session_mcp_config(
    global_config,            # 커스텀 MCP 서버
    allowed_builtin_tools,    # 내장 도구 이름 목록
    allowed_custom_tools,     # 커스텀 도구 이름 (프리셋 필터링됨)
    session_id,               # 세션 ID
    backend_port=8000,        # FastAPI 포트
    allowed_mcp_servers=None, # MCP 서버 필터 (None = 전체)
    extra_mcp=None,           # 추가 세션별 MCP
) -> MCPConfig
```

---

## 도구 카탈로그 API

**파일**: `controller/tool_controller.py`

### 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /api/tools/catalog` | 전체 카탈로그 (내장 + 커스텀 + MCP) |
| `GET /api/tools/catalog/mcp-servers` | MCP 서버만 |

### MCPServerInfo 모델

```python
class MCPServerInfo(BaseModel):
    name: str           # 서버 이름 (파일명)
    type: str           # "stdio", "http", "sse"
    description: str    # JSON 설정의 description
    is_built_in: bool   # mcp/built_in/ 서버이면 True
    source: str         # "built_in" 또는 "custom"
```

### 소스 결정

카탈로그는 각 서버에 `source`를 할당합니다:

1. **`built_in`** — `mcp/built_in/`에서 로드, 항상 포함, `is_built_in=True`
2. **`custom`** — `mcp/custom/`에서 로드, 프리셋 필터링 대상

---

## 프론트엔드 통합

### 타입

```typescript
// types/index.ts
interface MCPServerInfo {
  name: string
  type: string
  description?: string
  is_built_in?: boolean
  source?: string  // "built_in" | "custom"
}
```

### UI 컴포넌트

**SessionToolsTab** — 세션별 도구 상태 표시:
- 빌트인 MCP 서버는 **BUILT-IN** 뱃지 표시 및 항상 활성화
- 커스텀 서버는 Tool Set 설정에 따라 활성화/비활성화
- 개수: `builtInMcpCount + enabledMcpServers.size`

**ToolSetsTab** — Tool Set 편집기:
- 빌트인 MCP 서버는 비활성화된 체크박스 (항상 체크됨) + **BUILT-IN** 뱃지
- 커스텀 MCP 서버는 개별 토글 가능
- 서버 이름 아래에 설명 텍스트 표시

---

## 빌트인 MCP 서버: GitHub

**파일**: `mcp/built_in/github.json`

```json
{
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
  },
  "description": "GitHub MCP — Repository, PR, Issue management (Settings에서 자동 구성)"
}
```

### 자동 구성 흐름

1. 사용자가 **Settings → GitHub → Token**에서 GitHub 토큰 입력
2. `GitHubConfig.apply_change`가 `_github_token_sync()` 트리거
3. `env_sync("GITHUB_TOKEN")` + `env_sync("GH_TOKEN")`이 `os.environ` 업데이트
4. `reload_builtin_mcp()`이 `mcp/built_in/github.json` 재로드
5. `${GITHUB_TOKEN}`이 새 토큰 값으로 확장됨
6. 다음 세션 생성 시 업데이트된 `builtin_mcp_config` 적용

`GITHUB_TOKEN`이 설정되지 않으면 서버는 스킵됩니다 (오류 아님).

---

## 새 MCP 서버 추가하기

### 빌트인 서버로 추가 (항상 포함)

1. `mcp/built_in/{이름}.json` 생성
2. 비밀 정보에 `${ENV_VAR}` 사용
3. Settings에서 구성 가능하도록 `service/config/sub_config/`에 해당 설정 추가
4. `apply_change` → `reload_builtin_mcp()` 연결하여 변경 즉시 반영

### 커스텀 서버로 추가 (사용자 추가, 프리셋 필터링)

1. `mcp/custom/{이름}.json` 생성
2. 비밀 정보에 `${ENV_VAR}` 사용 — 변수 누락 시 서버 스킵
3. Tool Sets UI에 표시되어 프리셋별 토글 가능

---

## 관련 문서

- [TOOLS_KO.md](TOOLS_KO.md) — Python 도구 & 프록시 MCP 패턴
- [CONFIG_KO.md](CONFIG_KO.md) — 설정 시스템 (BaseConfig, env_sync)
- [WORKFLOW_KO.md](WORKFLOW_KO.md) — 워크플로우 시스템 & 세션 관리
