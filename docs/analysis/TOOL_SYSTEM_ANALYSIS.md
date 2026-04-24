# Geny Tool System 완벽 분석 리포트

> 작성일: 2026-04-04
> 목적: VTuber/Sub-Worker 모드별 Tool 고도화를 위한 현행 시스템 분석

---

## 1. 아키텍처 전체 개요

```
┌─────────────────────────────────────────────────────────────────┐
│                        Geny Backend (FastAPI)                   │
│                                                                 │
│  ┌──────────────┐   ┌───────────────┐   ┌────────────────────┐ │
│  │  ToolLoader   │   │ ToolPresetStore│   │ AgentSessionManager│ │
│  │  (Singleton)  │   │  (JSON Files)  │   │   (Orchestrator)   │ │
│  └──────┬───────┘   └───────┬───────┘   └────────┬───────────┘ │
│         │                   │                     │             │
│  ┌──────▼──────────────────▼─────────────────────▼───────────┐ │
│  │                   Session Creation Flow                    │ │
│  │  1. Tool Preset 결정 (role → default preset)               │ │
│  │  2. allowed_tools 필터링 (preset 기반)                      │ │
│  │  3. build_session_mcp_config() → .mcp.json 생성            │ │
│  │  4. Workflow 할당 (role에 따라 다른 workflow)                │ │
│  └───────────────────────────────────────────────────────────┘ │
│                                                                 │
│  ┌─────────────────────┐     ┌──────────────────────────────┐  │
│  │  /internal/tools/    │◄────│  Proxy MCP Server (stdio)    │  │
│  │  execute (POST)      │     │  (Claude CLI subprocess)     │  │
│  └──────────┬──────────┘     └──────────────────────────────┘  │
│             │                                                   │
│  ┌──────────▼──────────────────────────────────────────────┐   │
│  │  Tool.run(**args) 실행 → Singleton 접근 가능               │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 핵심 원리: Tool은 Workflow 노드가 아니라 Claude CLI의 MCP에서 제공

- Workflow 그래프에는 tool 실행 전용 노드가 필요 없음
- 모든 노드에서 `context.resilient_invoke()` → Claude CLI 호출시 Claude가 `.mcp.json`에 설정된 tool을 **자율적으로** 판단하여 사용
- VTuber든 Sub-Worker든 **Claude CLI subprocess 자체가 MCP를 통해 tool에 접근**

---

## 2. Tool 분류 체계

### 2.1 Python Tool (자체 구현)

| 분류 | 디렉토리 | 제어 방식 |
|------|----------|----------|
| **Built-in** | `backend/tools/built_in/` | **항상 포함** — 프리셋 필터링 대상 아님 |
| **Custom** | `backend/tools/custom/` | **프리셋으로 필터링** — 전체/선택/없음 |

### 2.2 MCP Server (외부 프로세스)

| 분류 | 디렉토리 | 제어 방식 |
|------|----------|----------|
| **Built-in MCP** | `backend/mcp/built_in/` | **항상 포함** — 필터링 없음 |
| **Custom MCP** | `backend/mcp/custom/` | **프리셋으로 필터링** |

---

## 3. 전체 Tool 목록

### 3.1 Built-in Tools (항상 포함 — 17개)

#### Geny Platform Tools (`built_in/geny_tools.py`) — 11개

| Tool Name | 기능 | 파라미터 |
|-----------|------|---------|
| `geny_session_list` | 전체 에이전트(팀원) 세션 목록 조회 | 없음 |
| `geny_session_info` | 특정 에이전트 상세 프로필 조회 | `session_id: str` |
| `geny_session_create` | 새 에이전트 세션 생성(고용) | `session_name`, `role?`, `model?` |
| `geny_room_list` | 전체 채팅방 목록 조회 | 없음 |
| `geny_room_create` | 새 채팅방 생성 + 멤버 추가 | `room_name`, `member_ids` |
| `geny_room_info` | 채팅방 상세 정보 조회 | `room_id: str` |
| `geny_room_add_members` | 기존 방에 멤버 초대 | `room_id`, `member_ids` |
| `geny_send_room_message` | 채팅방에 메시지 전송 | `room_id`, `content` |
| `geny_send_direct_message` | DM 전송 (수신자 **자동 트리거**) | `target_session_id`, `content` |
| `geny_read_room_messages` | 채팅방 메시지 읽기 | `room_id`, `limit?` |
| `geny_read_inbox` | 받은 DM 확인 | `unread_only?`, `mark_read?` |

#### Memory Tools (`built_in/memory_tools.py`) — 6개

| Tool Name | 기능 | 파라미터 |
|-----------|------|---------|
| `memory_write` | 구조화된 메모리 노트 생성 | `session_id`, `title`, `content`, `category`, `tags`, `importance` |
| `memory_read` | 특정 노트 읽기 | `session_id`, `filename` |
| `memory_update` | 노트 수정 | `session_id`, `filename`, `content`, `tags?`, `importance?` |
| `memory_delete` | 노트 삭제 | `session_id`, `filename` |
| `memory_search` | 풀텍스트 + 벡터 검색 | `session_id`, `query`, `max_results?` |
| `memory_list` | 노트 목록 조회 | `session_id`, `category?`, `tag?` |

### 3.2 Custom Tools (프리셋 기반 필터링 — 8개)

#### Web Search (`custom/web_search_tools.py`) — 2개

| Tool Name | 기능 | 파라미터 |
|-----------|------|---------|
| `web_search` | DuckDuckGo 메타검색 | `query`, `max_results?`, `region?`, `timelimit?` |
| `news_search` | 뉴스 검색 | `query`, `max_results?`, `region?`, `timelimit?` |

#### Web Fetch (`custom/web_fetch_tools.py`) — 3개

| Tool Name | 기능 | 파라미터 |
|-----------|------|---------|
| `web_fetch` | 단일 URL 텍스트 추출 (httpx, JS 미지원) | `url`, `extract_text?`, `max_length?`, `timeout?` |
| `web_fetch_multiple` | 최대 5개 URL 병렬 페치 | `urls`, `extract_text?`, `max_length?` |

#### Browser Automation (`custom/browser_tools.py`) — 3개

| Tool Name | 기능 | 파라미터 |
|-----------|------|---------|
| `browser_navigate` | Chromium 브라우저로 URL 탐색 (JS 실행, 세션 유지) | `url`, `wait_for?`, `max_length?` |
| `browser_click` | CSS 셀렉터로 요소 클릭 | `selector`, `wait_after?` |
| `browser_fill_form` | 폼 입력 + 제출 | `selectors`, `submit_selector?` |

### 3.3 MCP Server (외부 프로세스 — 1개)

| Server | 위치 | 기능 |
|--------|------|------|
| **GitHub MCP** | `mcp/built_in/github.json` | Repository, PR, Issue 관리 (`@modelcontextprotocol/server-github`) |

---

## 4. Tool 베이스 클래스 구조

### 4.1 클래스 상속 구조

```
BaseTool (ABC)                    # backend/tools/base.py
├── GenySessionListTool          # 직접 상속 (클래스 기반)
├── WebSearchTool
├── BrowserNavigateTool
└── ...

@tool decorator                   # backend/tools/base.py
└── ToolWrapper                   # 함수를 BaseTool 호환 객체로 래핑
    ├── web_fetch (함수 기반)
    └── ...
```

### 4.2 BaseTool 인터페이스

```python
class BaseTool(ABC):
    name: str          # 고유 식별자 (미지정시 클래스명에서 자동 추론)
    description: str   # LLM이 보는 설명 (미지정시 docstring 사용)
    parameters: Dict   # JSON Schema (미지정시 run() 시그니처에서 자동 생성)

    @abstractmethod
    def run(self, **kwargs) -> str:        # 동기 실행

    async def arun(self, **kwargs) -> str: # 비동기 실행 (기본: sync 위임)

    def to_dict(self) -> Dict:            # MCP 스키마 변환
```

### 4.3 파라미터 스키마 자동 생성

- `run()` 메서드의 `inspect.signature()` 에서 타입 힌트 추출
- Python 타입 → JSON Schema 타입 변환 (`str→string`, `int→integer`, `bool→boolean`)
- Google 스타일 docstring `Args:` 섹션에서 파라미터 설명 파싱
- `inspect.Parameter.empty` 체크로 필수/선택 파라미터 구분

---

## 5. Tool Preset 시스템

### 5.1 프리셋 정의 모델

```python
class ToolPresetDefinition(BaseModel):
    id: str                    # UUID 또는 "template-xxx"
    name: str                  # "Web Research" 등
    description: str
    icon: Optional[str]        # 이모지 아이콘

    custom_tools: List[str]    # ["*"]=전체, []=없음, ["tool1","tool2"]=선택
    mcp_servers: List[str]     # ["*"]=전체, []=없음, ["server1"]=선택

    is_template: bool          # 읽기 전용 템플릿 여부
    template_name: Optional[str]
```

### 5.2 현재 존재하는 프리셋

| 프리셋 ID | 이름 | custom_tools | mcp_servers |
|-----------|------|-------------|-------------|
| `template-all-tools` | All Tools | `["*"]` (전부) | `["*"]` (전부) |

**→ 단 1개의 프리셋만 존재. 모든 role이 동일한 프리셋을 공유**

### 5.3 Role별 기본 프리셋 매핑

```python
ROLE_DEFAULT_PRESET = {
    "worker": "template-all-tools",
    "developer": "template-all-tools",
    "researcher": "template-all-tools",
    "planner": "template-all-tools",
    "vtuber": "template-all-tools",     # ← VTuber도 동일
}
```

### 5.4 프리셋 필터링 로직

```
Built-in Tools → 항상 전부 포함 (필터링 대상 아님)
Custom Tools   → preset.custom_tools로 필터링
   - ["*"]              → 전체 custom tool 포함
   - ["web_search", ...]→ 명시된 tool만 포함
   - []                 → custom tool 없음
MCP Servers    → preset.mcp_servers로 필터링 (동일 로직)
```

---

## 6. VTuber와 Sub-Worker의 Tool 사용 방식

### 6.1 핵심: 둘 다 Tool을 직접 사용한다

VTuber와 Sub-Worker 모두 Claude CLI subprocess를 통해 tool을 **직접 자율적으로** 사용함.

```
모든 노드에서:
  context.resilient_invoke(messages)
    → ClaudeCLIChatModel.invoke()
      → Claude CLI subprocess (with .mcp.json)
        → Claude가 tool 사용 여부 자율 판단
          → MCP로 tool 호출 가능 (web_search, memory_write, etc.)
```

### 6.2 VTuber의 Tool 사용 (직접 + 위임 2가지 경로)

| 방식 | 작동 원리 | 사용 시점 |
|------|----------|----------|
| **직접 사용** | VTuber의 respond/think/classify 노드에서 Claude CLI 호출 → Claude가 MCP tool을 자율적으로 사용 | 간단한 검색, 메모리 저장, 정보 조회 등 |
| **Sub-Worker 위임** | vtuber_delegate 노드가 linked Sub-Worker 세션에 DM으로 task 전달 → Sub-Worker가 autonomous workflow로 실행 | 코드 작성, 파일 조작, 복잡한 멀티스텝 작업 |

#### 실제 동작 예시 (프로덕션 로그에서 확인)

```
14:52:34  COMMAND   "지니야 인터넷에서 2024년 한국시리즈 우승팀 검색해서 정보를 알려줘"
14:53:35  TOOL      mcp___custom_tools__web_search  query="2024년 한국시리즈 우승팀"
14:53:45  RESPONSE  "검색 결과가 나왔어요! 2024년 한국시리즈 우승팀은 KIA 타이거즈에요!"
14:55:34  COMMAND   [THINKING_TRIGGER] 자체 사고
14:55:48  TOOL      mcp___builtin_tools__memory_write  "성준오빠가 한국시리즈 검색 요청..."
14:55:58  RESPONSE  (메모리에 대화 내용 저장 완료)
```

→ VTuber가 `web_search`로 직접 검색 + `memory_write`로 대화 기억 저장

### 6.3 Sub-Worker의 Tool 사용

```
┌─────────────────────────────────────────────────────────┐
│  Sub-Worker Workflow: template-optimized-autonomous             │
│                                                         │
│  START → adaptive_classify                              │
│            ├─ easy → easy_answer → END                  │
│            └─ not_easy → mem_inject                     │
│                         → create_todos (최대 4)          │
│                         → batch_execute_todo ◄── Tool!  │
│                         → mem_reflect → END             │
│                                                         │
│  각 노드에서 Claude CLI가 tool 자율 사용 가능             │
│  batch_execute_todo에서 집중적으로 tool 호출              │
└─────────────────────────────────────────────────────────┘
```

### 6.4 VTuber → Sub-Worker 위임 상세 흐름

```
User: "새 프로젝트 구조 만들어줘"
         │
         ▼
VTuber classify: "delegate_to_sub_worker" (코드/파일 작업 필요)
         │
         ▼
VTuber delegate_node:
  1. linked Sub-Worker session ID 조회
  2. LLM으로 task 재구성 ("새 프로젝트 구조를 생성하세요")
  3. 최근 5개 대화 맥락 추출 (각 300자 제한)
  4. DM 전송 → Sub-Worker 세션 inbox
  5. _trigger_dm_response() → background asyncio task
  6. User에게 즉시 응답: "[joy] 알겠어요! 지금 바로 처리 시작할게요~"
         │
         ▼
Sub-Worker 세션 (자동 트리거):
  1. DM 읽기 → task 파악
  2. execute_command() → autonomous workflow 실행
  3. 파일 생성, git 명령 등 tool 호출
  4. 결과를 DM으로 VTuber에게 회신
         │
         ▼
VTuber:
  1. [SUB_WORKER_RESULT] 수신 → thinking 경로
  2. 결과를 자연어로 재해석
  3. [joy] 감정 태그 + 사용자에게 응답
```

---

## 7. VTuber Workflow 상세 (`template-vtuber.json`)

### 7.1 노드 구성 (8개)

```
START → mem_inject → classify → [respond | delegate | think] → mem_reflect → END
```

| 노드 | 타입 | 역할 |
|------|------|------|
| `start` | start | 시작점 |
| `mem_inject` | memory_inject | 메모리 컨텍스트 주입 |
| `classify` | vtuber_classify | 입력 분류 (3경로) |
| `respond` | vtuber_respond | 직접 대화 응답 (**tool 직접 사용 가능**) |
| `delegate` | vtuber_delegate | Sub-Worker 세션에 작업 위임 |
| `think` | vtuber_think | 자체 사고/반성 (**tool 직접 사용 가능**) |
| `mem_reflect` | memory_reflect | 메모리 반영 |
| `end` | end | 종료 |

### 7.2 분류 경로

| 경로 | 조건 | 대상 |
|------|------|------|
| `direct_response` | 인사, 일상 대화, 간단한 질문, 감정 표현, 일정 이야기 | → respond |
| `delegate_to_sub_worker` | 코드 작성, 파일 작업, 쉘 명령, 복잡한 리서치 | → delegate |
| `thinking` | `[THINKING_TRIGGER]` 또는 `[SUB_WORKER_RESULT]` prefix | → think |

### 7.3 각 노드에서의 Tool 사용

모든 노드가 `context.resilient_invoke()` → Claude CLI를 호출하므로, **Claude가 자율적으로 MCP tool 사용 가능**

| 노드 | Claude CLI 호출 | Tool 사용 빈도 | 대표 tool |
|------|----------------|--------------|----------|
| classify | ✅ `resilient_invoke()` | 낮음 | 분류 작업이므로 tool 거의 안 씀 |
| respond | ✅ `resilient_invoke()` | **높음** | `web_search`, `news_search`, `web_fetch` |
| delegate | ✅ `resilient_invoke()` (task 재구성) | 낮음 | task 문장 생성용으로만 |
| think | ✅ `resilient_invoke()` | **높음** | `memory_write`, `memory_search` |

---

## 8. Tool 실행 플로우 (기술 상세)

### 8.1 Tool 호출 체인

```
1. Workflow Node → context.resilient_invoke(messages)
   └─ ClaudeCLIChatModel.invoke()
      └─ Claude CLI subprocess 실행

2. Claude CLI (subprocess)
   └─ .mcp.json 로드 → MCP Server 목록 확인
   └─ Tool 사용 결정 (LLM 자율 판단)
   └─ MCP 프로토콜로 Proxy MCP Server에 요청

3. Proxy MCP Server (_proxy_mcp_server.py - stdio subprocess)
   └─ Tool 스키마 확인
   └─ HTTP POST → http://localhost:8000/internal/tools/execute
   └─ Body: { tool_name, args, session_id }

4. FastAPI Main Process (internal_tool_controller.py)
   └─ ToolLoader.get_tool(tool_name) → BaseTool/ToolWrapper 인스턴스
   └─ tool.arun(**args) 또는 tool.run(**args)
   └─ Singleton 접근 가능 (AgentSessionManager, ChatStore 등)

5. 결과 반환
   └─ ToolExecuteResponse(result=str(result))
   └─ Proxy → Claude CLI → 다음 동작 결정
```

### 8.2 MCP 서버 네이밍

Claude CLI에서 보이는 tool 이름 형식:
```
mcp___builtin_tools__memory_write      ← _builtin_tools MCP 서버의 memory_write
mcp___custom_tools__web_search         ← _custom_tools MCP 서버의 web_search
```

### 8.3 Proxy 패턴을 쓰는 이유

- Claude CLI는 별도 **subprocess**로 실행됨
- Tool은 FastAPI **메인 프로세스**의 싱글톤에 접근 필요 (AgentSessionManager, ChatStore, InboxManager)
- Proxy가 HTTP로 메인 프로세스에 실행을 위임하여 싱글톤 접근 가능

---

## 9. Tool 로딩 매커니즘

### 9.1 ToolLoader (`service/tool_loader.py`)

```python
class ToolLoader:
    builtin_tools: Dict[str, Any]   # 항상 로드
    custom_tools: Dict[str, Any]    # 항상 로드 (프리셋으로 필터링은 별도)
    _tool_source: Dict[str, str]    # tool_name → source_file (UI 그룹핑용)
```

### 9.2 로딩 순서

```
1. load_all() 호출
   ├─ tools/built_in/ 스캔 → *_tools.py 파일 찾기
   │   ├─ geny_tools.py → 모듈 로드 (11개 tool)
   │   └─ memory_tools.py → 모듈 로드 (6개 tool)
   └─ tools/custom/ 스캔 → *_tools.py 파일 찾기
       ├─ browser_tools.py → 모듈 로드 (3개 tool)
       ├─ web_search_tools.py → 모듈 로드 (2개 tool)
       └─ web_fetch_tools.py → 모듈 로드 (3개 tool)

2. 모듈당 Tool 수집
   ├─ 방법1: 모듈에 TOOLS 리스트 존재 → 그것 사용
   └─ 방법2: 모듈 전체 스캔 → BaseTool/ToolWrapper 인스턴스 자동 수집
```

### 9.3 build_session_mcp_config() 흐름

```python
def build_session_mcp_config(
    global_config,            # 글로벌 MCP 설정
    allowed_builtin_tools,    # 허용된 built-in tool 이름 목록
    allowed_custom_tools,     # 허용된 custom tool 이름 목록
    session_id,
    backend_port=8000,
    allowed_mcp_servers=None, # 허용된 MCP 서버 목록
    extra_mcp=None,           # 세션별 추가 MCP 설정
) -> MCPConfig:
```

생성하는 MCP 서버 목록:
1. `_builtin_tools` → Proxy MCP (built-in tools용, allowed_builtin_tools 필터)
2. `_custom_tools` → Proxy MCP (custom tools용, allowed_custom_tools 필터)
3. Built-in MCP → `mcp/built_in/*.json` (항상 포함)
4. Custom MCP → `mcp/custom/*.json` (allowed_mcp_servers로 필터)
5. Extra MCP → 세션별 추가 설정

**VTuber와 Sub-Worker 구분 없이** 동일한 함수 사용. preset 설정에 의해서만 차이 발생.

---

## 10. 현재 구조의 특성 및 개선 포인트

### 10.1 현재 상태 요약

| 항목 | 현황 |
|------|------|
| 프리셋 수 | **1개** (`template-all-tools`) |
| Role 구분 | 모든 role이 동일 프리셋 사용 |
| VTuber tool 사용 | **직접 사용** (Claude CLI의 MCP를 통해 자율적으로) |
| Sub-Worker tool 사용 | **직접 사용** (동일 메커니즘) |
| Built-in 필터링 | **불가능** — 프리셋 시스템이 built-in을 필터링 안 함 |
| VTuber/Sub-Worker tool 차이 | **없음** — 둘 다 동일한 25개 tool에 접근 |

### 10.2 VTuber와 Sub-Worker에서 각 Tool의 적합성 분석

| Tool | VTuber 적합성 | Sub-Worker 적합성 | 비고 |
|------|-------------|----------|------|
| `web_search` | ✅ 높음 — 일상 대화 중 검색 | ✅ 높음 — 리서치 | 양쪽 모두 유용 |
| `news_search` | ✅ 높음 — "요즘 뉴스 뭐 있어?" | ✅ 보통 | VTuber에 더 자연스러움 |
| `web_fetch` | ⚠️ 보통 — 가끔 유용 | ✅ 높음 — 데이터 수집 | |
| `web_fetch_multiple` | ❌ 낮음 — VTuber가 병렬 페치? | ✅ 높음 — 대량 수집 | Sub-Worker 전용이 적절 |
| `browser_navigate` | ❌ 낮음 — 일상 대화에 불필요 | ✅ 높음 — 웹 자동화 | Sub-Worker 전용이 적절 |
| `browser_click` | ❌ 낮음 | ✅ 높음 — UI 자동화 | Sub-Worker 전용이 적절 |
| `browser_fill_form` | ❌ 낮음 | ✅ 높음 — 자동화 | Sub-Worker 전용이 적절 |
| `memory_write` | ✅ 높음 — 대화 기억 저장 | ✅ 높음 — 작업 맥락 저장 | 양쪽 모두 필수 |
| `memory_read/search` | ✅ 높음 — "전에 뭘 얘기했지?" | ✅ 높음 — 맥락 참조 | 양쪽 모두 필수 |
| `memory_update/delete` | ⚠️ 보통 | ✅ 높음 | |
| `geny_session_list` | ⚠️ 보통 — "팀원 누구 있어?" | ✅ 높음 — 작업 분배 | |
| `geny_session_create` | ❌ 낮음 — VTuber가 세션 생성? | ✅ 높음 — 자동 스케일링 | Sub-Worker 전용이 적절 |
| `geny_room_create` | ❌ 낮음 | ✅ 높음 — 협업 구조 | Sub-Worker 전용이 적절 |
| `geny_send_direct_message` | ✅ 높음 — 팀원에게 연락 | ✅ 높음 — 협업 | 양쪽 모두 유용 |
| `geny_read_inbox` | ✅ 높음 — DM 확인 | ✅ 높음 — DM 확인 | 양쪽 모두 필수 |
| `geny_send_room_message` | ⚠️ 보통 | ✅ 높음 | |
| `geny_read_room_messages` | ⚠️ 보통 | ✅ 높음 | |

### 10.3 프리셋 시스템 미활용

- 프리셋 CRUD API, 프리셋 관리 UI, Role별 기본 프리셋 매핑이 **이미 존재**
- 하지만 `template-all-tools` 1개만 쓰고 있어서 **사실상 비활성**
- Built-in tools가 필터링 대상에서 제외되어 있어 세밀한 제어 불가

### 10.4 Built-in 필터링 불가 문제

현재 `get_allowed_tools_by_category()` 에서:
- Built-in tools → **무조건 전부 반환** (geny_tools 11개 + memory_tools 6개)
- Custom tools → 프리셋 기반 필터링

→ VTuber에 불필요한 `geny_session_create`, `browser_*` 등이 항상 노출

### 10.5 현재 구조에서 Tool 추가시 문제

1. **새 tool을 만들면 VTuber/Sub-Worker 구분 없이 모두에게 노출**
2. **VTuber에 불필요한 tool이 많을수록 LLM 컨텍스트 낭비 + 잘못된 tool 사용 가능성 증가**
3. **Role별 tool 세트를 만들 인프라는 있지만 실제로 사용하고 있지 않음**

---

## 11. 파일 참조 맵

| 파일 | 역할 |
|------|------|
| `backend/tools/base.py` | BaseTool, @tool 데코레이터, ToolWrapper 정의 |
| `backend/tools/built_in/geny_tools.py` | Geny 플랫폼 Tool 11개 |
| `backend/tools/built_in/memory_tools.py` | Memory Tool 6개 |
| `backend/tools/custom/web_search_tools.py` | Web/News 검색 2개 |
| `backend/tools/custom/web_fetch_tools.py` | URL 페치 3개 |
| `backend/tools/custom/browser_tools.py` | Playwright 브라우저 3개 |
| `backend/service/tool_loader.py` | Tool 로딩/검색/필터링 |
| `backend/service/tool_preset/templates.py` | 프리셋 템플릿 정의 + Role 매핑 |
| `backend/service/tool_preset/store.py` | 프리셋 JSON CRUD |
| `backend/service/tool_preset/models.py` | ToolPresetDefinition 모델 |
| `backend/service/mcp_loader.py` | MCP 설정 빌드 (`build_session_mcp_config`) |
| `backend/service/langgraph/agent_session_manager.py` | 세션 생성 + Tool/Preset 연결 |
| `backend/service/langgraph/claude_cli_model.py` | Claude CLI 모델 (MCP config 전달) |
| `backend/tools/_proxy_mcp_server.py` | Proxy MCP Server (subprocess) |
| `backend/controller/internal_tool_controller.py` | Tool 실행 엔드포인트 |
| `backend/controller/tool_controller.py` | Tool 카탈로그 API |
| `backend/service/workflow/nodes/vtuber/vtuber_classify_node.py` | VTuber 입력 분류 |
| `backend/service/workflow/nodes/vtuber/vtuber_respond_node.py` | VTuber 직접 응답 (tool 사용 가능) |
| `backend/service/workflow/nodes/vtuber/vtuber_delegate_node.py` | VTuber → Sub-Worker 위임 |
| `backend/service/workflow/nodes/vtuber/vtuber_think_node.py` | VTuber 자체 사고 (tool 사용 가능) |
| `backend/workflows/template-vtuber.json` | VTuber workflow 정의 |
| `backend/workflows/template-optimized-autonomous.json` | Sub-Worker workflow 정의 |
| `backend/mcp/built_in/github.json` | GitHub MCP 서버 설정 |

---

## 12. 데이터 흐름 요약

```
[시스템 시작]
    │
    ├─ ToolLoader.load_all()
    │   ├─ built_in/ → {geny_*, memory_*}  (17개)
    │   └─ custom/   → {web_search, news_search, web_fetch*, browser_*}  (8개)
    │
    ├─ ToolPresetStore 초기화
    │   └─ template-all-tools.json 로드/생성
    │
    └─ AgentSessionManager에 ToolLoader 연결

[세션 생성 — VTuber든 Sub-Worker든 현재 동일 흐름]
    │
    ├─ role 기반 preset 결정 → "template-all-tools" (모두 동일)
    ├─ ToolLoader.get_allowed_tools_by_category(preset)
    │   ├─ allowed_builtin = [모든 built-in 17개] (항상 전부)
    │   └─ allowed_custom  = [모든 custom 8개]   (["*"] 이므로 전부)
    │
    ├─ build_session_mcp_config(...)
    │   ├─ _builtin_tools Proxy MCP 생성
    │   ├─ _custom_tools Proxy MCP 생성
    │   └─ github MCP 포함
    │
    ├─ System Prompt에 전체 tool 목록 포함
    │
    ├─ Workflow 할당 (role에 따라 달라지는 부분)
    │   ├─ VTuber → template-vtuber (classify → respond/delegate/think)
    │   └─ Sub-Worker → template-optimized-autonomous (classify → easy/batch_execute)
    │
    └─ .mcp.json 저장 → Claude CLI가 사용

[Tool 실행 — VTuber/Sub-Worker 모든 노드에서 가능]
    │
    Workflow Node → context.resilient_invoke()
    → ClaudeCLIChatModel → Claude CLI subprocess
    → Claude 자율 판단 → MCP tool_use → Proxy MCP
    → POST /internal/tools/execute
    → ToolLoader.get_tool(name) → tool.run(**args)
    → 결과 반환 → Claude → 최종 응답
```
