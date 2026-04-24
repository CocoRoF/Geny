# Cycle 20260424_2 — claude_manager/ Dissolution Plan

**Baseline:** `main @ b42f8f2`
**Cadence:** 4 PRs, 각 PR 머지 후 smoke import 확인.

---

## PR-1 — `claude_controller` 삭제 (가장 안전·독립적)

### 변경
- 삭제: `backend/controller/claude_controller.py` (397 LOC)
- `backend/main.py`:
  - line 29: `from controller.claude_controller import router as claude_router` 제거
  - line 586: `app.include_router(claude_router)` 제거

### 검증
- `grep -rn "claude_controller\|claude_router" backend/` → 0
- `grep -rn "/api/sessions" backend/ frontend/src/` → 0 (이미 frontend 0 확인됨)
- 컨테이너 rebuild 시 FastAPI 라우트 리스트에 `/api/sessions/*` 없음

### Scope boundary
models.py 의 legacy-only 클래스 (`ToolCallInfo` 등) 는 이 PR 에서 건드리지 않음. PR-4 재배치 단계에서 일괄.

---

## PR-2 — `SessionManager` 상속 끊기

`AgentSessionManager(SessionManager)` → `AgentSessionManager` (독립 class).

### 변경
- `backend/service/executor/agent_session_manager.py`:
  - line 38: `from service.claude_manager.session_manager import SessionManager, merge_mcp_configs` 제거
  - line 94: `class AgentSessionManager(SessionManager):` → `class AgentSessionManager:`
  - line 108-109: `super().__init__()` 대체 — 자체 `__init__` 에서:
    - `self._global_mcp_config: Optional[MCPConfig] = None`
    - `self._local_processes` 는 **생성 안 함** (PR-3 에서 ClaudeProcess 사라지므로 populate 불가)
  - `set_global_mcp_config()` 메서드 자체 구현 (부모에서 상속받던 것):
    ```python
    def set_global_mcp_config(self, config: MCPConfig) -> None:
        self._global_mcp_config = config
        if config and config.servers:
            logger.info(f"✅ Global MCP config registered: {list(config.servers.keys())}")
    ```
  - `global_mcp_config` property 도 자체 구현
  - line 1065: `if session_id in self._local_processes: del ...` 블록 **제거** (3 lines)
  - line 1093: `return await super().delete_session(session_id, cleanup_storage)` — 도달 불가 경로. `_local_agents` 에 없으면 `False` 반환으로 변경.
  - line 1125-1134: `dead_processes = [...]` + `super().delete_session(session_id)` 루프 **제거** (legacy 전용, 빈 dict 순회)

### 영향 조사
- `set_global_mcp_config` 호출자가 있는지 grep 필수 — `main.py` 의 MCP 초기화 흐름
- `manager.get_process(session_id)` 호출자 — 있으면 더미 반환 or 제거

### 검증
- `grep -rn "super().__init__\|super().delete_session\|super().create_session\|super().list_sessions" backend/service/executor/` → 0
- AgentSessionManager 인스턴스 생성 + `set_global_mcp_config(config)` + `delete_session(id)` 스모크

---

## PR-3 — Dead chain 삭제

### 변경
- 삭제 (6 파일):
  - `backend/service/claude_manager/session_manager.py` (285)
  - `backend/service/claude_manager/process_manager.py` (988)
  - `backend/service/claude_manager/cli_discovery.py` (181)
  - `backend/service/claude_manager/stream_parser.py` (366)
  - `backend/service/claude_manager/constants.py` (63)
  - `backend/service/claude_manager/platform_utils.py` 의 CLI-specific 섹션들 (`WindowsProcessWrapper`, `AsyncStreamWriter/Reader`, `create_subprocess_cross_platform`, `get_claude_env_vars`) — 파일 분할의 일부로 generic 부분은 유지 후 PR-4 에서 이동

- `backend/service/claude_manager/__init__.py` 업데이트:
  - `ClaudeNodeConfig`, `CLAUDE_DEFAULT_TIMEOUT`, `CLAUDE_ENV_KEYS`, `ClaudeProcess`, `SessionManager`, `get_session_manager`, `merge_mcp_configs`, stream event types export 제거

- `backend/controller/command_controller.py:16` — `from service.claude_manager.session_manager import get_session_manager` 참조 확인 및 제거 (legacy API 전용 사용일 경우 해당 코드도 제거)

### 총 삭제 LOC
약 1,883 (constants + session_manager + process_manager + cli_discovery + stream_parser) + platform_utils CLI 부분 200 ≈ **2,083 LOC**

### 검증
- `grep -rn "ClaudeProcess\|ClaudeNodeConfig\|StreamParser\|StreamEventType\|CLAUDE_DEFAULT_TIMEOUT" backend/` → 0 (archive 제외)
- `grep -rn "session_manager.py\|process_manager.py\|cli_discovery.py\|stream_parser.py\|constants.py" backend/` → 0 (archive 제외)
- `import service.claude_manager` 시 ImportError 없음

---

## PR-4 — `claude_manager/` 해체 + 재배치

### 새 구조
```
backend/service/
├── sessions/                    # NEW
│   ├── __init__.py              # public re-exports
│   ├── models.py                # (from claude_manager/models.py — MCP 제외)
│   └── store.py                 # (from claude_manager/session_store.py)
└── utils/
    ├── (existing) text_sanitizer.py
    ├── (existing) utils.py
    ├── platform.py              # NEW — DEFAULT_STORAGE_ROOT, IS_*
    └── file_storage.py          # NEW — list_storage_files, read_storage_file, DEFAULT_IGNORE_PATTERNS
```

MCP 모델 (`MCPConfig`, `MCPServerStdio/HTTP/SSE`) 은 2 옵션:
- **A:** `service/sessions/models.py` 에 같이 둠 (기존 claude_manager/models.py 그대로 분할 없이 이동)
- **B:** `service/mcp_loader.py` 를 `service/mcp/` 폴더로 승격하고 `mcp/models.py` 에 배치

→ **A 선택** — 현재 `mcp_loader.py` 는 단일 파일. 승격은 과잉. `service/sessions/models.py` 에 그대로.

### 변경
- `git mv backend/service/claude_manager/models.py backend/service/sessions/models.py`
- `git mv backend/service/claude_manager/session_store.py backend/service/sessions/store.py`
- 신규 `backend/service/sessions/__init__.py` (re-exports)
- `platform_utils.py` 의 generic 부분을 추출해 `backend/service/utils/platform.py` 생성 (파일 쪼개기), CLI-specific 섹션은 PR-3 에서 이미 제거됨
- `git mv backend/service/claude_manager/storage_utils.py backend/service/utils/file_storage.py`
- `backend/service/claude_manager/` 폴더 및 `__init__.py` 제거
- 일괄 치환 (40+ 파일):
  - `from service.claude_manager.models` → `from service.sessions.models`
  - `from service.claude_manager.session_store` → `from service.sessions.store`
  - `from service.claude_manager.platform_utils` → `from service.utils.platform`
  - `from service.claude_manager.storage_utils` → `from service.utils.file_storage`
  - `from service.claude_manager import X` → 개별 새 경로로 분해
  - `service.claude_manager.X` 경로 문자열도 치환 (docs, comments)

### 검증
- `test -d backend/service/claude_manager` → 없음
- `grep -rn "from service.claude_manager\|import service.claude_manager\|service\.claude_manager" backend/ docs/` → 0 (archive 제외)
- `python -c "from service.sessions import SessionInfo; ..."` OK

---

## 리스크 & 롤백

| PR | 롤백 | 테스트 후 확인사항 |
|---|---|---|
| PR-1 | `git revert` | `/api/sessions/*` 404 예상 |
| PR-2 | `git revert` | 세션 생성·MCP 전역 설정·세션 삭제 모두 정상 |
| PR-3 | `git revert` | 순수 삭제, 롤백 가능 |
| PR-4 | `git revert` — rename 특성상 revert 깔끔 | 컨테이너 import 성공 |

---

## Cycle close 기준

- [ ] 4 PR 모두 main 머지
- [ ] `backend/service/claude_manager/` 폴더 없음
- [ ] `backend/controller/claude_controller.py` 없음
- [ ] `SessionManager`, `ClaudeProcess`, `StreamParser` 클래스 없음
- [ ] `/api/sessions/*` 라우트 없음
- [ ] ~2,400 LOC (controller 397 + dead chain 2,083) 삭제됨
- [ ] `dev_docs/20260424_2/progress/pr{1,2,3,4}_*.md` 작성
