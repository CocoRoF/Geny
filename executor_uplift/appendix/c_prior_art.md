# Appendix C — Prior Art

**Status:** Draft

이번 uplift 설계에 영향을 주었거나, 향후 참조 가치가 있는 외부 프로젝트들. 각각에서 **우리가 뽑아올 수 있는 구체 패턴** + **우리와의 차별점** 정리.

---

## 1. claude-code (이 문서의 1차 레퍼런스)

**Repo**: `/home/geny-workspace/claude-code-main/` (04 문서 전체)

### 핵심 영향
- Tool 계약의 완전성 (concurrency + destructive + permission + render)
- 번들/디스크/MCP 3 방향 Skill 로드
- Subprocess hook JSON 프로토콜
- Permission rule × source × pattern 매트릭스
- Streaming tool executor (수신 순 emit)
- Agent subagent_type + isolation 모드

### 우리와의 차별
- claude-code 는 **선형 query 루프** → 우리는 **16-stage 명시 구조**
- claude-code 는 React/Ink UI 내장 → 우리는 FastAPI + 별도 React 프론트
- claude-code 는 TypeScript → 우리는 Python (`buildTool` 같은 spread 패턴은 재현)
- claude-code 는 번들러 (Bun) 기반 dead-code elimination → 우리는 feature-flag + lazy import

---

## 2. LangChain

**Repo**: https://github.com/langchain-ai/langchain

### 우리에게 참조 가치

1. **OutputParser chain** — Stage 9 (Parse) 의 StructuredOutputParser 를 체인화할 때 참조
2. **Callback handler lifecycle** — LangChain 의 `BaseCallbackHandler` 가 LLM/Chain/Tool 시작·종료를 fire. Geny 의 EventBus + 새 Subprocess hook 과 대응
3. **Retry with exponential backoff** — Stage 6 의 `ExponentialBackoffRetry` 와 대응
4. **Tool decorator** (`@tool`) — 우리 `@tool` 과 동일 발상. 다만 LangChain 은 schema 생성이 더 적극적 (pydantic)
5. **Structured output with Pydantic** — `PydanticOutputParser`, `.with_structured_output()` — 우리 Stage 9 Structured contract 의 참조

### 차별
- LangChain 은 **체인 (linear composition)** 중심 — 우리는 **stage (명시적 분기)** 중심
- LangChain Tool 은 **상태 없음** (순수 함수) — 우리는 `ToolContext` 로 세션 상태 주입
- LangChain 은 "agent executor" 가 tool 실행 루프 — 우리는 Stage 10 + Stage 13 분리
- LangChain 은 "agent type" (ZeroShot / ReAct / OpenAIFunctions) 으로 루프 로직 결정 — 우리는 stage `controller` strategy

### 채택 가능 아이디어
- **LangChain `callbacks.BaseCallbackHandler` style handler registration API** — Python 에 친숙한 패턴. 우리 EventBus 에 `on_tool_start(tool, input, **kwargs)` 같은 메서드 기반 API 를 convenience layer 로 얹을 수 있음.
- **`with_structured_output(pydantic_model)` API** — Stage 3 + 9 를 함께 구성하는 factory

---

## 3. LangGraph

**Repo**: https://github.com/langchain-ai/langgraph

### 우리에게 참조 가치

1. **명시적 State machine** — `StateGraph(...)` 로 node + edge 선언. 우리 16-stage 는 고정 순서지만, Stage 11 (Agent) 내부에서 **sub-graph** 로 LangGraph 스타일 DAG 표현 가능
2. **Checkpointer** — `MemorySaver`, `SqliteSaver` 로 state 영속화. 우리 Geny `session_store` + executor `attach_runtime(state_snapshot=...)` 패턴과 대응
3. **Interrupt & resume** — `interrupt_before=["node_name"]` 으로 사람 개입. 우리 uplift 의 HITL (10 design Stage 13) 참조
4. **Conditional edges** — `add_conditional_edges(src, decider, {"continue": "loop", "end": END})`. 우리 Stage 13 loop controller 의 표현력이 이와 유사
5. **Streaming of intermediate state** — 각 node 전후의 state 변화 이벤트로 emit

### 차별
- LangGraph 는 **사용자가 graph 를 직접 선언** → 우리는 **16-stage 고정**. 표현력은 우리가 낮지만 일관성은 높음
- LangGraph node 는 state 를 순수 함수로 변환 → 우리 Stage 는 클래스 + strategy slot

### 채택 가능 아이디어
- **Sub-graph 개념** — Stage 11 Agent orchestrator 의 delegate 가 사실 sub-pipeline 을 spawn. 이를 명시적 sub-graph DSL 로 노출하면 사용자가 "이 자리에서 LangGraph 식 분기를 하고 싶다" 할 때 직관적
- **Checkpointer 인터페이스 공개** — 우리도 `PipelineSnapshot` 이 있지만 resume API 공식화 필요

---

## 4. LlamaIndex

**Repo**: https://github.com/run-llama/llama_index

### 우리에게 참조 가치

1. **Response synthesizer** — 긴 context 를 여러 chunk 로 나눠 LLM 에 순차 질의 + 결과 synthesize. Stage 2 Context 의 advanced retriever + Stage 9 Parse 와 Stage 15 Memory 사이의 multi-pass 흐름 참조
2. **Retriever composition** — `VectorIndexRetriever`, `BM25Retriever`, `FusionRetriever`. 우리 Stage 2 의 retriever slot 을 **chain** 으로 격상하는 아이디어
3. **Structured output with tool calling** — Pydantic schema → tool call 로 강제. 우리 Stage 9 Structured Output 과 유사
4. **Query engine patterns** — `RouterQueryEngine` (query 에 따라 다른 engine 으로 라우팅). 우리 adaptive model router (Stage 6) + adaptive retriever (Stage 2) 아이디어 원천
5. **Workflows (0.11+)** — 이벤트 기반 DAG, `@step` 데코레이터. LangGraph 와 비슷한 방향성

### 차별
- LlamaIndex 는 **RAG/검색 중심** — tool use 는 부가 기능
- 메모리 모델이 우리 4축 (Layer × Capability × Scope × Importance) 보다 단순

### 채택 가능 아이디어
- **Query rewriting / HyDE** — 검색 query 를 LLM 으로 개선 후 retrieve. Stage 2 의 사용자 쿼리 분석 단계로 추가 가능
- **Structured retrieval eval** — retrieved chunk 의 relevance 를 LLM-as-judge 로 평가. Stage 12 Evaluate 에 응용

---

## 5. AutoGen

**Repo**: https://github.com/microsoft/autogen

### 우리에게 참조 가치

1. **Multi-agent group chat** — 여러 agent 가 한 대화에 참여, speaker selection 전략. Stage 11 Agent orchestrator 의 `Delegate` pattern 확장 참조
2. **Conversable agent abstraction** — agent 가 서로 send/receive. 우리 Geny Messenger + AgentSession delegation 과 유사
3. **Code execution sandbox** — docker / jupyter 격리 실행. Stage 10 tool sandbox 참조 (현재 우리는 로컬 subprocess)
4. **Teachability (memory)** — agent 가 대화 중 학습. 우리 Stage 15 reflection + curated memory 와 대응
5. **Termination conditions** — 여러 agent 상호작용 종료 조건 (user input required, max consecutive replies, etc.) — 우리 Stage 13 Loop 의 multi-dimensional budget 아이디어

### 차별
- AutoGen 은 **agent 간 대화** 중심 — 우리는 **single agent + tools** 중심
- 우리 Geny 의 VTuber↔Sub-Worker pairing 은 AutoGen 2-agent 패턴과 비슷하지만 전용 구조 (Sub-Worker 는 VTuber 전용 도구 제공자)

### 채택 가능 아이디어
- **Speaker selection strategy** — Stage 11 의 `orchestrator` slot 에 "round robin / LLM-based selection / manual" 옵션
- **`register_reply` decorator** — agent 가 특정 메시지 패턴에 자동 응답. 우리 hook 시스템과 결합 가능

---

## 6. OpenAI Assistants API

**URL**: https://platform.openai.com/docs/assistants

### 우리에게 참조 가치

1. **Thread 개념** — 대화 context 를 assistant 와 분리 영속화. 우리 Geny `session_store` + `AgentSession` 조합과 유사
2. **File search (Retrieval)** — 첨부된 파일을 벡터화 후 자동 retrieve. 우리 MCP Resource + Stage 2 retriever 조합과 대응
3. **Code interpreter** — Python 샌드박스 tool. 우리 Bash / Write / Edit 조합으로 재현 가능
4. **Function calling JSON schema** — tool 정의의 표준 형식. 우리 `to_api_format()` 이 호환
5. **Run 상태** — queued / in_progress / requires_action / completed / failed / cancelled. Task FSM 의 참조

### 차별
- OpenAI Assistants 는 **블랙박스** — pipeline stage 제어 불가
- 제공 모델 사이 바인딩 — 우리는 multi-provider

### 채택 가능 아이디어
- **"requires_action" 상태** — Stage 10 의 permission ASK 상태와 일대일 대응. UI 가 "Assistant is waiting for your approval" 을 보여줄 때 유용
- **Thread-scoped file attachment** — 우리 `Geny/backend/static/uploads/` 와 session 연결 패턴 현재 있음. Thread 단위 index 도입 고려

---

## 7. CrewAI

**Repo**: https://github.com/crewAIInc/crewAI

### 우리에게 참조 가치

1. **Role-based agent** — `Agent(role="Senior Engineer", goal="...", backstory="...")`. 우리 `SessionRole` + Persona 와 유사 개념
2. **Crew** — 여러 agent 로 구성된 팀 + task 순서. Stage 11 multi-agent orchestration 참조
3. **Task 정의** — `Task(description, agent, expected_output)`. 선언적
4. **Hierarchical process** — manager agent 가 task 분배. AutoGen 과 유사

### 차별
- CrewAI 는 **role 이 강력** — agent 인격이 workflow 핵심
- 우리 Geny 도 VTuber role 은 강력하지만 worker/developer/researcher 는 기능적

### 채택 가능 아이디어
- **Crew = 복수 세션 orchestration layer** — 우리 ChatRoom + broadcast 는 이미 유사. 하지만 "이 task 는 developer 가 해결 후 결과를 reviewer 에게 전달" 같은 선언적 flow 는 부재
- **Backstory = expanded identity section** — prompt sections 에 persistent backstory 항목 고려

---

## 8. Haystack

**Repo**: https://github.com/deepset-ai/haystack

### 우리에게 참조 가치

1. **Pipeline as DAG** — nodes + edges. stage 기반이 아닌 DAG 기반
2. **Component 개념** — 각 노드가 `run(inputs) -> outputs` 인터페이스. 우리 Stage 와 유사
3. **Query preprocessing** — normalization, spell correction, expansion. Stage 1 Input normalizer 확장

### 차별
- Haystack 은 NLP 전용 (검색·질의·추출) — 범용 agent 아님

### 채택 가능 아이디어
- **Component validation at build time** — node 간 입출력 타입 매칭을 build 시 검증. 우리 Stage I/O 타입 체크 도입 시 참조

---

## 9. vercel/ai SDK

**Repo**: https://github.com/vercel/ai

### 우리에게 참조 가치

1. **Streaming 표준** — `streamText`, `streamObject` — SSE/stream 으로 토큰/객체 단위 emit. 우리 Stage 6 / Stage 9 streaming 확장 참조
2. **Tool call 파싱** — `generateObject` 가 Zod schema 로 structured output 강제
3. **Provider 추상** — Anthropic/OpenAI/Google/Mistral 일관 API. `BaseClient` 패턴 대응

### 차별
- vercel/ai 는 JavaScript/TS 생태계
- 프론트엔드 통합이 강점 — 우리는 backend pipeline 중심

### 채택 가능 아이디어
- **Token-level streaming events** — 10 design 의 Stage 6 "streaming granularity" 개선 직접 참조

---

## 10. ADK (Agent Development Kit) / OpenAI swarm

**Repo**: https://github.com/openai/swarm (experimental)

### 우리에게 참조 가치

1. **Agent handoff** — tool call 로 다른 agent 에게 제어권 넘김. 우리 Stage 11 delegate + Geny Sub-Worker pairing 의 단순화 형태
2. **Context variables** — 대화 전체에서 공유되는 가변 state. 우리 `state.shared` 대응

### 차별
- swarm 은 극히 minimal (50 KB 코드) — 의도적 단순함
- 우리는 production 용 복합 구조

### 채택 가능 아이디어
- **Handoff 함수를 tool 로 노출** — `handoff_to_expert(...)` 같은 메타 tool. Skill fork 와 비슷하지만 세션 전환.

---

## 11. Patterns summary (우리의 선별)

이 14 개 외부 프로젝트에서 **실제로 06–10 design 에 녹아들어간 구체 패턴**:

| 출처 | 패턴 | 적용 위치 |
|---|---|---|
| claude-code | Complete Tool contract | 06 |
| claude-code | Concurrency-safe partitioning | 06, 10 (Stage 10) |
| claude-code | Skill system (bundled + disk + MCP) | 08 |
| claude-code | Subprocess hook (JSON I/O) | 09 |
| claude-code | Permission matrix (source × pattern) | 09 |
| claude-code | Result persistence budget | 06 |
| claude-code | Streaming tool executor | 06 |
| claude-code | Subagent types + isolation | 10 (Stage 11) |
| LangChain | Callback handler 메서드 API | 09 (Event taxonomy convenience) |
| LangChain | `with_structured_output()` factory | 10 (Stage 3 + 9) |
| LangGraph | Checkpointer resume API | 10 (Stage 13) |
| LangGraph | Interrupt & resume | 10 (HITL) |
| LlamaIndex | Query rewriting / HyDE | 10 (Stage 2) |
| LlamaIndex | Response synthesizer multi-pass | 10 (Stage 9 → 15 통합) |
| AutoGen | Speaker selection strategy | 10 (Stage 11) |
| OpenAI Assistants | "requires_action" 상태 | 10 (Stage 10 permission ASK) |

---

## 12. 우리의 기여

반대로 **외부 프로젝트에 영향을 줄 수 있는 우리의 독창적 자산**:

1. **16-stage 고정 구조** — stage 별 책임 명확 + slot/chain 로 세밀한 확장
2. **4축 memory 모델** (Layer × Capability × Scope × Importance) — LangChain/LlamaIndex 보다 체계적
3. **Mutation audit log** — PipelineMutator 의 감사 추적성
4. **Environment manifest round-trip** — 파이프라인 포터블 + git-friendly
5. **Introspection API** — 런타임 구조 질의 (UI 자동 생성 기반)
6. **4-phase completeness marker** (pytest markers) — 완성도를 코드로 선언

이들은 **유지 + 강화** 가 원칙. claude-code / LangChain 을 따라가는 것이 아니라 **우리가 이미 더 나은 점** 을 인식하고 활용.
