# Claude Control Agent 고도화 마스터 플랜

> **목표**: OpenClaw의 프로덕션급 에이전트 실행 패턴을 참고하여,
> Claude CLI + LangGraph 기반의 Claude Control을 극한까지 고도화한다.

---

## 1. 현재 상태 vs 목표 상태 GAP 분석

### 1.1 핵심 GAP 매트릭스

| 영역 | 현재 Claude Control | OpenClaw 참고 수준 | GAP 심각도 |
|------|--------------------|--------------------|-----------|
| **시스템 프롬프트** | 5개 MD 파일 (15~150줄), 인라인 프롬프트 6개 | 25+ 섹션 모듈러 프롬프트, 프롬프트 모드, 훅 오버라이드 | 🔴 Critical |
| **실행 복원력** | 단일 시도, MemorySaver(휘발성) | 인증 로테이션, 컨텍스트 오버플로 컴팩션(3단계), 모델 폴백 | 🔴 Critical |
| **상태 관리** | MemorySaver(메모리), Redis(메타만) | 파일 기반 JSONL 트랜스크립트, 쓰기 잠금, 45s TTL 캐시 | 🟡 Major |
| **도구 정책** | 모든 도구 항상 활성 | 프로필 기반(minimal/coding/messaging/full), 소유자 전용, 그룹 확장 | 🟡 Major |
| **완료 감지** | 문자열 매칭 ("Task completed" 등) | SDK 레벨 turn 추적 + 구조적 완료 신호 | 🟡 Major |
| **컨텍스트 관리** | 없음 (CLI의 --resume에 의존) | 컨텍스트 윈도우 가드 (warn<32k, block<16k), 자동 컴팩션 | 🟡 Major |
| **세션 freshness** | 없음 | 채널별 자동 리셋 정책, freshness 평가 | 🟢 Minor |
| **스트리밍** | 의사 스트리밍 (100자 청크) | 실시간 이벤트 스트림 구독, 블록 리플라이 청킹 | 🟢 Minor |
| **서브에이전트** | Manager→Worker HTTP 자기 호출 | 게이트웨이 RPC, 깊이/자식 수 제한, 세션 키 격리 | 🟡 Major |

### 1.2 우리만의 차별점 (유지/강화)

Claude Control은 OpenClaw과는 근본적으로 다른 접근을 취한다:

| 특성 | Claude Control | OpenClaw |
|------|---------------|----------|
| **LLM 호출** | Claude CLI 서브프로세스 | 내장 SDK API |
| **상태 그래프** | LangGraph StateGraph | 없음 (while 루프) |
| **난이도 분류** | AutonomousGraph (EASY/MED/HARD) | 없음 |
| **자기 검토** | Review 루프 내장 | 없음 |
| **TODO 추적** | 구조적 TodoItem[] | 없음 |
| **멀티 팟** | Redis 기반 세션 라우팅 | 단일 인스턴스 |

**전략**: LangGraph 기반의 구조적 강점을 유지하면서, OpenClaw의 **프롬프트 설계**, **실행 복원력**, **도구 정책**, **컨텍스트 관리** 패턴을 흡수한다.

---

## 2. 개선 로드맵

### Phase 1: 시스템 프롬프트 고도화 (최우선)

현재 피상적인 role-based 프롬프트를 **OpenClaw의 25+ 섹션 모듈러 프롬프트** 수준으로 고도화.

#### TODO 1.1: 프롬프트 빌더 시스템 구축
- **파일**: `service/prompt/prompt_builder.py` (신규)
- **내용**:
  - `PromptSection` 데이터클래스 (name, content, condition, priority)
  - `PromptBuilder` 클래스 — 섹션별 조건부 조립
  - `PromptMode` enum (FULL / MINIMAL / NONE)
  - 빌더 패턴으로 섹션 추가/제거/오버라이드
  - 부트스트랩 파일 주입 (AGENTS.md, CLAUDE.md 등)

```python
# 목표 API:
builder = PromptBuilder(mode=PromptMode.FULL)
prompt = (builder
    .add_identity(agent_name="DevWorker", role=SessionRole.WORKER)
    .add_capabilities(tools=active_tools)
    .add_safety_guidelines()
    .add_workspace_context(working_dir="/project")
    .add_datetime()
    .add_execution_protocol(autonomous=True)
    .add_completion_protocol()
    .add_context_files(["AGENTS.md", "CLAUDE.md"])
    .add_runtime_line(model="claude-sonnet-4", session_id="abc")
    .build())
```

#### TODO 1.2: 역할별 프롬프트 심층 고도화
- **파일**: `prompts/` 디렉토리 전체 재설계
- 각 역할의 프롬프트를 **프롬프트 섹션 조합**으로 변환:
  - `developer.md` → Identity + Coding Guidelines + Safety + Tool Style
  - `worker.md` → Identity + Execution Protocol + Completion Protocol + Status Reporting
  - `self-manager.md` → Identity + CPEV Cycle + Milestone Tracking + Self-Sufficiency
  - `manager.md` → Identity + Delegation Protocol + Worker Management + Progress Tracking
  - `researcher.md` → Identity + Research Protocol + Citation + Synthesis
- 공통 섹션 추출 (Safety, DateTime, Workspace 등)

#### TODO 1.3: 실행 프로토콜 섹션 추가
- **핵심**: Claude CLI의 `--resume` 활용을 극대화하는 프롬프트 섹션
- **내용**:
  - 응답 종료 프로토콜 (`[CONTINUE: ...]` / `[TASK_COMPLETE]` 구조화)
  - Silent Reply 프로토콜 (불필요한 응답 방지)
  - 도구 사용 스타일 가이드 (도구 호출 시 설명/결과 형식)
  - 에러 자기 복구 프로토콜
  - 컨텍스트 효율성 가이드 (토큰 절약 패턴)

### Phase 2: 실행 엔진 복원력 강화

#### TODO 2.1: 모델 폴백 시스템
- **파일**: `service/langgraph/model_fallback.py` (신규)
- **내용**:
  - `ModelFallbackRunner` — 후보 모델 목록 순회
  - `FailoverError` 예외 클래스 (401, 403, 429, overloaded)
  - 모델 허용 목록 (allowlist) 지원
  - AbortError는 폴백 없이 즉시 전파

```python
class ModelFallbackRunner:
    async def run_with_fallback(self, fn, candidates, allowlist=None):
        for candidate in candidates:
            if allowlist and candidate not in allowlist:
                continue
            try:
                return await fn(candidate)
            except FailoverError:
                continue
            except AbortError:
                raise
        raise AllCandidatesFailedError(...)
```

#### TODO 2.2: 컨텍스트 오버플로 복구
- **파일**: `service/langgraph/context_guard.py` (신규)
- **내용**:
  - 컨텍스트 윈도우 크기 추적
  - 오버플로 감지 (에러 메시지 패턴 매칭)
  - 3단계 복구: 대화 요약 컴팩션 → 재 컴팩션 → 도구 결과 트렁케이션
  - `ContextWindowGuard` — warn/block 임계값

#### TODO 2.3: 향상된 재시도 루프
- **파일**: `service/langgraph/agent_session.py` 수정
- **내용**:
  - `_agent_node`에 재시도 래퍼 추가
  - 인증 오류 → 다른 API 키 시도 (env var 기반)
  - 타임아웃 → 지수 백오프 재시도
  - 컨텍스트 오버플로 → 컴팩션 후 재시도

### Phase 3: 도구 정책 시스템

#### TODO 3.1: 도구 정책 엔진
- **파일**: `service/tool_policy/policy.py` (신규)
- **내용**:
  - `ToolProfile` enum (MINIMAL / CODING / MESSAGING / FULL)
  - `ToolPolicyEngine` — 프로필 기반 허용 도구 집합 계산
  - 역할별 기본 프로필 매핑
  - 그룹 확장 (`group:fs`, `group:runtime` 등)
  - 세션별 오버라이드 지원

```python
class ToolPolicyEngine:
    def resolve_allowed_tools(
        self, role: SessionRole, profile: ToolProfile,
        custom_allow: List[str] = None, custom_deny: List[str] = None
    ) -> Set[str]:
        base = PROFILE_TOOLS[profile]
        result = base | set(custom_allow or [])
        result -= set(custom_deny or [])
        return result
```

#### TODO 3.2: MCP 설정 동적 필터링
- `MCPLoader`에 정책 기반 필터링 추가
- 역할에 따라 MCP 서버 부분 집합만 활성화

### Phase 4: 상태 관리 강화 (LangGraph 특화)

#### TODO 4.1: 영속 체크포인터
- MemorySaver → SqliteSaver 또는 Redis 기반 체크포인터로 교체
- 프로세스 크래시 후 그래프 상태 복원 가능

#### TODO 4.2: 세션 freshness 정책
- **파일**: `service/langgraph/session_freshness.py` (신규)
- 세션 만료 시간 설정 가능 (기본: 6시간)
- 만료 시 자동 리셋 또는 컴팩션

#### TODO 4.3: 향상된 완료 감지
- 문자열 매칭 → 구조적 완료 프로토콜
- `[TASK_COMPLETE]` 신호를 위 프롬프트와 연동
- LangGraph `is_complete` 상태를 CLI 출력에서 구조적으로 파싱

---

## 3. Phase 1 상세 실행 계획

### 3.1 프롬프트 빌더 구현

```
service/prompt/
├── __init__.py
├── builder.py          # PromptBuilder 메인 클래스
├── sections.py         # 모든 프롬프트 섹션 정의
├── protocols.py        # 실행/완료/에러 복구 프로토콜
└── context_loader.py   # 부트스트랩 파일 로더
```

### 3.2 섹션 목록 (OpenClaw 참고 + Claude Control 특화)

| # | 섹션 | 조건 | 설명 |
|---|------|------|------|
| 1 | Identity | 항상 | 에이전트 이름, 역할, 핵심 정체성 |
| 2 | Role Protocol | 역할별 | 역할별 행동 지침 (developer/worker/manager...) |
| 3 | Capabilities | 도구 활성 시 | 사용 가능한 도구 목록 및 사용법 |
| 4 | Tool Style | 도구 활성 시 | 도구 호출 형식, 결과 처리 가이드 |
| 5 | Safety | 항상 | 안전 가이드라인, 데이터 보호 |
| 6 | Execution Protocol | autonomous=True | CPEV 사이클, 자기 관리 프로토콜 |
| 7 | Completion Protocol | 항상 | [CONTINUE]/[TASK_COMPLETE] 신호 규약 |
| 8 | Workspace | working_dir 존재 시 | 작업 디렉토리 정보 |
| 9 | DateTime | 항상 | 현재 시각 (KST/UTC) |
| 10 | Error Recovery | autonomous=True | 에러 자기 복구 프로토콜 |
| 11 | Context Efficiency | 항상 | 토큰 효율적 응답 가이드 |
| 12 | Delegation | role=MANAGER | 위임 프로토콜, Worker 관리 규칙 |
| 13 | Status Reporting | role=WORKER | 진행 상태 보고 형식 |
| 14 | Bootstrap Context | 파일 존재 시 | AGENTS.md, CLAUDE.md 등 |
| 15 | Runtime Line | 항상 | 모델, 세션 ID, 시각 한 줄 메타 |

### 3.3 구현 우선순위

```
1. PromptBuilder + PromptSection 기본 골격    → builder.py
2. 15개 섹션 내용 작성                         → sections.py
3. 실행/완료 프로토콜 상세 작성                → protocols.py
4. 부트스트랩 파일 로더                        → context_loader.py
5. 기존 코드에 빌더 통합                       → agent_session.py, process_manager.py
6. 기존 prompts/*.md를 빌더 기반으로 마이그레이션
```

---

## 4. 예상 영향 분석

### 4.1 프롬프트 고도화 효과
- 에이전트 응답 품질 대폭 향상 (구조적 행동 프로토콜)
- 불필요한 질문/대기 완전 제거 (자기 관리 강화)
- 에러 자기 복구율 증가 (복구 프로토콜)
- 토큰 효율성 향상 (효율 가이드)

### 4.2 실행 복원력 효과
- 단일 실패 → 자동 복구 (모델 폴백, 컨텍스트 컴팩션)
- 장시간 작업의 안정성 대폭 향상
- API 키 만료/Rate Limit의 자동 우회

### 4.3 도구 정책 효과
- 보안 강화 (최소 권한 원칙)
- 역할별 적절한 도구 접근
- Manager가 파일 시스템 직접 접근 방지

---

## 5. Execution Log (updated)

### Completed Items
1. ✅ `service/prompt/` directory structure
2. ✅ `builder.py` — PromptBuilder core
3. ✅ `sections.py` — 15 prompt sections
4. ✅ `protocols.py` — Execution/completion/error recovery protocols
5. ✅ `context_loader.py` — Bootstrap file loader
6. ✅ Integration (`_build_system_prompt()` → `AgentSessionManager`)
7. ✅ Model fallback system (`service/langgraph/model_fallback.py`)
8. ✅ Context guard (`service/langgraph/context_guard.py`)
9. ✅ Enhanced completion detection (structured `CompletionSignal` enum)
10. ✅ Enhanced LangGraph State (`service/langgraph/state.py`)
    - Single source of truth for `AgentState` / `AutonomousState`
    - First-class fields: `iteration`, `max_iterations`, `completion_signal`, `completion_detail`, `context_budget`, `fallback`, `memory_refs`
    - Centralized enums: `CompletionSignal`, `Difficulty`, `ReviewResult`, `TodoStatus`, `ContextBudgetStatus`
    - Compound types: `TodoItem`, `MemoryRef`, `FallbackRecord`, `ContextBudget`
    - Custom reducers: `_add_messages`, `_merge_todos`, `_merge_memory_refs`
    - Helpers: `make_initial_agent_state()`, `make_initial_autonomous_state()`
11. ✅ Session Memory system (`service/memory/`)
    - `types.py` — `MemorySource`, `MemoryEntry`, `MemorySearchResult`, `MemoryStats`
    - `long_term.py` — `LongTermMemory` (MEMORY.md + dated + topic files, keyword+recency search)
    - `short_term.py` — `ShortTermMemory` (JSONL transcript + summary.md)
    - `manager.py` — `SessionMemoryManager` (unified facade, cross-store search, context injection, auto-flush)
12. ✅ Resilience graph nodes (`service/langgraph/resilience_nodes.py`)
    - `make_context_guard_node()` — context budget check node
    - `make_memory_inject_node()` — memory injection node
    - `make_transcript_record_node()` — post-LLM transcript recording
    - `completion_detect_node()` / `detect_completion_signal()` — structured completion parsing
13. ✅ Integrated `state.py` into `agent_session.py`
    - Removed inline `AgentState` / `add_messages` — now imports from `state.py`
    - Graph topology: `START → context_guard → agent → process_output → (continue|end)`
    - `_process_output_node` writes `iteration`, `completion_signal`, `completion_detail`
    - `_should_continue` reads structured `CompletionSignal` from state
    - Memory manager initialized on session init, records transcripts, flushes on cleanup
    - All docstrings/comments translated to English
14. ✅ Integrated `state.py` into `autonomous_graph.py`
    - Removed inline enums/types/reducers/state — imports from `state.py`
    - `get_initial_state()` → delegates to `make_initial_autonomous_state()`
    - All docstrings/comments translated to English
15. ✅ Updated `__init__.py` — exports `CompletionSignal` + re-routes imports to `state.py`
16. ✅ Memory context injection in `AgentSessionManager._build_system_prompt()`

### Remaining (Phase 3+)
- ⬜ Tool policy engine (profile-based tool filtering)
- ⬜ AutonomousGraph prompt externalization (move CLASSIFY_PROMPT etc. to sections.py)
- ⬜ Migrate `prompts/*.md` to builder-based system
- ⬜ Persistent checkpointer (SqliteSaver or Redis-backed)
- ⬜ Session freshness policy

### Phase 3 Completed Items (Session 3)

17. ✅ Tool Policy Engine (`service/tool_policy/`)
    - `policy.py` — `ToolProfile` enum (MINIMAL/CODING/MESSAGING/RESEARCH/FULL), server-group prefixes, `ROLE_DEFAULT_PROFILES` mapping
    - `ToolPolicyEngine` — factory `for_role()`, `filter_mcp_config()` (returns new MCPConfig with disallowed servers removed), `filter_tool_names()`, `is_server_allowed()`, `is_tool_allowed()`
    - `__init__.py` — exports `ToolProfile`, `ToolPolicyEngine`, `ROLE_DEFAULT_PROFILES`
    - Integrated into `AgentSessionManager._build_system_prompt()` — filters MCP servers before prompt building
    - Integrated into `AgentSessionManager.create_agent_session()` — filters MCP config before passing to AgentSession

18. ✅ AutonomousGraph prompt externalization
    - `AutonomousPrompts` class added to `service/prompt/sections.py` with 7 static methods:
      `classify_difficulty()`, `review()`, `create_todos()`, `execute_todo()`, `final_review()`, `final_answer()`, `retry_with_feedback()`
    - All 6 class-attribute prompts + 1 inline f-string removed from `autonomous_graph.py`
    - All usage sites updated to `AutonomousPrompts.xxx().format(...)`

19. ✅ Migrate `prompts/*.md` to builder-based system
    - `service/prompt/template_loader.py` — `PromptTemplateLoader` class: reads role-specific `.md` files from `prompts/` at build time, caches content, maps role → filename
    - Integrated into `build_agent_prompt()` — when a role's `.md` template exists, it overrides the hardcoded `role_protocol` section via `builder.override_section()`
    - All Korean docstrings in `build_agent_prompt()` translated to English

20. ✅ Persistent checkpointer (`service/langgraph/checkpointer.py`)
    - `create_checkpointer(storage_path, persistent, db_name)` factory function
    - Attempts `SqliteSaver` (from `langgraph-checkpoint-sqlite`) backed by `.db` file in session storage dir
    - Falls back to `MemorySaver` if sqlite package not installed or path not writable
    - Integrated into `agent_session.py` `_build_graph()` — replaces direct `MemorySaver()` call
    - Integrated into `autonomous_graph.py` `build()` — accepts `storage_path` parameter, uses factory
    - Exported from `__init__.py`

21. ✅ Session freshness policy (`service/langgraph/session_freshness.py`)
    - `FreshnessConfig` — configurable thresholds: max age (4h), warn age (2h), max idle (1h), warn idle (30m), max iterations (200), compact after messages (80), warn after iterations (100)
    - `FreshnessStatus` enum — FRESH / STALE_WARN / STALE_COMPACT / STALE_RESET, with `.should_compact`, `.should_reset`, `.is_fresh` properties
    - `FreshnessResult` — evaluation result dataclass
    - `SessionFreshness` — evaluator, checks age → idle → iterations → messages in severity order
    - Integrated into `AgentSession`: `_freshness` attribute instantiated at init, `_check_freshness()` called at start of `invoke()` and `astream()`, raises `RuntimeError` on STALE_RESET

### Remaining (Phase 4+)
- ⬜ Sub-agent depth/concurrency limits (gateway RPC pattern)
- ⬜ Real-time event stream subscription (replace pseudo-streaming)
- ⬜ Context compaction trigger from freshness STALE_COMPACT signal
- ⬜ Redis-backed persistent checkpointer option
- ⬜ Tool permission enforcement at MCP level (beyond prompt-level filtering)
