# PR-3 Progress — Rename `service/langgraph/` → `service/executor/`

**Branch:** `refactor/20260424_1-pr3-rename-executor`
**Base:** `main @ 597021e` (PR-2 merged)

## Changes

### Folder rename (git mv)
- `backend/service/langgraph/` → `backend/service/executor/` (10 files, 5,901 LOC preserved)
- `backend/tests/service/langgraph/` → `backend/tests/service/executor/` (13 test files)

### Bulk text substitution (54 files)
`sed -i -e 's|service\.langgraph|service.executor|g' -e 's|service/langgraph|service/executor|g'` over:
- Python source: controllers, service modules, tools, tests
- Markdown: `backend/docs/*`, `docs/*`, `backend/prompts/README*`, `backend/CHAT_AND_MESSENGER_REVIEW.md`

### Additional path fixes (not caught by path-separator grep)
- `backend/tests/service/persona/test_sidedoor_removed.py:70` — `_BACKEND / "service" / "langgraph"` → `"executor"` (Path segment form)
- `backend/README.md:111`, `backend/README_KO.md:111` — tree diagram `langgraph/` → `executor/`
- `docs/optimizing_model.md:56,470` — two `langgraph/agent_session.py` residual table cells

## Scope boundaries

PR-3 은 **path 치환**에 한정. README 본문의 "LangGraph-based autonomous workflows" 같은 서술 문장, `backend/docs/WORKFLOW{,_KO}.md` 의 내용 기반 "LangGraph StateGraph" 설명, `main.py:588` 주석 등 **텍스트 설명**은 PR-4 scope 로 밀었다 — 내용 정확성 검토가 path 치환 이상이므로 분리.

## Verification

```
$ grep -rn "service/langgraph\|service\.langgraph" backend/ docs/ \
    | grep -v __pycache__ | grep -v "_archive/"
(empty)

$ grep -rn "langgraph/agent_session\|langgraph/agent_session_manager\|langgraph/stage_manifest\|langgraph/default_manifest\|langgraph/context_guard\|langgraph/model_fallback\|langgraph/session_freshness\|langgraph/tool_bridge\|langgraph/geny_tool" backend/ docs/ \
    | grep -v __pycache__ | grep -v "_archive/"
(empty)

$ git diff --cached --stat | tail -1
 62 files changed, 136 insertions(+), 136 deletions(-)
```

회귀 없음: 순수 rename + path 치환이므로 동작 의미론 변화 0.

## Intentional leftovers (PR-4)

- `backend/README{,_KO}.md` — "LangGraph-based autonomous workflows" 본문 서술
- `backend/main.py:588` — `# LangGraph agent sessions` 주석
- `backend/docs/WORKFLOW{,_KO}.md` — StateGraph 기반 설명
- `backend/docs/SESSIONS{,_KO}.md` — "CompiledStateGraph" 언급
- `backend/docs/LOGGING{,_KO}.md` — "LangGraph state transitions"
- `docs/EXECUTOR_INTEGRATION_REPORT.md:220` — dead import 언급 (내용 갱신 대상)
- `docs/optimizing_model.md` — 전체 내용이 LangGraph era 수준. PR-4 에서 `_archive/langgraph-era/` 이동 검토

## Next

PR-4: 남은 LangGraph 서술 텍스트 갱신 + `CURRENT_STATE_REPORT.md` / `EXECUTOR_INTEGRATION_REPORT.md` 에 2026-04-24 cleanup 메모 + `optimizing_model.md` 아카이브 여부 판단.
