# 03 — Geny consumer 측 tool 등록 사슬

Geny 가 자신의 built-in / custom tool 을 `geny-executor` 에 "넣는" 방식이다.
모든 경로는 `/home/geny-workspace/Geny` 기준.

## 정의 계층 — `BaseTool` 패밀리

- `backend/tools/base.py:32-165` — `BaseTool`, `ToolWrapper`.
  - `BaseTool.run(**kwargs) -> str` (line 154-165) — handler 추상. **반환값은
    문자열** 이어야 함을 타입으로 강제.
  - 파라미터 스키마는 `run()` 시그니처 + docstring 에서 자동 추출
    (`base.py:64-101`).
  - `.to_dict()` → `{name, description, parameters}`.
- 실제 tool 구현은 `backend/tools/built_in/*_tools.py` 와
  `backend/tools/custom/*_tools.py`.
  - 예: `backend/tools/custom/web_search_tools.py:101-169`, `NewsSearchTool`.
  - `run()` 의 반환은 항상 `json.dumps(...)` 된 문자열 — 에러 케이스도
    `{"error": "..."}` 로 감싸서 문자열로 반환 (line 145).
  - 모듈 끝에서 `TOOLS = [WebSearchTool(), NewsSearchTool()]` 로 노출 (line 176).

## 수집 — `ToolLoader`

- `backend/service/tool_loader.py:32-225`
  - `load_all()` (line 47) — `tools/built_in/*_tools.py` + `tools/custom/*_tools.py`
    스캔.
  - 모듈에 `TOOLS` 리스트가 있으면 그것을, 없으면 `BaseTool / ToolWrapper`
    인스턴스를 자동 발견 (line 111-122).
  - 결과: `self.builtin_tools`, `self.custom_tools` 이름 → 인스턴스 매핑.

## 세션 생성 시 주입 — `AgentSessionManager`

- `backend/service/langgraph/agent_session_manager.py:434-467`
  ```python
  geny_tool_registry = build_geny_tool_registry(
      self._tool_loader, allowed_tool_names
  )
  ...
  if env_id:
      prebuilt_pipeline = self._environment_service.instantiate_pipeline(
          env_id, api_key=api_key
      )
  ```
  - `allowed_tool_names` 는 `ToolPresetDefinition` 의 custom_tools 필터로 결정.
  - built-in 은 항상 포함, custom 은 preset 으로 걸러짐 (line 364-372).

## 어댑터 — `tool_bridge`

- `backend/service/langgraph/tool_bridge.py:24-59` — `build_geny_tool_registry()`
  - 각 Geny `BaseTool` 을 `_GenyToolAdapter` 로 감싸 executor 의 `Tool` 구현체로
    변환.
- `backend/service/langgraph/tool_bridge.py:62-149` — `_GenyToolAdapter`
  - `name / description / input_schema` 프록시.
  - `execute(input, context)` (line 104-149):
    - `ToolContext` 에서 `session_id` 를 뽑아 input 에 자동 주입 (line 115-116).
    - `tool.run(**input)` 동기 또는 `arun(**input)` 비동기 호출.
    - 반환이 문자열이 아니면 `json.dumps(..., default=str)` 로 강제 직렬화
      (line 135-140). JSON 직렬화 실패 시 `str(result)` 로 폴백.
    - `ToolResult(content=result)` 를 반환 — **is_error 는 설정하지 않음**
      (모든 성공/실패가 `is_error=False` 로 평탄화됨).

## 파이프라인 합류 — `AgentSession._build_pipeline`

- `backend/service/langgraph/agent_session.py:680-758` (non-env_id 경로)
  - `ToolRegistry()` 생성 후 `ReadTool/WriteTool/...` 를 직접 등록 (line
    691-697).
  - `self._geny_tool_registry` 가 있으면 `tools.register(t)` 루프
    (line 700-702).
  - 이 `tools` 를 `GenyPresets.vtuber(tools=tools, ...)` 혹은
    `worker_adaptive(tools=tools, ...)` 의 kwarg 로 전달 (line 729-752).

## 실행 — `AgentSession.run_stream`

- `backend/service/langgraph/agent_session.py:818-938`
  - `pipeline.run_stream(input_text, _state)` 로 위임.
  - 이벤트 스트림에서 `tool.execute_start / execute_complete` 이벤트를 찍어
    실시간 로그에 반영 (line 857-870).

## 요약 표

| 역할 | 파일 | 라인 | 비고 |
|------|------|------|------|
| Tool 추상 | `backend/tools/base.py` | 32-165 | `run(**kwargs) -> str` |
| news_search 구현 | `backend/tools/custom/web_search_tools.py` | 101-169 | JSON 문자열 반환 |
| 노출 리스트 | 〃 | 176 | `TOOLS = [...]` |
| 스캔/수집 | `backend/service/tool_loader.py` | 32-225 | built_in / custom 디렉터리 기반 |
| 레지스트리 빌드 | `backend/service/langgraph/tool_bridge.py` | 24-59 | `build_geny_tool_registry()` |
| 어댑터 | 〃 | 62-149 | `_GenyToolAdapter` |
| 매니저 진입 | `backend/service/langgraph/agent_session_manager.py` | 434-491 | env_id / non-env_id 분기 |
| 세션 파이프라인 | `backend/service/langgraph/agent_session.py` | 680-758 | tools kwarg 로 Preset 에 전달 |
| 실행 | 〃 | 818-938 | `pipeline.run_stream` |

## 관찰

1. **모든 경로가 문자열**: `BaseTool.run() -> str`, `_GenyToolAdapter` 도
   비문자열을 강제로 `json.dumps` 로 평탄화. 결국 LLM 에 가는 tool_result 는
   항상 문자열. 이 자체는 문제없지만 **`is_error` 플래그가 세팅되지 않아**
   Stage 10 이 실패를 실패로 인식할 수 없다.
2. **etc(preset) 우회**: `AgentSession._build_pipeline` 에 `prebuilt_pipeline`
   (`env_id` 경로) 가 전달되면 **built-in 등록 / `GenyPresets` 분기가 모두
   건너뛰어진다**. 이때 Geny 의 `_geny_tool_registry` 는 파이프라인 어디에도
   주입되지 않는다 → 다음 문서 (`04_...`) 의 핵심 gap.
3. **어댑터 안의 예외**는 현재 `_GenyToolAdapter.execute` 안에서 어떻게
   처리되는지 명시적으로 따져봐야 한다. 대부분의 경우 `tool.run(**input)` 이
   던진 예외가 상위로 propagate 되어 Stage 10 router 의 `except Exception`
   블록에서 stringified 된다 (→ `ToolResult(content="Tool '...' failed:
   ...", is_error=True)`).
