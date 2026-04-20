# 03 — MCP Lifecycle and Discovery (Phase B)

MCP 서버와 executor 의 계약을 **세션 시작 시** 완결하고, Stage 10 런타임은
그저 레지스트리에서 조회만 하면 되도록 수명주기를 재정의한다. 대응 취약점:
F-4, F-5, F-6.

## §A. Manifest 로드 시 `connect_all + list_tools`

**변경 위치**: `geny-executor/src/geny_executor/tools/composer.py` 또는
`core/pipeline.py` 의 `Pipeline.from_manifest` 내부.

**현재**: MCPManager 가 언제 connect 되는지 코드 경로가 불분명.
`from_manifest` 가 connect 를 트리거하는지 호출자가 사전에 해야 하는지 명시
되지 않음.

**변경 후 계약**:
1. `Pipeline.from_manifest(manifest, ...)` 는 **반드시** 내부에서 다음 순서를
   수행:
   - `MCPManager(config_list=manifest.tools.mcp_servers)` 생성.
   - `await manager.connect_all()` — 각 서버에 stdio/http 로 접속.
   - `await manager.discover_all()` — 각 서버의 `list_tools()` 호출 결과를
     `MCPToolAdapter` 로 감싸 `ToolRegistry` 에 등록.
2. 어느 단계든 실패하면 `MCPConnectionError(server_name, cause)` 로 즉시
   raise → 세션 시작이 실패로 끝나고 사용자는 "어느 서버의 어느 단계에서
   실패했는지" 를 즉시 본다.

실패는 **항상 즉시 raise**. 과거 `strict=False` 로 서버 실패를 스킵하던 fallback
경로는 제거한다. MCP 서버 연결 실패를 숨긴 채 세션이 살아있으면 "어떤 tool 이
활성인가" 가 런타임 상태에 의존해 예측이 불가능해진다. 일시적으로 일부 MCP
서버를 비활성화하고 싶다면 manifest 의 `tools.mcp_servers` 에서 해당 항목을
제거하는 것이 정답이다.

## §B. 재연결 / 수명 관리

**요구사항 소환**: "외부 호환성을 위해 자유롭게 넣고 빼기가 가능한 강력한
인터페이스".

**현재**: `MCPManager.add_server()` (manager.py:368) 가 런타임 주입을 지원.
단, 추가 후 discovery 를 자동으로 트리거하는지 불명확.

**변경**:
- `MCPManager.add_server(config)` → 내부적으로 `connect + list_tools` 까지
  수행해야 함. 실패 시 예외.
- `MCPManager.remove_server(name)` → 연결 종료 + 해당 서버가 공급한 tool 을
  레지스트리에서 제거. **이름 prefix 규칙** (plan/02 §C) 에 따라
  `mcp__{name}__*` 패턴을 스캔.
- `ToolRegistry.unregister(name)` 메서드 추가 (현재 없음).

**API exposure (Geny 측)**: `EnvironmentService` 에 다음 메서드 추가 검토:
- `add_mcp_server(env_id, config)` — live 세션에 즉시 반영할지, manifest 갱신
  후 재시작할지는 Phase E 의 UX 결정 (별도 섹션).

## §C. MCP 결과의 원형 보존

**변경 위치**: `geny-executor/tools/mcp/manager.py:210-240`,
`tools/mcp/adapter.py:48-60`.

**현재**: MCP 서버의 응답 콘텐츠 블록을 `\n` 으로 join 해서 단일 문자열로
평탄화.

**변경**:
- MCP 응답이 **단일 텍스트 블록** 이면 지금처럼 문자열.
- **여러 블록** 이거나 **비텍스트 블록 (image, resource)** 가 있으면 `list[dict]`
  형태로 보존. `ToolResult.content` 는 `Any` 이므로 타입 변경 불필요.
- `ToolResult.to_api_format(tool_use_id)` (base.py:45-61) 가 이미 list/str
  분기를 가지므로 Anthropic 메시지에 list 그대로 전달 가능.

이렇게 하면 MCP 가 구조화 데이터를 돌려줬을 때 호출자가 다시 JSON parse 하다
실패하는 F-4 가 소거된다.

## §D. Health Check Probe

MCP 서버가 연결 유지 중 조용히 죽는 경우에 대비:
- `MCPManager.probe(name) -> bool` — 가벼운 RPC (list_tools 캐시된 등록 시간
  비교) 로 생존 확인.
- Stage 10 의 tool 실행 직전 probe 는 성능 부담이 크므로 **세션 시작 시
  1회** + **선택적 주기 probe** (세션 설정에서 비활성 기본).

## 롤백

- 세 섹션 모두 breaking change. 회귀 발견 시 해당 PR 을 revert 한다.
  `strict=False` 등 "우회용 compat flag" 는 남기지 않는다.
- §A 의 엄격화로 기존에 조용히 실패하던 manifest 가 세션 시작 시 에러를
  내게 된다. Phase E 의 수동 QA 단계에서 저장된 모든 env 를 한 번씩 세션
  생성해보며 사전에 걸러낸다.

## 성공 기준

- MCP 서버가 manifest 에 선언되고 정상 동작하면 세션 시작 시 tool 목록에 즉시
  노출된다.
- 서버 연결 실패는 세션 시작에서 명시적 에러로 끝난다 ("Stage 10 에서
  Unknown tool" 로 위장되지 않는다).
- MCP tool 이 구조화 데이터를 반환하면 LLM 이 받는 tool_result 도 구조를 유지.
