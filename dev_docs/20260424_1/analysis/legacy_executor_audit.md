# Legacy Executor Audit (Cycle 20260424_1)

**Date:** 2026-04-24
**Scope:** `/home/geny-workspace/Geny/backend/`, `/home/geny-workspace/Geny/docs/`, `/home/geny-workspace/Geny/backend/docs/`
**Question:** "geny-executor 기반으로 개편되면서 레거시 코드가 남고 있다" — 진짜 어디가 legacy인가?

---

## 1. 세 채널 executor 현황 (결론: 전부 geny-executor 기반)

| 채널 | 진입점 | 실행 경로 | 레거시 여부 |
|---|---|---|---|
| Command | `POST /api/agents/{id}/execute` — `backend/controller/agent_controller.py:642` | `execute_agent_prompt()` → `execute_command()` → `agent.invoke()` → `Pipeline.run()` | 🟢 완전 마이그레이션 |
| VTuber | `POST /api/chat/rooms/{id}/broadcast` — `backend/controller/chat_controller.py:432` | `broadcast_to_room()` → `_run_broadcast()` → `execute_command()` → `Pipeline.run()` | 🟢 완전 마이그레이션 |
| Messenger | `POST /api/chat/rooms/{id}/send` — `backend/controller/chat_controller.py:489` | `send_message_to_room()` → `asyncio.create_task(_run_broadcast(...))` → `execute_command()` → `Pipeline.run()` | 🟢 완전 마이그레이션 |

세 채널 모두 동일한 `backend/service/execution/agent_executor.py:757 execute_command()` 지점으로 수렴. 그 아래는 전부 `geny-executor` Pipeline.

**`from langgraph` / `import langgraph`:** backend 전체 **0건**.

---

## 2. 실제로 남아있는 legacy (정확한 목록)

### 2.1 Dead code (985 LOC)

| 파일 | 상태 | 조치 |
|---|---|---|
| `backend/service/langgraph/autonomous_graph.py.bak` | `.bak` 백업, import 0건 | 삭제 |

### 2.2 사용되지 않는 LangChain 어댑터 (381 LOC)

| 파일 | 설명 | 사용 여부 | 조치 |
|---|---|---|---|
| `backend/service/claude_manager/mcp_tools_server.py` | `MCPToolsServer` — LangChain `BaseTool` → MCP 서버 래퍼 | 코드베이스 전체 import 0건 (자기 참조 + docstring만) | 삭제 |

→ 이 파일이 유일한 `langchain_core` 소비자. 파일 삭제 시 `langchain-anthropic`, `langchain-core` 의존성 불필요.

### 2.3 `requirements.txt` / `pyproject.toml`

| 패키지 | 실 import 지점 | 조치 |
|---|---|---|
| `langchain-anthropic>=0.3.0` | **0건** (requirements.txt:10 / pyproject.toml:19) | 제거 |
| `langchain-core>=0.3.0` | 2건 — 모두 `mcp_tools_server.py` 내부 | PR-2 파일 삭제 후 제거 |

### 2.4 오해를 부르는 폴더 이름

`backend/service/langgraph/` — 내용물은 **전부 geny-executor 어댑터**인데 폴더 이름이 레거시를 암시. 향후 "또 남은 레거시 아닌가?" 혼선을 완전히 차단하려면 리네임.

**내부 파일 (모두 활성, geny-executor 계층):**

| 파일 | LOC | 역할 |
|---|---|---|
| `agent_session.py` | 2,306 | `AgentSession` — `Pipeline` 생명주기 래퍼 + invoke 인터페이스 |
| `agent_session_manager.py` | 1,252 | 세션 생성/관리, 메모리/프롬프트 연동 |
| `stage_manifest.py` | 429 | `EnvironmentManifest` 로더/빌더 |
| `default_manifest.py` | 397 | Role별 기본 manifest (worker/researcher/developer/vtuber) |
| `context_guard.py` | 500 | 도구 실행 전/후 권한·경로 검증 |
| `session_freshness.py` | 350 | 세션 재활성화 타이밍 |
| `model_fallback.py` | 364 | LLM 모델 폴백 체인 |
| `tool_bridge.py` | 175 | Geny 커스텀 도구 → geny-executor Tool 어댑터 |
| `geny_tool_provider.py` | 96 | 도구 제공자 프로토콜 |
| `__init__.py` | 32 | 공개 API |

**총 활성 코드:** 5,901 LOC (전부 보존, 이름만 리네임 대상)

---

## 3. Path 참조 전수 조사 (PR-3 영향 범위)

`grep -rn "service\.langgraph\|service/langgraph" backend/ docs/` → **181개 매치**

- Python source (imports): ~40 파일
- Python tests: `backend/tests/service/langgraph/` 전체 (~10 파일)
- Docs: `backend/docs/`, `docs/`, `backend/prompts/README*.md`, `backend/CHAT_AND_MESSENGER_REVIEW.md` 등

PR-3에서 일괄 `sed` 로 `service.langgraph` → `service.executor`, `service/langgraph/` → `service/executor/` 치환 + 폴더 `git mv`.

---

## 4. 레거시 문서 인벤토리

### 4.1 `backend/docs/` — LangGraph 시절 문서 (archive 대상)

| 파일 쌍 (EN + KO) | 내용 | 이유 |
|---|---|---|
| `AUTONOMOUS_AGENT_ANALYSIS*` | AgentState/AutonomousState 분석 | `state.py` 없어진 지 오래 |
| `AUTONOMOUS_GRAPH_ANALYSIS*` | `autonomous_graph.py` 해부 | 파일 자체가 `.bak`로 묻힘 |
| `AUTONOMOUS_GRAPH_DEEP_DIVE*` | 9개 노드 딥다이브 | 노드 시스템 폐기 |
| `AUTONOMOUS_GRAPH_OPTIMIZATION*` | 최적화 계획 (결국 geny-executor로 대체) | 계획 자체가 실현 안 됨 |
| `NODE_EXECUTION*` | LangGraph 노드 실행 의미론 | 노드 시스템 폐기 |
| `NODE_INTERFACE*` | 노드 인터페이스 계약 | 노드 시스템 폐기 |
| `LANGGRAPH_PORTING*` | LangGraph 포팅 계획 | 이미 포팅 완료, geny-executor로 이사감 |
| `NEW_NODE_GUIDE*` | 새 노드 작성 가이드 | 노드 시스템 폐기 |
| `WORKFLOW_OVERVIEW*` | 워크플로우 시스템 개관 | 워크플로우 실행기 폐기 |
| `AGENT_IMPROVEMENT_PLAN*` | resilience/fallback 계획 (LangGraph era) | geny-executor 도입으로 재구현됨 |
| `TOOLS_INTEGRATION_ANALYSIS*` | LangGraph Node 관점 도구 분석 | 관점 폐기 |
| `COST_TRACKING_ANALYSIS*` | `claude_cli_model.py` 기반 비용 추적 | CLI era 산출물 |
| `SUDO_COMPILER*` | LangGraph StateGraph dry-run 도구 | StateGraph 폐기 |

**소계:** 26 파일 (13 쌍)

### 4.2 `backend/docs/` — 활성 유지 (geny-executor 시대에도 유효)

`CHAT*`, `CONFIG*`, `DATABASE*`, `DATABASE_ARCHITECTURE*`, `EXECUTION*`, `LOGGING*`, `MCP*`, `MEMORY*`, `PROMPTS*`, `SESSIONS*`, `SHARED_FOLDER*`, `SUB_WORKER*`, `TOOLS*`, `WORKFLOW*` — 총 28 파일 (14 쌍)

단, 내부에 `service/langgraph/...` 경로 언급 존재 → PR-3 일괄 치환으로 자연스럽게 해소.

### 4.3 `docs/` (프로젝트 루트) — 상태별 분류

**Active (최근, 유효):**
- `CURRENT_STATE_REPORT.md`
- `EXECUTOR_INTEGRATION_REPORT.md`
- `DUAL_AGENT_ARCHITECTURE_PLAN.md`
- `VTUBER_ARCHITECTURE_REVIEW.md`

**Planning (WIP):**
- `OMNIVOICE_STREAMING_IMPROVEMENT_PLAN.md`
- `MEMORY_UPGRADE_PLAN.md`
- `MEMORY_MODEL_LIGHTWEIGHT_PLAN.md`
- `PROMPT_IMPROVEMENT_PLAN.md`
- `THINKING_TRIGGER_ENHANCEMENT_PLAN.md`
- `GPT_SOVITS_WEBUI_INTEGRATION_PLAN.md`
- `TTS_VOICE_IMPROVEMENT_PLAN.md`
- `OPSIDIAN_ENHANCEMENT_PLAN.md`
- `ADMIN_AUTH_IMPLEMENTATION_PLAN.md`
- `PHASE2_PLAN.md`

**Analysis/Review (완료된 조사):**
- `CHAT_SYSTEM_DEEP_ANALYSIS_REPORT.md`
- `CHAT_IMPROVEMENT_VERIFICATION_REPORT.md`
- `VTUBER_ISSUES_ANALYSIS.md`
- `TOOL_SYSTEM_ANALYSIS.md`
- `VOICE_PROFILE_SYSTEM_REVIEW.md`
- `STORAGE_MEMORY_INTERACTION_REVIEW.md`
- `USER_OPSIDIAN_MEMORY_INTEGRATION_ANALYSIS.md`
- `TRIGGER_CONCURRENCY_ANALYSIS.md`
- `THINKING_TRIGGER_CHAT_ISSUE_REPORT.md`
- `VRM_3D_통합_심층_분석.md`
- `AIRI_Live2D_이식_심층_분석.md`
- `obsidian_network_report.md`
- `playground2d-analysis.md`

**Features / Guides (레퍼런스):**
- `VTUBER_AVATAR_CREATION_GUIDE.md`
- `Thinking_trigger.md`
- `broadcast_logic.md`
- `OmniVoice_INTEGRATION.md`
- `source_live2d_model.md`
- `optimizing_model.md`

**Archive 대상 (레거시):**
- `01_VTuber_렌더링_시스템_분석_리포트.md`, `02_Geny_구조_및_이식_가능성_리포트.md`, `03_VTuber_이식_세부_계획서.md` — 초기 VTuber 포팅 기획, 완료됨
- `AIRI_이식_구현_리포트.md` — AIRI 이식 완료 후 보고서 (히스토리)
- `SESSION_CLI_LIFECYCLE_REPORT.md` — Claude CLI era
- `OPTIMIZED_GRAPH_ENHANCEMENT_PLAN.md` — LangGraph era 최적화 계획
- `MIGRATION_PROGRESS.md`, `MIGRATION_REPORT.md` — 이전 라운드 마이그레이션
- `EXECUTION_AUDIT_V2.md`, `EXECUTION_FINAL_REPORT.md` — 이전 라운드 감사
- `TTS_CUDA_ERROR_DIAGNOSTIC_REPORT.md`, `tts_problem_0401.md`, `GPT_SOVITS_DEBUG_COMMANDS.md` — 단발성 디버깅 기록

---

## 5. README 및 코드 주석의 stale 언급

PR-4에서 업데이트 필요:

- `backend/README.md:7,12,44,111` — "LangGraph StateGraph automates...", "LangGraph agent sessions"
- `backend/README_KO.md:7,12,44,111,247` — 동일 (한글판)
- `backend/main.py:588` — `# LangGraph agent sessions` 주석
- `backend/prompts/README.md:110` + `README_KO.md:110` — `service/langgraph/` 경로 언급 (PR-3 치환으로 해소)
- `backend/CHAT_AND_MESSENGER_REVIEW.md:52` — 동일

---

## 6. 요약 판정

| 범주 | 크기 | 조치 |
|---|---|---|
| **순수 dead code** | 1 file, 985 LOC | PR-1 삭제 |
| **Dead LangChain 어댑터** | 1 file, 381 LOC | PR-2 삭제 + 의존성 제거 |
| **Misleading 폴더명** | `backend/service/langgraph/` (5,901 LOC 보존) | PR-3 리네임 `executor/` |
| **LangGraph-era 문서** | 26 files | PR-1 archive |
| **기타 legacy docs** | 12 files | PR-1 archive (타 카테고리로 분리) |
| **Active docs의 stale 텍스트** | README + 5개 파일 | PR-4 갱신 |

**주 위험:**
- PR-3 폴더 리네임: 운영 스크립트·배포 문서에 경로가 박혀 있으면 첫 배포 시 에러. 리네임 후 `service/langgraph/` 를 남기는 shim 파일 (re-export) 을 **의도적으로 넣지 않음** — 사용자 지침("완벽하게 제거")에 부합.
- `MCPToolsServer`: 외부 (user scripts, notebooks) 에서 import하고 있을 가능성. 사용자 코드는 우리가 관리하지 않는 영역이지만, changelog 한 줄 + 대안 (function + `@mcp.tool()`) 제시.
