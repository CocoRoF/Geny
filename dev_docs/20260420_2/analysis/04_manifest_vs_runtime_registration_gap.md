# 04 — Manifest vs runtime 등록 경로의 분기 (핵심 원인)

이 문서가 본 사이클의 핵심 원인을 지목한다. 두 개의 tool-registration 경로가
**서로를 모른 채** 공존하며, `env_id` 기반 세션에서 Geny built-in 이 실행
파이프라인에 영영 들어가지 않는다.

## 두 경로

### 경로 A — Legacy "Preset" 경로 (env_id 없음)

`backend/service/langgraph/agent_session.py:680-752`

```python
tools = ToolRegistry()
tools.register(ReadTool()); tools.register(WriteTool()); ...
if self._geny_tool_registry:
    for t in self._geny_tool_registry.list_all():
        tools.register(t)            # ← Geny built-in 주입 지점
...
self._pipeline = GenyPresets.worker_adaptive(tools=tools, ...)
```

이 경로에서는 Geny 의 built-in + `ReadTool/WriteTool/...` + adapter 가
**전부** `ToolRegistry` 에 들어가며, `GenyPresets` 가 이 레지스트리를 받아
파이프라인을 구성한다. `news_search` 가 정상 동작하는 케이스.

### 경로 B — Manifest 경로 (env_id 있음)

`backend/service/langgraph/agent_session_manager.py:448-466`

```python
if env_id:
    prebuilt_pipeline = self._environment_service.instantiate_pipeline(
        env_id, api_key=api_key
    )
...
agent = await AgentSession.create(
    ...,
    geny_tool_registry=geny_tool_registry,
    env_id=env_id,
    prebuilt_pipeline=prebuilt_pipeline,
)
```

그리고 `backend/service/environment/service.py:484-495`:

```python
def instantiate_pipeline(self, env_id, *, api_key, strict=True) -> Pipeline:
    manifest = self.load_manifest(env_id)
    if manifest is None: raise EnvironmentNotFoundError(env_id)
    return Pipeline.from_manifest(manifest, api_key=api_key, strict=strict)
```

`Pipeline.from_manifest` 는 `geny-executor` 측 공장 메서드로,
`manifest.tools` (`ToolsSnapshot`) 만 읽어 레지스트리를 구성한다.

→ **이 경로에서는 `geny_tool_registry` 가 어디에서도 사용되지 않는다**.
`AgentSession.create(...)` 가 `geny_tool_registry` 를 파라미터로 받기는 하지만,
`_build_pipeline` 이 `prebuilt_pipeline` 존재를 감지하고 legacy 경로 전체를
스킵하므로 주입 훅이 없다.

## 결과

- `env_id` 가 있는 세션에서 LLM 은 `news_search` 의 **존재를 advertise 받지
  못한 채** 혹은 (프롬프트/메모리에 남은 과거 호출 패턴 때문에) tool name 만
  알고 호출한다.
- Stage 10 의 `RegistryRouter.route("news_search", ...)` → `registry.get(...)
  == None` → `ToolResult("Unknown tool: news_search", is_error=True)`.
- 이후 로그 포맷터가 이 결과를 사람 읽기 좋게 만들다 예외 → `(parse error)` 로
  치환 → UI / LLM 모두 `(parse error)` 만 본다.

## 경로 분기가 만든 2차 문제

1. **Built-in 파일 IO tool 도 누락**: 경로 B 에서는 `ReadTool/WriteTool/...` 도
   manifest 의 `tools.built_in` 에 명시되지 않은 한 등록되지 않는다. manifest
   작성자가 이를 일일이 넣어야 한다는 암묵적 요구가 생겼고, 비전문가 사용자가
   만든 env 는 빈 tool 세션이 될 수 있다.
2. **Tool preset 의 의미 소실**: `ToolPresetDefinition` 은 경로 A 에서만
   `allowed_tool_names` 필터에 쓰인다. 경로 B 에서 preset 은 실질적으로 무시된다.
3. **Frontend 혼란**: `SessionEnvironmentTab` / `PipelineCanvas` (PR #128, #129)
   는 manifest 의 `tools` 섹션만 보여준다. 사용자는 "nothing registered here"
   를 보고 왜 tool 이 동작 안 하는지 역추적할 단서가 없다.

## `Pipeline.from_manifest` 의 의도와 실제

공장 메서드의 **선언된 의도**: "manifest 하나로 모든 tool 구성이 끝나야 한다".
그 방향 자체는 올바르며 본 사이클의 목표와도 정합한다.

**실제 구현의 누락**: manifest 에 들어갈 수 있는 tool 유형은
`built_in / adhoc / mcp_servers` 세 가지뿐이다. Geny 의 `BaseTool` 기반 built-in
은 이 중 어느 쪽에도 들어가지 않는다 — 그것들은 **Python 클래스 + 수동
인스턴스화** 기반이라 `AdhocToolDefinition` 의 executor_type
(`http|script|template|composite`) 중 어느 것에도 들어맞지 않는다.

즉 Geny 의 도메인 tool 은 manifest 직렬 형식으로는 **표현 불가능한 형태**
이며, 그래서 이들을 파이프라인에 얹을 수 있는 **보조 훅** 이 필요하다.
`plan/01_unified_tool_surface.md` 가 이 훅을 제안한다.

## 정리

- 증상의 근본 원인: `env_id` 분기에서 Geny 의 `BaseTool` 이 실행 레지스트리에
  주입되지 않는다.
- 구조적 원인: `Pipeline.from_manifest` 는 선언된 tool 유형만 인스턴스화하며,
  Geny 의 "Python 구현체 tool" 을 받아줄 인터페이스가 host 에 없다.
- 설계 문제: 두 등록 경로가 **동시에 존재** 하는 것 자체가 취약함. 하나로
  통합되거나, manifest 자체가 "런타임-제공 tool" 을 선언할 수 있는 slot 을
  가져야 한다.
