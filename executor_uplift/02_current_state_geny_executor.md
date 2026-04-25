# 02. Current State — geny-executor Architecture (v2 baseline + v3 21-stage)

**Status:** Updated — v3 layout shipped
**Date:** 2026-04-25
**Source:** `/home/geny-workspace/geny-executor/` (현재 PyPI `>=1.0.0`)
**Audit log:** 세 번째 사이클 Explore agent 보고서 (2026-04-24) + Sub-phase 9a 통합 사이클 (2026-04-25)

> **Note on versioning.** Sections 1–7 below describe the **v2 16-stage baseline** that this uplift started from. As of geny-executor `1.0.0` (Sub-phase 9a) the engine ships **21 stages**: the original 16 stay in place, the agent-loop tail is renumbered (`agent` 11→12, `evaluate` 12→14, `loop` 13→16, `emit` 14→17, `memory` 15→18, `yield` 16→21), and **5 new scaffold stages** land — `tool_review` (11), `task_registry` (13), `hitl` (15), `summarize` (19), `persist` (20). See **§A. v3 21-stage layout** at the bottom of this document for the wired-vs-scaffold delta and which §8 gap items the new stages now address.

이 문서는 **현재 존재하는** 구조의 스냅샷이야. "이랬으면 좋겠다" 는 06–10 의 design 문서에서 다룸.

---

## 1. 16 Stage 전수 표

Phase 구분:
- **Phase A (Ingress):** Stage 1–3
- **Phase B (Agent Loop):** Stage 2–13 (loop body, iteration 마다 반복)
- **Phase C (Egress / Finalize):** Stage 14–16

> Stage 2–3 은 Ingress 이자 Loop body 의 진입부 — 첫 iteration 의 데이터 준비와 후속 iteration 의 context 갱신을 동시에 맡음.

| # | Stage | Path | 역할 요약 | 입 → 출 | Slots / Chains | 확장 방식 |
|---|---|---|---|---|---|---|
| 1 | **Input** | `s01_input/` | 원본 입력을 canonical `NormalizedInput` 으로 검증·정규화 | `Any` → `NormalizedInput` | slots: `validator`, `normalizer` | Config · Strategy · Bypass |
| 2 | **Context** | `s02_context/` | 대화 history 조립 + 선택적 memory retrieval + 토큰 예산 압축 | `Any` → `Any` | slots: `strategy`, `compactor`, `retriever` + optional `MemoryProvider` | Config · Strategy · Memory provider 주입 |
| 3 | **System** | `s03_system/` | system prompt 작성 + `state.tools` 에 tool 목록 등록 | `Any` → `Any` (pass-through) | slot: `builder` (Static / Composable) + optional `ToolRegistry` | Config · Strategy · Tool registry 바인딩 |
| 4 | **Guard** | `s04_guard/` | 토큰 예산 · 비용 예산 · 반복 횟수 · 권한 등 pre-flight 검사 | `Any` → `Any` | **chain**: `guards` (TokenBudget / CostBudget / Iteration / Permission) | Config · Chain mutation (append/remove/reorder) |
| 5 | **Cache** | `s05_cache/` | Anthropic prompt caching breakpoint 전략 적용 | `Any` → `Any` | slot: `strategy` (No / System / Aggressive) | Config · Strategy |
| 6 | **API** | `s06_api/` | `state.llm_client` 를 통해 LLM 호출; 재시도 관리 | `Any` → `APIResponse` | slots: `provider` (legacy), `retry` (ExpBackoff / None / RateLimit-aware) | Config · Strategy · ClientRegistry lookup · 로컬 fallback |
| 7 | **Token** | `s07_token/` | 토큰 사용량 추적 + 비용 계산 | `APIResponse` → `Any` | slots: `tracker` (Default / Detailed), `calculator` (Anthropic / Custom / Unified pricing) | Config · Strategy · Custom pricing |
| 8 | **Think** | `s08_think/` | Extended thinking 블록 처리 (`thinking_enabled` 전용) | `Any` → `Any` | slot: `processor` (Passthrough / ExtractAndStore / Filter) | Config · Strategy · bypass when disabled |
| 9 | **Parse** | `s09_parse/` | API 응답을 text / tool-call / thinking 으로 분해; completion signal 감지 | `APIResponse` → `ParsedResponse` | slots: `parser` (Default / StructuredOutput), `signal_detector` (Regex / Structured / Hybrid) | Config · Strategy · Custom detector |
| 10 | **Tool** | `s10_tool/` | `ToolRegistry` 를 통해 tool 호출 실행; binding / permission 적용 | `Any` → `Any` | slots: `executor` (Sequential / Parallel), `router` (RegistryRouter) + `ToolRegistry` | Config · Strategy · Tool binding · Executor parallelism |
| 11 | **Agent** | `s11_agent/` | Sub-pipeline 위임 · multi-agent orchestration | `Any` → `Any` | slot: `orchestrator` (SingleAgent / Delegate / Evaluator) | Config · Strategy |
| 12 | **Evaluate** | `s12_evaluate/` | 응답 품질 평가 (signal · criteria · agent · binary-classify) | `Any` → `Any` | slots: `strategy` (Signal / Criteria / Agent / BinaryClassify), `scorer` (None / Weighted) | Config · Strategy · adaptive artifact |
| 13 | **Loop** | `s13_loop/` | 루프 지속 여부 결정 (continue / complete / error / escalate) | `Any` → `Any` | slot: `controller` (Standard / SingleTurn / BudgetAware) | Config · Strategy · budget-aware |
| 14 | **Emit** | `s14_emit/` | 결과 외부 소비자에게 전달 (text / callback / vtuber / TTS) | `Any` → `Any` | **chain**: `emitters` | Config · Chain mutation |
| 15 | **Memory** | `s15_memory/` | 실행 결과를 memory 에 기록 + 선택적 LLM reflection | `Any` → `Any` | slots: `strategy` (AppendOnly / None / Reflective), `persistence` (InMemory / File / Null) + optional `MemoryProvider` + `MemoryHooks` | Config · Strategy · Provider 주입 · ReflectionResolver |
| 16 | **Yield** | `s16_yield/` | 최종 출력 포맷팅 및 assemble | `Any` → `PipelineResult` | slot: `formatter` (Default / Structured / Streaming) | Config · Strategy |

**Loop boundary 상수:** `LOOP_START=2`, `LOOP_END=13`, `FINALIZE_START=14`, `FINALIZE_END=16` (`core/pipeline.py`).

---

## 2. Core Primitives

### 2.1 `core/pipeline.py` — Pipeline

- `__init__(config: PipelineConfig)` — 설정 받아 stage 인스턴스 조립
- `from_manifest(manifest, api_key, strict, adhoc_providers, tool_registry)` — sync 구성 (MCP 연결 skip)
- `from_manifest_async(...)` — async 구성 (MCP 서버 연결 포함)
- `register_stage(stage)` / `remove_stage(order)` — stage 교체·삭제 (chaining)
- `run(input, max_iterations) → PipelineResult` — 한 번 실행
- `run_stream(input) → AsyncIterator` — 스트리밍 실행
- `attach_runtime(...)` — **런타임 의존성 주입** (아래 별도 섹션)
- `_init_state(input)` — PipelineState 초기화
- `_run_phases(state)` — 본 루프 (Phase A → B loop → C)

속성: `mcp_manager`, `tool_registry` (공개).

### 2.2 `core/state.py` — PipelineState

**Identity / Execution / Behavior**
- `session_id`, `pipeline_id`, `iteration`, `max_iterations`, `current_stage`, `stage_history`
- `stream`, `single_turn` (from config)

**Model / Message**
- `system` (str or List[blocks]), `messages` (List[dict])
- `model`, `max_tokens`, `temperature`, `top_p`, `top_k`, `tools`, `tool_choice`, `stop_sequences`

**Thinking**
- `thinking_enabled`, `thinking_budget_tokens`, `thinking_type`, `thinking_display`, `thinking_history`

**Tokens / Cost / Cache**
- `token_usage: TokenUsage`, `turn_token_usage`, `total_cost_usd`, `cost_budget_usd`
- `cache_metrics: CacheMetrics`

**Context / Loop / Tools / Agent / Evaluation**
- `memory_refs`, `context_window_budget`
- `loop_decision`, `completion_signal`, `completion_detail`
- `pending_tool_calls`, `tool_results`
- `delegate_requests`, `agent_results`
- `evaluation_score`, `evaluation_feedback`

**Output / Debug / Metadata**
- `final_text`, `final_output`
- `last_api_response` (raw passthrough)
- `created_at`, `updated_at`, `metadata` (free-form), `shared` (cross-stage), `events`

**Runtime (attach_runtime 경유)**
- `llm_client: Optional[BaseClient]`
- `session_runtime: Optional[Any]` (0.30.0+ 플러그인 carrier)
- `_event_listener` (스트리밍 콜백)

### 2.3 `core/stage.py` — Stage + Strategy ABC

**Strategy ABC**
- `name`, `description` (property)
- `configure(config: Dict)`
- `config_schema() → ConfigSchema` (classmethod)
- `from_config(config) → Strategy` (factory)
- `get_config() → Dict`

**Stage ABC (Generic[T_In, T_Out])**
- `name`, `order`, `category`
- `execute(input, state)` — abstract
- `should_bypass(state) → bool`
- `on_enter` / `on_exit` / `on_error` hooks
- `describe() → StageDescription`
- `list_strategies()`, `get_strategy_slots()`, `get_strategy_chains()`
- `set_strategy(slot_name, impl_name, config)`
- `get_config_schema()`, `get_config()`, `update_config()`
- `tool_binding`, `model_override` — per-stage override (PipelineMutator 로 set)

### 2.4 `core/slot.py` — Multi-strategy composition

- `StrategySlot` — single-choice (swap API)
- `SlotChain` — ordered list (add / append / remove / reorder / clear)

### 2.5 `core/mutation.py` — Runtime modification

- `PipelineMutator` — Pipeline 을 감싸고 모든 변경을 `MutationKind` 기반 감사 로그 + 스레드 락과 함께 수행
- 18종 mutation kind: SWAP_STRATEGY, UPDATE_*_CONFIG, SET_STAGE_ACTIVE, REGISTER/REMOVE/REPLACE_STAGE, REORDER/ADD/REMOVE_CHAIN, REGISTER/UNREGISTER_HOOK, BIND/UNBIND_TOOL, SET_TOOL_SCOPE, SET_STAGE_MODEL, RESTORE_SNAPSHOT
- `snapshot() / restore(snapshot)` — 상태 캡처/복원

### 2.6 `core/builder.py` — PipelineBuilder

Fluent chain API: `with_model`, `with_system`, `with_tools`, `with_cache`, `with_context`, `with_memory`, `with_loop`, `with_think`, `with_guard`, `with_artifact`, `build()`.

### 2.7 `core/environment.py` — Manifest 직렬화

- `EnvironmentManifest` — 전체 파이프라인 구성 직렬화
- `EnvironmentResolver` — `${VAR}` 환경 변수 치환
- `EnvironmentSanitizer` — 크레덴셜 제거 (export 안전용)
- `EnvironmentManager` — 디스크 입출력
- `EnvironmentDiff` — 두 manifest 비교

### 2.8 `core/schema.py` — UI 친화적 Config 정의

- `ConfigField` — name/type/label/description/default/validators/ui_widget/visible_when
- `ConfigSchema` — field 모음 + validate + to_json_schema

### 2.9 `core/presets.py` — 프리셋 등록소

- `PresetRegistry` — 클래스 레벨 thread-safe 레지스트리 (RLock)
- Python entry-point (`geny_executor.presets`) 로 자동 발견
- `PipelinePresets` / `PresetManager` / `PresetInfo`

### 2.10 `core/introspection.py` — 런타임 구조 질의

- `introspect_stage(stage, artifact)` → 단일 stage 메타
- `introspect_all()` → 16개 stage 일괄
- `_STAGE_CAPABILITY_MATRIX` — tool_binding · model_override 지원 여부 flag

### 2.11 `core/artifact.py`

- `create_stage`, `describe_artifact`, `list_artifacts`, `list_artifacts_with_meta`, `get_artifact_map`

### 2.12 `events/` — EventBus

- `EventBus.on(event_pattern, callback)` / `off(...)` — pub/sub
- `PipelineEvent` — 이벤트 타입 enum (stage.enter, stage.exit, mutation.applied, tool.call_start/complete, feature.unsupported, ...)

---

## 3. LLM Client Layer

### 3.1 `llm_client/base.py` — BaseClient ABC

- `ClientCapabilities` (frozen) — supports_thinking / tools / streaming / tool_choice / stop_sequences / top_k / system_prompt / `drops: tuple[str]`
- `create_message(...) → APIResponse`
- `create_message_stream(...) → AsyncIterator`
- `_send(request, purpose) → APIResponse` — 서브클래스 구현
- `_build_request(...) → APIRequest` — canonical 조립, drops 에 대해 `feature.unsupported` 이벤트 발사

### 3.2 `llm_client/types.py` — Canonical payload

- `APIRequest` — model / messages / max_tokens / system / temperature / top_p / top_k / tools / tool_choice / stop_sequences / thinking / metadata / stream
- `ContentBlock` — type (text / tool_use / thinking) + 필드별 값 + `raw` (vendor passthrough)
- `APIResponse` — content blocks / stop_reason / usage / model / message_id / raw; 편의 property: `text`, `tool_calls`, `thinking_blocks`, `has_tool_calls`
- `TokenUsage` — input / output / cache_creation / cache_read; `+=`, `+` 지원

### 3.3 `llm_client/registry.py` — Provider 등록

- `ClientRegistry.register(provider, factory)` / `get(provider)` / `available()`
- Pre-registered: `anthropic` (hard dep), `openai` / `google` (optional extras), `vllm`

---

## 4. Memory Integration

### 4.1 `memory/provider.py` — 4축 모델

- **Layer**: STM · LTM · NOTES · VECTOR · INDEX · CURATED · GLOBAL
- **Capability**: READ · WRITE · SEARCH · LINK · PROMOTE · REINDEX · SNAPSHOT · REFLECT · SUMMARIZE
- **Scope**: EPHEMERAL · SESSION · USER · TENANT · GLOBAL
- **Importance**: CRITICAL · HIGH · MEDIUM · LOW

`MemoryProvider` 프로토콜 + 각 layer 별 핸들 (`STMHandle`, `LTMHandle`, ...).

### 4.2 구현체

- `EphemeralMemoryProvider`, `FileMemoryProvider`, `SQLMemoryProvider`, `CompositeMemoryProvider`, `GenyManagerAdapter`

### 4.3 Stage 와의 결합

- Stage 2 (Context) — `provider.retrieve(RetrievalQuery)` → `state.metadata["memory_context"]`
- Stage 15 (Memory) — `provider.record_turn(Turn)`, `record_execution(ExecutionSummary)`, reflection via hooks

### 4.4 `memory/strategy.py` — GenyMemoryStrategy

Geny 의 `SessionMemoryManager` 를 s15 에 맞추는 어댑터. Reflection 3경로 (callback / native / deferred), `auto_promote_importance`, `max_insights`.

---

## 5. Tool / Function-calling 현재 지원

### 5.1 Tool 획득 경로

1. **Built-in** (`src/geny_executor/tools/built_in/`) — Read, Write, Edit, Bash, Glob, Grep. manifest 가 `tools.built_in: ["*"]` 또는 명시 이름 시 자동 등록
2. **External (AdhocToolProvider)** — 호스트 (Geny) 가 제공하는 provider 에게 `manifest.tools.external` 이름 조회
3. **MCP servers** — `manifest.tools.mcp_servers` (List[MCPServerConfig]); async 경로에서 연결 후 `mcp__{server}__{tool}` 로 등록

### 5.2 Tool ABC (현재)

```
class Tool(ABC):
    name: str
    description: str
    input_schema() -> Dict
    async execute(input: Dict, context: ToolContext) -> ToolResult
```

API 포맷: `{"name", "description", "input_schema"}` (Anthropic tool definition).

### 5.3 실행 경로

1. Stage 3 (System) — `state.tools` 에 tool 목록 기록 (ToolRegistry 경유)
2. Stage 6 (API) — `state.tools` 를 LLM 요청에 포함 → tool_use 블록 반환 가능
3. Stage 9 (Parse) — tool_use 블록 추출 → `state.pending_tool_calls`
4. Stage 10 (Tool) — 각 tool 실행 (router → executor), binding 체크, 결과 → `state.tool_results`
5. Stage 11 (Agent) — 필요 시 sub-pipeline 위임
6. 다음 iteration 시 messages + tool_results 재전송

### 5.4 MCP layer

`tools/mcp/manager.py` `MCPManager`:
- `connect_all(configs)` — 모든 서버 기동
- `discover_all() → List[MCPAdapter]` — 각 서버의 tool 질의
- `disconnect_all()`
- 연결 실패 시 `MCPConnectionError` (half-connected 상태 없음)

Adapter 패턴: 각 MCP tool 을 `Tool` 서브클래스로 감싸고 `mcp__{server}__{tool}` 명으로 등록.

---

## 6. 확장 포인트 매트릭스

| 메커니즘 | 용도 | 장점 | 한계 |
|---|---|---|---|
| **Config schema** (`ConfigField` / `ConfigSchema`) | 파라미터 튜닝 | UI 자동화, serializable, validated | scalar/enum/object 값만. 구현체 교체 불가 |
| **Strategy / Slot** (`StrategySlot.swap`) | 내부 로직 교체 | Hot-swap, stage identity 보존 | slot 당 1 active, 사전 등록 필요 |
| **Slot chain** (`SlotChain`) | 순서 있는 composition (Guard, Emit) | 순서·추가·삭제 유연 | chain-aware stage (4, 14) 만 |
| **Stage 추가/삭제** (`PipelineBuilder`, `PipelineMutator`) | bypass · 커스텀 stage | 전면 유연성 | 1–16 순서 invariant 깨지기 쉬움 |
| **Mutation API** (`PipelineMutator`) | 런타임 변경 + 감사 | Atomic · change log · thread-safe | `MutationKind` 이해 필요 |
| **Event subscription** (`EventBus`) | 실시간 observer | 결합도 낮음, 와일드카드 | 구조화된 스키마 부재, 핸들러 예외는 로그만 |
| **Runtime attach** (`attach_runtime`) | llm_client + tools + session state 주입 | 크레덴셜 지연, 런타임 바인딩 | `session_runtime` 하나만, build 후 run 전 |
| **Preset** (`PresetRegistry`) | 사전 구성 패턴 | 재사용·entry-point 발견 | factory 만, 파라미터화 제한적 |
| **Manifest** (`EnvironmentManifest`) | 파이프라인 직렬화 | 포터블·auditable·git-friendly | 스키마 evolve 시 마이그레이션 부담 |
| **Tool binding** (`StageToolBinding`) | stage 당 tool 제한 | 세밀한 권한 | post-construction 에서 set |
| **Model override** (`_model_override`) | stage 별 다른 모델 | stage 튜닝 | 명시적 override 경로 있는 stage (2, 15) 만 |
| **Artifact selection** | Stage 구현 전체 교체 | 전면 제어 | 사전 작성된 artifact 만 |

---

## 7. 테스트 구조

### 7.1 디렉토리

```
tests/
├── unit/
│   ├── test_phase1_foundation.py
│   ├── test_phase1_pipeline.py
│   ├── test_phase2_agent_loop.py
│   ├── test_phase2_tools.py
│   ├── test_phase3_context_memory.py
│   ├── test_phase4_think_agent_evaluate.py
│   ├── test_phase5_emit_presets_mcp.py
│   ├── test_phase5_environment.py
│   ├── test_phase6_history.py
│   ├── test_geny_memory.py
│   ├── test_mcp_lifecycle.py
│   ├── test_llm_client_*.py
│   └── ... (여러 specialty 테스트)
└── integration/
    └── test_integration.py
```

### 7.2 Phase 기반 완성도

- Phase 1: Foundation + construction (~118 tests)
- Phase 2: Agent loop + tools (~64 tests)
- Phase 3: Memory / context (~12 tests)
- Phase 4: Advanced (thinking / evaluation / delegation) (~20 tests)
- Phase 5: Serialization / presets / MCP (~50 tests)
- Phase 6: History / persistence (~48 tests)
- Specialty: LLM clients / built-ins / artifacts / manifests (>80 tests)

**Total:** 약 400+ 테스트.

**pyproject.toml 커스텀 마커:** `c_phase_1`..`c_phase_4` — Interface / Native providers / Validation / Web mirror 완성도 축.

---

## 8. 현재 구조에서의 "고도화 여지" (Explore 보고서 요약)

### 8.1 관측성 (dashboard 부재) — **부분 해결 (v3)**
- EventBus 로 이벤트 방출 중. **시각화 UI 없음**. 운영자가 stage 실행·상태·mutation·token 을 실시간으로 볼 방법 부재.
- v3 업데이트: Geny 측에 21-stage `PipelineCanvas` (`frontend/src/components/session-env/PipelineCanvas.tsx`) 가 manifest 기반 read-only 시각화를 제공. 실시간 실행 상태 dashboard 는 여전히 미구현.

### 8.2 Adaptive model routing
- `model_override` 는 존재하지만 **언제 어떤 override 를 쓸지** 결정하는 router / classifier 없음. 토큰 비용의 30–50% 절약 기회.

### 8.3 Structured output 계약
- Stage 9 에 `StructuredOutputParser` slot 있으나 **Stage 3 system prompt 와 연동하여 schema 안내** 하는 first-class 메커니즘 없음.

### 8.4 Streaming granularity
- `create_message_stream()` 은 `APIResponse` 단위로 yield. **토큰/블록 단위 스트리밍** 과 custom chunking 없음.

### 8.5 Human-in-the-loop / approval gate — **해결 (v3)**
- ~~Stage hook (`on_enter` 등) 존재하나 **pause/resume 프로토콜** 과 UI 승인 흐름 없음. 고위험 tool (파일 삭제, 외부 API) 앞 승인 gate 부재.~~
- v3 업데이트: **Stage 15 (HITL)** 가 `PipelineResumeRequester` + `Pipeline.resume(token, decision)` 을 통해 cross-request pause/resume 을 표준화. Geny 측에 `HITLApprovalModal` + `/api/agents/{id}/hitl/{pending,resume,{token}}` REST 가 wired (G2.5 / G4.1 사이클).

### 8.6 Composite agent DAG
- Stage 11 (Agent) 는 slot + orchestrator 가 있지만 **DAG 수준의 multi-agent graph** 표현 부재. LangGraph / AutoGen 에 비해 explicit topology 표현이 약함.
- v3 메모: **Stage 13 (`task_registry`)** 가 scaffold 로 등장 — 향후 multi-agent task plan 의 carrier 가 될 자리. 현재는 advisory 만.

### 8.7 Tool-level review chain — **해결 (v3, 신규 항목)**
- v2 에는 tool 호출 직전 정책 검사 layer 가 없었음 (Stage 4 Guard 는 pre-flight budget 만).
- v3 업데이트: **Stage 11 (`tool_review`)** 가 5-단계 reviewer chain (`schema → sensitive → destructive → network → size`) 으로 worker_adaptive 에서 활성. 위반 시 severity-tagged flag 가 `tool_review.flag` 이벤트로 방출되며 timeline 에 inline 렌더 (G2.4 / G4.2 사이클).

이 목록은 `05_gap_analysis.md` 에서 claude-code 측 관점과 교차하여 우선순위를 재평가함.

---

## 9. 다음 문서

- [`03_current_state_geny_integration.md`](03_current_state_geny_integration.md) — geny-executor 위에 올라간 Geny 측 레이어 (tool loader, MCP loader, policy, persona, environment service)
- [`04_reference_claude_code.md`](04_reference_claude_code.md) — claude-code-main 의 참조 패턴
- [`05_gap_analysis.md`](05_gap_analysis.md) — 본 문서 + 03 을 04 와 교차

---

## A. v3 21-stage layout (geny-executor 1.0+, Sub-phase 9a)

> 이 섹션은 v3 의 변경된 stage 번호와 신규 5개 scaffold 만 정리하는 reference. 구현 세부는 위 §1–7 의 v2 표가 그대로 유효 — 단, 번호가 바뀐 stage 들은 아래 매핑을 적용.

### A.1 Layout 매핑 (v2 → v3)

| v2 # | v2 name | v3 # | v3 name | 변경 |
|---|---|---|---|---|
| 1–10 | input … tool | 1–10 | input … tool | 동일 |
| — | (없음) | **11** | **tool_review** | 신규 scaffold (5-reviewer chain) |
| 11 | agent | **12** | agent | 번호만 +1 |
| — | (없음) | **13** | **task_registry** | 신규 scaffold (multi-agent task plan carrier) |
| 12 | evaluate | **14** | evaluate | 번호만 +2 |
| — | (없음) | **15** | **hitl** | 신규 scaffold (cross-request approval gate) |
| 13 | loop | **16** | loop | 번호만 +3 |
| 14 | emit | **17** | emit | 번호만 +3 |
| 15 | memory | **18** | memory | 번호만 +3 |
| — | (없음) | **19** | **summarize** | 신규 scaffold (turn-end importance + summarize) |
| — | (없음) | **20** | **persist** | 신규 scaffold (FilePersister + on_significant) |
| 16 | yield | **21** | yield | 번호만 +5 |

### A.2 Phase 경계

- **Phase A (Ingress):** Stage 1 (= v2)
- **Phase B (Agent Loop):** Stage 2–16 (loop body 가 길어짐 — `LOOP_END` 가 13 → 16)
- **Phase C (Egress / Finalize):** Stage 17–21 (`FINALIZE_START` 가 14 → 17, `FINALIZE_END` 가 16 → 21)

### A.3 신규 scaffold 활성화 (preset-by-preset)

`build_default_manifest(preset)` 의 `_PRESET_SCAFFOLD_OVERRIDES` 표 (`Geny/backend/service/executor/default_manifest.py`) 가 각 preset 별로 어떤 scaffold 를 manifest 에서 `active=True` 로 켜는지 결정. 현재 상태:

#### A.3.1 Sub-phase 9a 신규 scaffold (5종)

| Preset | `tool_review` (11) | `task_registry` (13) | `hitl` (15) | `summarize` (19) | `persist` (20) |
|---|---|---|---|---|---|
| `worker_adaptive` | ✅ G2.4 | ⏸ scaffold-off | ✅ G2.5 (null requester → install_pipeline_resume_requester) | ✅ G2.2 (rule_based + heuristic) | ✅ G2.3 (no_persist → install_file_persister) |
| `worker_easy` | ⏸ off (single-turn Q&A) | ⏸ off | ⏸ off | ⏸ off | ⏸ off |
| `vtuber` | ⏸ off (no general tools) | ⏸ off | ⏸ off (no approval surface) | ⏸ off | ⏸ off |

`runtime-only` swap 패턴: `summarize` / `persist` / `hitl` 은 manifest 에 placeholder (`no_persist`, `null` requester) 만 두고, session-build time 에 `service.persist.install_file_persister` / `service.hitl.install_pipeline_resume_requester` 가 실제 객체로 교체. Pipeline 참조가 필요하거나 storage path 가 runtime 결정이라서 manifest-serialisable 하지 않은 의존성을 다루는 표준 방식.

#### A.3.2 Phase 7 strategy 활성화 (G9.9 + G12)

기존 stage 들의 slot strategy 를 default 에서 Phase 7 신규 구현체로 flip. 모두 strict-superset default 로 동작 — 추가 config 없으면 종전 동작과 동일, `strategy_configs` 로 튜닝 가능:

| Preset | s06 router | s08 budget_planner | s14 strategy | s16 controller | s18 strategy |
|---|---|---|---|---|---|
| `worker_adaptive` | `adaptive` (G12) | `adaptive` (G9.9) | `evaluation_chain` (G12) | `multi_dim_budget` (G12) | `structured_reflective` (G12) |
| `worker_easy` | `adaptive` (G12) | `adaptive` (G9.9) | `evaluation_chain` (G12) | `multi_dim_budget` (G12) | `structured_reflective` (G12) |
| `vtuber` | `passthrough` (legacy) | (no s08 — think omitted) | `signal_based` (legacy) | `standard` (legacy) | `append_only` (legacy) |

Strict-superset 의미:
- `multi_dim_budget` 의 default 는 `dimensions=["iterations"]` → `standard` 와 동일 동작
- `evaluation_chain` 의 default 는 `["binary_classify", "signal_based"]` first-non-null → 사실상 `binary_classify` 단일
- `structured_reflective` 의 default schema 는 `append_only` 의 데이터 모양과 동일
- `adaptive` router 의 default 는 bound model 만 사용 → `passthrough` 와 동일

**vtuber 는 conservative default 유지** (단일 turn + tool 없는 affect_tag 전용 → chain 류 wrapper 가 latency 만 추가).

#### A.3.3 Slot registry 확장 + 추가 wired strategies

- s02 retriever: `mcp_resource` 옵션을 Stage 2 slot 에 register (G9.1 / `service/strategies/__init__.py:register_mcp_resource_retriever`). 활성 retriever 는 여전히 attach_runtime 의 `GenyMemoryRetriever` — preset 이 명시 선택 시 swap.
- s17 emit chain: `OrderedEmitterChain` 으로 install (G2.1 / `service/emit/chain_install.py`).
- s03 system: `DynamicPersonaPromptBuilder` (S7.1, `service/persona/dynamic_builder.py`).

### A.4 새 이벤트 채널

| Stage | 이벤트 (executor) | event_type (Geny session_logger) | 용도 / consumer |
|---|---|---|---|
| 11 (tool_review) | `tool_review.flag` | `tool_review_flag` | reviewer 1건 마다 — severity / reviewer / reason; ExecutionTimeline 의 `getToolReviewVisual` 분기 |
| 11 (tool_review) | `tool_review.reviewer_error` | `tool_review_error` | reviewer 가 raise — 동일 |
| 11 (tool_review) | `tool_review.completed` | `tool_review_summary` | turn 단위 요약 (flags 개수) — 동일 |
| 15 (hitl) | `hitl.request` | `hitl_request` | HITLApprovalModal 의 `deriveHitlFromLogEvent` listen |
| 15 (hitl) | `hitl.decision` | `hitl_decision` | 모달 닫힘 신호 — 동일 |
| 15 (hitl) | `hitl.timeout` | `hitl_timeout` | timeout policy fire — 동일 |
| 16 (loop) | `loop.escalate` / `loop.error` | `loop_signal` | 권한 거부 / 예산 초과 / hook 차단; ExecutionTimeline 의 `loop_signal` 분기 (Lock / ShieldOff icon, G6.6) |
| 시스템 | `mcp.server.state` | `mcp_server_state` | MCPManager FSM 전이 (PENDING/CONNECTED/FAILED/NEEDS_AUTH/DISABLED); MCPAdminPanel + Dashboard 가 listen (G8.2) |
| 시스템 | `mutation.applied` | `mutation_applied` | PipelineMutator 변경; Dashboard MutationLog → MutationDiffViewer (G15) |

이벤트는 모두 `session_logger.log_stage_event` 를 거쳐 `LogLevel.STAGE` 행으로 직렬화 → WS `log` 이벤트로 frontend 로 흐름. Geny side 의 분기 helper:
- `frontend/src/components/tabs/CommandTab.tsx` — `deriveHitlFromLogEvent`
- `frontend/src/components/execution/ExecutionTimeline.tsx` — `getToolReviewVisual` (tool_review 3종 + loop_signal 4 분기)
- `frontend/src/components/dashboard/MutationLog.tsx` — `extractMutations` → `MutationDiffViewer`
- `frontend/src/components/mcp/MCPAdminPanel.tsx` — 직접 polling (이벤트 구독은 추후 cycle)

### A.5 관련 문서

- [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) §13 — 21-stage 재구성의 설계 근거
- [`11_migration_roadmap.md`](11_migration_roadmap.md) Phase 9 — Sub-phase 9a 실행 일정
- [`12_detailed_plan.md`](12_detailed_plan.md) — 사이클별 PR 분해
