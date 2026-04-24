# 03. Current State — Geny Integration Layer

**Status:** Draft
**Date:** 2026-04-24
**Source:** `/home/geny-workspace/Geny/backend/` (post-cycle 20260424_2 — `claude_manager/` 해체됨)

이 문서는 **Geny backend 가 geny-executor Pipeline 위에 올린 통합 레이어** 의 현재 상태다. 02 문서가 "엔진 내부" 라면 이 문서는 "엔진을 호스트에 물리는 어댑터" 를 다룸.

---

## 1. Pipeline 빌드 & 런타임 결속

### 1.1 세션 생명 주기 한눈에

```
request → AgentSessionManager.create_agent_session(role, env_id, ...)
              │
              ▼
        EnvironmentService.instantiate_pipeline(env_id, adhoc_providers=[GenyToolProvider])
              │
              ▼
        Pipeline.from_manifest_async(manifest, adhoc_providers=..., tool_registry=...)
              │
              ▼
        AgentSession(prebuilt_pipeline=...)._build_pipeline()
              │
              ▼
        Pipeline.attach_runtime(
            system_builder = DynamicPersonaSystemBuilder | ComposablePromptBuilder,
            tool_context   = ToolContext(session_id, working_dir, storage_path),
            llm_client     = <anthropic/other BaseClient>,
            memory_retriever / memory_strategy / memory_persistence  (optional),
        )
              │
              ▼
        AgentSession.invoke(input_text)
              ├─ _check_freshness()
              ├─ _ensure_alive()
              ├─ status = RUNNING
              └─ _invoke_pipeline()
                    ├─ STM 기록: self._memory_manager.record_message(...)
                    ├─ _state = PipelineState(session_id=...)
                    ├─ _hydrate_state_safely(registry, _state)   # creature state 등
                    └─ _pipeline_events_scoped():
                          bind_mutation_buffer(buf)
                          bind_creature_role(...)
                          async for event in pipeline.run_stream(pipeline_input, _state):
                              session_logger.log(...)
                              yield event
```

### 1.2 `attach_runtime` 호출 지점

`backend/service/executor/agent_session.py:1144–1173`

전달 kwargs:
- `system_builder` — `DynamicPersonaSystemBuilder` (VTuber 또는 persona-사용 세션) 또는 `ComposablePromptBuilder`
- `tool_context` — `ToolContext(session_id, working_dir, storage_path)` (tool 이 세션 컨텍스트에 접근)
- `llm_client` — `BaseClient` 인스턴스 (보통 Anthropic)
- `memory_retriever` — `GenyMemoryRetriever(...)` (있을 때만)
- `memory_strategy` — `GenyMemoryStrategy(...)` (있을 때만)
- `memory_persistence` — `GenyPersistence(...)` (있을 때만)

`attach_runtime` 은 build 이후·run 이전 한 번만 호출하는 경계 (pipeline 수명 내에서 재결속 불가).

### 1.3 주요 파일 위치

| 파일 | 라인 | 역할 |
|---|---|---|
| `service/executor/agent_session_manager.py` | 79–250 | 매니저 초기화 + 싱글턴 |
| `service/executor/agent_session.py` | 238–260 | 런타임 wiring 주석 |
| `service/executor/agent_session.py` | 924–1173 | `_build_pipeline()` + `attach_runtime` |
| `service/executor/agent_session.py` | 1938–2020 | `invoke()` 진입점 |
| `service/executor/agent_session.py` | 1441–1650 | `_invoke_pipeline()` 이벤트 루프 |
| `service/executor/agent_session.py` | 1312–1413 | `_pipeline_events_scoped()` contextvar 관리 |

---

## 2. Tool 시스템 (Geny 측)

### 2.1 디렉토리 레이아웃

```
backend/
├── tools/
│   ├── base.py                # BaseTool / ToolWrapper / @tool decorator
│   ├── built_in/              # 항상 로드되는 Geny 플랫폼 tool
│   │   ├── geny_tools.py      # 세션 관리 / 메시징 / 플랫폼 API
│   │   ├── knowledge_tools.py # 지식 질의
│   │   └── memory_tools.py    # 메모리 조작
│   └── custom/                # preset 필터링 대상인 일반 tool
│       ├── web_search_tools.py
│       ├── browser_tools.py
│       └── web_fetch_tools.py
├── service/
│   ├── tool_loader.py         # ToolLoader 싱글턴 (발견 + 조회)
│   ├── tool_policy/
│   │   └── policy.py          # ToolPolicyEngine (역할 기반 허용 서버 필터)
│   ├── tool_preset/
│   │   ├── models.py          # ToolPresetDefinition
│   │   ├── store.py           # 프리셋 영속화 (DB)
│   │   └── templates.py       # 기본 프리셋 템플릿
│   └── executor/
│       ├── tool_bridge.py     # _GenyToolAdapter — Geny Tool → geny-executor Tool
│       └── geny_tool_provider.py  # AdhocToolProvider 구현
```

### 2.2 Tool 정의

`tools/base.py` (라인 32–210).

```python
class BaseTool(ABC):
    name: str
    description: str
    parameters: Optional[Dict[str, Any]]   # JSON Schema (자동 생성 가능)

    @abstractmethod
    def run(self, **kwargs) -> str: ...
    async def arun(self, **kwargs) -> str:
        return self.run(**kwargs)  # 기본은 sync → to_thread
```

`ToolWrapper` + `@tool` 데코레이터로 plain function 을 BaseTool 처럼 노출. Parameter schema 는 `inspect.signature` + 타입힌트 + 독스트링 파싱으로 자동 생성.

### 2.3 ToolLoader (발견 + 필터링)

`service/tool_loader.py:32–237`

```python
class ToolLoader:
    builtin_tools: Dict[str, Any]   # 항상 포함
    custom_tools:  Dict[str, Any]   # preset 필터링

    def load_all(self) -> None:
        # 1. built_in/*.py 스캔 → builtin_tools
        # 2. custom/*.py  스캔 → custom_tools

    def get_allowed_tools_for_preset(
        self, preset: ToolPresetDefinition
    ) -> List[str]:
        # builtin 은 항상 포함
        # preset.custom_tools 에 따라 custom 필터:
        #   ["*"]           → 전체
        #   ["web_search"]  → 명시된 것만
```

### 2.4 geny-executor 로 넘기는 adapter

`service/executor/tool_bridge.py` `_GenyToolAdapter` (라인 28–175):

- Geny `BaseTool` → geny-executor `Tool` ABC 매핑
- `name`, `description`, `input_schema` property 노출
- `to_api_format() → Dict` — Anthropic tool definition 포맷
- `execute(input, context)`:
  1. `_accepts_session_id` probing 결과에 따라 `session_id` 주입 여부 결정
  2. `tool.arun(...)` 또는 `tool.run(...)` 호출
  3. 결과를 `ToolResult` 로 래핑

세션 ID 주입 프로빙 (라인 47–94) — `tool.func` / `tool.run` / `tool.arun` 서명에 `session_id` 또는 `**kwargs` 가 있는지 검사. 실패 시 **false-safe**.

### 2.5 AdhocToolProvider

`service/executor/geny_tool_provider.py` — `GenyToolProvider`:
- `Pipeline.from_manifest_async(..., adhoc_providers=[GenyToolProvider(tool_loader)])` 에 주입
- manifest 의 `tools.external: ["search_web", ...]` 이름 → `GenyToolProvider.get(name)` 해석
- 결과가 `_GenyToolAdapter` 로 감싸져 `ToolRegistry` 에 등록

### 2.6 새 tool 추가 흐름

**built-in**
1. `tools/built_in/my_tools.py` 에 `@tool` 함수 또는 `TOOLS = [...]` 선언
2. `ToolLoader.load_all()` 이 자동 발견
3. 정책 조정 불필요 (플랫폼 tool 은 항상 포함)

**custom**
1. `tools/custom/my_tools.py` 작성
2. `ToolPresetDefinition.custom_tools` 에 `"my_tool"` 이름 포함
3. 프리셋이 적용된 세션에서 사용 가능

**마찰도:** 1–2 파일.

---

## 3. MCP 통합 (Geny 측)

### 3.1 MCPLoader

`service/mcp_loader.py:165–400+`

```python
class MCPLoader:
    mcp_dir        = PROJECT_ROOT / "mcp"
    builtin_dir    = mcp_dir / "built_in"   # 항상 포함
    custom_dir     = mcp_dir / "custom"     # 프리셋 필터링
    servers:          Dict[str, MCPServerConfig]  # custom
    builtin_servers:  Dict[str, MCPServerConfig]

    def load_all(self) -> MCPConfig:
        self._load_builtin_configs()  # mcp/built_in/*.json
        self._load_custom_configs()   # mcp/custom/*.json
```

설정 파일 (JSON):
```json
{
    "type": "http",
    "url": "https://api.github.com/mcp/",
    "headers": { "Authorization": "Bearer ${GITHUB_TOKEN}" },
    "description": "GitHub MCP"
}
```

`_expand_env_vars` (라인 265) — `${VAR}` 해석. 미해결 변수 있으면 **조용히 건너뜀** ("skipped: missing env vars" 로그).

### 3.2 세션 MCP 구성

`service/mcp_loader.py:114–162` `build_session_mcp_config`:

```python
def build_session_mcp_config(
    global_config: Optional[MCPConfig],          # custom
    allowed_mcp_servers: Optional[List[str]] = None,
    extra_mcp: Optional[MCPConfig] = None,
) -> MCPConfig:
    # 1. 내장 MCP (always)
    # 2. custom MCP (allowed_mcp_servers 필터)
    # 3. 세션별 추가 MCP (extra_mcp)
```

### 3.3 MCP transport 모델

`service/sessions/models.py:47–129`:
- `MCPServerStdio` — command + args + env
- `MCPServerHTTP` — url + headers
- `MCPServerSSE` — legacy (HTTP 권장)

`MCPConfig.to_mcp_json()` — 세션 working dir 의 `.mcp.json` 으로 serialize.

### 3.4 Role 기반 tool policy

`service/tool_policy/policy.py`:

```python
class ToolProfile(Enum):
    MINIMAL, CODING, MESSAGING, RESEARCH, FULL

_PROFILE_SERVER_GROUPS = {
    MINIMAL:   {"_geny_servers"},
    CODING:    {"_geny_servers", "_custom_servers", "filesystem", "git", ...},
    MESSAGING: {"_geny_servers", "_custom_servers", "slack", "email", ...},
    RESEARCH:  {"_geny_servers", "_custom_servers", "web", "search", ...},
    FULL:      frozenset(),     # empty = allow all
}

ROLE_DEFAULT_PROFILES = {
    "worker":    CODING,
    "developer": CODING,
    "researcher": RESEARCH,
    "planner":   FULL,
}
```

`ToolPolicyEngine.filter_mcp_config(mcp_config)` — prefix 매칭으로 서버 필터링.

### 3.5 새 MCP 서버 추가 흐름

1. `backend/mcp/custom/my_server.json` 작성
2. `.env` 에 참조 변수 (예: `MY_API_KEY`) 설정
3. 필요 시 `service/tool_policy/policy.py` 의 `_PROFILE_SERVER_GROUPS` 에 해당 서버 prefix 추가

**마찰도:** 1–3 파일 (정책 수정이 필요하면 3).

---

## 4. Environment / Manifest

### 4.1 EnvironmentService

`service/environment/service.py:78–200`:

```python
class EnvironmentService:
    storage = Path("./data/environments")

    def load_manifest(env_id: str) -> Optional[EnvironmentManifest]: ...
    def instantiate_pipeline(
        env_id: str,
        *, adhoc_providers=[...], tool_registry=None, ...
    ) -> Pipeline: ...
```

### 4.2 기본 manifest factory

`service/executor/default_manifest.py:1–189`:

- preset 이름 → EnvironmentManifest 변환
- 지원 preset: `"vtuber"`, `"worker_adaptive"`, `"worker_easy"`, `"default"`
- 각 preset 은 16-stage chain + stage 별 strategy + cache + loop 제약을 반환

### 4.3 성장 단계 manifest

`service/executor/stage_manifest.py:1–200+`:

- VTuber 성장 단계 (`infant` / `child` / `teen` / `adult`) × 아키타입 (`cheerful`, `curious`, ...)
- 차이점:
  - `max_turns`: 2 / 5 / 8 / 10
  - cache 전략: `system_cache` (infant/child) vs `aggressive_cache` (teen/adult)
  - evaluator: `signal_based` vs `binary_classify`
  - 사용 가능한 게임 tool set (`feed` → `feed+play` → `+gift` → `+talk`)

### 4.4 새 preset 추가 흐름

1. `service/executor/default_manifest.py` 의 `_KNOWN_PRESETS` 에 이름 추가
2. `_my_preset_stage_entries(StageManifestEntry)` 함수로 stage chain 반환
3. `build_default_manifest(preset)` 분기에 포함
4. 필요 시 policy 프로필 추가

**마찰도:** 1–2 파일, 다만 stage chain 을 이해해야 함.

---

## 5. Prompt & Persona

### 5.1 PromptBuilder / Section 라이브러리

`service/prompt/builder.py`:

- `PromptMode` — `FULL` / `MINIMAL` / `NONE`
- `PromptSection` — name / content / priority / condition / modes / tag (XML 래핑)
- `PromptBuilder.add_section(...).build()` — 모드 필터 + 정렬 + 렌더

`service/prompt/sections.py` `SectionLibrary`:
- `identity(...)` — 역할 기반 신원 (worker / developer / researcher / planner / vtuber)
- `user_context()` — 사용자 정보 (UserConfig)
- `geny_platform(session_id)` — MCP 로 플랫폼 tool 사용 가능 안내

**Tool schema 포함 전략:** 시스템 프롬프트에는 **tool 스키마를 포함하지 않음**. 스키마는 API 요청의 `tools` 파라미터로만 전달 (LLM 이 그걸 이미 구조화된 형태로 받음).

### 5.2 Persona

`service/persona/`:
- `PersonaProvider` (protocol) — `resolve(state, session_meta) → PersonaResolution`
- `CharacterPersonaProvider` — VTuber 캐릭터 프롬프트 제공자 (아키타입별: cheerful / curious / introvert / extrovert / artisan)
- `DynamicPersonaSystemBuilder` — 매 턴 `persona_provider.resolve()` 호출 → 인스턴스 상태 없이 최신 persona 로 system prompt 재구성
  - `set_character` / `append_context` 가 즉시 다음 턴에 반영되는 원리

### 5.3 새 role / persona 추가 흐름

1. `service/sessions/models.py` `SessionRole` enum 에 항목 추가
2. `service/prompt/sections.py` `_ROLE_IDENTITY` 에 신원 문구 추가
3. `service/tool_policy/policy.py` `ROLE_DEFAULT_PROFILES` 에 프로필 매핑
4. `backend/prompts/<role>_prompt.md` 작성 (기본 역할 프롬프트)
5. VTuber 와 유사한 캐릭터 기반이라면 `service/persona/` 에 추가 작업
6. 필요 시 `agent_session.py` 의 role-specific 분기 로직 업데이트

**마찰도:** 4–6 파일.

---

## 6. Hooks — SessionLifecycleBus

`service/lifecycle/bus.py:52–105`:

```python
class SessionLifecycleBus:
    def subscribe(event, handler) -> SubscriptionToken: ...
    def subscribe_all(handler)    -> SubscriptionToken: ...
    async def emit(event, session_id, **meta): ...
```

`service/lifecycle/events.py`:
```python
class LifecycleEvent(Enum):
    CREATED, DELETED, PAIRED, RESTORED, IDLE, REVIVED
```

현재 등록된 구독자는 거의 없음 (내부 정리·VTuber↔Sub-Worker pairing 정도). claude-code 의 PreToolUse / PostToolUse / PermissionRequest 같은 **fine-grained** 훅은 부재. 이 지점은 04 → 05 로 이어짐.

---

## 7. Skills / Slash commands 대응

현재 Geny 에는 "Skill" 이라는 공식 개념이 없음. 기능적 대응물:

| claude-code | Geny 대응 | 위치 | 구현 방식 |
|---|---|---|---|
| Skill (specialized behavior) | Role + Persona 조합 | `service/prompt/sections.py`, `service/persona/` | system prompt 에 인코딩 |
| Slash command | 게임 tool (feed / play / gift / talk) | `service/game/tools/` | Tool ABC 로 노출, state.shared 변형 |
| Hook (lifecycle event) | `SessionLifecycleBus` | `service/lifecycle/` | async pub/sub |
| Hook (PreToolUse 등) | **부재** | — | — |

즉 "프롬프트 + tool 묶음" 을 파일로 추가하는 Skill 흐름이 없음. 이건 08 design 에서 다룸.

---

## 8. 새 기능 추가 Friction 정량표

| 시나리오 | 수정 파일 수 | 난이도 | 재테스트 범위 |
|---|---|---|---|
| 새 built-in tool | 1–2 | ⭐ | tool 실행 + preset 필터 |
| 새 MCP 서버 | 2–3 | ⭐ | MCP 연결 + 정책 필터 |
| 새 role + persona | 4–6 | ⭐⭐ | role-specific prompt + tool access |
| 새 pipeline preset | 1–2 | ⭐⭐ | stage chain 실행 + cache 전략 |
| 새 memory provider | 2–4 | ⭐⭐⭐ | 메모리 저장·복구 + reflection |
| Skill 추가 | **N/A** (개념 부재) | — | — |

설계 원칙 P3 (확장 friction 최소화) 의 baseline.

---

## 9. 중복 / 책임 모호 지점

### 9.1 Tool schema 정의
- **Geny**: `BaseTool.parameters` + `_GenyToolAdapter.to_api_format()`
- **geny-executor**: `Tool.input_schema` + `ToolRegistry.to_api_format()`
- **현재 해소 지점**: `_GenyToolAdapter` 가 유일한 변환점 역할
- **위험**: 두 계층 모두 schema 검증 가능하여 책임이 모호

### 9.2 Prompt 생성
- **Geny**: `PromptBuilder` 가 최종 텍스트 생성
- **geny-executor**: Stage 3 `system_builder` slot 이 system prompt 조립
- **현재 해소**: `DynamicPersonaSystemBuilder` 를 system_builder 로 주입 → Stage 3 가 이미 완성된 프롬프트를 그대로 사용 (이중 가공 방지)
- **위험**: Stage 3 내부에서 추가 가공하는 artifact 가 도입되면 silent 간섭

### 9.3 Tool 필터링
- **Geny**: `ToolPolicyEngine` (role 기반 서버 화이트리스트)
- **geny-executor**: `ToolRegistry.register` + manifest `tools.external` (manifest 레벨 화이트리스트)
- **현재 해소**: Geny 가 정책 먼저, manifest 가 차순
- **위험**: 두 레벨 모두 "tool 을 거부" 할 수 있어 디버깅 난이도 증가. 명시적 책임 경계 문서화 필요.

### 9.4 Memory 저장 / Reflection
- **Geny**: `GenyMemoryRetriever` / `GenyMemoryStrategy` / `GenyPersistence` (어댑터)
- **geny-executor**: Stage 2 (Context) / Stage 15 (Memory) 구현
- **현재 해소**: Geny 어댑터가 Stage slot 인터페이스에 정확히 맞춤
- **위험**: reflection 결과 형식이 레이어마다 달라질 수 있어 통합 테스트 필수

### 9.5 State 관리
- **Geny**: `StateProvider` (creature state 등 게임 상태)
- **geny-executor**: `PipelineState`
- **현재 해소**: `state.shared[CREATURE_STATE_KEY]` 로 분리 + contextvar 수명 관리
- **위험**: `state.shared` 는 free-form dict — 키 네임 충돌 가능. 05 gap 에서 "shared dict 스키마화" 다룸.

---

## 10. 요약 — Geny 측의 구조적 특징

**강점**
- 명확한 3 단계 wiring (SessionManager → EnvironmentService → AgentSession) — 각 단계의 책임이 분리됨
- role 기반 tool policy → 외부 tool 접근을 세분화된 profile 로 통제
- Persona provider 추상 — 매 턴 reset 없이 시스템 프롬프트 동적 변경
- contextvar 기반 mutation buffer + creature role — sub-component 가 상태를 안전히 읽고 쓸 수 있음

**한계 (05 gap analysis 로 이어짐)**
- Tool "계약" 이 `BaseTool` + 별도 adapter 두 곳에 분산 (`tools/base.py` + `tool_bridge.py`)
- MCP 서버 등록이 정적 JSON 에 의존 — 런타임 add/remove API 부재
- Skill 개념 부재 — "role + custom tool 세트" 묶음이 hardcoded
- Fine-grained hook (PreToolUse 등) 부재 — permission / observability / audit 훅 자리 없음
- `state.shared` dict 의 키 스키마 없음 — 런타임에 키 충돌 가능

다음 문서 ([`04_reference_claude_code.md`](04_reference_claude_code.md)) 는 이 한계들을 해소할 수 있는 **참조 패턴 카탈로그**.
