# 02 — geny-executor host 인터페이스

`geny-executor` 가 외부에서 tool 과 MCP 서버를 "넣고 빼는" 인터페이스의 현재
모양을 정리한다. 모든 경로는 `/home/geny-workspace/geny-executor` 기준.

## Tool 추상 (ABC)

- `src/geny_executor/tools/base.py:64-99` — `Tool` ABC
  - `name: str`, `description: str`, `input_schema: Dict[str, Any]`
  - `async def execute(input: Dict[str, Any], context: ToolContext) -> ToolResult`
- `ToolResult` dataclass (`base.py:37-61`)
  - `content: Any`, `is_error: bool`
  - `.to_api_format(tool_use_id) -> dict` — Anthropic `tool_result` 형태로 직렬화.
- `ToolContext` dataclass (`base.py:10-34`)
  - `session_id, working_dir, storage_path, env_vars, allowed_paths, metadata,
    stage_order, stage_name`

## 레지스트리

- `src/geny_executor/tools/registry.py:10-70` — `ToolRegistry`
  - `register(tool: Tool)` 로 이름별 저장, 중복 이름 처리 없음.
  - `get(name) -> Optional[Tool]` — dispatch 시점에 Stage 10 에서 사용.

## Built-in / Ad-hoc / MCP 의 세 갈래

### Built-in

- `src/geny_executor/tools/__init__.py:50-77` — `get_built_in_registry()` 공장
  함수. `ReadTool, WriteTool, EditTool, BashTool, GlobTool, GrepTool` 을 수동으로
  등록한 `ToolRegistry` 를 반환. 데코레이터/리플렉션 없음.

### Ad-hoc (manifest 기반)

- `src/geny_executor/tools/adhoc.py:90-225` — `AdhocToolDefinition` 데이터클래스
  - 필드: `name, description, input_schema, executor_type,
    http_config|script_config|template_config|composite_config`
  - `.to_dict() / .from_dict()` 로 manifest 직렬화.
- `src/geny_executor/tools/composer.py:84-88` — `ToolComposer.register_adhoc()`
  - `AdhocToolFactory.create()` 로 `Tool` 인스턴스 생성 후 내부 딕셔너리에 저장.

### MCP

- `src/geny_executor/tools/mcp/manager.py:243-456` — `MCPManager`
  - `connect(name, config: MCPServerConfig)` (line 261-268) — 단건 연결.
  - `connect_all()` (line 270) — 일괄.
  - `add_server()` (line 368) — 런타임 주입.
- `src/geny_executor/tools/mcp/adapter.py:48-60` — `MCPToolAdapter`
  - `Tool` ABC 를 구현하면서 내부적으로 `self._server.call_tool(name, input)` 호출.
  - 결과를 **항상 문자열화** 해서 `ToolResult(content=...)` 로 감싼다.

### 이름 공간

- MCP 측 tool 은 prefix 없이 원래 이름 그대로 레지스트리에 들어간다
  (`manager.py:300`). → **built-in / adhoc / MCP 이름 충돌 시 나중에 register
  된 쪽이 이긴다**. 충돌 감지 로직 없음.

## Dispatch 경로 (stage chain)

1. **Stage 6 (API 호출)** —
   `stages/s06_api/artifact/default/providers.py:135-167`
   Anthropic 응답의 `tool_use` 블록 → `ContentBlock(type="tool_use",
   tool_use_id, tool_name, tool_input)`. 검증 없음.
2. **Stage 9 (Parse)** —
   `stages/s09_parse/artifact/default/stage.py:110-117`
   `state.pending_tool_calls` 리스트 채움.
3. **Stage 10 (Tool)** —
   `stages/s10_tool/artifact/default/stage.py:88-138`
   - `StageToolBinding.is_allowed(tool_name)` 로 allowlist 체크 → 실패 시
     `ToolAccessDenied`.
   - `SequentialExecutor` (기본) 또는 `ParallelExecutor` 로 실행 위임.
4. **Router** —
   `stages/s10_tool/artifact/default/routers.py:30-45`
   ```python
   tool = registry.get(tool_name)
   if tool is None:
       return ToolResult(content=f"Unknown tool: {tool_name}", is_error=True)
   try:
       return await tool.execute(tool_input, context)
   except Exception as e:
       return ToolResult(content=f"Tool '{tool_name}' failed: {str(e)}", is_error=True)
   ```
   (⚠ 입력 스키마 검증 없음, 예외는 문자열로 평탄화됨.)
5. **결과 직렬화** — `ToolResult.to_api_format(tool_use_id)`
   (`base.py:45-61`) → Anthropic `tool_result` 메시지.

## Manifest → 런타임 바인딩

- `src/geny_executor/core/environment.py:180-220` — `EnvironmentManifest`
  - 최상단 `tools: ToolsSnapshot`.
  - 각 stage 의 `StageManifestEntry.tool_binding` (dict).
- `ToolsSnapshot` (`environment.py:69-92`)
  - `built_in: List[str]`, `adhoc: List[Dict]`, `mcp_servers: List[Dict]`,
    `scope: Dict` (예약).
- `tools/stage_binding.py:22-84` — `StageToolBinding`
  - `allowed / blocked` set, `is_allowed(name)`, `filter(registry)`.

### 간극

`ToolsSnapshot` 은 "무엇이 있어야 하는지" 를 선언하지만, **manifest 로드 시점
에서 ad-hoc / MCP 를 실제 인스턴스화해서 `ToolRegistry` 에 넣는 단일 함수가
노출되지 않았다**. `Pipeline.from_manifest()` 내부에서 이 글루가 수행되는
것으로 보이지만, Geny 가 자기 `BaseTool` 을 **같은 시점에** 끼워 넣을 수 있는
훅은 없다. `04_manifest_vs_runtime_registration_gap.md` 에서 이 결과를
자세히 다룬다.

## 관측된 취약점 (요약)

- **입력 스키마 미검증**: tool_input 이 그대로 handler 로 전달됨.
- **Unknown tool 의 문자열 반환**: LLM 이 이걸 정상 tool_result 로 오인할 수 있음.
- **예외 평탄화**: stacktrace 가 사라져 관측성 0.
- **MCP 결과 이중 인코딩**: MCP 서버가 돌려준 구조화 응답이 그냥 문자열로
  `ToolResult.content` 에 들어감. 호출자가 또 JSON 파싱하면 실패.
- **Tool 이름 공간 없음**: built-in / adhoc / MCP 가 동일 네임스페이스를 공유.

각 항목의 완화 전략은 `plan/02_host_contract_hardening.md`.
