# PR-4 Progress — Delete Claude CLI dead chain

**Branch:** `chore/20260424_2-pr4-delete-cli-dead-chain`
**Base:** `main @ 33e158b` (PR-3 merged)

## Deleted files (5, ~1,883 LOC)

- `backend/service/claude_manager/session_manager.py` (285 LOC) — `SessionManager` + `get_session_manager` + `merge_mcp_configs`
- `backend/service/claude_manager/process_manager.py` (988 LOC) — `ClaudeProcess`
- `backend/service/claude_manager/cli_discovery.py` (181 LOC) — `ClaudeNodeConfig`, `find_claude_node_config`, `build_direct_node_command`
- `backend/service/claude_manager/stream_parser.py` (366 LOC) — `StreamParser`, `StreamEvent`, `StreamEventType`, `ExecutionSummary`
- `backend/service/claude_manager/constants.py` (63 LOC) — `CLAUDE_DEFAULT_TIMEOUT`, `CLAUDE_ENV_KEYS`, `STDIO_BUFFER_LIMIT`

## `platform_utils.py` 축소 (274 → ~50 LOC)

CLI-specific 섹션 제거:
- `WindowsProcessWrapper` (Popen 을 asyncio 처럼 래핑)
- `AsyncStreamWriter`, `AsyncStreamReader`
- `create_subprocess_cross_platform()`
- `get_claude_env_vars()`
- `STDIO_BUFFER_LIMIT` import (constants.py 삭제에 맞춰)

남긴 것 (generic):
- `IS_WINDOWS`, `IS_MACOS`, `IS_LINUX`
- `DEFAULT_STORAGE_ROOT` + `_get_default_storage_root()`

Module docstring 에 "PR-5 에서 `service/utils/platform.py` 로 이전 예정" 메모 추가.

## `__init__.py` 재작성

re-export 목록 감축 — 이제 모두 활성:
- Models: 전부 (unchanged)
- Platform: `IS_WINDOWS`, `IS_MACOS`, `IS_LINUX`, `DEFAULT_STORAGE_ROOT`
- Storage utils: `DEFAULT_IGNORE_PATTERNS`, `list_storage_files`, `read_storage_file`

제거된 export: `SessionManager`, `get_session_manager`, `ClaudeProcess`, `CLAUDE_DEFAULT_TIMEOUT`, `CLAUDE_ENV_KEYS`, `ClaudeNodeConfig`, `find_claude_node_config`, `StreamParser`, `StreamEvent`, `StreamEventType`, `ExecutionSummary`

## Dead endpoint cleanup in `agent_controller.py`

- `POST /api/agents/{session_id}/upgrade` 라우트 + 핸들러 삭제 (32 LOC). 이 엔드포인트는 "기존 ClaudeProcess 세션을 AgentSession 으로 업그레이드" 를 의도했지만:
  - `agent_manager.upgrade_to_agent()` 메서드는 현재 존재하지 않음 → 호출 시 `AttributeError` (런타임 dead)
  - Frontend `/upgrade` 호출 0건
  - ClaudeProcess 가 사라졌으므로 "upgrade" 개념 자체가 무의미
- `UpgradeToAgentRequest` Pydantic 모델 삭제

## Verification

### 삭제 심볼 0 잔존 (서술성 주석 제외)
```
$ grep -rn "ClaudeProcess\|StreamParser\|StreamEventType\|ExecutionSummary\|ClaudeNodeConfig\|CLAUDE_DEFAULT_TIMEOUT\|CLAUDE_ENV_KEYS\|WindowsProcessWrapper\|create_subprocess_cross_platform\|get_claude_env_vars\|STDIO_BUFFER_LIMIT" \
    backend/ --include="*.py" | grep -v __pycache__ | grep -v _archive
```
→ 결과 전부 **주석/docstring** (의도적 히스토리 서술):
- `mcp_loader.py:427` — `merge_mcp_configs` 본체 (live copy, 의도)
- `claude_manager/__init__.py` 설명
- `claude_manager/platform_utils.py` 설명
- `executor/agent_session_manager.py:1094` — "legacy ClaudeProcess fallback since cycle 20260424_2 PR-2"
- `executor/agent_session.py:2151` — `SessionInfo for backward compatibility with SessionManager` 주석

### 폴더 상태
```
backend/service/claude_manager/
├── __init__.py
├── models.py          (504 LOC, 유지 — PR-5 에서 이동)
├── platform_utils.py  (50 LOC, 축소됨 — PR-5 에서 이동)
├── session_store.py   (431 LOC, 유지 — PR-5 에서 이동)
└── storage_utils.py   (295 LOC, 유지 — PR-5 에서 이동)
```

10 파일 → 4 파일 (+ __init__), 3,480 → ~1,330 LOC.

## Next

PR-5: `claude_manager/` 폴더 해체:
- `models.py` → `service/sessions/models.py`
- `session_store.py` → `service/sessions/store.py`
- `platform_utils.py` → `service/utils/platform.py`
- `storage_utils.py` → `service/utils/file_storage.py`
- `__init__.py` 삭제, `claude_manager/` 폴더 제거
- 30+ 파일에서 `from service.claude_manager.X` 일괄 치환
