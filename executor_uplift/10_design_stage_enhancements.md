# 10. Design — Stage-by-Stage Enhancements

**Status:** Draft
**Date:** 2026-04-24
**Priority:** P1–P2 (누적, 대부분 06–09 의 결과를 stage 에 뿌림)

각 stage 마다: **현재 한계 → 제안 → 확장 포인트 + 테스트 기준**. 이 문서는 06–09 의 설계를 16 개 stage 에 매핑한 "적용 가이드".

---

## Stage 1 — Input

### 현재
- 2 slots: `validator` (Default/Passthrough/Strict/Schema), `normalizer` (Default/Multimodal)

### 제안
- **JSONSchema 기반 Validator** 를 기본 — PydanticV2 생성 schema 와 호환
- **Multimodal normalizer** 를 향후 OpenAI vision / Gemini 와도 호환되게 추상화
- `MCPNormalizer` — MCP resource URI 가 입력에 포함되면 pre-fetch → inline

### 확장 포인트
- ConfigSchema: `strict_mode: bool`, `max_text_bytes: int`, `allow_file_attachments: bool`
- Strategy slot: `validator`, `normalizer`

### 테스트
- Multimodal + MCP URI 혼합 입력 → 정규화 결과 Anthropic block list

---

## Stage 2 — Context

### 현재
- 3 slots: `strategy`, `compactor`, `retriever` + optional `MemoryProvider`

### 제안
- **`SkillCatalogRetriever`** — skill 카탈로그 섹션을 context 에 주입
- **`MCPResourceRetriever`** — 07 design 참조, memory_refs 에서 mcp:// URI 읽기
- **Adaptive compactor** — 토큰 예산 초과 시 summary 강도 자동 조정
- **Progressive disclosure** — 대화 초반엔 minimal, 필요시 단계적 확장

### 확장 포인트
- Strategy slot: `strategy`, `compactor`, `retriever` (기존) + chain 가능하게 `retrievers: SlotChain` 로 격상 검토
- Memory provider injection (이미 있음)

### 테스트
- 토큰 예산 경계값 (95%, 99%, 105%) 에서 compactor 동작
- 복수 retriever 가 결과 병합 시 중복 제거

---

## Stage 3 — System

### 현재
- 1 slot: `builder` (Static / Composable) + optional `ToolRegistry`

### 제안
- **Skill catalog section** 자동 추가 (08 design)
- **Permission summary** — 현재 `permission_mode` 와 activated rules 를 간략 공유 (모델이 "어떤 도구가 막혔는지" 알면 덜 헤맴)
- **Persona 주입을 내장 섹션화** — 현재 Geny `DynamicPersonaSystemBuilder` 가 하던 역할을 executor 수준 `PersonaSection` 으로 이식 검토
- **DynamicSection** — 매 턴 `ctx` 기반 생성 (예: 현재 git 상태, CWD)

### 확장 포인트
- Strategy slot: `builder`
- 새로운 PromptSection 등록 API (현재 Geny 측에만 있음 → executor 로 승격)

### 테스트
- Persona 변경 후 다음 턴에 반영됨
- Skill 카탈로그 토큰 사이즈 cap

---

## Stage 4 — Guard

### 현재
- 1 chain: `guards` (TokenBudget / CostBudget / Iteration / Permission)

### 제안
- **`PermissionRuleMatrixGuard`** — 09 design 의 rule matrix 적용 (tool call 직전 ASK/DENY 판정)
- **`DestructiveConfirmationGuard`** — destructive tool 호출 시 사람 승인 필수 (permission_mode 와 교차)
- **`HookGateGuard`** — subprocess hook 응답이 `continue=false` 인 경우 block
- **`MCPHealthGuard`** — 사용하려는 MCP tool 의 서버가 CONNECTED 아니면 fail fast

### 확장 포인트
- Chain mutation — 새 guard append 용이

### 테스트
- Permission ASK → hook 으로 approve 요청 → 다음 상태 확인
- MCP server 가 PENDING 이면 fast fail

---

## Stage 5 — Cache

### 현재
- 1 slot: `strategy` (No / System / Aggressive)

### 제안
- **Adaptive cache** — prompt 안정도에 따라 breakpoint 자동 결정 (messages 가 자주 바뀌면 shorter, 안정되면 longer)
- **MCP tool schema cache** — MCP 서버별 tool list 가 변하지 않으면 system 에 캐싱 (재연결 시 invalidate)

### 확장 포인트
- Strategy slot: `strategy`

### 테스트
- cache_metrics (hit rate) 가 Aggressive 모드에서 높아지는지

---

## Stage 6 — API

### 현재
- 2 slots: `provider` (legacy), `retry`
- `BaseClient` 추상 + registry 기반 provider lookup

### 제안
- **Adaptive model router** — 쿼리 특성 (토큰 수 / thinking 필요 여부 / tool 사용 여부) 에 따라 Opus/Sonnet/Haiku 자동 선택
- **Fallback chain** — 1차 provider 실패 시 2차로 (예: Anthropic → OpenAI)
- **Cost-aware retry** — 남은 cost budget 이 적으면 retry 금지
- **Streaming token events** — 현재는 `message_complete` 만. **토큰 단위 event** 도입 (옵션)

### 확장 포인트
- Strategy slot: `provider`, `retry`
- 새 slot: `router` (adaptive model selection)

### 테스트
- Provider failover (rate limit → 다른 provider)
- Router 가 short query 를 Haiku 로 보냄

---

## Stage 7 — Token

### 현재
- 2 slots: `tracker`, `calculator`

### 제안
- **Per-stage token attribution** — "Stage 3 에서 X 토큰, Stage 10 tool result 에서 Y 토큰" 분해 → 최적화 타겟팅
- **Session-wide cost budget** — stage cost budget 과 별개로 세션 전체 예산 enforce
- **Multi-provider cost unification** — provider 간 가격이 다른데 한 계정 여러 세션 돌릴 때 비용 통합 뷰

### 확장 포인트
- Strategy slot: `tracker`, `calculator`
- EventBus: `cost.stage_breakdown`, `cost.session_near_limit`

---

## Stage 8 — Think

### 현재
- 1 slot: `processor` (Passthrough / ExtractAndStore / Filter)

### 제안
- **Adaptive thinking budget** — task 난이도에 따라 budget_tokens 자동 조정
- **Thinking content persistence** — thinking block 을 별도 로그에 저장 (감사용, 컨텍스트에는 포함 안 됨)
- **Thinking summary** — 긴 thinking 후 3 문장 요약 → 다음 iteration 에 참조

### 확장 포인트
- Strategy slot: `processor`
- ConfigSchema: `adaptive_budget: bool`, `min_budget`, `max_budget`

---

## Stage 9 — Parse

### 현재
- 2 slots: `parser` (Default / StructuredOutput), `signal_detector`

### 제안
- **Structured output schema contract** — Stage 3 가 system prompt 에 schema 안내를 자동 주입 + Stage 9 가 schema validate. 현재 slot 은 있지만 체인 완성 미흡.
- **Fallback parsing** — JSON parse 실패 시 LLM 에 retry 요청 (1회) 후 plain text 로
- **Multi-block parser** — tool_use 블록과 text 블록 혼재 시 순서 보존

### 확장 포인트
- Strategy slot: `parser`, `signal_detector`
- ConfigSchema: `schema: dict` (structured output 계약)

### 테스트
- Schema 위반 응답 → retry → 성공
- Tool-use 블록 순서 보존

---

## Stage 10 — Tool (★ 가장 큰 변화)

### 현재
- 2 slots: `executor` (Seq/Parallel), `router`, `ToolRegistry`

### 제안 (06 design 전면 이식)
- **Partition orchestrator** — tool 별 `isConcurrencySafe` 기반 safe batch (parallel, max_concurrent) + unsafe serial
- **Streaming tool executor** — API 에서 tool_use 블록이 올 때마다 즉시 실행 시작, 결과는 수신 순 emit
- **Result persistence** — `max_result_chars` 초과 시 디스크 저장 + path 반환
- **Permission evaluation** — 각 tool call 전에 09 design 의 matrix 평가
- **Lifecycle hooks** — `on_enter` / `on_exit` / `on_error` + subprocess hook `PreToolUse` / `PostToolUse` 연동
- **Contextual tool selection** — `state.tool_binding` 에 따라 허용 tool subset

### 확장 포인트
- Strategy slot: `executor` (Partition / Streaming), `router` (Registry / Adaptive)
- ConfigSchema: `max_concurrent`, `default_permission_mode`, `persist_threshold_chars`, `skill_allowed_fallback: bool`

### 테스트
- 2 read + 1 write 가 섞여 들어올 때 partition 결과 (read 병렬 후 write 직렬)
- `max_result_chars=1000` 에서 5000 자 결과 → 디스크 저장 + path 리턴
- Permission deny 시 LLM 에 deny 이유가 전달되어 다음 턴에 다른 접근 시도

---

## Stage 11 — Agent

### 현재
- 1 slot: `orchestrator` (SingleAgent / Delegate / Evaluator)

### 제안
- **`SubagentTypeOrchestrator`** — claude-code 의 `subagent_type` 개념 이식. 등록된 subagent type (`code-reviewer`, `Plan`, `Explore`, `general-purpose`) 중 LLM 이 이름으로 선택
- **Isolation modes** — `inline` (같은 프로세스), `worktree` (git 격리), `remote` (RPC) — 현재 `inline` 만 지원
- **Task lifecycle FSM** — Task = (pending / running / completed / failed / killed). claude-code 의 `LocalAgentTask` 대응
- **Skill `context: fork` 연동** — Skill 이 fork 모드 요청하면 orchestrator 가 subagent 로 실행

### 확장 포인트
- Strategy slot: `orchestrator`
- ConfigSchema: `default_isolation`, `max_parallel_subagents`, `allowed_subagent_types`

### 테스트
- `subagent_type=Explore` 호출 시 서브 파이프라인의 tool 제한
- `isolation=worktree` 시 메인 세션 파일 변경 안 됨

---

## Stage 12 — Evaluate

### 현재
- 2 slots: `strategy` (Signal / Criteria / Agent / BinaryClassify), `scorer`

### 제안
- **`EvaluatorChain`** — 여러 evaluator 를 순차 적용 (완화: SlotChain 화)
- **Per-task evaluator selection** — task difficulty 에 따라 가벼운/무거운 evaluator 자동 선택
- **Adaptive stop criteria** — 품질이 N turn 연속 개선 안 되면 loop exit
- **Human eval hook** — `permission_mode=plan` 에서 각 completion 을 사용자 승인 요청

### 확장 포인트
- Strategy slot → Chain 격상 검토
- ConfigSchema: `min_score`, `max_non_improving_turns`

---

## Stage 13 — Loop

### 현재
- 1 slot: `controller` (Standard / SingleTurn / BudgetAware)

### 제안
- **Multi-dimensional budget** — max_turns + max_tokens + max_cost + max_wall_clock 동시 평가
- **Escalation controller** — stuck 감지 시 model upgrade (Haiku → Sonnet) 자동 제안
- **Resumable loop** — controller 가 `pause` 시그널 수용 → 세션 suspend, 나중 resume

### 확장 포인트
- Strategy slot: `controller`
- ConfigSchema: `budget_matrix: dict`, `escalation_enabled: bool`

---

## Stage 14 — Emit

### 현재
- 1 chain: `emitters` (Text / Callback / VTuber / TTS)

### 제안
- **Ordering constraints** — 일부 emitter 는 선행 emitter 결과 의존 (예: TTS 는 sanitized text 필요)
- **Failure isolation** — 한 emitter 실패가 다른 emitter 에 영향 없음 (현재 이미 보장되는지 확인)
- **Backpressure** — TTS 등 느린 emitter 가 누적 시 skip 정책

### 확장 포인트
- Chain mutation — 새 emitter (예: WebSocket, Slack, Email) 등록 용이

---

## Stage 15 — Memory

### 현재
- 2 slots: `strategy` (AppendOnly / None / Reflective), `persistence` (InMemory / File / Null) + MemoryProvider + MemoryHooks

### 제안
- **Structured reflection schema** — reflection 결과를 자유 텍스트가 아닌 `InsightRecord{kind, importance, evidence, tags}` 로
- **Reflection backpressure** — 연속 reflect 실패 시 일시 중단 → 예산 보호
- **Memory graph linking** — 새 insight 가 기존 knowledge 와 연결되면 edge 생성 (curated memory 확장)
- **Promotion policy** — HIGH / CRITICAL importance insight 는 LTM 로 auto-promote (기존에 있으나 정책 재조명)

### 확장 포인트
- Strategy slot: `strategy`, `persistence`
- MemoryProvider / MemoryHooks 주입

---

## Stage 16 — Yield

### 현재
- 1 slot: `formatter` (Default / Structured / Streaming)

### 제안
- **MCP-formatted output** — 결과를 MCP response spec (content blocks, structured content) 에 맞춰 emit
- **Multi-format yield** — 동시에 text + structured + markdown 세 포맷 제공 (소비자에 맞게 선택)
- **Thinking visibility toggle** — 최종 결과에 thinking 포함 여부 설정

### 확장 포인트
- Strategy slot: `formatter`
- ConfigSchema: `include_thinking: bool`, `output_formats: list[str]`

---

## 11. Stage 간 상호작용 (bird's-eye)

```
  [Input] ── normalized ──▶ [Context] ── prompt+history ──▶ [System] ── system_prompt ──▶ [Guard]
                                                                                            │
                                                                                            ▼
                                                                                         [Cache]
                                                                                            │
                                                                                            ▼
                                                                                          [API] ◀─── state.llm_client
                                                                                            │
                                                                                            ▼
                                                                                         [Token]
                                                                                            │
                                            ┌──────────┴──────────┐
                                            ▼                     ▼
                                       [Think]              [Parse] ──── tool_use blocks ──▶ [Tool] ◀─── PermissionMatrix
                                                                                            │          │
                                                                                            │          └──▶ Hooks (PreToolUse)
                                                                                            ▼
                                                                                         [Agent] ◀─── Skill fork
                                                                                            │
                                                                                            ▼
                                                                                       [Evaluate]
                                                                                            │
                                                                                            ▼
                                                                                         [Loop] ── continue? ──▶ back to [Context]
                                                                                            │
                                                                                      complete/error
                                                                                            │
                                                                                            ▼
                                                                                       [Emit ⛓] ── [Memory] ── [Yield]
```

**핵심 관찰**
- Stage 4 (Guard) 와 Stage 10 (Tool) 사이의 "tool call 직전 permission 평가" 는 새 MatrixGuard 로 이동
- Stage 10 내부에서 Tool Lifecycle hooks + Subprocess Hooks (`PreToolUse`/`PostToolUse`) 동시 fire
- Stage 11 (Agent) 는 Skill fork 경로와 Subagent delegation 경로 양쪽의 합류점
- Memory (Stage 15) 는 Reflection schema 로 structured insight 생성 → next-session context (Stage 2) 의 MemoryProvider retrieve 소스

---

## 12. 공통 설계 제약

모든 stage 개선은 다음을 지킴:

1. **16 개 순서 불변** (P1)
2. **Existing manifest 와 backward compatible** — 기존 manifest 로 새 engine 이 돌아야 함
3. **Strategy / Slot 를 기본 확장 수단** — 새 파라미터는 ConfigSchema, 새 로직은 Strategy
4. **Event 방출** — 변경 지점마다 EventBus 이벤트 발사 (event taxonomy 는 09 design)
5. **Test** — 새 slot/strategy 마다 unit + integration round-trip

## 13. 21-Stage 재구성 — 5 개 신설 stage 통합

01 원칙 P1 의 완화로 stage 추가가 옵션이었는데, **cycle 내 재평가** 결과 **5 개 후보 모두 승격**. 각각의 책임이 기존 16 개 중 어느 stage 에도 자연스럽게 들어가지 않고, 전부 매 iteration 또는 finalize 마다 실행할 가치가 있음. 전체를 한 번의 major bump 로 흡수한다 (`0.x → 1.0.0`, stage count 변경은 이때가 유일한 기회).

### 13.1 최종 21-stage 레이아웃

```
Phase A (Ingress — 1 회)        Phase B (Agent Loop — 반복)           Phase C (Finalize — 1 회)
─────────────────────────────   ─────────────────────────────────    ─────────────────────────────
 1  Input                        2  Context                            17 Emit
                                 3  System                             18 Memory
                                 4  Guard                              19 Summarize     ★ 신설
                                 5  Cache                              20 Persist        ★ 신설
                                 6  API                                21 Yield
                                 7  Token
                                 8  Think
                                 9  Parse
                                10  Tool
                                11  Tool Review      ★ 신설
                                12  Agent
                                13  Task Registry    ★ 신설
                                14  Evaluate
                                15  HITL             ★ 신설
                                16  Loop
```

**Loop boundary 상수 재조정:**
- `LOOP_START = 2`
- `LOOP_END   = 16` (기존 13 → 16)
- `FINALIZE_START = 17` (기존 14 → 17)
- `FINALIZE_END   = 21` (기존 16 → 21)

### 13.2 신설 stage 5 종 — 상세

---

#### Stage 11 — Tool Review (신설)

**위치:** Tool (10) 직후, Agent (12) 이전
**책임:** Tool 실행 결과를 **LLM 호출 없이** 사전 검증. Anomaly 발견 시 Stage 12 (Agent) 로 넘기지 않고 즉시 error 로 routing.

**검증 항목**
| 항목 | 설명 |
|---|---|
| Size | `ToolResult.display_text` 가 `max_result_chars` 를 초과했나 (이미 Stage 10 에서 persist, 여기선 log 만) |
| Schema match | Tool 의 `output_schema` 가 선언돼 있으면 jsonschema validate |
| Destructive alert | `ToolCapabilities.destructive=True` 이고 결과가 실패면 즉각 escalation |
| Network egress audit | `network_egress=True` tool 의 외부 URL 을 log 에 기록 |
| Sensitive pattern | API key / password / PII 패턴이 결과에 섞였나 (opt-in pattern rule) |
| Iteration counter | 이 턴 내 tool 호출 횟수 제한 |

**Slots**
- `reviewers: SlotChain` (ordered chain): `SchemaReviewer`, `SensitivePatternReviewer`, `DestructiveResultReviewer`, `NetworkAuditReviewer`, `SizeReviewer`

**출력:** `state.tool_review_flags` 에 `[{tool_call_id, severity, reason}, ...]` 누적. Stage 12/14 가 이 플래그를 읽어 escalation 결정.

**설계 근거:** claude-code 에서는 tool 결과를 그대로 LLM 에 돌려 처리. 우리는 pipeline 구조의 이점을 살려 LLM 이전에 "싼 검증" 을 한 레이어 추가 → 토큰 절약 + 보안 감사 용이.

---

#### Stage 13 — Task Registry (신설)

**위치:** Agent (12) 직후, Evaluate (14) 이전
**책임:** Stage 12 (Agent) 가 spawn 한 background task 를 **일급 레이어** 로 추적. 기존에는 AgentTool 내부 숨겨진 state 였지만, task 개수가 많아지면 인과 관계 파악이 어려움.

**동작**
- Agent 가 spawn 한 task 들의 `{id, type, status, spawned_at, parent_tool_call_id}` 를 `state.tasks` (registry) 에 등록
- 이전 iteration 의 task 중 `completed` / `failed` 상태 도달한 것을 LLM 에 context 로 주입 (다음 iteration 의 Stage 2 가 이를 읽어 tool result 와 같은 형식으로 포함)
- Long-running task 는 `running` 상태 유지 + 후속 stage 는 이를 방해하지 않고 통과

**Slots**
- `registry: StrategySlot` — `InMemoryRegistry` (기본), `PostgresRegistry` (Geny 에서 사용), `RemoteRegistry` (원격 RPC)
- `policy: StrategySlot` — `EagerWait` (다음 iteration 전에 완료 대기) / `FireAndForget` (기본) / `TimedWait(ms)`

**출력:** `state.tasks_by_status: Dict[TaskStatus, List[Task]]` + `state.tasks_new_this_turn: List[Task]`

**설계 근거:** claude-code 의 `LocalAgentTask` 가 암묵적으로 하던 기능. 이를 stage 로 명시화하면 task 관찰·감사·정책 제어가 일관됨.

---

#### Stage 15 — HITL (신설)

**위치:** Evaluate (14) 직후, Loop (16) 이전
**책임:** Human-in-the-loop approval. Stage 14 의 evaluation 이 "approval 필요" 로 귀결되거나, tool review (11) 에서 sensitive flag 가 떴거나, permission mode 가 `plan` / `ask` 일 때 blocking gate.

**동작**
- `state.hitl_request` 가 set 되어 있으면 실행되고, 아니면 **bypass** (대부분의 iteration)
- Request 설정되면 외부 (UI 또는 CLI subscriber) 에게 approval event 발사 + `resume_token` 생성 + 대기
- Resume 경로: `Pipeline.resume(resume_token, decision)` API 가 대기 상태의 pipeline 을 깨움
- Decision: `approve` (다음 stage 로) / `reject` (Loop 에 error 통보) / `modify` (수정된 input 반영 후 이전 stage 로 replay)

**Slots**
- `requester: StrategySlot` — `NullRequester` (기본, no-op), `UIRequester` (websocket 이벤트), `CLIRequester` (stdin 대기)
- `timeout_policy: StrategySlot` — `IndefiniteWait` / `AutoApproveAfter(N)` / `AutoRejectAfter(N)`

**출력:** `state.hitl_decision: Optional[HITLDecision]` 에 결과 저장. Loop 이 이를 참조해 `error` 또는 `continue` 결정.

**설계 근거:** Permission `ask` 에 대한 blocking 메커니즘이 지금은 없음 — Stage 10 에서 async exception 으로 빠져나가는 형태. Stage 화하면 resume 프로토콜이 깔끔해지고, UI 가 "대기 중" 상태를 표현할 위치가 명확해짐.

---

#### Stage 19 — Summarize (신설)

**위치:** Memory (18) 직후, Persist (20) 이전
**책임:** 완료된 turn 전체를 **다음 세션이 참조 가능한 단일 인덱스 entry** 로 응축. LTM 의 search index 에 들어가는 재료를 한 자리에서 생성.

**동작**
- Turn 의 user prompt + final output + 중요 tool call 결과를 input 으로
- LLM 호출 또는 rule-based 로 요약 생성 (strategy 에 따라)
- 결과물: `SummaryRecord { turn_id, abstract (~3 sentences), key_facts: [...], entities: [...], tags: [...], importance: LOW|MEDIUM|HIGH|CRITICAL }`
- `state.memory_provider` 가 있으면 자동으로 `provider.record_summary(...)` 호출

**Slots**
- `summarizer: StrategySlot` — `NoSummary` (bypass), `RuleBasedSummarizer` (cheap), `LLMSummarizer` (Haiku override), `HybridSummarizer`
- `importance_classifier: StrategySlot` — `FixedImportance` / `HeuristicClassifier` / `LLMClassifier`

**출력:** `state.turn_summary: SummaryRecord`

**설계 근거:** 현재 Stage 15 (Memory) 의 `ReflectiveStrategy` 가 이 역할을 일부 수행하지만, "기록" 과 "요약" 이 같은 stage 에 섞여 있어 각 strategy 의 책임이 커짐. 분리하면 Memory 는 raw persist, Summarize 는 LTM index generation 으로 역할 선명.

---

#### Stage 20 — Persist (신설)

**위치:** Summarize (19) 직후, Yield (21) 이전
**책임:** 세션 전체의 **재개 가능한 checkpoint** 를 write-through 로 영속화. Pipeline crash · host restart · 장시간 idle 후에도 중간 상태에서 resume 가능.

**동작**
- `PipelineSnapshot` (이미 `core/snapshot.py` 존재) 에 현재 상태 캡처
- state.messages, state.total_cost_usd, state.tasks, state.metadata, summary 등 포함
- 저장소는 strategy 에 따라:
  - `FilePersistStrategy` — `<storage_path>/checkpoints/{turn_id}.json`
  - `PostgresPersistStrategy` — Geny DB
  - `RedisPersistStrategy` — 빠른 resume 용 캐시
  - `NoPersistStrategy` — stateless 세션용
- Resume: `Pipeline.resume_from_checkpoint(checkpoint_id) → Pipeline`

**Slots**
- `persister: StrategySlot` — 위 4 종
- `frequency: StrategySlot` — `EveryTurn` (기본), `EveryNTurns(3)`, `OnSignificantChange` (importance=HIGH/CRITICAL 일 때만)

**출력:** `state.last_checkpoint_id: str` + event `checkpoint.written`

**설계 근거:** Stage 15 의 `persistence` slot 은 "memory 저장소" 목적 (InMemory/File/Null). "세션 전체 체크포인트" 는 목적이 달라 — crash recovery 와 time-travel 가능한 snapshot. 분리하면 두 축을 각자 튜닝 가능.

### 13.3 Loop 에 준하는 "Finalize loop" 가능성 (차후 숙제)

재구성 후 Phase C (17–21) 는 **1 회 실행** 이지만, 향후 "Emit 이 실패하면 재시도 후 Persist" 같은 Phase C 내부 mini-loop 가 필요할 수도. 이번 cycle 은 1 회 실행 원칙 유지.

### 13.4 Stage Numbering Migration

`0.x → 1.0.0` major bump 에 포함.

**Manifest v2 → v3 변환**
- v2 manifest (16-stage) 로딩 시 **자동 변환**: 누락된 5 stage 를 default pass-through / no-op strategy 로 채워 v3 형태로 로드
- 사용자가 저장한 DB 기반 preset 도 load time 에 동일 변환
- "변환됨" 마크를 manifest 메타에 기록 → 다음 save 시 v3 로 저장

**Pipeline runtime**
- `Pipeline.from_manifest` 가 v2 / v3 양쪽 허용. 내부에서 v2 는 migrate 후 v3 스키마로 처리
- 외부 pin 은 `geny-executor >=1.0.0,<2.0.0` 을 새 기준으로

**Introspection API**
- `introspect_all()` 이 21 개 항목 반환
- UI 는 `len(introspect_all())` 로 stage 수를 동적 조회 (하드코딩 금지)

**Capability Matrix**
- `_STAGE_CAPABILITY_MATRIX` 에 신설 5 stage 의 `tool_binding` / `model_override` 지원 여부 선언
- Tool Review (11), HITL (15) — tool_binding 읽지 않음
- Summarize (19) — `model_override` 사용 (Haiku 등 cheap model)
- Persist (20) — 둘 다 안 씀
- Task Registry (13) — tool_binding 참조 (task spawn 시 child 에게 전달)

### 13.5 Stage 삽입 체크리스트 (통합)

5 stage 를 한 번에 추가 → 체크리스트 역시 한 번에 clear.

- [ ] `core/pipeline.py`:
  - [ ] `LOOP_END = 16`, `FINALIZE_START = 17`, `FINALIZE_END = 21` 상수 업데이트
  - [ ] `_run_phases` 가 21 stage 전체를 iterate
  - [ ] Loop body 에서 Stage 16 (Loop) 결정이 `continue` 면 Stage 2 로 돌아가는 경로
- [ ] `core/introspection.py`:
  - [ ] `_STAGE_CAPABILITY_MATRIX` 에 5 개 entry 추가
  - [ ] `introspect_all()` 이 21 개 StageIntrospection 반환
- [ ] 신설 stage 디렉토리 5 개 생성:
  - [ ] `stages/s11_tool_review/`
  - [ ] `stages/s13_task_registry/`
  - [ ] `stages/s15_hitl/`
  - [ ] `stages/s19_summarize/`
  - [ ] `stages/s20_persist/`
- [ ] 기존 번호 변경 stage rename:
  - [ ] 기존 `s11_agent` → `s12_agent`
  - [ ] 기존 `s12_evaluate` → `s14_evaluate`
  - [ ] 기존 `s13_loop` → `s16_loop`
  - [ ] 기존 `s14_emit` → `s17_emit`
  - [ ] 기존 `s15_memory` → `s18_memory`
  - [ ] 기존 `s16_yield` → `s21_yield`
- [ ] Manifest schema `v2 → v3` 변환 tool + backward-compat loader
- [ ] Pipeline snapshot schema 에 새 stage state 포함
- [ ] 기본 preset 5 종 (`vtuber`, `worker_adaptive`, `worker_easy`, `default`, 추가로 VTuber 성장 단계들) 모두 v3 로 regen + 동작 검증
- [ ] UI / introspection 소비자가 `len(stages)` 를 동적 조회
- [ ] 새 이벤트 타입 (stage.enter / stage.exit) 5 쌍 추가
- [ ] 테스트:
  - [ ] 각 신설 stage 의 unit + integration
  - [ ] 기존 stage 들이 번호 변경 후에도 동일 동작
  - [ ] v2 → v3 migration round-trip (기존 manifest 로딩 → run → v3 로 저장 → 재로딩 → 동일 결과)
- [ ] 버전 `1.0.0` 릴리스 + changelog 에 major change 명시
- [ ] 문서 sync:
  - [ ] 02 의 16-stage 표 유지하되 "legacy (v2)" 표기
  - [ ] 새 21-stage 표로 확장 (본 문서 §13.1)
  - [ ] Appendix A 파일 인덱스 업데이트

### 13.6 결론

기존 10 개 stage 개선 (13.1–12) 위에 **5 stage 신설 + stage 번호 재조정** 을 얹어 21-stage 체제로 전환. 이 변화는 uplift 의 **가장 큰 구조 변경** 이며, 별도 Phase 로 묶어 **한 번에 배포** (부분 적용 금지 — 일관성 확보). 구체 Phase 편성은 [`11_migration_roadmap.md`](11_migration_roadmap.md), 실행 레벨 상세는 [`12_detailed_plan.md`](12_detailed_plan.md).

---

## 14. 다음 문서

- [`11_migration_roadmap.md`](11_migration_roadmap.md) — 이 모든 설계를 phase 로 나누어 언제 무엇을 하는지
