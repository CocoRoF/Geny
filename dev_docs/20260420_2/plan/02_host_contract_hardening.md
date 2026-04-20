# 02 — Host Contract Hardening (Phase A)

`Tool` ABC 와 그 주변 계약을 **예측 가능하고 구조화된** 모양으로 다듬는다.
대응 취약점: F-1, F-2, F-3, F-5, F-9.

## §A. 입력 스키마 검증

**변경 위치**: `geny-executor/stages/s10_tool/artifact/default/routers.py:30-45`

**현재**:
```python
tool = registry.get(tool_name)
if tool is None:
    return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)
try:
    return await tool.execute(tool_input, context)
except Exception as e:
    return ToolResult(content=f"Tool '{tool_name}' failed: {str(e)}", is_error=True)
```

**변경**:
```python
tool = registry.get(tool_name)
if tool is None:
    return ToolResult.error(ToolError.unknown_tool(tool_name))

try:
    validated = validate_input(tool.input_schema, tool_input)
except JSONSchemaError as e:
    return ToolResult.error(ToolError.invalid_input(tool_name, e))

try:
    return await tool.execute(validated, context)
except ToolRaise as e:
    # tool 이 구조화 에러를 스스로 raise 한 경우는 그대로 통과
    return ToolResult.error(e.error)
except Exception as e:
    logger.exception("tool %s raised unexpected exception", tool_name)
    return ToolResult.error(ToolError.tool_crashed(tool_name, e))
```

- `validate_input` 은 `jsonschema` 기반 경량 래퍼. 이미 공개 인터페이스에서
  `input_schema` 를 JSON Schema 형태로 받고 있으므로 의존성 추가만 필요.
- 검증 실패는 tool 구현체에 도달하기 전에 `invalid_input` 에러로 조기 종료.

## §B. Structured Error

**새 파일**: `geny-executor/src/geny_executor/tools/errors.py`

```python
class ToolErrorCode(str, Enum):
    UNKNOWN_TOOL    = "unknown_tool"
    INVALID_INPUT   = "invalid_input"
    TOOL_CRASHED    = "tool_crashed"
    TRANSPORT       = "transport_error"       # MCP 연결 실패 등
    ACCESS_DENIED   = "access_denied"

@dataclass(frozen=True)
class ToolError:
    code: ToolErrorCode
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_api_format(self) -> Dict[str, Any]:
        return {"error": {"code": self.code.value, "message": self.message,
                          "details": self.details}}
```

`ToolResult.error(err: ToolError) -> ToolResult`:
- `content = err.to_api_format()` (dict 형태, `to_api_format(tool_use_id)` 에서
  json.dumps).
- `is_error = True`.

**Anthropic 호환**: Anthropic 의 `tool_result` 는 `content` 로 문자열/블록 모두
허용. 우리는 `content` 를 JSON 문자열화하여 LLM 에게 전달하되, **첫 줄에 에러
마커** 를 붙여 LLM 이 쉽게 인식하게 한다:

```
ERROR invalid_input: schema validation failed for 'query'
{"code":"invalid_input","message":"...","details":{...}}
```

이 형식을 LLM 시스템 프롬프트에서 설명 (system prompt 변경은 Phase D 와 같이
진행).

## §C. Tool Namespace

**변경 위치**: `geny-executor/tools/mcp/manager.py:300`

MCP tool 을 레지스트리에 등록할 때 이름에 prefix 를 강제:

```python
display_name = f"mcp__{server_name}__{defn['name']}"
```

Anthropic 의 tool 이름 제약 (알파벳/숫자/언더스코어, 64자) 을 유지하며
서버 간 충돌을 원천 제거. built-in / adhoc 이름과도 구분.

**Breaking change 정책**: prefix 는 항상 강제된다. per-server 로 prefix 를
끄거나 바꾸는 옵션은 **도입하지 않는다** (그런 옵션을 두면 이름 공간이
다시 분기되어 원래의 문제를 재도입). 기존에 prefix 없는 이름을 참조하던
manifest 는 v0.22.0 에서 명시적으로 깨지며, Phase C 의 마이그레이션
스크립트 (plan/01 참조) 가 `tools.mcp_servers[*].name` 을 읽어 해당 tool 의
prompt / allowlist 참조를 새 이름으로 일괄 변환한다.

**충돌 탐지**: `ToolRegistry.register` 에 중복 이름 감지 경고 추가:
```python
if name in self._tools:
    logger.warning("tool name collision: %s replaces %s", name, ...)
```

## §D. `is_error` 의 자동 추론 제거

현재 Geny 의 `_GenyToolAdapter.execute` 는 tool 이 반환한 JSON 안에 `"error"`
필드가 있어도 `is_error=False` 로 감싼다 (F-9). 본 사이클에서 Geny 의 `BaseTool`
계약을 바꾼다:

- `BaseTool.run(**kwargs) -> str` (반환 타입은 유지). 성공은 문자열 반환.
- 실패는 **반드시** `raise ToolFailure(message, details)` — JSON 본문에
  `"error"` 필드만 넣고 조용히 리턴하는 관행은 허용하지 않는다.
- `_GenyToolAdapter.execute` 는 `ToolFailure` 를 `ToolRaise` 로 bridge,
  `routers.py` 가 이를 `ToolError.tool_crashed` 로 구조화.

**적용**: 기존에 JSON 안에 `{"error": "..."}` 만 넣어 리턴하던 tool 들
(`web_search_tools.py:145` 등) 은 본 사이클에서 `raise ToolFailure(...)` 로
**전부 일괄 수정**. 두 방식을 동시에 인정하는 dual-path 는 두지 않는다.

## 테스트 전략

- `tests/tools/test_input_validation.py` — 필수 필드 누락 / 잘못된 타입 /
  잉여 필드 케이스.
- `tests/tools/test_structured_errors.py` — `ToolError` → `to_api_format` →
  `ToolResult` 직렬화 왕복.
- `tests/tools/test_namespace.py` — prefix 적용, 기본값 오버라이드, 충돌
  감지 로깅.

## 되돌리기

본 Phase 의 변경은 `geny-executor` 측 breaking change 를 포함한다
(routers.py 의 에러 타입, MCP prefix 강제, `is_error` 계약). 되돌리기 필요 시
해당 PR 을 revert 하며, 같은 시점에 Geny 의 `pyproject.toml` 의 executor 버전
pin 도 함께 원복해야 한다. flag 뒤에 숨긴 상태로 회귀하는 경로는 두지
않는다.
