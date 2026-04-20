# 05 — 취약점 카탈로그

`news_search (parse error)` 증상 외에도, 조사 중 드러난 산재된 취약점들을
모아둔다. 일부는 본 증상의 간접 원인이고, 일부는 장차 비슷한 증상을 낳을
독립적 리스크다. 각 항목은 `plan/` 의 대응 문서로 연결한다.

## F-1. 입력 스키마 미검증

**위치**: `geny-executor/stages/s10_tool/.../routers.py:30-45`

tool_input (LLM 이 생성한 dict) 이 스키마 검증 없이 그대로 `tool.execute` 로
전달된다. 필수 필드 누락, 잘못된 타입, 잉여 필드 모두 tool 구현체가 직접
처리해야 한다. 실패 시 exception → stringified → LLM 은 원인을 못 본다.

→ `plan/02_host_contract_hardening.md` §A.

## F-2. Unknown tool 호출이 정상 문자열로 반환

**위치**: `routers.py:35-38`

```python
if tool is None:
    return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)
```

`is_error=True` 이긴 하지만 **content 는 평문 문자열** 이라 LLM 이 이를
"실제 답변" 으로 오인해서 재시도 또는 포기 판단을 내리기 어렵다. 구조적
에러 객체 (code/details) 가 필요.

→ `plan/02_host_contract_hardening.md` §B.

## F-3. 예외의 평탄화

**위치**: `routers.py:41-45`

```python
except Exception as e:
    return ToolResult(content=f"Tool '{tool_name}' failed: {str(e)}", is_error=True)
```

stacktrace 가 tool_result 에도, 어떤 logger 에도 남지 않는다. 관측성 0.
특히 Geny 의 `_GenyToolAdapter.execute` 안에서 난 예외까지 여기서 평탄화되면
실제 버그 위치 추적이 어렵다.

→ `plan/04_observability_and_error_surface.md` §A.

## F-4. MCP 결과 이중 인코딩

**위치**: `geny-executor/tools/mcp/manager.py:210-240`,
`tools/mcp/adapter.py:48-60`

MCPServerConnection.call_tool 은 MCP 서버의 응답을 **항상 문자열로 평탄화**
(여러 콘텐츠 블록을 `\n` 으로 join). 구조화된 JSON 을 반환하는 MCP 서버의 경우
호출자가 그 문자열을 다시 JSON parse 해야 하고, 실패 시 "parse error" 의 또
다른 원인이 된다.

→ `plan/03_mcp_lifecycle_and_discovery.md` §C.

## F-5. Tool 이름 공간 충돌

**위치**: `tools/mcp/manager.py:300` (MCP tool 을 prefix 없이 등록),
built-in `get_built_in_registry()` (같은 네임스페이스).

`read`, `write`, `search` 같은 평범한 이름의 MCP tool 이 built-in 또는
Geny BaseTool 과 충돌할 때 **마지막에 등록된 쪽이 이긴다**. 충돌을 감지하고
경고하거나 네임스페이스 prefix (예: `mcp:<server>/<tool>`) 를 강제해야 한다.

→ `plan/02_host_contract_hardening.md` §C.

## F-6. MCP 수명주기의 불명확성

**위치**: `MCPManager.connect()` 호출 주체가 어디인지 코드 탐색으로 명확히
드러나지 않음. `Pipeline.from_manifest` 가 manifest 의 `mcp_servers` 를 읽어
자동 connect 하는지, 아니면 호출자가 사전에 `MCPManager.connect_all()` 을
호출해야 하는지 불분명. 세션 실행 중간에 서버 다운이 발생하면 Stage 10 runtime
에서 처음 발견되고 `ToolResult("Tool 'X' failed: ...", is_error=True)` 만 남는다.

→ `plan/03_mcp_lifecycle_and_discovery.md` §A, §B.

## F-7. Logging 측 예외 swallower (`(parse error)`)

**위치**:
- `Geny/backend/service/logging/session_logger.py:667`
- `Geny/backend/service/claude_manager/process_manager.py:870`

두 곳에 **동일한 목적의 `_format_tool_detail` 이 중복 정의** 되어 있고, 둘 다
광범위 `except Exception` 으로 `"(parse error)"` 라는 무정보 문자열을 반환.
사용자는 물론 개발자도 실제 원인을 볼 수 없다. 이 함수가 로그가 아닌 **UI
표시용** 으로도 쓰이기 때문에 LLM 에게 `(parse error)` 가 전달되는 통로가 될
수 있다.

→ `plan/04_observability_and_error_surface.md` §B, §D.

## F-8. 레거시 tool 주입 경로의 잔존

**위치**: `agent_session.py:689-702` 의 `ToolRegistry()` + 수동 `register(...)` 블록.

`env_id` 가 없을 때만 작동하는 이 경로가 manifest 시스템과 병존하면서 "어떤
세션에선 tool 이 있고 어떤 세션에선 없다" 는 일관성 문제를 만든다.
Built-in / BaseTool 을 manifest 층에 일원화하면 이 블록은 사라져야 한다.

→ `plan/01_unified_tool_surface.md`.

## F-9. `is_error` 플래그 일관성

**위치**: `_GenyToolAdapter.execute`
(`backend/service/langgraph/tool_bridge.py:104-149`).

Geny tool 은 자기 에러 상태를 **JSON 본문 내부 `{"error": "..."}` 로만**
표현 (`web_search_tools.py:145`). 어댑터는 `ToolResult(content=str)` 로만
감싸고 `is_error` 를 세팅하지 않는다. LLM 은 스스로 JSON 을 parse 해서
`error` 필드를 찾아야 하며, Stage 10 이 이 실패를 "실패" 로 인식할 방법이
없다.

→ `plan/02_host_contract_hardening.md` §D.

## F-10. Manifest 와 실행-시간 tool 목록의 괴리

**위치**: Frontend `SessionEnvironmentTab` 은 manifest 의 `tools` 를 그대로
표시. 실행 시 실제 레지스트리에는 경로 A 가 덧붙인 `ReadTool/...` 와 Geny
BaseTool 이 추가되어 있다. **사용자 화면에 표시된 tool 목록 ≠ 실제 활성 tool
목록** → 사용자가 "왜 news_search 가 UI 에 없는지" 또는 "왜 manifest 에 명시
안 한 Read 가 동작하는지" 혼란을 겪는다.

→ `plan/01_unified_tool_surface.md` §C (manifest 가 권위 있는 단일 source).

## 우선순위

| ID | 증상 기여도 | 구조 영향 | 우선 |
|----|-----------|----------|------|
| F-8, F-10 | 높음 | 높음 | 1 |
| F-7 | 높음 (가시 증상) | 중 | 1 |
| F-1, F-2, F-3 | 중 | 높음 | 2 |
| F-6 | 중 (MCP 도입 시) | 중 | 2 |
| F-4, F-9 | 낮음 | 중 | 3 |
| F-5 | 잠재 | 중 | 3 |
