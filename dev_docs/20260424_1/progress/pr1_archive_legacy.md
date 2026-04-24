# PR-1 Progress — Dead code + Docs archive + Layout

**Branch:** `chore/20260424_1-pr1-archive-legacy`
**Status:** Ready for review
**Base:** `main @ f16103a`

## Changes

### Deleted (dead code)
- `backend/service/langgraph/autonomous_graph.py.bak` — 985 LOC, 0 references

### Archived — `backend/docs/_archive/langgraph-era/` (26 files)
- `AGENT_IMPROVEMENT_PLAN{,_KO}.md`
- `AUTONOMOUS_AGENT_ANALYSIS{,_KO}.md`
- `AUTONOMOUS_GRAPH_ANALYSIS{,_KO}.md`
- `AUTONOMOUS_GRAPH_DEEP_DIVE{,_KO}.md`
- `AUTONOMOUS_GRAPH_OPTIMIZATION{,_KO}.md`
- `COST_TRACKING_ANALYSIS{,_KO}.md`
- `LANGGRAPH_PORTING{,_KO}.md`
- `NEW_NODE_GUIDE{,_KO}.md`
- `NODE_EXECUTION{,_KO}.md`
- `NODE_INTERFACE{,_KO}.md`
- `SUDO_COMPILER{,_KO}.md`
- `TOOLS_INTEGRATION_ANALYSIS{,_KO}.md`
- `WORKFLOW_OVERVIEW{,_KO}.md`

### Archived — `docs/_archive/` (13 files)
- `vtuber-porting-v1/`: 01~03 리포트 + `AIRI_이식_구현_리포트.md` (4)
- `langgraph-era/`: `SESSION_CLI_LIFECYCLE_REPORT.md`, `OPTIMIZED_GRAPH_ENHANCEMENT_PLAN.md` (2)
- `executor-migration-v1/`: `MIGRATION_*`, `EXECUTION_AUDIT_V2.md`, `EXECUTION_FINAL_REPORT.md` (4)
- `debugging-logs/`: `TTS_CUDA_ERROR_*`, `tts_problem_0401.md`, `GPT_SOVITS_DEBUG_COMMANDS.md` (3)

### Taxonomized — `docs/`
- `docs/planning/` ← 10 WIP plans
- `docs/analysis/` ← 13 완료된 조사·리뷰
- `docs/` 루트 = Current & Reference (10 files)

### New navigation files
- `docs/README.md` — 프로젝트 문서 네비게이션
- `docs/_archive/README.md` — 아카이브 분류 설명
- `backend/docs/README.md` — 백엔드 내부 문서 네비게이션
- `backend/docs/_archive/README.md` — 레거시 분류 설명

### Cycle 문서
- `dev_docs/20260424_1/analysis/legacy_executor_audit.md`
- `dev_docs/20260424_1/plan/cycle_plan.md`
- `dev_docs/20260424_1/progress/pr1_archive_legacy.md` (이 파일)

## Verification

- 삭제 파일: `git ls-files backend/service/langgraph/ | grep bak` → empty
- Archive 구조: `find docs/_archive backend/docs/_archive -name "*.md" | wc -l` → 39 (+2 README = 41)
- Python 회귀: 파일 이동·삭제만 (import 변경 없음) → sanity import 통과
- Dev docs cycle 폴더: `dev_docs/20260424_1/{analysis,plan,progress}/` 모두 채워짐

## Next

PR-2: `mcp_tools_server.py` 삭제 + `langchain-{anthropic,core}` 의존성 제거.
