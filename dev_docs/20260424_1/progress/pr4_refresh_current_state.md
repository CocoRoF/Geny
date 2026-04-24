# PR-4 Progress — Refresh current-state references

**Branch:** `docs/20260424_1-pr4-refresh-current-state`
**Base:** `main @ 8c0ced5` (PR-3 merged)

## Changes

### Additional archive moves (stale beyond rename)
현재 존재하지 않는 엔티티를 설명하는 문서 3쌍 = 5 파일을 archive로 이동:

- `backend/docs/SESSIONS.md` + `_KO.md` → `_archive/langgraph-era/` — `ClaudeCLIChatModel`, `ClaudeProcess`, `CompiledStateGraph` 전제. 현재 Source of Truth 는 코드 (`service/executor/agent_session.py`, `service/execution/agent_executor.py`) 직접.
- `backend/docs/WORKFLOW.md` + `_KO.md` → `_archive/langgraph-era/` — `WorkflowExecutor`, `StateGraph(AutonomousState)`, `backend/service/workflow/` 폴더 자체가 현재 존재하지 않음.
- `docs/optimizing_model.md` → `docs/_archive/langgraph-era/` — `ClaudeCLIChatModel`, `AgentSession._build_graph()`, `claude_cli_model.py` 모두 없음.

### Navigation refresh
- `backend/docs/README.md` — 실행 흐름 테이블에서 SESSIONS/WORKFLOW 링크 제거 + archive 안내 추가. `_archive/langgraph-era/` 파일 수 업데이트 (13쌍 → 15쌍).
- `backend/docs/_archive/README.md` — 신규 추가된 3쌍 설명 + 카테고리 표에 행 추가.
- `docs/README.md` — `optimizing_model.md` 링크 제거.
- `docs/_archive/README.md` — `optimizing_model.md` 추가.

### Current-state notes
- `docs/CURRENT_STATE_REPORT.md` 상단에 `2026-04-24 Update` 블록 추가 — PR #258/259/260 요약 + cycle 링크.
- `docs/EXECUTOR_INTEGRATION_REPORT.md` 상단에 동일 업데이트 블록 + "본문은 2026-04-14 스냅샷" 경고.

### README refresh
- `backend/README.md`, `backend/README_KO.md` — 머리말·핵심기능·ASCII 다이어그램의 "LangGraph StateGraph" / "Claude CLI 기반" 서술을 "geny-executor Pipeline" 관점으로 교체.
- `backend/main.py:588` — 주석 `# LangGraph agent sessions` → `# geny-executor agent sessions`.

### Docstring + body substitutions
| File | 변경 |
|---|---|
| `backend/controller/agent_controller.py` | 5 docstring 라인 (module, AgentInvokeRequest, create_agent, invoke, execute loop comment) |
| `backend/service/prompt/protocols.py` | module docstring — "LangGraph graph controls loop" → geny-executor Pipeline |
| `backend/service/prompt/sections.py` | design philosophy 블록 |
| `backend/service/vtuber/emotion_extractor.py` | map_state_to_emotion docstring |
| `backend/service/executor/context_guard.py` | 모듈 docstring — "Integrable with LangGraph state" → PipelineState |
| `backend/service/executor/agent_session_manager.py` | 2곳 (class docstring + prompt-build docstring) |
| `backend/service/executor/agent_session.py` | 2곳 (`enable_checkpointing` arg doc) |
| `backend/docs/LOGGING.md` + `_KO.md` | `GRAPH` 레벨 표 설명 + "Pipeline Event Logging" 섹션 제목 |
| `backend/prompts/README.md` + `_KO.md` | execution-loops 표 행 + "Don't repeat executor's job" 가이드 |
| `docs/broadcast_logic.md` | ASCII 다이어그램 박스 내용 교체 (LangGraph 노드 → geny-executor Stage) |

## Intentional leftovers (not edited)

아래는 의도적으로 "LangGraph" 언급을 유지:

- `backend/service/logging/session_logger.py:49` — `# Legacy alias kept so DB rows persisted under the old LangGraph-era ...` (DB row 호환 주석)
- `backend/tests/service/logging/test_stage_logging.py:4` — 이 테스트의 목적이 바로 "legacy LangGraph Graph → geny-executor Environment" migration 검증
- `docs/README.md`, `backend/docs/README.md`, `docs/_archive/README.md`, `backend/docs/_archive/README.md` — archive 폴더 이름 (`langgraph-era/`) 설명
- `docs/analysis/*` + `docs/planning/*` — 특정 시점 스냅샷 문서. 본문을 retroactively 수정하면 시간 맥락이 왜곡되므로 유지. `docs/README.md` 에서 이미 "snapshot" 으로 분류.
- `docs/EXECUTOR_INTEGRATION_REPORT.md` 본문 — 2026-04-14 상태 기록. 상단 update 블록으로 현재 상태 연결.

## Verification

```
$ grep -rn "LangGraph\|langgraph" backend/ docs/ --include="*.py" --include="*.md" \
    | grep -v __pycache__ | grep -v "_archive/"
```

결과는 위 "Intentional leftovers" 카테고리 22건만 남음. 의도적 유지 근거 각 항목에 기재.

## Cycle complete

PR-1 `#258` + PR-2 `#259` + PR-3 `#260` + PR-4 (this). `dev_docs/20260424_1/` 의 analysis/plan/progress 문서가 전체 근거로 남는다.
