# 12. Detailed Implementation Plan — 통합 구현 manual

**Status:** Draft
**Date:** 2026-04-24
**Horizon:** 12–16 주 집중 작업 (solo) / 6–9 주 (2 인 병렬)

이 문서는 **설계 문서 01–10 의 결정을 실행으로 옮기는 manual**. 11 roadmap 이 "phase 단위 개요" 라면 이 문서는 **주차별 schedule · PR skeleton · 코드 scaffolding · 검증 매트릭스 · 운영 체크리스트** 까지 내려간 실행 지침.

---

## 0. 전체 지도

### 0.1 최종 상태 — 21-stage 레이아웃

```
Phase A ─┐   Phase B (Loop: 2 ↔ 16)                Phase C
Ingress   │                                         Finalize
          ▼                                           ▼
[1 Input][2 Context][3 System][4 Guard][5 Cache][6 API][7 Token]
          [8 Think][9 Parse][10 Tool][★11 Tool Review]
          [12 Agent][★13 Task Registry][14 Evaluate][★15 HITL]
          [16 Loop]  ← Loop 결정
                                  Phase C ─▶ [17 Emit][18 Memory]
                                             [★19 Summarize][★20 Persist][21 Yield]

★ = 이번 cycle 신설 (Phase 9)
```

### 0.2 실행 Phase 매핑

| # | Phase | executor 주차 | Geny 주차 | 주 산출물 |
|---|---|---|---|---|
| 1 | Foundation (Tool ABC · Permission · Events) | 주 1–3 | 주 2–3 | `0.32.0` |
| 2 | Orchestration (Stage 10) | 주 3–4 | 주 4 | `0.33.0` |
| 3 | Built-in catalog (15–20 종) | 주 4–7 | 주 5–7 | `0.34.0` |
| 4 | Skills | 주 7–9 | 주 8–9 | `0.35.0` |
| 5 | Hooks | 주 9–10 | 주 10 | `0.36.0` |
| 6 | MCP uplift | 주 10–12 | 주 11–12 | `0.37.0` |
| 7 | Stage enhancements | 주 11–14 | 주 12–14 | `0.38.x` |
| 8 | MCP advanced | 주 13–14 | 주 14 | `0.39.0` |
| 9 | **21-stage 재구성** | 주 14–17 | 주 15–17 | `1.0.0` |
| 10 | Observability (선택) | 주 17+ | 주 18+ | `1.1.x` |

**주차 = 5 일 집중 작업 기준**. Phase 7 과 Phase 5/6 은 병렬 가능 (서로 다른 stage 건드림).

### 0.3 릴리스 calendar (예시)

```
Month 1 (주 1–4)  : 0.32.0 · 0.33.0 — Tool ABC + Orchestration
Month 2 (주 5–8)  : 0.34.0 · 0.35.0 — Built-in catalog + Skills
Month 3 (주 9–12) : 0.36.0 · 0.37.0 — Hooks + MCP
Month 4 (주 13–16): 0.38.x · 0.39.0 · 1.0.0 — Stage 개선 + MCP advanced + 21-stage
Month 4+          : 1.1.x — Observability (선택)
```

Geny 의 pin 업데이트는 각 executor 릴리스에서 PyPI publish 직후 자동 트리거. PR 은 별도 branch 에서 CI 통과 후 즉시 머지.

---

## 1. Phase 1 — Foundation (주 1–3)

### 1.1 목표 재확인
Tool ABC · Permission matrix · Event taxonomy. 이 3 개가 Phase 2–9 의 **선결 조건** 이라 가장 먼저.

### 1.2 주차별 breakdown

#### Week 1 — Tool ABC 뼈대
- **E-1.1–1.3** (executor)
  - `geny_executor/tools/base.py` 에 새 Tool ABC · ToolCapabilities · ToolContext · ToolResult · PermissionDecision dataclass
  - `build_tool()` factory
  - `LegacyToolAdapter` (기존 BaseTool 호환)
- **수동 smoke 테스트**: `Read` / `Bash` 2 개를 새 ABC 로 작성해 `run()` 까지 돌아가는지

#### Week 2 — Permission + Event
- **E-1.5–1.7**
  - `geny_executor/permission/types.py` — PermissionRule / Mode / evaluate_permission
  - `geny_executor/permission/loader.py` — YAML 로더
  - `geny_executor/events/hook_event.py` — HookEvent enum + dataclass
  - `geny_executor/core/shared_keys.py` — SharedKeys namespace + SharedDict TypedDict
- **G-1.5–1.6** (Geny)
  - Permission YAML 예시 (`.geny/permissions.yaml`) + 기본 rule set
  - CLI/env flag `GENY_PERMISSION_MODE`

#### Week 3 — Stage 10 준비 + 릴리스
- **E-1.4**: Stage 10 에 "tool 이 new Tool ABC 면 새 경로, legacy 면 adapter 로" 분기
- **E-1.8**: `0.32.0` PyPI publish + CHANGELOG
- **G-1.1–1.4**:
  - `requirements.txt` `geny-executor >=0.32.0,<0.33.0`
  - `_GenyToolAdapter` 를 `LegacyToolAdapter` 위에서 재구성
  - `BaseTool._capabilities` optional 속성 지원
  - Read-like / Bash-like / Write-like 3 개 tool 에 capability 선언

### 1.3 Code scaffolding — Tool ABC 핵심 (단축)

```python
# geny_executor/tools/base.py (Phase 1 W1 작업물)

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Callable, Generic, TypeVar

T_Input  = TypeVar("T_Input")
T_Output = TypeVar("T_Output")
T_Progress = TypeVar("T_Progress")

@dataclass(frozen=True)
class ToolCapabilities:
    concurrency_safe: bool = False
    read_only:        bool = False
    destructive:      bool = False
    idempotent:       bool = False
    network_egress:   bool = False
    interrupt:        str  = "block"
    max_result_chars: int  = 100_000

@dataclass(frozen=True)
class PermissionDecision:
    behavior: str                      # allow | deny | ask
    updated_input: Optional[dict] = None
    reason: Optional[str] = None

@dataclass
class ToolContext:
    session_id:   str
    working_dir:  Optional[str] = None
    storage_path: Optional[str] = None
    state_view:   Optional[Any] = None
    event_emit:   Optional[Callable[[str, dict], None]] = None
    permission_mode: str = "default"
    parent_tool_use_id: Optional[str] = None
    extras: dict = field(default_factory=dict)

@dataclass
class ToolResult(Generic[T_Output]):
    data: T_Output
    new_messages: list = field(default_factory=list)
    state_mutations: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)
    display_text: Optional[str] = None
    persist_full: Optional[str] = None
    is_error: bool = False
    mcp_meta: Optional[dict] = None

class Tool(ABC, Generic[T_Input, T_Output, T_Progress]):
    name: str
    description: str
    aliases: tuple[str, ...] = ()

    @abstractmethod
    def input_schema(self) -> dict: ...
    def output_schema(self) -> Optional[dict]: return None
    def validate_input(self, raw: dict) -> dict: return raw

    def capabilities(self, input: dict) -> ToolCapabilities:
        return ToolCapabilities()

    async def check_permissions(self, input: dict, ctx: ToolContext) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def prepare_permission_matcher(self, input: dict):
        return lambda pattern: pattern == self.name

    @abstractmethod
    async def execute(self, input, ctx, *, on_progress=None) -> ToolResult: ...

    async def on_enter(self, input, ctx) -> None: ...
    async def on_exit(self, result, ctx) -> None: ...
    async def on_error(self, error, ctx) -> None: ...

    def user_facing_name(self, input) -> str: return self.name
    def activity_description(self, input) -> Optional[str]: return None

    is_mcp: bool = False
    mcp_info: Optional[dict] = None

    def is_enabled(self) -> bool: return True

    def to_api_format(self) -> dict:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema()}
```

### 1.4 검증 매트릭스

| 항목 | pass 조건 |
|---|---|
| New Tool ABC import | `from geny_executor.tools import Tool, ToolCapabilities, build_tool` 성공 |
| LegacyToolAdapter | 기존 BaseTool 하나를 `LegacyToolAdapter(tool)` 로 감싸 `.execute(...)` 호출 → 기존 동작 |
| Permission rule parse | `.geny/permissions.yaml` load → `list[PermissionRule]` |
| Event taxonomy | `HookEvent.PRE_TOOL_USE` 등 enum 값 접근 가능 |
| PyPI 0.32.0 | `pip install geny-executor==0.32.0` 성공 |
| Geny pin | Geny CI green with `>=0.32.0,<0.33.0` |

---

## 2. Phase 2 — Orchestration (주 3–4)

### 2.1 주차별

#### Week 3 (overlap with Phase 1 W3) — Partition orchestrator
- **E-2.1**: `partition_tool_calls()` + `orchestrate_tools()`
- **E-2.2**: Stage 10 에 새 artifact `partition_orchestrator/`

#### Week 4 — Streaming + persistence
- **E-2.3**: `StreamingToolExecutor` (수신 순 emit)
- **E-2.4**: `_persist_large_result` — storage_path 하위 `tool-results/{call_id}.json`
- **E-2.5**: Tool lifecycle hooks 호출 경로
- **E-2.6**: `max_concurrent` ConfigSchema
- **E-2.7**: `0.33.0` publish

#### Week 4 Geny
- **G-2.1–2.4**: pin 업데이트 + Read/Grep/Glob 에 `concurrency_safe=True`

### 2.2 검증

- 3 개 read-only tool 을 동시 호출 → 로그에 병렬 실행 확인
- 10,000 line grep 결과 → `tool-results/{id}.json` 저장 + summary 만 LLM 전달

---

## 3. Phase 3 — Built-in Tool Catalog (주 4–7)

### 3.1 주차별

#### Week 4–5 — Web 계열 + 재구성
- 디렉토리 재구성 (`built_in/filesystem/`, `shell/`, `web/`, ...)
- `WebFetch` (httpx + markdownify) + `WebSearch` (DDG backend)
- `get_builtin_tools(features=...)` + feature-flag

#### Week 5–6 — Agent / Skill / Task
- `AgentTool` (inline mode 먼저, isolation worktree 는 Phase 7 로)
- `SkillTool` 기본 구현 (Phase 4 에서 완성)
- `TaskCreate / Get / List / Update / Stop / Output` 6 종

#### Week 6 — Workflow / Notebook / Meta
- `TodoWrite`, `NotebookEdit`
- `Schedule` / `CronCreate` / `CronList` / `CronDelete` (APScheduler backend)
- `Monitor`, `ToolSearch`
- `EnterPlanMode` / `ExitPlanMode` / `EnterWorktree` / `ExitWorktree`

#### Week 7 — Provider Protocol + 릴리스
- `ToolProvider` Protocol + `Pipeline.from_manifest_async(tool_providers=[...])`
- `0.34.0` publish
- 문서: built-in tool authoring 가이드

#### Week 5–7 Geny (병렬)
- `GenyPlatformToolProvider` 신설
- 기존 custom web_search/web_fetch/browser tool **제거** (executor 대응품으로 대체)
- 플랫폼 특화 tool (feed/play/gift/talk/knowledge_tools/memory_tools) 을 새 Tool ABC 로 재작성

### 3.2 검증

- `len(get_builtin_tools())` ≥ 15
- `GenyPlatformToolProvider.list_tools()` ≤ 10
- Web 관련 Geny custom 파일 제거 확인 (`grep -r "web_search_tools" backend/` empty)

---

## 4. Phase 4 — Skills System (주 7–9)

### 4.1 주차별

#### Week 7 — 뼈대
- Skill / SkillMetadata / SkillRegistry / SkillContext 타입
- `register_bundled_skill` + 전역 레지스트리
- Frontmatter parser + `load_skills_dir`

#### Week 8 — Integration
- `SkillTool` 완성 (Phase 3 에서 stub 있던 것)
- Stage 3 `SkillCatalogSection`
- Stage 11(→12) — Skill fork 경로 (sub-pipeline spawn)
- 번들 skill 3 개: `summarize-session`, `search-web-and-summarize`, `draft-pr`

#### Week 9 — Geny integration + 릴리스
- `AgentSession` 에 SkillRegistry 주입
- 사용자/프로젝트 skill 디렉토리 로드
- Slash command 파싱 → SkillTool 호출
- Skill 관리 API (`/api/skills/list`)
- `0.35.0` publish

### 4.2 검증

- `~/.geny/skills/test.md` 추가 후 다음 세션에서 `/test` 동작
- `SkillTool(skill="summarize-session")` LLM 자동 호출 성공
- `context: fork` skill 이 제한된 tool 집합으로 sub-pipeline 실행

---

## 5. Phase 5 — Hooks (주 9–10)

### 5.1 주차별

#### Week 9 (overlap) — HookRunner
- `HookRunner` + `HookOutcome` + subprocess 프로토콜
- Stage 4 `HookGateGuard`
- Stage 10 `PreToolUse` / `PostToolUse` fire

#### Week 10 — Config + 릴리스
- `load_hooks_config` YAML 로더 + 기본 disabled
- Hook audit log
- Geny: `GENY_ALLOW_HOOKS=1` opt-in + 예제 스크립트 3 종
- `0.36.0` publish

### 5.2 검증

- `GENY_ALLOW_HOOKS=1` + Bash 실행 전 `pre_check.sh` 호출
- Hook `{"continue": false}` 반환 시 tool 실행 block
- Timeout 시 fail-open + 로그

---

## 6. Phase 6 — MCP Uplift (주 10–12)

### 6.1 주차별

#### Week 10–11 — Transport + FSM
- `MCPTransport` ABC + stdio/http/sse 재구성
- WebSocket / SDK-managed transport
- `MCPConnection` FSM (5 상태)

#### Week 11–12 — Manager + Runtime
- `MCPManager.register_server / unregister_server / disable / enable`
- MCP annotation → ToolCapabilities 자동 매핑
- `attach_runtime(mcp_manager=...)` kwarg

#### Week 12 — Geny + 릴리스
- `MCPLoader.build_manager` 신설
- Runtime MCP admin API (`POST /api/mcp/servers`)
- Frontend: MCP 서버 상태 리스트
- `0.37.0` publish

### 6.2 검증

- `POST /api/mcp/servers {name, config}` → 해당 세션 다음 턴부터 tool 보임
- 서버 연결 실패 시 해당 tool 만 invisible, 다른 서버에 영향 없음
- `mcp.server.state` 이벤트가 UI 에 흐름

---

## 7. Phase 7 — Stage Enhancements (주 11–14)

10 design §1–12 의 stage 별 개선을 **병렬** 작업으로 진행. 각 PR 은 독립이라 phase 안에서 순서 자유.

### 7.1 Sprint 매핑 (제안)

| Sprint | 대상 Stage | 주요 변경 |
|---|---|---|
| S7.1 | Stage 3 System | PersonaSection executor 내장 |
| S7.2 | Stage 2 Context | MCPResourceRetriever (Phase 6 의존) |
| S7.3 | Stage 9 Parse | Structured output schema contract |
| S7.4 | Stage 4 Guard | PermissionRuleMatrixGuard (Phase 1 의존) |
| S7.5 | Stage 11 Agent | SubagentTypeOrchestrator (Skill fork 공용) |
| S7.6 | Stage 12 Evaluate | Evaluator chain |
| S7.7 | Stage 13 Loop | Multi-dimensional budget |
| S7.8 | Stage 6 API | Adaptive model router |
| S7.9 | Stage 15 Memory | Structured reflection schema |
| S7.10 | Stage 8 Think | Adaptive thinking budget |
| S7.11 | Stage 14 Emit | Emitter ordering + backpressure |
| S7.12 | Stage 16 Yield | Multi-format yield |

### 7.2 릴리스 정책

Sprint 2–4 개마다 하나의 minor 릴리스 (`0.38.0 → 0.38.1 → 0.38.2 ...`). Geny 는 안정 빌드에만 pin 업데이트.

---

## 8. Phase 8 — MCP Advanced (주 13–14)

- `OAuthFlow` (callback port + state)
- Keychain credential 저장
- `MCPResource` + `mcp://` URI
- `mcp_prompts_to_skills` bridge
- `0.39.0` publish

### 8.1 검증

- Google Drive MCP 연결 시 브라우저 consent → 성공
- MCP prompt → SkillRegistry 자동 등록

---

## 9. Phase 9 — 21-stage 재구성 (주 14–17) — **이번 uplift 의 핵심**

이 phase 는 가장 큰 구조 변경. **2 sub-phase** 로 분할하여 rollback 가능성 확보.

### 9.1 Sub-phase 9a — Scaffolding + Rename (주 14–15)

목적: **no-op** 으로 21 stage 뼈대만 세움. 기존 동작 완전히 유지.

#### Week 14

**Day 1–2: 기존 stage rename (git mv)**
```bash
git mv src/geny_executor/stages/s11_agent     src/geny_executor/stages/s12_agent
git mv src/geny_executor/stages/s12_evaluate  src/geny_executor/stages/s14_evaluate
git mv src/geny_executor/stages/s13_loop      src/geny_executor/stages/s16_loop
git mv src/geny_executor/stages/s14_emit      src/geny_executor/stages/s17_emit
git mv src/geny_executor/stages/s15_memory    src/geny_executor/stages/s18_memory
git mv src/geny_executor/stages/s16_yield     src/geny_executor/stages/s21_yield
```

+ import 일괄 치환 (grep + sed):
```bash
grep -rln "from geny_executor.stages.s11_agent"     | xargs sed -i 's|s11_agent|s12_agent|g'
# ... (6 stage 모두 동일 패턴)
```

**Day 3: 빈 stage 디렉토리 scaffolding**
- `stages/s11_tool_review/` — pass-through 기본 artifact
- `stages/s13_task_registry/` — pass-through 기본 artifact
- `stages/s15_hitl/` — bypass 기본 artifact
- `stages/s19_summarize/` — no-op 기본 artifact
- `stages/s20_persist/` — NoPersistStrategy 기본

각 scaffolding 은:
```python
# stages/s11_tool_review/__init__.py
from .artifact.default.stage import ToolReviewStage
__all__ = ["ToolReviewStage"]

# stages/s11_tool_review/artifact/default/stage.py
from geny_executor.core.stage import Stage
class ToolReviewStage(Stage):
    name = "tool_review"
    order = 11
    category = "review"
    async def execute(self, input, state):
        # Sub-phase 9a: pass-through no-op
        return input
```

**Day 4–5: pipeline.py + introspection 업데이트**
- `LOOP_END = 16`, `FINALIZE_START = 17`, `FINALIZE_END = 21`
- `_run_phases` loop body 범위 조정
- `_STAGE_CAPABILITY_MATRIX` 에 5 신규 entry 추가
- `introspect_all()` 결과가 21 개

#### Week 15

**Day 1–3: Manifest v2 → v3 migration**
- Loader 에서 v2 감지: stage 배열 길이 16 이고 version 필드 없거나 "2"
- v3 변환: 누락된 5 stage 를 default pass-through artifact 로 채움
- 저장 시 v3 로만 저장 (v2 backward write 없음)

**Day 4: 기본 preset 재생성**
- `vtuber`, `worker_adaptive`, `worker_easy`, `default` — 4 종 preset 의 stage 배열에 5 신규 stage default 추가
- 생성 스크립트 `scripts/regen_presets.py` + CI 에 포함

**Day 5: 9a 단위 테스트**
- v2 preset load → v3 로 migrate → run → v2 와 동일 결과
- Introspection 이 21 개 보고
- 모든 rename 된 stage import 정상

### 9.2 Sub-phase 9b — 실제 Stage 구현 (주 15–17)

각 stage 를 독립 PR 로 구현. 하나라도 동작 이슈 시 그 stage 만 revert.

#### Week 15 — Stage 11 Tool Review

**Artifact 구조:**
```
stages/s11_tool_review/artifact/default/
├── stage.py            # ToolReviewStage
├── reviewers/
│   ├── __init__.py
│   ├── schema.py       # SchemaReviewer
│   ├── sensitive.py    # SensitivePatternReviewer
│   ├── destructive.py  # DestructiveResultReviewer
│   ├── network.py      # NetworkAuditReviewer
│   └── size.py         # SizeReviewer
└── chain.py            # SlotChain 설정
```

**기본 체인:** Schema → Sensitive → Destructive → Network → Size (순서대로).

**출력:**
```python
state.tool_review_flags: list[dict] = [
    {"tool_call_id": "...", "severity": "warn|error", "reviewer": "sensitive", "reason": "..."},
    ...
]
```

**Stage 14 (Evaluate) 가 severity="error" 플래그 있으면 escalate 로 loop 종료.**

#### Week 15–16 — Stage 13 Task Registry

**Artifact:**
```
stages/s13_task_registry/artifact/default/
├── stage.py
├── registry/
│   ├── __init__.py
│   ├── base.py         # Registry ABC
│   ├── in_memory.py    # InMemoryRegistry
│   └── types.py        # TaskRecord, TaskStatus
└── policy/
    ├── __init__.py
    ├── eager_wait.py
    ├── fire_and_forget.py
    └── timed_wait.py
```

**Stage 12 (Agent) 가 task spawn 시 `state.tasks_new_this_turn` 에 추가.
Stage 13 이 이를 받아 registry 에 등록하고 `state.tasks_by_status` 갱신.
이전 iteration 의 완료된 task 는 Stage 2 (Context) 가 context 로 주입.**

#### Week 16 — Stage 15 HITL

**Artifact:**
```
stages/s15_hitl/artifact/default/
├── stage.py
├── requester/
│   ├── __init__.py
│   ├── null.py         # NullRequester (bypass)
│   └── ui.py           # UIRequester (WebSocket — Phase 9 Geny 몫)
├── timeout/
│   ├── __init__.py
│   ├── indefinite.py
│   ├── auto_approve.py
│   └── auto_reject.py
└── resume.py           # resume_token 생성/조회
```

**Pipeline 에 `resume(token, decision)` API 추가:**
```python
# core/pipeline.py
class Pipeline:
    async def resume(self, token: str, decision: HITLDecision) -> PipelineResult:
        # 대기 중인 _pending_hitl dict 에서 token 으로 조회
        # decision 을 state 에 반영 후 다음 stage 부터 재개
        ...
```

**Stage 15 가 request 설정되면 await 로 대기 (with timeout).
resume API 가 호출되면 대기 해제 + 다음 stage 로.**

#### Week 16 — Stage 19 Summarize

**Artifact:**
```
stages/s19_summarize/artifact/default/
├── stage.py
├── summarizer/
│   ├── __init__.py
│   ├── no_summary.py
│   ├── rule_based.py
│   ├── llm.py          # Haiku override 로 실행
│   └── hybrid.py
└── importance/
    ├── __init__.py
    ├── fixed.py
    ├── heuristic.py
    └── llm.py
```

**출력:**
```python
state.turn_summary = SummaryRecord(
    turn_id="...",
    abstract="...",         # ~3 sentences
    key_facts=[...],
    entities=[...],
    tags=[...],
    importance=Importance.MEDIUM,
)
```

**`state.memory_provider` 존재 시 자동 `provider.record_summary(...)`.**

#### Week 17 — Stage 20 Persist

**Artifact:**
```
stages/s20_persist/artifact/default/
├── stage.py
├── persister/
│   ├── __init__.py
│   ├── no_persist.py
│   ├── file.py
│   ├── postgres.py     # Geny 측 구현
│   └── redis.py
└── frequency/
    ├── __init__.py
    ├── every_turn.py
    ├── every_n_turns.py
    └── on_significant.py
```

**`Pipeline.resume_from_checkpoint(checkpoint_id) → Pipeline` API 추가.
state 의 messages, tasks, memory_refs, turn_summary, llm_client ref (not pickled), tool_context 등을 직렬화.**

#### Week 17 — 통합 검증 + 릴리스

- End-to-end 테스트: v2 preset 로딩 → 21-stage 실행 → 동일 출력
- Crash recovery: SIGKILL 후 `Pipeline.resume_from_checkpoint` 로 복구
- HITL: CLI subscriber 로 approval 받고 resume 성공
- 문서 sync: 02 의 16-stage → "legacy v2" 표기, 새 21-stage 섹션 추가
- Geny: `PostgresRegistry`, `UIRequester`, `PostgresPersistStrategy` 구현 + pin `>=1.0.0,<2.0.0`
- `1.0.0` PyPI publish + CHANGELOG major entry

### 9.3 Phase 9 검증 매트릭스

| 항목 | pass 조건 |
|---|---|
| v2 round-trip | v2 preset load → run → v3 save → reload → v2 와 동일 결과 |
| Stage 11 review | Sensitive API key 패턴이 포함된 tool 결과 → `state.tool_review_flags` 에 severity="error" |
| Stage 13 registry | AgentTool 이 spawn 한 task 가 `state.tasks_by_status["running"]` 에 등록, 완료 시 `"completed"` 로 이동 |
| Stage 15 HITL | CLI subscriber 가 approval 대기 → resume API → 다음 stage 진행 |
| Stage 19 summary | `state.turn_summary` 에 SummaryRecord, `memory_provider` 에 record_summary 호출 |
| Stage 20 persist | SIGKILL 후 `Pipeline.resume_from_checkpoint(id)` → state 복원 |
| Introspection count | `len(introspect_all()) == 21` |
| Event count | 21 stage × {enter, exit} = 42 + 신규 이벤트 (task.registered, hitl.request, summary.written, checkpoint.written) |
| Geny regression | 기존 VTuber / worker 세션 동일 응답 (300 seed 비교) |

### 9.4 Rollback 전략

| 실패 지점 | Rollback 동작 |
|---|---|
| Sub-phase 9a 중 | git revert — rename 과 scaffolding 은 모두 atomic (노-op) |
| Sub-phase 9b 개별 stage 구현 | 해당 stage 만 pass-through artifact 로 전환 (config 수정) — 전체 revert 불필요 |
| Manifest migration 실패 | load 에서 v2 를 거부 대신 error surfacing → Geny 가 사용자에게 안내 |

---

## 10. Phase 10 — Observability (주 17+, 선택)

11 roadmap 참조. 우선순위 P3 — uplift 핵심 완료 후 진행.

- Event stream WebSocket
- Stage 그리드 시각화
- Tool 타임라인
- Token / cost 실시간
- Mutation audit log

---

## 11. 전체 PR 수 예상

| Phase | executor PR | Geny PR | 합계 |
|---|---|---|---|
| 1 | 8 | 6 | 14 |
| 2 | 7 | 4 | 11 |
| 3 | 17 | 7 | 24 |
| 4 | 7 | 5 | 12 |
| 5 | 5 | 3 | 8 |
| 6 | 6 | 4 | 10 |
| 7 | 12 | 6 | 18 |
| 8 | 4 | 1 | 5 |
| 9 | 15 | 10 | 25 |
| **합계** | **81** | **46** | **127** |

127 PR = 12–16 주 기준 일일 평균 1 PR. 병렬 작업 시 2 PR/일 가능.

---

## 12. 인원 배치 시나리오

### 12.1 Solo (1 인)
- 직렬 진행 — 12–16 주
- Week 11–14 은 Phase 6 / 7 이 많이 겹침 → 주의 집중

### 12.2 Pair (2 인)
- **Person A**: Phase 1 → 2 → 3 → 5 (executor + orchestration 중심)
- **Person B**: Phase 4 Skills 병행 + Phase 6 MCP + Phase 7 Geny-side + Phase 8
- 둘이 Phase 9 합류 — 6–9 주 완료 가능

### 12.3 Team (3 인 이상)
- 추가 인력은 Phase 7 Stage Enhancement sprint 병렬화 + Phase 3 Built-in catalog tool 병렬 구현
- 5–7 주 완료 가능

---

## 13. Anti-pattern 경고

### 13.1 하지 말 것

1. **Phase 순서 건너뛰기** — Phase 3 built-in catalog 이 Phase 4 Skills 이전 완료되어야 SkillTool 의 AgentTool 의존성 해결
2. **Stage 번호 변경을 부분 적용** — 어떤 stage 는 16, 어떤 stage 는 21 이면 manifest migration 이 깨짐. Phase 9 전체 완료 후에만 v3 저장
3. **Executor 릴리스 없이 Geny PR 머지** — Geny 가 새 API 를 써도 PyPI 미배포 상태면 CI 실패
4. **Legacy tool 즉시 삭제** — `LegacyToolAdapter` 로 2 릴리스 유예 후 제거. deprecated warning 반드시 먼저
5. **HITL 기본값을 blocking 으로** — `NullRequester` 기본이 bypass 인지 확인 (기존 세션이 모두 대기 걸림)

### 13.2 자주 발생할 실수

1. Tool ABC 마이그레이션 중 `capabilities()` 기본값이 opt-in 이 아닌 fail-open 으로 설정됨 → concurrency 버그
2. Stage 10 Result persistence 가 session storage_path 없이 시도 → fallback 필요
3. Skill frontmatter 의 `allowed_tools` 에 존재하지 않는 tool 이름 → 실행 시 silent fail 대신 parse 시 validate
4. MCP 서버 FSM 에서 NEEDS_AUTH 상태가 무한 반복 (재시도 중 OAuth) → exponential backoff
5. Stage 19 Summarize LLM 호출이 메인 session 의 cost budget 에 합산되지 않음 → `state.total_cost_usd` 업데이트 필수
6. Stage 20 Persist frequency 가 EveryTurn 이면 I/O 과부하 → 기본 OnSignificantChange 로

---

## 14. 체크포인트 — 매주 진행 점검

| 주차 | 예상 완료 상태 |
|---|---|
| W1 끝 | Tool ABC 타입 import 가능, LegacyToolAdapter 동작 |
| W2 끝 | Permission YAML 파싱, HookEvent enum |
| W3 끝 | `0.32.0` published, Geny pin 업데이트 |
| W4 끝 | `0.33.0` published, 병렬 tool 실행 확인 |
| W5 끝 | 5+ built-in tool (web/agent) 동작 |
| W6 끝 | 10+ built-in tool, Task 계열 완성 |
| W7 끝 | `0.34.0` published, built-in 15 종 |
| W8 끝 | Skill system 동작, 번들 skill 3 개 |
| W9 끝 | `0.35.0` + Hooks 구현 시작 |
| W10 끝 | `0.36.0`, MCP transport 확장 |
| W11 끝 | MCP FSM + runtime add/remove |
| W12 끝 | `0.37.0`, Stage enhancement sprint 시작 |
| W13 끝 | 6+ stage enhancement 완료 |
| W14 끝 | `0.38.x` + `0.39.0`, Phase 9 scaffolding 시작 |
| W15 끝 | Sub-phase 9a 완료 (no-op 21-stage 동작) |
| W16 끝 | Tool Review + Task Registry + HITL 구현 |
| W17 끝 | `1.0.0` published, uplift 완료 |

---

## 15. 완료 정의 (최종)

- [ ] geny-executor `1.0.0` PyPI 배포
- [ ] 21 stage 모두 기능 구현 (no-op 아님)
- [ ] Geny 가 `>=1.0.0,<2.0.0` pin 으로 production 운영
- [ ] 기존 모든 세션 유형 (VTuber / worker / developer / researcher) regression 0
- [ ] 번들 skill 3+ 동작, 사용자 skill 로드 경로 검증
- [ ] MCP runtime add/remove 시나리오 검증
- [ ] Subprocess hook 감사 시나리오 검증
- [ ] HITL resume 시나리오 검증
- [ ] Crash recovery (Persist → resume_from_checkpoint) 검증
- [ ] Tool Review 가 민감 패턴 1+ 차단 시나리오 검증
- [ ] 문서 sync 완료 (01–11 + appendix)
- [ ] `dev_docs/<cycle>/` 에 Phase 별 progress 문서 누적

---

## 16. 참고 문서

- [`01_overview.md`](01_overview.md) — 원칙 + 성공 기준
- [`05_gap_analysis.md`](05_gap_analysis.md) — 격차 + 우선순위
- [`06`–`10`] — 설계 세부
- [`11_migration_roadmap.md`](11_migration_roadmap.md) — Phase 개요
- [`appendix/a_file_inventory.md`](appendix/a_file_inventory.md) — 레포 파일 인덱스
- [`appendix/b_terminology.md`](appendix/b_terminology.md) — 용어 정의
- [`appendix/c_prior_art.md`](appendix/c_prior_art.md) — 외부 참조
