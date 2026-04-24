# PR-2 Progress — Sever `SessionManager` inheritance

**Branch:** `refactor/20260424_2-pr2-sever-inheritance`
**Base:** `main @ 2e6181a` (PR-1 merged)

## Changes

`backend/service/executor/agent_session_manager.py` 만 변경.

### Inheritance 제거
- `class AgentSessionManager(SessionManager):` → `class AgentSessionManager:`
- `super().__init__()` 제거 → 자체 `__init__` 에서 `self._global_mcp_config = None` 직접 초기화

### Imports
- `from service.claude_manager.session_manager import SessionManager, merge_mcp_configs` 제거 (전체)
- `merge_mcp_configs` 는 이미 unused 였음 (Explore audit 확인)

### 자체 구현 메서드 추가
상속으로 받던 `set_global_mcp_config()` + `global_mcp_config` property 를 매니저 안에 직접 정의:

```python
def set_global_mcp_config(self, config: MCPConfig) -> None:
    self._global_mcp_config = config
    if config and config.servers:
        logger.info(f"✅ Global MCP config registered: ...")

@property
def global_mcp_config(self) -> Optional[MCPConfig]:
    return self._global_mcp_config
```

`main.py:228 agent_manager.set_global_mcp_config(mcp_config)` 호출은 그대로 작동.

### Legacy compat 제거
- `delete_session` 의 `if session_id in self._local_processes: del ...` 3-line 블록 제거 (parent dict, AgentSessionManager 가 populate 하지 않으므로 항상 no-op)
- `delete_session` 의 `return await super().delete_session(session_id, cleanup_storage)` legacy fallback → `return False` (`_local_agents` 에 없으면 실패 처리)
- `cleanup_dead_sessions` 의 `dead_processes` 루프 + `super().delete_session()` 블록 제거 (`_local_processes` 항상 empty)
- docstring: "Extends the existing SessionManager…", "Legacy SessionManager compatibility" 예제 제거

## Verification

```
$ grep -n "_local_processes\|super()\.\|SessionManager\|merge_mcp_configs" \
    backend/service/executor/agent_session_manager.py \
    | grep -v "class AgentSessionManager:\|AgentSessionManager" | head
(empty)
```

### 외부 호출 호환성 확인
- `main.py:228` `agent_manager.set_global_mcp_config(mcp_config)` — ✅ 새 메서드로 계속 작동
- `agent_session_manager.py:558` `self._global_mcp_config` 참조 — ✅ 속성 여전히 존재
- `command_controller.py:136` `session_manager.get_process()` — `SessionManager` singleton 직접 호출, `AgentSessionManager` 와 무관. PR-3 에서 `session_manager.py` 삭제 시 같이 정리 (이 controller 의 legacy 사용처도 PR-3 에서).

## Impact

~48 LOC 순감. AgentSessionManager 가 더 이상 `claude_manager.session_manager.SessionManager` 에 의존하지 않음 → PR-3 에서 `session_manager.py` 삭제 가능.

## Next

PR-3: Dead chain 삭제 (`session_manager.py`, `process_manager.py`, `cli_discovery.py`, `stream_parser.py`, `constants.py`, `platform_utils.py` CLI-specific 섹션). `command_controller.py` 가 `get_session_manager()` 를 여전히 import 하는데 그 쪽 legacy 사용처도 같이 제거.
