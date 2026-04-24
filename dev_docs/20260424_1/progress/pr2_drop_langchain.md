# PR-2 Progress — Drop LangChain dependency

**Branch:** `chore/20260424_1-pr2-drop-langchain`
**Base:** `main @ afa40f2` (PR-1 merged)

## Changes

### Deleted
- `backend/service/claude_manager/mcp_tools_server.py` (381 LOC, 0 repo references)
  - `MCPToolsServer` 클래스는 LangChain `BaseTool` → MCP 서버 래퍼. repo 전체 import 없음 (자기 참조 + docstring + SESSIONS 문서 트리 언급만).

### Dependency removal
- `backend/requirements.txt` — `langchain-anthropic>=0.3.0`, `langchain-core>=0.3.0` + 관련 주석 제거
- `backend/pyproject.toml` — 동일

### Docs refresh
- `backend/docs/SESSIONS.md:420` — 파일 트리에서 `mcp_tools_server.py` 줄 제거
- `backend/docs/SESSIONS_KO.md:420` — 동일

## Verification

```
$ grep -rn "langchain" backend/ --include="*.py" --include="*.md" --include="*.toml" --include="*.txt" \
  | grep -v __pycache__ | grep -v _archive
(empty)

$ grep -rn "mcp_tools_server\|MCPToolsServer" backend/ docs/ --include="*.py" --include="*.md" \
  | grep -v __pycache__ | grep -v _archive
(empty)
```

`_archive/langgraph-era/` 내부의 역사 문서는 의도적으로 유지 (과거 설계 맥락).

## Next

PR-3: `backend/service/langgraph/` → `backend/service/executor/` 리네임 (~181 매치 일괄 치환).
