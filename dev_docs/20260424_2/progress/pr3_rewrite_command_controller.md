# PR-3 Progress — Rewrite `command_controller` to drop legacy `SessionManager`

**Branch:** `chore/20260424_2-pr3-delete-dead-chain`
**Base:** `main @ 045f804` (PR-2 merged)

## Scope reshape

Audit 중 발견: `command_controller.py` 의 `/api/command/batch` 가 `ClaudeProcess.execute()` 를 직접 호출하며 `SessionManager.get_process()` 에 의존. 이 소비자를 먼저 갈아끼워야 PR-4 에서 dead chain 을 삭제해도 build 가 깨지지 않음. PR-3 를 **command_controller 정리** 에만 집중시키고, dead chain 파일 삭제는 PR-4 로 분리.

## Changes — `backend/controller/command_controller.py`

### 실사용 (frontend 호출) 은 유지·재작성
- `POST /api/command/batch` — `ClaudeProcess.execute()` → `service.execution.agent_executor.execute_command()` 로 전환. `AgentNotFoundError / AgentNotAliveError / AlreadyExecutingError` 분기 추가. 로깅 흐름 (`session_logger.log_command` / `log_response`) 그대로 보존.
- `GET /api/command/logs`, `GET /api/command/logs/{session_id}` — 원래부터 `session_logger` / `read_logs_from_file` / `count_logs_for_session` 직접 사용. `SessionManager` 의존 없었음. 그대로 유지.
- `GET /api/command/prompts`, `GET /api/command/prompts/{name}` — 파일시스템 기반, SessionManager 무관. 유지.

### Frontend 미사용 + SessionManager 의존 → 삭제
- `POST /api/command/broadcast` (40 LOC)
- `GET /api/command/monitor` (35 LOC)
- `GET /api/command/monitor/{session_id}` (32 LOC)
- `GET /api/command/stats` (20 LOC)
- `SessionMonitorInfo` model class (12 LOC)

### Imports 정리
- `from service.claude_manager.session_manager import get_session_manager` 제거
- `from service.claude_manager.models import SessionStatus, ExecuteResponse` 제거 (두 심볼 모두 삭제된 엔드포인트 전용이었음)
- 추가: `from service.execution.agent_executor import execute_command, AgentNotFoundError, AgentNotAliveError, AlreadyExecutingError`

### 필드 제거
- `BatchCommandRequest.skip_permissions` — Claude CLI era 전용. `execute_command()` 는 permission 개념 없음. frontend `types/index.ts:96` 에 optional 로 선언돼있지만 실제 컴포넌트에서 값 전달 0건 (i18n label 만 존재). 호환성 영향 없음.

### 파일 크기
- Before: 577 LOC
- After: 408 LOC (−169 LOC, -29%)

## Verification

```
$ grep -n "session_manager\|SessionStatus\|SessionMonitorInfo\|get_session_manager\|skip_permissions\|ExecuteResponse" \
    backend/controller/command_controller.py
(empty)

$ grep -rn "from service.claude_manager.session_manager\|get_session_manager" backend/ \
    | grep -v __pycache__ | grep -v _archive
backend/service/claude_manager/__init__.py:32: ... (re-export only; PR-4 제거)
```

`claude_manager/__init__.py` 의 re-export 는 **외부 소비자 없음** — 그래도 파일과 함께 PR-4 에서 정리.

## Next

PR-4: 이제 `SessionManager` / `ClaudeProcess` / `StreamParser` / `cli_discovery` / `constants` 와 `platform_utils` 의 CLI-specific 섹션을 삭제해도 import 소비자 없음. 일괄 삭제 + `claude_manager/__init__.py` 에서 제거 심볼 re-export 정리.
