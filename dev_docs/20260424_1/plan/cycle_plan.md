# Cycle 20260424_1 — Legacy Executor Cleanup Plan

**Goal:** geny-executor 기반으로 이미 통일된 backend에서 (a) dead code와 dead LangChain 어댑터 제거, (b) 오해의 소지가 있는 폴더 이름 (`service/langgraph/`) 을 `service/executor/` 로 리네임, (c) LangGraph-era 문서를 `_archive/` 로 이동하고 문서 레이아웃을 재정비.

**Baseline:** `main` @ `f16103a feat: implement inline base64 resolution for chat attachments in AgentSession`

**Cadence:** 4 PRs, 순차. 각 PR은 독립적으로 rebuild + smoke test.

---

## PR-1 — Dead code 제거 + 문서 아카이브 + 새 레이아웃

### 코드 변경
- 삭제: `backend/service/langgraph/autonomous_graph.py.bak` (985 LOC)

### 문서 재구조화

**Principle:** 깊은 중첩 금지. `docs/` 는 *활성 / planning / analysis / _archive*, `backend/docs/` 는 *활성 / _archive*.

#### `docs/` (프로젝트 루트)

```
docs/
├── README.md                    # NEW — 네비게이션 인덱스
├── CURRENT_STATE_REPORT.md
├── EXECUTOR_INTEGRATION_REPORT.md
├── DUAL_AGENT_ARCHITECTURE_PLAN.md
├── VTUBER_ARCHITECTURE_REVIEW.md
├── VTUBER_AVATAR_CREATION_GUIDE.md
├── Thinking_trigger.md
├── broadcast_logic.md
├── OmniVoice_INTEGRATION.md
├── source_live2d_model.md
├── optimizing_model.md
│
├── planning/                    # NEW — WIP 계획
│   ├── OMNIVOICE_STREAMING_IMPROVEMENT_PLAN.md
│   ├── MEMORY_UPGRADE_PLAN.md
│   ├── MEMORY_MODEL_LIGHTWEIGHT_PLAN.md
│   ├── PROMPT_IMPROVEMENT_PLAN.md
│   ├── THINKING_TRIGGER_ENHANCEMENT_PLAN.md
│   ├── GPT_SOVITS_WEBUI_INTEGRATION_PLAN.md
│   ├── TTS_VOICE_IMPROVEMENT_PLAN.md
│   ├── OPSIDIAN_ENHANCEMENT_PLAN.md
│   ├── ADMIN_AUTH_IMPLEMENTATION_PLAN.md
│   └── PHASE2_PLAN.md
│
├── analysis/                    # NEW — 완료된 조사·리뷰
│   ├── CHAT_SYSTEM_DEEP_ANALYSIS_REPORT.md
│   ├── CHAT_IMPROVEMENT_VERIFICATION_REPORT.md
│   ├── VTUBER_ISSUES_ANALYSIS.md
│   ├── TOOL_SYSTEM_ANALYSIS.md
│   ├── VOICE_PROFILE_SYSTEM_REVIEW.md
│   ├── STORAGE_MEMORY_INTERACTION_REVIEW.md
│   ├── USER_OPSIDIAN_MEMORY_INTEGRATION_ANALYSIS.md
│   ├── TRIGGER_CONCURRENCY_ANALYSIS.md
│   ├── THINKING_TRIGGER_CHAT_ISSUE_REPORT.md
│   ├── VRM_3D_통합_심층_분석.md
│   ├── AIRI_Live2D_이식_심층_분석.md
│   ├── obsidian_network_report.md
│   └── playground2d-analysis.md
│
└── _archive/                    # NEW
    ├── README.md                # NEW — 왜 archive됐는지
    ├── vtuber-porting-v1/
    │   ├── 01_VTuber_렌더링_시스템_분석_리포트.md
    │   ├── 02_Geny_구조_및_이식_가능성_리포트.md
    │   ├── 03_VTuber_이식_세부_계획서.md
    │   └── AIRI_이식_구현_리포트.md
    ├── langgraph-era/
    │   ├── SESSION_CLI_LIFECYCLE_REPORT.md
    │   └── OPTIMIZED_GRAPH_ENHANCEMENT_PLAN.md
    ├── executor-migration-v1/
    │   ├── MIGRATION_PROGRESS.md
    │   ├── MIGRATION_REPORT.md
    │   ├── EXECUTION_AUDIT_V2.md
    │   └── EXECUTION_FINAL_REPORT.md
    └── debugging-logs/
        ├── TTS_CUDA_ERROR_DIAGNOSTIC_REPORT.md
        ├── tts_problem_0401.md
        └── GPT_SOVITS_DEBUG_COMMANDS.md
```

#### `backend/docs/`

```
backend/docs/
├── README.md                    # NEW — 네비게이션
├── CHAT.md + CHAT_KO.md
├── CONFIG.md + CONFIG_KO.md
├── DATABASE.md + DATABASE_KO.md
├── DATABASE_ARCHITECTURE.md + KO
├── EXECUTION.md + EXECUTION_KO.md
├── LOGGING.md + LOGGING_KO.md
├── MCP.md + MCP_KO.md
├── MEMORY.md + MEMORY_KO.md
├── PROMPTS.md + PROMPTS_KO.md
├── SESSIONS.md + SESSIONS_KO.md
├── SHARED_FOLDER.md + SHARED_FOLDER_KO.md
├── SUB_WORKER.md + SUB_WORKER_KO.md
├── TOOLS.md + TOOLS_KO.md
├── WORKFLOW.md + WORKFLOW_KO.md        # PR-4에서 내용 갱신
│
└── _archive/                    # NEW
    ├── README.md                # NEW
    └── langgraph-era/
        ├── AUTONOMOUS_AGENT_ANALYSIS.md + KO
        ├── AUTONOMOUS_GRAPH_ANALYSIS.md + KO
        ├── AUTONOMOUS_GRAPH_DEEP_DIVE.md + KO
        ├── AUTONOMOUS_GRAPH_OPTIMIZATION.md + KO
        ├── NODE_EXECUTION.md + KO
        ├── NODE_INTERFACE.md + KO
        ├── LANGGRAPH_PORTING.md + KO
        ├── NEW_NODE_GUIDE.md + KO
        ├── WORKFLOW_OVERVIEW.md + KO
        ├── AGENT_IMPROVEMENT_PLAN.md + KO
        ├── TOOLS_INTEGRATION_ANALYSIS.md + KO
        ├── COST_TRACKING_ANALYSIS.md + KO
        └── SUDO_COMPILER.md + KO
```

### 테스트
- `python -c "import backend"` (sanity)
- `pytest backend/tests/ -x -q` 일부 (변경 없음, 회귀 없음 확인)

### Commit 메시지
```
chore(docs): archive LangGraph-era docs + delete dead backup
```

---

## PR-2 — LangChain 의존성 완전 제거

**발견:** `MCPToolsServer` (381 LOC) 는 repo 전체에서 실사용 0건. `langchain_core`의 유일한 소비자.

### 변경
- 삭제: `backend/service/claude_manager/mcp_tools_server.py`
- `backend/requirements.txt`: `langchain-anthropic>=0.3.0`, `langchain-core>=0.3.0` 두 줄 제거
- `backend/pyproject.toml`: 동일 두 줄 제거 (line 19-20)
- `backend/docs/SESSIONS*.md:420` — `mcp_tools_server.py` 언급 제거 (파일 구조 트리 업데이트)

### 테스트
- `python -c "from backend.service.claude_manager import *"` — import 성공
- `pytest backend/tests/ -x -q` — 전체 회귀 없음
- `pip install -r backend/requirements.txt --dry-run` — langchain 제거 확인

### Commit 메시지
```
chore(deps): remove unused LangChain adapter + dependency
```

---

## PR-3 — `service/langgraph/` → `service/executor/` 리네임

**블래스트 반경:** ~40 Python source + 10 test files + 20+ doc refs. 전수 치환 필요.

### 변경 순서
1. `git mv backend/service/langgraph backend/service/executor`
2. `git mv backend/tests/service/langgraph backend/tests/service/executor`
3. 일괄 치환 (`rg -l` 로 리스트 만들고 `sed -i`):
   - `service.langgraph` → `service.executor`
   - `service/langgraph/` → `service/executor/`
   - `service/langgraph` → `service/executor` (docstring 용)
   - 검증: `grep -r "langgraph" backend/` → geny-executor 어댑터가 아닌 실제 LangGraph 라이브러리 이름 언급만 남음 (있다면 개별 평가)
4. `backend/prompts/README*.md`, `backend/CHAT_AND_MESSENGER_REVIEW.md`, `backend/docs/*.md` 에 남은 `service/langgraph` 언급 정리
5. `backend/service/executor/__init__.py` 의 docstring 업데이트 ("LangGraph" → "geny-executor adapter layer")

### 후퇴 금지 정책
- `backend/service/langgraph.py` shim 파일 같은 걸로 역호환성 남기지 **않는다** (사용자 요청: "완벽하게 제거")

### 테스트
- `python -c "from backend.service.executor import AgentSession"` — 성공
- `pytest backend/tests/ -x -q` — 회귀 없음
- `grep -rn "service\.langgraph\|service/langgraph" backend/` — 0 match 확인

### Commit 메시지
```
refactor(executor): rename service/langgraph/ → service/executor/
```

---

## PR-4 — Current-state 문서 리프레시

### 변경
- `backend/README.md` + `backend/README_KO.md`:
  - "LangGraph-based autonomous execution" → "geny-executor Pipeline-based execution"
  - ASCII 다이어그램 `(LangGraph)` → `(geny-executor)`
  - 폴더 트리의 `langgraph/` → `executor/`
  - "그래프 엔진 | LangGraph (StateGraph)" 표 항목 교체
- `backend/main.py:588` 주석 수정
- `backend/CHAT_AND_MESSENGER_REVIEW.md:52` 경로 갱신
- `docs/CURRENT_STATE_REPORT.md` 상단에 "2026-04-24 — LangGraph-era cleanup 완료" 메모
- `docs/EXECUTOR_INTEGRATION_REPORT.md` 상단에 "Legacy cleanup reference: dev_docs/20260424_1/" 링크
- `docs/README.md` + `backend/docs/README.md` 네비게이션 추가 (PR-1 에서 이미 생성됐지만 PR-4 에서 내용 완성)
- `backend/docs/WORKFLOW*.md` — 더 이상 "LangGraph workflow executor" 가 아님, geny-executor Pipeline 관점으로 내용 갱신 (축약 가능)

### 테스트
- Markdown 링크 체크: `find docs/ backend/docs/ -name "*.md" -exec grep -l "service/langgraph" {} \;` → empty

### Commit 메시지
```
docs: refresh current-state references to geny-executor
```

---

## 리스크 & 롤백

| PR | 롤백 난이도 | 리스크 |
|---|---|---|
| PR-1 | Easy (`git revert`) | 없음 (파일 이동만) |
| PR-2 | Easy (`git revert`) | 외부 사용자 코드가 `MCPToolsServer` 를 import 하고 있을 가능성. 단, 내부 사용 0건. |
| PR-3 | Medium (revert 가능, 단 후속 PR-4의 path 수정이 따라옴) | 배포 스크립트/monitoring path에 `service/langgraph` 박혀있을 경우 운영 영향. 사용자에게 사전 점검 권장. |
| PR-4 | Easy | 없음 (문서만) |

## 완료 정의 (Cycle-level)

- [ ] `grep -rn "langgraph\|LangGraph\|langchain\|LangChain" backend/` → 오직 `_archive/langgraph-era/` 안에서만 매치
- [ ] `grep -rn "autonomous_graph" backend/` → 0 match
- [ ] `pip install -r backend/requirements.txt` 후 `pip list | grep langchain` → empty
- [ ] `pytest backend/tests/ -q` green (기존 대비 동일)
- [ ] `docs/README.md` 가 존재하고 현재 디렉토리 네비게이션 제공
- [ ] `dev_docs/20260424_1/progress/` 각 PR별 완료 기록
