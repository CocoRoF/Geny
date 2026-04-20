# 01 — Host 구조화 에러 + 입력 검증 (PR1, Phase A)

- **Repo**: `geny-executor`
- **Plan 참조**: `plan/02_host_contract_and_error_surface.md` §A–§C
- **Branch**: `feat/tool-structured-errors`
- **PR**: (작성 예정)
- **대상 버전**: v0.22.0 (아직 bump 전; PR5 에서 일괄 bump)

## 변경 요지

`RegistryRouter` 의 **모든 실패 경로** 를 구조화된 `ToolError` 로 통일하고,
tool 실행 직전에 `Tool.input_schema` 에 대해 `jsonschema.validate` 를 통과해야
실행되도록 게이트를 건다. 자유형 문자열 ("Unknown tool: X", "Tool 'X' failed:
...")은 전량 제거.

## 추가 / 변경된 파일

1. **신규** `src/geny_executor/tools/errors.py`
   - `ToolErrorCode` Enum: `UNKNOWN_TOOL`, `INVALID_INPUT`, `TOOL_CRASHED`,
     `TRANSPORT`, `ACCESS_DENIED`.
   - `ToolError` frozen dataclass: `code / message / details`, `to_payload()` 는
     `{"error": {"code", "message", "details"}}` 반환.
   - 팩토리: `unknown_tool / invalid_input / tool_crashed / access_denied /
     transport`.
   - `ToolFailure(Exception)`: tool 구현체가 구조화 실패를 raise 할 때 사용.
     `.error: ToolError` 로 라우터가 브리지.
   - `make_error_result(ToolError) -> ToolResult`: `content=to_payload()`,
     `is_error=True`, `metadata["error_code"] = code.value`.
   - `validate_input(schema, payload)`: `jsonschema.validate` 박막 래퍼.

2. **수정** `src/geny_executor/tools/base.py`
   - `ToolResult.to_api_format` 이 dict content 를 감지하고, `{"error": {"code":
     str, "message": str}}` 패턴이면 첫 줄에 `ERROR <code>: <message>` 헤더를
     prepend 한 뒤 JSON 바디를 이어붙임. LLM 이 파싱 없이 실패를 감지 가능.
   - 일반 dict 는 `json.dumps` 로 평탄화 (기존 동작은 문자열 content 만 처리).

3. **재작성** `src/geny_executor/stages/s10_tool/artifact/default/routers.py`
   - `RegistryRouter.route` 가 다음 네 경로를 모두 `make_error_result` 로 반환:
     1. `registry.get(tool_name) is None` → `ToolError.unknown_tool(known=...)`.
     2. `jsonschema.ValidationError` → `ToolError.invalid_input(path=...)`.
     3. `ToolFailure` → 로거 info + `failure.error` 그대로 브리지.
     4. 기타 `Exception` → `logger.exception(...)` + `tool_crashed`.
   - `bind_registry(reg)` 로 사후 등록 교체 가능 (테스트 / Phase C 준비).

4. **신규** `tests/unit/test_tool_errors.py` (26 tests, 전부 PASS)
   - `ToolError` 팩토리별 payload / details 확인.
   - `ToolResult.to_api_format` 의 `ERROR` 헤더 렌더링 / 일반 dict / string /
     list content 모두 커버.
   - `validate_input` pass/fail.
   - `ToolFailure` 기본 / 명시적 code.
   - `RegistryRouter` 6 케이스: unknown / missing required / wrong type /
     happy path / `ToolFailure` 패스스루 / 크래시 로깅 / `bind_registry`.

5. **수정** `pyproject.toml`
   - runtime dependencies 에 `jsonschema>=4.0` 추가. (이미 호스트 환경에 설치되어
     있어 기존 레포 테스트는 import 에러 없음; 계약상 명시.)

## 검증

- `pytest tests/unit` → **524 passed, 1 skipped** (기존 모든 테스트 그대로 통과).
- `pytest tests/contract tests/integration` → **432 passed, 4 skipped**.
- `grep "Unknown tool:\|Tool '.*' failed"` → `errors.py` 의 docstring (변경 이유
  설명) 과 `ToolError.unknown_tool` 의 message format 문자열만 잔존. 문자열 반환
  경로는 0건.

## 후속 TODO (PR2+)

- PR2 (Phase A 이어서): MCP adapter 가 등록하는 tool 이름에 `mcp__{server}__`
  prefix 를 항상 붙이도록 강제 + 충돌 시 `ToolRegistry` 가 raise.
- PR3 (Phase B): `Pipeline.from_manifest` 가 MCP connect + discovery 까지 포함.
- PR6 (Geny): `_format_tool_detail` swallower 제거는 이 PR 이 merge 된 뒤 그
  위에서 진행.

## 호환성 경고

- **Breaking**: tool_result 의 에러 메시지가 자유형 문자열에서 구조화 JSON (+
  헤더) 로 변경. 외부에서 tool_result 의 본문을 문자열 패턴매칭하던 코드가
  있다면 동작이 달라짐. plan/05 의 cutover (PR8) 에서 Geny 측 파서가
  구조화 포맷을 직접 읽도록 전환됨.
