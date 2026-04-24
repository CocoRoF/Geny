# PR-1 Progress — Remove legacy `/api/sessions` claude_controller

**Branch:** `chore/20260424_2-pr1-remove-claude-controller`
**Base:** `main @ b42f8f2` (cycle 20260424_1 완료)

## Changes

### Deleted
- `backend/controller/claude_controller.py` (397 LOC) — `/api/sessions/*` CRUD, execute, storage 라우트. frontend 호출 0건, backend internal 호출 0건 확인.

### Main.py unmount
- `backend/main.py:29` — `from controller.claude_controller import router as claude_router` 제거
- `backend/main.py:586` — `app.include_router(claude_router)` 제거

### Docs refresh (claude_controller 언급 제거, session_memory_controller 와 혼동 방지)
- `backend/README.md:28, 99` — router list + file tree
- `backend/README_KO.md:28, 99, 228` — 같은 세 곳 + API 표
- `backend/docs/SUB_WORKER.md:70`, `SUB_WORKER_KO.md:70` — sub-worker 생성 시퀀스 예제에서 `POST /api/sessions` → `POST /api/agents` 로 갱신, `create_session` → `create_agent_session` 도 일치
- `backend/controller/agent_controller.py:1-8` module docstring — "Legacy Session API: /api/sessions" 줄 제거

### Scope boundary
- `backend/service/claude_manager/models.py` 내 `ExecuteRequest`, `ExecuteResponse`, `ToolCallInfo`, `StorageFile/List/Content` 등 모델은 **건드리지 않음**. `agent_controller.py:642` `POST /api/agents/{id}/execute` 가 `ExecuteRequest/Response` 를 active 사용, `ToolCallInfo` 는 legacy only 였지만 PR-4 재배치 단계에서 일괄 정리.
- `backend/controller/session_memory_controller.py` (`/api/sessions/{id}/memory`) 는 별개 라우터, 계속 mount 상태.

## Verification

```
$ grep -rn "claude_controller\|claude_router" backend/ \
    | grep -v __pycache__ | grep -v _archive
(empty)

$ grep -rn "/api/sessions" backend/ | grep -v __pycache__ | grep -v _archive
```

→ 결과는 전부 `session_memory_controller` (/api/sessions/{id}/memory) 언급 + main.py:297 의 `/api/sessions/{id}/memory endpoints return 404` 주석 — 올바른 활성 경로.

## Next

PR-2: `AgentSessionManager(SessionManager)` 상속 끊기. `_global_mcp_config` / `set_global_mcp_config` 자체 구현, `_local_processes` legacy compat 코드 제거.
