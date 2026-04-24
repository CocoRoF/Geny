# Geny Agent — Backend

> Claude CLI 기반 다중 세션 에이전트 관리 시스템

## 프로젝트 개요

Geny Agent는 Claude CLI를 래핑하여 **다중 에이전트 세션**을 관리하는 FastAPI 백엔드입니다. LangGraph 기반의 자율 실행 워크플로우, MCP 도구 통합, 벡터 메모리, 실시간 채팅을 지원합니다.

### 핵심 기능

- **다중 세션** — 독립적인 Claude CLI 프로세스를 병렬 실행·관리
- **자율 워크플로우** — LangGraph StateGraph로 난이도별 분기·리뷰·TODO 분해 자동화
- **MCP 프록시** — 외부 MCP 서버 + 내장 Python 도구를 단일 인터페이스로 통합
- **벡터 메모리** — FAISS + Embedding API로 장기 기억 의미 검색
- **실시간 채팅** — 세션 간 브로드캐스트·DM·SSE 스트리밍
- **설정 관리** — 데이터클래스 기반 UI 자동 생성, DB+JSON 이중 저장

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                     FastAPI (main.py)                    │
│                                                         │
│  10 Routers ─────────────────────────────────────────── │
│  ├── /api/agent/*          세션·에이전트 CRUD + 실행    │
│  ├── /api/sessions/*       레거시 세션 관리             │
│  ├── /api/commands/*       로그 조회 + 모니터           │
│  ├── /api/config/*         설정 CRUD + 내보내기/가져오기│
│  ├── /api/workflows/*      워크플로우 편집기            │
│  ├── /api/shared-folder/*  공유 폴더 파일 CRUD          │
│  ├── /api/chat/*           채팅 브로드캐스트 + DM       │
│  ├── /api/internal-tool/*  프록시 MCP 도구 실행         │
│  ├── /api/tool-presets/*   도구 프리셋 관리             │
│  └── /api/tools/*          도구 카탈로그                │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                     Service Layer                        │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ AgentSession  │  │  Workflow    │  │   Memory     │  │
│  │ Manager       │  │  Executor   │  │   Manager    │  │
│  │ (LangGraph)   │  │  (Compiler) │  │ (LTM+STM+V) │  │
│  └──────┬───────┘  └──────┬──────┘  └──────────────┘  │
│         │                  │                            │
│  ┌──────┴───────┐  ┌──────┴──────┐  ┌──────────────┐  │
│  │ ClaudeProcess │  │ 20 Node    │  │   Prompt     │  │
│  │ (CLI Wrapper) │  │ Types      │  │   Builder    │  │
│  └──────┬───────┘  └─────────────┘  └──────────────┘  │
│         │                                               │
│  ┌──────┴───────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ StreamParser  │  │  ToolLoader │  │  ConfigMgr   │  │
│  │ (JSON Stream) │  │  MCPLoader  │  │  (DB+JSON)   │  │
│  └──────────────┘  └─────────────┘  └──────────────┘  │
│                                                         │
├─────────────────────────────────────────────────────────┤
│                   Infrastructure                         │
│                                                         │
│  PostgreSQL ──── psycopg3 ConnectionPool                │
│  File System ─── JSON/JSONL/Markdown/FAISS              │
│  Claude CLI ──── node.exe + cli.js (stream-json)        │
└─────────────────────────────────────────────────────────┘
```

---

## 시작 시퀀스

`main.py`의 `lifespan()` 핸들러에 의해 순서대로 초기화:

| 단계 | 시스템 | 설명 |
|------|--------|------|
| 1 | **Database** | PostgreSQL 연결, 모델 등록, 테이블 생성, 데이터 마이그레이션 |
| 2 | **Config** | ConfigManager 초기화, DB 백엔드 연결, JSON→DB 마이그레이션 |
| 3 | **Sessions** | SessionStore·ChatStore에 DB 연결 |
| 4 | **Logging** | SessionLogger·AgentSession에 DB 연결 |
| 5 | **Tools** | ToolLoader로 built-in + custom Python 도구 로드 |
| 6 | **MCP** | MCPLoader로 외부 MCP 서버 설정 로드 |
| 7 | **Presets** | ToolPreset 템플릿 설치 |
| 8 | **Workflow** | 워크플로우 노드 등록 + 템플릿 설치 |
| 9 | **Shared** | SharedFolderManager 초기화 + 설정 적용 |
| 10 | **Monitor** | 세션 유휴 모니터 시작 (10분 임계값) |

DB 연결 실패 시 **파일 전용 모드**로 자동 전환 (JSON 기반).

---

## 디렉토리 구조

```
backend/
├── main.py                    # FastAPI 앱 + lifespan 핸들러
├── requirements.txt           # Python 의존성
├── Dockerfile                 # 컨테이너 이미지
│
├── controller/                # API 라우터 (10개)
│   ├── agent_controller.py    #   /api/agent/*
│   ├── claude_controller.py   #   /api/sessions/* (레거시)
│   ├── command_controller.py  #   /api/commands/*
│   ├── config_controller.py   #   /api/config/*
│   ├── workflow_controller.py #   /api/workflows/*
│   ├── shared_folder_controller.py
│   ├── chat_controller.py
│   ├── internal_tool_controller.py
│   ├── tool_preset_controller.py
│   └── tool_controller.py
│
├── service/                   # 비즈니스 로직
│   ├── claude_manager/        #   Claude CLI 프로세스 관리
│   ├── executor/              #   geny-executor 에이전트 세션
│   ├── workflow/              #   워크플로우 정의·실행·컴파일러
│   │   ├── nodes/             #     20종 워크플로우 노드
│   │   └── compiler/          #     워크플로우 테스트 컴파일러
│   ├── memory/                #   LTM + STM + FAISS 벡터
│   ├── chat/                  #   채팅 룸·메시지·인박스
│   ├── config/                #   설정 관리 + 자동 탐색
│   │   └── sub_config/        #     12종 설정 클래스
│   ├── database/              #   PostgreSQL 매니저 + 헬퍼
│   ├── logging/               #   세션별 구조화 로깅
│   ├── prompt/                #   프롬프트 빌더 + 섹션 라이브러리
│   ├── shared_folder/         #   세션 간 공유 폴더
│   ├── tool_policy/           #   도구 접근 정책 엔진
│   ├── tool_preset/           #   도구 프리셋 관리
│   ├── proxy/                 #   Redis 프록시 (미사용)
│   ├── middleware/             #   미들웨어 (미사용)
│   ├── pod/                   #   Pod 관리 (미사용)
│   ├── utils/                 #   유틸리티 (KST 시간 등)
│   ├── mcp_loader.py          #   외부 MCP 서버 설정 로더
│   └── tool_loader.py         #   Python 도구 탐색·로더
│
├── tools/                     # Python 도구 정의
│   ├── base.py                #   BaseTool ABC + @tool 데코레이터
│   ├── _mcp_server.py         #   FastMCP 서버 (내장 도구 노출)
│   ├── _proxy_mcp_server.py   #   프록시 MCP 서버 (Claude ↔ 백엔드)
│   ├── built_in/              #   11종 내장 도구
│   └── custom/                #   11종 커스텀 도구
│
├── prompts/                   # 역할별 Markdown 프롬프트 템플릿
│   ├── worker.md
│   ├── developer.md
│   ├── researcher.md
│   ├── planner.md
│   └── templates/             #   6종 특화 템플릿
│
├── workflows/                 # 워크플로우 JSON 템플릿
│   ├── template-simple.json
│   └── template-autonomous.json
│
├── tool_presets/              # 도구 프리셋 JSON 템플릿
├── mcp/                       # MCP 서버 설정 예제
├── logs/                      # 세션 로그 파일
└── docs/                      # 📖 상세 문서 (아래 참조)
```

---

## 문서 목록

각 시스템의 상세 문서:

| 문서 | 설명 |
|------|------|
| [docs/WORKFLOW.md](docs/WORKFLOW.md) | 워크플로우 시스템 — 20종 노드, StateGraph 컴파일, 실행 흐름, 템플릿 |
| [docs/DATABASE.md](docs/DATABASE.md) | 데이터베이스 — ConnectionPool, 6개 테이블, 쿼리 연산자, 마이그레이션 |
| [docs/TOOLS.md](docs/TOOLS.md) | 도구 & MCP — BaseTool, 프록시 패턴, 정책 엔진, 프리셋 |
| [docs/SESSIONS.md](docs/SESSIONS.md) | 세션 관리 — ClaudeProcess, StreamParser, AgentSession 생명주기 |
| [docs/CHAT.md](docs/CHAT.md) | 채팅 — 브로드캐스트, DM, SSE 스트리밍, 대화 저장소 |
| [docs/MEMORY.md](docs/MEMORY.md) | 메모리 — LTM, STM, FAISS 벡터, 임베딩, 컨텍스트 빌드 |
| [docs/PROMPTS.md](docs/PROMPTS.md) | 프롬프트 — PromptBuilder, 섹션, 역할 템플릿, 컨텍스트 로더 |
| [docs/CONFIG.md](docs/CONFIG.md) | 설정 — BaseConfig, 12종 설정 클래스, 자동 탐색, env_sync |
| [docs/LOGGING.md](docs/LOGGING.md) | 로깅 — 11종 LogLevel, 삼중 기록, 구조화 추출 |
| [docs/SHARED_FOLDER.md](docs/SHARED_FOLDER.md) | 공유 폴더 — 심볼릭 링크, 보안 검증, REST API |

---

## 환경 설정

### 필수 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | Anthropic API 키 | — |
| `POSTGRES_HOST` | PostgreSQL 호스트 | `localhost` |
| `POSTGRES_PORT` | PostgreSQL 포트 | `5432` |
| `POSTGRES_DB` | 데이터베이스명 | `geny_agent` |
| `POSTGRES_USER` | DB 사용자 | `geny` |
| `POSTGRES_PASSWORD` | DB 비밀번호 | — |

### 선택 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `ANTHROPIC_MODEL` | Claude 모델 | `claude-sonnet-4-6` |
| `APP_PORT` | 서버 포트 | `8000` |
| `GITHUB_TOKEN` | GitHub PAT | — |
| `GENY_LANGUAGE` | UI 언어 (`en`/`ko`) | `en` |
| `CLAUDE_MAX_BUDGET_USD` | 세션당 최대 비용 | `10.0` |
| `CLAUDE_MAX_TURNS` | 태스크당 최대 턴 | `50` |

전체 환경변수 목록은 [docs/CONFIG.md](docs/CONFIG.md) 참조.

---

## 실행

### Docker Compose (권장)

```bash
docker compose -f docker-compose.dev.yml up
```

### 로컬 실행

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## API 개요

| 접두사 | 컨트롤러 | 주요 기능 |
|--------|----------|-----------|
| `/api/agent` | agent_controller | 에이전트 세션 CRUD, 메시지 전송, SSE 스트리밍 |
| `/api/sessions` | claude_controller | 레거시 세션 관리 |
| `/api/commands` | command_controller | 로그 조회, 모니터링, 프롬프트 목록 |
| `/api/config` | config_controller | 설정 CRUD, 내보내기/가져오기, 재로드 |
| `/api/workflows` | workflow_controller | 워크플로우 CRUD, 노드 카탈로그 |
| `/api/shared-folder` | shared_folder_controller | 공유 폴더 파일 CRUD, 업·다운로드 |
| `/api/chat` | chat_controller | 채팅 룸, 메시지, 브로드캐스트, SSE |
| `/api/internal-tool` | internal_tool_controller | 프록시 MCP 도구 실행 |
| `/api/tool-presets` | tool_preset_controller | 도구 프리셋 CRUD |
| `/api/tools` | tool_controller | 도구 카탈로그 조회 |
| `/health` | main.py | 헬스 체크 (DB 상태 포함) |

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 웹 프레임워크 | FastAPI + Uvicorn |
| 데이터베이스 | PostgreSQL + psycopg3 |
| 그래프 엔진 | LangGraph (StateGraph) |
| LLM | Claude CLI (node.exe + cli.js) + Anthropic API |
| 벡터 DB | FAISS (IndexFlatIP) |
| 임베딩 | OpenAI / Google / Voyage AI |
| MCP | Model Context Protocol (stdio ↔ HTTP 프록시) |
| 템플릿 | Jinja2 (대시보드 렌더링) |
