# Appendix B — Terminology

**Status:** Draft

본 문서 전체에서 쓰이는 용어 정의. 알파벳 순.

---

### Agent (vs AgentSession)

- **Agent**: 대화 주체. Geny 에서는 `AgentSession` 인스턴스 하나가 하나의 agent
- **Subagent**: 메인 agent 가 spawn 한 격리된 다른 agent (claude-code 용어). Geny 에서는 `subagent_type` 에 해당하는 파이프라인
- **Agent orchestrator**: Stage 11 의 strategy. SingleAgent / Delegate / Evaluator 패턴으로 여러 agent 를 조율

### AgentSession

Geny 측 래퍼. 하나의 `geny-executor Pipeline` 을 생명주기 (생성·invoke·idle·revive·삭제) 와 함께 감싼다. `backend/service/executor/agent_session.py`.

### Artifact

특정 Stage 의 구체 구현체. 예: `s01_input/artifact/default/`, `s01_input/artifact/multimodal/`. Strategy 보다 큰 단위.

### Attach runtime

`Pipeline.attach_runtime(...)` — build 된 pipeline 에 런타임 의존성 (llm_client, tools, session_runtime, mcp_manager) 을 주입하는 boundary. build 후 run 전 한 번만 호출.

### BaseClient

`geny-executor/llm_client/base.py` 의 provider 추상. Anthropic / OpenAI / Google / vLLM 구현체가 canonical `APIRequest` / `APIResponse` 를 따름.

### BaseTool

Geny 측 tool ABC. `backend/tools/base.py`. uplift 에서는 새 `Tool` ABC 에 `LegacyToolAdapter` 로 자동 래핑.

### buildTool()

파이썬 factory. 간단한 tool 을 subclass 없이 dict 스타일로 생성. claude-code 의 TypeScript `buildTool()` 패턴을 Python 으로 이식.

### Capabilities (ToolCapabilities)

Tool 의 runtime trait: `concurrency_safe`, `read_only`, `destructive`, `idempotent`, `network_egress`, `interrupt`, `max_result_chars`. Stage 10 orchestrator 의 partition 기준.

### Chain (SlotChain)

Stage 가 가진 순서 있는 확장 지점. Guard(4), Emit(14) 에서 사용. `add/append/remove/reorder/clear` 가능.

### Command (Slash)

`/name args` 로 호출하는 단축키. `prompt` 타입 (= Skill) 또는 `builtin` 타입 (코드 핸들러).

### ConfigField / ConfigSchema

파라미터 선언. UI 자동 생성, validation, 직렬화. `geny-executor/core/schema.py`.

### Connection FSM

MCP 서버의 연결 상태 기계: CONNECTED / FAILED / NEEDS_AUTH / PENDING / DISABLED. 현재 Geny 는 "성공/실패" 2 상태만 — uplift 에서 5 상태로.

### ContextLoader

`backend/service/prompt/context_loader.py`. 세션 외부 컨텍스트 (사용자·환경 메타) 를 PromptBuilder 에 공급.

### EnvironmentManifest

Pipeline 구성 전체를 JSON/YAML 로 직렬화한 것. `stages + strategies + config + tools` 포함. Round-trip 가능.

### EventBus

`geny-executor/events/`. 비동기 pub/sub. `stage.enter`, `mutation.applied`, `tool.call_start` 등 이벤트를 외부 observer 가 수신.

### Frontmatter

YAML 블록을 `---`로 감싼 파일 앞머리. `SKILL.md`, `CLAUDE.md` 에서 사용. 메타데이터 선언.

### Guard

Stage 4. pre-flight 검사 (토큰·비용·반복·권한). chain 형 — 여러 guard 를 순서대로.

### Hook

- **Geny LifecycleBus hook**: Python callable, session lifecycle 이벤트 (CREATED/DELETED 등)
- **Subprocess hook** (uplift 신설): settings.json 에 command 로 등록. JSON stdin/stdout. `PreToolUse`, `PostToolUse`, `PermissionRequest` 등.

### LLM Client

`BaseClient` 구현체. provider 별 (anthropic / openai / google / vllm). Stage 6 가 호출.

### Manifest

= EnvironmentManifest. Pipeline 의 직렬화 형식.

### MCP (Model Context Protocol)

외부 프로세스가 tool / resource / prompt 를 표준 프로토콜로 노출. stdio / HTTP / SSE / WS / SDK-managed 등 transport 다양.

### MCPManager

MCP 서버 pool + lifecycle. uplift 에서 FSM + runtime add/remove 지원.

### MemoryProvider

4축 모델 (Layer × Capability × Scope × Importance) 의 메모리 추상. Stage 2 (retrieve) + Stage 15 (record + reflect) 가 사용.

### Mutation (PipelineMutator)

Pipeline build 후 런타임 변경. Atomic + audit log + thread-safe. 18 종 `MutationKind`.

### Permission

- **Rule**: `{tool_name, pattern, behavior: allow/deny/ask, source}` — uplift 신설
- **Mode**: default / plan / auto / bypass — 세션 레벨 정책
- **Matrix**: rule × source × pattern 의 결정 테이블

### Persona / PersonaProvider

Geny 측 동적 프롬프트 주입. 매 턴 `provider.resolve()` 호출 → PersonaResolution. VTuber 캐릭터 아키타입에 사용.

### Phase (A/B/C)

Pipeline 실행의 3 단계:
- **A (Ingress)**: Stage 1–3. 입력 정규화 + 컨텍스트 조립 + 시스템 프롬프트 생성
- **B (Agent Loop)**: Stage 2–13. iteration 마다 반복
- **C (Egress)**: Stage 14–16. 한 번 실행되는 마무리

### Pipeline

geny-executor 의 중심 객체. 16 stage + state + config + runtime. `run(input)` / `run_stream(input)` 진입점.

### PipelineState

실행 중 mutable context. 모든 stage 가 읽고 쓸 수 있음. `session_id`, `messages`, `tools`, `token_usage`, `shared`, `llm_client`, `session_runtime` 등.

### Preset

Pipeline 구성 factory. `PipelinePresets`, `PresetRegistry` 로 중앙 관리. 번들 / 사용자 / 플러그인 소스.

### PromptBuilder

`service/prompt/builder.py`. 섹션 조립 → 최종 시스템 프롬프트 텍스트. mode (FULL/MINIMAL/NONE) + tag 래핑.

### Role

Session 역할 (worker / developer / researcher / planner / vtuber). ToolPolicy 의 default profile 과 prompt identity 가 role 에 매핑.

### Session

Geny AgentSession 의 약칭. 하나의 대화 맥락 + AgentSession 인스턴스 + storage_path + session_id.

### session_runtime

`PipelineState.session_runtime: Any`. 0.30.0 도입. host (Geny) 가 실행 중 필요한 임의 데이터를 pipeline 안으로 주입하는 plugin carrier.

### Skill (uplift 신설)

코드 수정 없이 capability 를 추가하는 단위. `SKILL.md` 프론트매터 + 프롬프트 본문 + 허용 tool 리스트 + 모델 override + 실행 모드 (inline/fork).

### Slot (StrategySlot)

Stage 의 1:1 교체 지점. 한 번에 하나의 Strategy 가 active. `swap(impl_name, config)` 으로 교체.

### Stage

Pipeline 의 16 실행 단위. 각 Stage 는 `execute(input, state) → output` 책임. `order` (1–16) + `name` + `category`.

### state.shared

`PipelineState.shared: Dict[str, Any]`. stage 간 자유 형식 통신. uplift 에서 `SharedKeys` 네임스페이스 + `SharedDict` 타입 힌트 도입.

### Strategy

Stage 내부 로직의 교체 가능 단위. `configure()`, `from_config()`, `config_schema()`. Stage 의 slot 에 채워 넣음.

### Streaming tool executor (uplift 신설)

스트리밍으로 도착한 tool_use 블록을 즉시 실행 + 수신 순 결과 emit. claude-code `StreamingToolExecutor` 대응.

### Subagent

메인 agent 가 spawn 한 자식 agent. claude-code `subagent_type` (`code-reviewer`, `Plan`, `Explore`, `general-purpose` 등). Geny 에서는 VTuber ↔ Sub-Worker pairing 형태.

### Subprocess hook

= Hook (uplift 신설형). subprocess + JSON I/O 로 정책·감사 동작. 언어 중립.

### Task

Background 작업 단위. FSM (pending/running/completed/failed/killed). claude-code `LocalAgentTask`, `RemoteAgentTask` 등.

### Tool

- **기존 `Tool` ABC** (geny-executor): `name`/`description`/`input_schema`/`execute`
- **새 `Tool` ABC** (uplift): 위 + `capabilities` / `check_permissions` / `prepare_permission_matcher` / lifecycle hooks / render metadata

### ToolContext

Tool 실행 시 주입되는 컨텍스트 (session_id, working_dir, storage_path, permission_mode 등). `ToolContext` 타입.

### ToolPolicyEngine

Geny 측 role 기반 서버 prefix 필터. `service/tool_policy/policy.py`. uplift 의 PermissionRule matrix 와 **상보적** (서버 수준 vs call 수준).

### ToolRegistry

Stage 3 이 사용하는 tool 목록 저장소. Pipeline attach 시 구축.

### ToolResult

Tool 실행 결과. `data`, `display_text`, `new_messages`, `state_mutations`, `artifacts`, `persist_full`, `is_error`, `mcp_meta`.

### Transport (MCP)

MCP 서버와의 통신 방식. stdio / HTTP / SSE / WebSocket / SDK-managed / claudeai-proxy.
