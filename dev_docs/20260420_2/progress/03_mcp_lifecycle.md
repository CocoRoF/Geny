# 03 — MCP 수명주기 하드닝 (PR3, Phase B)

- **Repo**: `geny-executor`
- **Plan 참조**: `plan/03_mcp_lifecycle_and_discovery.md` §A–§C
- **Branch**: `feat/mcp-lifecycle`
- **PR**: [CocoRoF/geny-executor#24](https://github.com/CocoRoF/geny-executor/pull/24)
- **의존**: PR1 (`#22`, `ToolError`), PR2 (`#23`, `mcp__` prefix)

## 변경 요지

MCP 서버 수명주기를 **fail-fast** 로 재정의한다. 그동안 MCP connect/initialize/
list_tools 실패가 조용히 "connected 지만 no-op" 상태로 넘어가면서, 이후 tool
호출 시점에 `unknown_tool` 로 드러났다. v0.22.0 은 **세션 시작 시점에** 단일
구조화 예외 (`MCPConnectionError`) 로 전 단계 실패를 표현하고, 한 서버가
실패하면 전체를 깨끗이 롤백한다. 동시에 MCP 응답의 **원형** 을 보존하여
멀티 블록이나 non-text 컨텐츠를 flatten 없이 그대로 전달한다.

## 추가 / 변경된 파일

1. **신규** `src/geny_executor/tools/mcp/errors.py`
   - `MCPConnectionError(RuntimeError)`: `server_name`, `phase` (`"connect"
     | "initialize" | "list_tools" | "sdk_missing"`), `cause`. 기본 메시지는
     `"MCP server '{name}' failed during {phase}: {ExcType}: {msg}"`.

2. **수정** `src/geny_executor/tools/mcp/manager.py` (거의 재작성)
   - `MCPServerConnection.connect` 계통이 no-op 으로 빠지던 모든 fallback 제거.
     `_attach_session` 헬퍼가 transport attach / initialize / list_tools 세
     단계를 각각 라벨링하여 `MCPConnectionError` 로 raise. 중간 실패 시
     `_safe_cleanup()` 으로 확실히 해제.
   - `_connect_stdio / _connect_http` 는 SDK import 실패도 `MCPConnectionError
     (phase="sdk_missing")` 으로 전환.
   - `MCPManager.connect_all` 이 `return_exceptions=True` 를 제거하고,
     첫 실패 시 ① 미완료 task cancel ② `disconnect_all()` ③ raise 로 중간
     상태를 남기지 않음.
   - `MCPManager.connect` 는 실패 시 `self._configs` 에서 해당 이름을 삭제.
   - `MCPServerConnection.call_tool` 반환값: 단일 text 블록이면 `str`, 그
     외에는 `[{type, text}, ...]` 형태의 `list[dict]`. 헬퍼
     `_normalize_mcp_result` 로 분리.
   - `MCPManager.add_server(config, registry=None)` / `remove_server(name,
     registry=None)` — registry 가 주어지면 adapter 를 그 자리에 register /
     `mcp__{name}__*` 만 unregister.
   - `discover_all()` alias 추가 (세션 시작 가독성).
   - `test_connection` 의 `success` 계산을 "connect + discover 가 raise 없이
     끝났는가" 로 단순화.

3. **수정** `src/geny_executor/tools/mcp/adapter.py`
   - `execute()` 가 `str | list` 모두 그대로 ToolResult.content 로 전달.
     비-list/str 만 `str(...)` 으로 강등.

4. **수정** `src/geny_executor/core/pipeline.py`
   - `Pipeline` 에 `_mcp_manager` / `_tool_registry` 필드 + `mcp_manager` /
     `tool_registry` property 추가.
   - `_mcp_configs_from_manifest(manifest)` helper: `manifest.tools.mcp_servers`
     dict list → `MCPServerConfig` dict.
   - **신규 `Pipeline.from_manifest_async(manifest, *, api_key=None,
     strict=True, tool_registry=None)`**: 기존 sync `from_manifest` 를 호출한
     뒤, MCP 서버가 선언되어 있으면 `MCPManager.connect_all + discover_all` 을
     수행하고 adapter 를 `tool_registry` 에 등록. 실패 시 `disconnect_all()`
     후 raise. pipeline 에 manager / registry 를 attach.

5. **수정** `src/geny_executor/tools/mcp/__init__.py`
   - `MCPConnectionError` export.

6. **신규** `tests/unit/test_mcp_lifecycle.py` (19 tests, 전부 PASS)
   - **Lifecycle errors**: unsupported transport, HTTP URL 누락, initialize
     실패, list_tools 실패, 성공 시 tool list 적재.
   - **connect_all**: empty no-op, "나쁜 서버 하나" 가 섞이면 전체 롤백.
   - **add_server / remove_server**: namespaced tool 이 registry 에 들어감,
     remove 는 해당 서버의 prefix 만 제거 (다른 서버는 유지), 모르는 서버
     제거는 `False`.
   - **_normalize_mcp_result**: 단일 text → str, 멀티 → list, non-text → list,
     empty → fallback.
   - **Adapter pass-through**: list content 가 그대로 ToolResult.content 로.
   - **from_manifest_async**: 서버 0개면 빈 manager/registry, 서버 연결 성공
     시 namespaced 등록, 서버 실패 시 disconnect_all + raise, caller-supplied
     registry 는 그대로 유지되고 built-in + MCP 가 공존.

7. **수정** `tests/unit/test_phase5_emit_presets_mcp.py`
   - 기존 `echo` 명령으로 "connect 성공" 을 기대하던 케이스를
     `MCPConnectionError` 를 raise 하는 것으로 갱신. adapter 단위 테스트는
     real connect 가 필요 없으므로 connection 호출 제거.

## 검증

- `pytest tests/unit tests/contract tests/integration` → **984 passed,
  5 skipped**. PR1 / PR2 합산 대비 19 테스트 증가.

## 호환성 경고

- **Breaking**: 기존에 "MCP 가 연결은 안 되어도 세션은 살았던" 시나리오는
  v0.22.0 에서 세션 생성 시점에 실패. Geny manifest 에 깨진 MCP 서버가 있으면
  session start 단계에서 명시적으로 에러가 나며, Phase E 의 수동 QA 에서
  저장된 env 를 한 번씩 돌려 사전 정리가 필요.
- `MCPServerConnection.call_tool` 의 반환 타입이 `str` 전용에서 `Any` (str |
  list[dict]) 로 확장. 직접 호출자는 `isinstance` 분기가 필요할 수 있으나,
  `MCPToolAdapter.execute` 는 내부적으로 처리하므로 일반적 경로는 영향 없음.

## 후속 TODO (다음 PR)

- **PR4 (Phase C)**: `AdhocToolProvider` 프로토콜 + `Pipeline.from_manifest_async
  (adhoc_providers=...)` 인자 + `ToolsSnapshot.external` 필드. Geny 의
  `BaseTool` 을 executor 측에서 한 관문으로 수용하는 통합.
- **PR5**: v0.22.0 bump + CHANGELOG + tag.
