# 01 — 증상, 재현, 진짜 근원

## 관측된 증상

채팅 세션에서 LLM 이 `news_search` tool 을 호출하면 다음 패턴이 세 번 반복된
뒤 agent 가 포기한다.

```
[tool_use]    news_search({...})
[tool_result] (parse error)
```

세 번 모두 같은 문자열 `(parse error)` 만 받고 실제 뉴스 결과는 오지 않는다.
동일한 tool 을 CLI / 단위 테스트에서 직접 호출하면 정상적인 JSON 이
나오므로, tool **자체의 버그가 아니라 executor ↔ Geny 통합 지점의 문제** 다.

## `(parse error)` 문자열의 출처

리포 전체에서 literal 은 두 곳에만 있다.

1. `Geny/backend/service/logging/session_logger.py:667`
   ```python
   except Exception as e:
       return f"(parse error)"
   ```
2. `Geny/backend/service/claude_manager/process_manager.py:870`
   ```python
   except Exception as e:
       return f"(parse error: {e})"
   ```

두 경로 모두 **로그/UI 포맷팅 함수** `_format_tool_detail(tool_name, tool_input)`
의 예외 핸들러이며, tool 실행 결과가 아니라 tool 호출 **input 을 사람이
읽기 좋은 요약 문자열** 로 만드는 과정에서 터진 예외를 문자열로 치환한다.

즉 `(parse error)` 는 **로깅-측 swallower** 의 부산물이다. 이 문자열 자체는
LLM 에게 가는 tool_result 페이로드에 들어가면 안 된다.

## 그럼 LLM 은 왜 `(parse error)` 를 tool_result 로 받았는가

추적한 경로는 다음과 같다 (`geny-executor` 측 기준).

1. `stages/s06_api/.../providers.py:145-159` — Anthropic 응답의 `tool_use`
   블록을 그대로 `ContentBlock(tool_name=..., tool_input=...)` 에 복사한다.
   검증 없음.
2. `stages/s09_parse/.../stage.py:110-117` — `state.pending_tool_calls` 에
   `{"tool_use_id", "tool_name", "tool_input"}` 딕셔너리 생성.
3. `stages/s10_tool/.../routers.py:30-45`:
   ```python
   tool = registry.get(tool_name)
   if tool is None:
       return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)
   try:
       return await tool.execute(tool_input, context)
   except Exception as e:
       return ToolResult(content=f"Tool '{tool_name}' failed: {str(e)}", is_error=True)
   ```

문제는 **registry 에 `news_search` 가 들어있지 않다** 는 점이다 (자세한 이유는
`04_manifest_vs_runtime_registration_gap.md`). 따라서 실제로 LLM 이 받는
tool_result 는 `"Unknown tool: news_search"` 와 같은 문자열이다.

하지만 사용자는 그 문자열이 아니라 `(parse error)` 를 본다. 이는 **UI/로그
레이어가 tool_result 표시를 다시 `_format_tool_detail` 을 통해 재포맷** 하고,
이 과정에서 input 딕셔너리 구조가 기대와 어긋나 예외가 나서 `"(parse error)"`
로 대체되기 때문이다. `session_logger.py:408` 이 그 호출 지점이다.

정리하면:

- **실제 executor 내부 에러**: `"Unknown tool: news_search"` (혹은 스키마
  불일치로 인한 stringified exception).
- **사용자에게 노출되는 문자열**: `"(parse error)"` — 로깅 포맷터가 위 문자열
  을 파싱하려다 실패해서 뱉는 대체 문자열.
- **LLM 의 반응**: tool_result 가 `"(parse error)"` 라는 쓸모없는 문자열이므로
  세 번 재시도 후 포기.

## 재현 경로 (call graph)

1. 사용자가 `env_id` 가 바인딩된 세션에서 `news_search` 가 필요한 질문을 한다.
2. `agent_controller` → `AgentSessionManager.create_agent_session(...)`.
3. `env_id` 분기 (`agent_session_manager.py:448-466`) 에서
   `instantiate_pipeline(env_id, api_key=...)` 호출 → 내부에서
   `Pipeline.from_manifest(manifest, ...)` (`environment/service.py:484-495`).
4. `Pipeline.from_manifest` 는 manifest 의 `tools.adhoc / mcp_servers` 만 보고
   레지스트리를 구성한다. Geny 의 `BaseTool` 들 (`news_search` 포함) 은 이
   레지스트리에 **등록되지 않는다**.
5. LLM 이 `news_search` 를 호출 → Stage 10 의 `RegistryRouter.route()` 에서
   `registry.get("news_search")` = None → `ToolResult("Unknown tool: ...",
   is_error=True)` 반환.
6. Geny 의 실시간 로그 파이프라인이 해당 tool 이벤트를 포맷하면서
   `_format_tool_detail` 예외 → `"(parse error)"` 로 치환.
7. UI / 대화 로그에는 `(parse error)` 만 표시되고, LLM 도 같은 문자열을 세 번
   받는다.

## 결론: 두 개의 버그가 서로를 가린다

- **Bug A (구조적)**: manifest 기반 파이프라인에 Geny built-in tool 이 섞여
  들어가는 경로가 없다. `04_manifest_vs_runtime_registration_gap.md` 참조.
- **Bug B (관측성)**: 에러의 실체가 `(parse error)` 라는 로그 포맷 예외 메시지
  로 덮여 사용자도 LLM 도 근본 원인을 볼 수 없다. `05_fragility_catalogue.md`
  의 "Logging swallower" 항목 참조.

두 버그는 각각의 plan 문서 (`01_unified_tool_surface.md`,
`04_observability_and_error_surface.md`) 에서 함께 해결해야 하며, B 를 먼저
제거해야 A 의 재현·검증이 정확해진다.
