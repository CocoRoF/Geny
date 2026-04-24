# claude_manager/ Dissolution Audit (Cycle 20260424_2)

**Date:** 2026-04-24
**Baseline:** `main @ b42f8f2` (post-cycle 20260424_1)
**Target:** `backend/service/claude_manager/` — 3,480 LOC across 10 files

---

## 1. 파일별 inventory

| File | LOC | 역할 | 상태 |
|---|---|---|---|
| `__init__.py` | 93 | public API re-exports | 유지 (레이아웃 완료 후 재배치) |
| `models.py` | 504 | 세션·MCP·스토리지 데이터 모델 | 🟡 활성 (이름/위치만 잘못) |
| `session_store.py` | 431 | Postgres + JSON 세션 메타데이터 영속화 | 🟡 활성 (이름만 잘못) |
| `session_manager.py` | 285 | `ClaudeProcess` dict 관리 singleton | 🔴 legacy dead |
| `process_manager.py` | 988 | `ClaudeProcess` — Claude CLI 서브프로세스 래퍼 | 🔴 legacy dead |
| `cli_discovery.py` | 181 | Claude CLI Node 바이너리 탐색 | 🔴 legacy dead |
| `stream_parser.py` | 366 | Claude CLI `--output-format stream-json` 파서 | 🔴 legacy dead |
| `platform_utils.py` | 274 | 경로 + subprocess 크로스플랫폼 유틸 | 🟡 일부 범용·일부 CLI-specific |
| `storage_utils.py` | 295 | gitignore 필터 + 파일 I/O | 🟡 활성 (이름만 잘못) |
| `constants.py` | 63 | `CLAUDE_*` 상수 | 🔴 legacy dead |

**삭제 대상 (dead chain):** ~2,083 LOC (60%)
**재배치 대상 (활성):** ~1,397 LOC (40%)

---

## 2. Dead chain 의존 관계

```
controller/claude_controller.py  (/api/sessions/*)
        │
        │ get_session_manager() + process.execute()
        ▼
service/claude_manager/session_manager.py   (SessionManager)
        │
        │ self._local_processes: Dict[str, ClaudeProcess]
        ▼
service/claude_manager/process_manager.py   (ClaudeProcess)
        │
        │ subprocess + stream parse
        ▼
 service/claude_manager/{cli_discovery,stream_parser,constants}.py
```

`claude_controller` (루트) 를 뽑으면 전체 체인이 매달리는 구조. 단, `AgentSessionManager(SessionManager)` 상속이 **부차적 지탱점**:

```python
# backend/service/executor/agent_session_manager.py:94
class AgentSessionManager(SessionManager):
    def __init__(self):
        super().__init__()   # → self._local_processes = {}, self._global_mcp_config = None
```

상속으로 가져오는 것:
- `self._local_processes: Dict[str, ClaudeProcess]` — **항상 빈 dict** (AgentSessionManager 는 이걸 populate 하지 않음)
- `self._global_mcp_config: Optional[MCPConfig]` — **실제 사용됨** (`agent_session_manager.py:558` `global_config=self._global_mcp_config`)
- `set_global_mcp_config()` 메서드 — `main.py` 초기화에서 호출하는지 확인 필요

**compat 잔재 (empty dict defense):**
- `agent_session_manager.py:1065` — `if session_id in self._local_processes: del ...` (항상 거짓)
- `agent_session_manager.py:1093` — `await super().delete_session(session_id, cleanup_storage)` (`_local_agents` 에 없을 때 legacy fallback. 현실적으로 도달 불가)
- `agent_session_manager.py:1125-1134` — `for session_id, process in self._local_processes.items()` 순회 후 `super().delete_session()` (항상 0회)

**`merge_mcp_configs` import (line 38) — unused**. `agent_session_manager.py` 에서 호출 0회.

---

## 3. Active 부분 의존 관계

### `models.py` — 다형적

| 클래스 | 외부 소비자 | 판정 |
|---|---|---|
| `SessionStatus`, `SessionRole`, `SessionInfo` | executor, agent_session, 모든 controller | 🟢 core domain |
| `CreateSessionRequest` | tools/built_in/geny_tools.py, controllers, executor | 🟢 core domain |
| `ExecuteRequest`, `ExecuteResponse` | **`agent_controller.py:642, 639, 660` 활성 사용** + `claude_controller` (legacy) + `command_controller.py` | 🟢 active (정정: legacy 전용 아님) |
| `ToolCallInfo` | `claude_controller.py:182` 만 | 🔴 legacy-only |
| `StorageFile`, `StorageListResponse`, `StorageFileContent` | `agent_controller.py`, `claude_controller.py` | 🟢 active (agent API 에서도 사용) |
| `MCPConfig`, `MCPServerStdio/HTTP/SSE` | `mcp_loader.py`, `tool_policy/policy.py`, executor | 🟢 core cross-cutting |

→ models.py 는 wholesale 이동. PR-1 에서 `claude_controller` 를 지우면 `ToolCallInfo` 의 유일 소비자가 사라지지만 이건 PR-4 재배치 시 함께 정리.

### `session_store.py`

`get_session_store()` singleton. 외부 소비자 **15+ 사이트** (main.py, environment_controller, tts_controller, claude_controller, agent_controller, executor 등). Claude CLI 와 무관. PostgreSQL + `sessions.json` 이중 영속화.

→ 순수 이동 (`service/sessions/store.py`).

### `platform_utils.py` — 분할 필요

| 심볼 | 사용처 | 성격 |
|---|---|---|
| `DEFAULT_STORAGE_ROOT` | shared_folder, memory/global, memory/user_opsidian, memory/curated_knowledge, executor/agent_session | 범용 |
| `IS_WINDOWS`, `IS_MACOS`, `IS_LINUX` | cli_discovery (internal), `__init__` export | 범용 |
| `get_claude_env_vars()` | process_manager (internal) | CLI-specific |
| `WindowsProcessWrapper`, `AsyncStreamWriter/Reader` | process_manager (internal) | CLI-specific |
| `create_subprocess_cross_platform()` | process_manager (internal) | CLI-specific |

→ generic 부분만 `service/utils/platform.py` 로, CLI-specific 은 process_manager 와 함께 삭제.

### `storage_utils.py`

`list_storage_files()`, `read_storage_file()`, `DEFAULT_IGNORE_PATTERNS`. gitignore 필터 + 파일 I/O. Claude CLI 와 무관.

→ `service/utils/file_storage.py` 로 이동.

---

## 4. `/api/sessions/*` 라우트 실사용 검증

`claude_controller.py:38` `router = APIRouter(prefix="/api/sessions", ...)`

| Endpoint | Method | frontend 사용 | backend internal 사용 |
|---|---|---|---|
| `/api/sessions` | POST/GET | 0건 | 0건 |
| `/api/sessions/{id}` | GET/DELETE | 0건 | 0건 |
| `/api/sessions/{id}/execute` | POST | 0건 | 0건 |
| `/api/sessions/{id}/execute/stream` | POST | 0건 | 0건 |
| `/api/sessions/{id}/storage` | GET | 0건 | 0건 |
| `/api/sessions/{id}/storage/{path}` | GET | 0건 | 0건 |

`grep -r "/api/sessions" frontend/src/` → empty.
Controller 간 HTTP 호출은 없는 구조 (직접 import 방식).

→ 완전 dead 라우트. 삭제 가능.

---

## 5. Final Layout Target

현재 Geny 의 flat `service/X/` 규약에 맞춰 최소 침습 구조:

```
backend/service/
├── claude_manager/              # ❌ 삭제
├── sessions/                    # ✨ NEW
│   ├── __init__.py              # SessionStatus, SessionRole, SessionInfo, ... re-exports
│   ├── models.py                # ← claude_manager/models.py (MCP 제외)
│   ├── mcp_models.py            # ← claude_manager/models.py 의 MCPConfig 계열 (선택)
│   └── store.py                 # ← claude_manager/session_store.py
├── utils/                       # 기존 (text_sanitizer.py, utils.py)
│   ├── platform.py              # ✨ NEW  — DEFAULT_STORAGE_ROOT, IS_WINDOWS 등
│   └── file_storage.py          # ✨ NEW  — list_storage_files, read_storage_file
└── mcp_loader.py                # 기존. MCP 모델을 여기 통합할 수도 있음 (PR-4 결정)
```

MCP 모델 분리 여부는 PR-4 에서 `mcp_loader.py` 와 함께 구조 결정.

---

## 6. 위험도

| PR | 롤백 난이도 | 리스크 |
|---|---|---|
| PR-1 (controller 삭제) | Easy | 외부 스크립트가 `/api/sessions` 호출 시 404. frontend 영향 0 (확인됨). |
| PR-2 (상속 끊기) | Medium | `_global_mcp_config` / `set_global_mcp_config` 등 실제 사용 속성을 자체 구현으로 정확히 옮겨야 함. 회귀 시 MCP 동작 깨짐. |
| PR-3 (dead 파일 삭제) | Easy | PR-2 성공 후엔 아무도 참조 안 함. 실수로 active 파일 지우지만 않으면 됨. |
| PR-4 (폴더 해체·이동) | High-volume | 40+ 파일에서 `from service.claude_manager.X` import 일괄 치환. PR-3 (`service/langgraph/` rename) 와 유사 패턴이므로 절차 검증됨. |

---

## 7. 완료 정의 (Cycle-level)

- [ ] `backend/service/claude_manager/` 폴더 없음
- [ ] `grep -rn "from service.claude_manager\|import service.claude_manager" backend/` → 0 match
- [ ] `grep -rn "ClaudeProcess\|ClaudeNodeConfig\|StreamParser" backend/` → 0 match (archive 제외)
- [ ] `/api/sessions/*` 라우트 없음 (`grep "/api/sessions" backend/` → 0)
- [ ] 컨테이너 import 성공 + 세션 생성·invoke 스모크 테스트 green (리뷰어 환경)
- [ ] `dev_docs/20260424_2/progress/` 각 PR 기록
