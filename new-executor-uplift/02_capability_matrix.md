# 02. Capability Matrix — claude-code-main vs Geny (53 items, layer-aware)

**Source data:** 두 병렬 Explore agent 의 출력 + 직접 검증 (의심되는 claim 만).
**Date:** 2026-04-25 (revised — Layer 컬럼 추가)
**Layer 분류 axiom:** [`00_layering_principle.md`](00_layering_principle.md)

**상태 범례:**
- ✅ **SHIPPED** — 동등 또는 우월. 일부 항목은 Geny 가 ahead.
- 🟡 **PARTIAL** — 부분 구현. 누락 사항을 비고에 명시.
- ❌ **MISSING** — 등가 0. 향후 cycle 의 후보.
- 🚫 **OUT_OF_SCOPE** — Anthropic 내부 / IDE 전용 / Geny 도메인 외 (영구 제외).

**Layer 범례:**
- **EXEC-CORE** — geny-executor 의 built-in (claude-code-main reference). 모든 framework 사용자가 누림.
- **EXEC-INTERFACE** — geny-executor 가 노출하는 ABC + register API. 구현은 service-side.
- **SERVICE** — Geny 전용 (도메인 / REST / 웹 UI / 운영 인프라).
- **BOTH** — EXEC + SERVICE 양쪽 작업 필요. 의존성 한 방향 (executor → service).

---

## A. Tool system

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| A.1 | Tool ABC + capabilities | Tool.ts (concurrency_safe, destructive 등) | `tools/base.ToolCapabilities` | ✅ | EXEC-CORE | 동등 |
| A.2 | **Built-in tool catalog** | **39 stable + 9 feature-gated** | **13 built-ins** | 🟡 | EXEC-CORE | **26 누락** — A.2 표 참조. 거의 모두 executor 측 작업 |
| A.3 | Concurrency / scheduling | serial only | `s10_tool/PartitionExecutor` | ✅ **AHEAD** | EXEC-CORE | Geny 가 한 발 앞 |
| A.4 | Tool input preview / approval UI | PermissionRequest comp | ExecutionTimeline + StepDetailPanel | ✅ | SERVICE | 웹 UI 는 service |
| A.5 | Background tasks (TaskCreate/Get/List/Update/Output/Stop) | 6 tool + 7 task type | scaffold (s13) only | ❌ | BOTH | tool/runner=EXEC-CORE, REST+UI+lifespan=SERVICE |

### A.2 — built-in tool 26 누락 항목 (layer 표시)

| Tool | 용도 | 가치 | Layer | 누가 ship |
|---|---|---|---|---|
| **AgentTool** | sub-agent 호출 | HIGH | EXEC-CORE | geny-executor (Stage 12 이미 ship, tool 만 추가) |
| **AskUserQuestionTool** | LLM→user 질문 | HIGH | EXEC-CORE | geny-executor (HITL slot 활용) |
| **TaskCreate / Get / List / Update / Output / Stop (6)** | task lifecycle | HIGH | EXEC-CORE | geny-executor (Stage 13 이미 ship, tool 6 + runner 추가) |
| **CronCreate / Delete / List (3)** | scheduling | HIGH | EXEC-CORE | geny-executor (tool 3 + daemon ABC 표준 backend) |
| **EnterWorktree / ExitWorktree (2)** | git worktree 격리 | MED | EXEC-CORE | geny-executor |
| **LSPTool** | language server | MED | EXEC-CORE | geny-executor |
| **MonitorTool** | tool 출력 watch | MED | EXEC-CORE | geny-executor (EventBus 활용) |
| **REPLTool** | python REPL | MED | EXEC-CORE | geny-executor |
| **PowerShellTool** | Windows 환경 | LOW | OUT | Geny 는 Linux only |
| **BriefTool** | 문맥 요약 | MED | EXEC-CORE | geny-executor (Stage 19 활용) |
| **ConfigTool** | 설정 조회/변경 | MED | EXEC-CORE | geny-executor (PipelineMutator 활용) |
| **SendMessageTool** | session 간 메시지 | MED | EXEC-INTERFACE + SERVICE | ABC=executor, channel impl=Geny (이미 send_dm 있음) |
| **SyntheticOutputTool** | LLM mock | LOW | EXEC-CORE | 테스트 전용 |
| **PushNotificationTool** | webhook | HIGH | EXEC-CORE | geny-executor (URL 은 config 주입) |
| **SubscribePRTool** | GitHub webhook | 🚫 | — | Anthropic-internal |
| **RemoteTriggerTool** | Anthropic Managed Agents | 🚫 | — | Anthropic-internal |
| **SleepTool** | 시간 지연 | 🚫 | — | KAIROS-only |
| **TeamCreateTool / TeamDeleteTool** | 팀 워크스페이스 | 🚫 | — | Anthropic-internal |
| **VerifyPlanExecutionTool** | dry-run | 🚫 | — | Anthropic-internal |
| **MCPTool / ListMcpResources / ReadMcpResource / McpAuth (4)** | MCP wrapper | HIGH | EXEC-CORE | geny-executor (MCPManager 이미 ship) |
| **SendUserFile** | user 에게 파일 | MED | EXEC-CORE | geny-executor (file slot 표준) |

→ **HIGH/MED 합계: 14 tool, 모두 EXEC-CORE**. Geny 측은 register/wire 만.

---

## B. Permission system

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| B.6 | Rule sources | 7+ (user/project/local/flag/policy/cliArg/command/session) | 5 (env/user/project/local/preset) | 🟡 | EXEC-CORE + EXEC-INTERFACE | flag/policy/session source ABC 추가 → executor |
| B.7 | PLAN mode variants | 6 (acceptEdits/bypass/default/dontAsk/plan/auto) | 4 (default/plan/auto/bypass) | 🟡 | EXEC-CORE | acceptEdits/dontAsk 추가 → executor |
| B.8 | Permission regex matcher | 있음 | `permission/matrix.py` | ✅ | EXEC-CORE | 동등 |

---

## C. Hook system

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| C.9 | Hook event taxonomy | extensible HOOK_EVENTS | 16 enum events | ✅ | EXEC-CORE | Geny 가 stricter typed |
| C.10 | Subprocess JSON contract | STDIN/STDOUT JSON | HookRunner | ✅ | EXEC-CORE | 동등 |
| C.11 | In-process callbacks | `registerHookEventHandler` | EventBus (observability only) | 🟡 | EXEC-CORE | blocking handler API → executor |

---

## D. Skill system

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| D.12 | SKILL.md frontmatter | 8 fields | 7 fields | 🟡 | EXEC-CORE | category/examples/effort schema 확장 → executor |
| D.13 | Skill loader paths | bundled / user / project / MCP | bundled + user + project (MCP advisory) | 🟡 | EXEC-INTERFACE | path 주입 API + MCP→skill 자동 변환 → executor |
| D.14 | SkillTool dispatch | 있음 | `skills/skill_tool.py` | ✅ | EXEC-CORE | 동등 |
| D.15 | Execution mode (inline/sub-agent/forked) | inline + forked | inline only | 🟡 | EXEC-CORE | fork mode → executor |
| D-extra | Bundled skill 목록 | claude-code 의 자체 set | Geny 의 3종 | — | SERVICE | 어떤 skill 을 ship 할지 = service 결정 |

---

## E. MCP integration

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| E.16 | Transport types | 6 (stdio/SSE/HTTP/WS/SDK/SSE-IDE) | 3 (stdio/HTTP/SSE) | 🟡 | EXEC-CORE | WS / SDK-managed → executor (SSE-IDE OUT) |
| E.17 | Connection FSM | 있음 | `mcp/state.py` | ✅ | EXEC-CORE | 동등 |
| E.18 | OAuth flow | 있음 | `mcp/oauth.py` (G10.2) | ✅ | EXEC-CORE | 동등 |
| E.19 | mcp:// URI | 있음 | `mcp/uri.py` (G10.3) | ✅ | EXEC-CORE | 동등 |
| E.20 | Server runtime add/remove | 있음 | `MCPManager` (G8.1) | ✅ | EXEC-INTERFACE | 동등 |
| E.21 | Credential storage ABC | 있음 | `FileCredentialStore` (G10.1) | ✅ | EXEC-INTERFACE + SERVICE | ABC=executor, file backend impl=service |
| E.22 | XAA (Cross-App Access) | `McpXaaConfigSchema` | 없음 | ❌ | — | enterprise feature |
| E.23 | SSE-IDE transport | `vscodeSdkMcp` | 없음 | 🚫 | — | OUT_OF_SCOPE |
| E.24 | SDK-managed MCP (InProcess/SdkControl) | 있음 | 없음 | ❌ | EXEC-CORE | plugin-style 가능 → executor |

---

## F. Slash commands

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| F.25 | Discovery (built-in / project / user) | **~100 commands** | **3 bundled skills + skill panel** | ❌ | BOTH | parser+registry+12 introspection 명령=EXEC-CORE / `/preset` 등 도메인 명령=SERVICE |

> Note: `/cost`, `/clear`, `/status`, `/help`, `/memory`, `/context`, `/cancel`, `/compact`, `/config`, `/model`, `/tasks` 의 12 introspection 명령은 **executor state 위의 introspection** → 모두 **EXEC-CORE built-in**. Geny 는 `/preset` (worker_adaptive ↔ vtuber 전환) 같은 도메인 명령만 register.

---

## G. Memory / Context

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| G.26 | CLAUDE.md / AGENTS.md / .cursorrules 자동 발견 | 있음 | `service/prompt/context_loader.py` | ✅ | EXEC-CORE | path resolver 는 framework 책임. 서비스가 더 많은 file 추가는 register API 로 |
| G.27 | Session memory + auto-compaction | 자동 | s19_summarize opt-in | 🟡 | EXEC-CORE | auto trigger → executor |
| G.28 | Per-message context injection | 있음 | s02 + s03 stage | ✅ | EXEC-CORE | 동등 |
| G-extra | MemoryProvider / KnowledgeProvider ABC | 있음 (LongMemory etc.) | 있음 (GenyMemoryProvider 등) | ✅ | EXEC-INTERFACE + SERVICE | ABC=executor, SQLite/Postgres backend=service |

---

## H. Sub-agent / Task system

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| H.29 | AgentTool spawning | 있음 | SubagentTypeOrchestrator 등록만 | 🟡 | BOTH | tool=EXEC-CORE / type descriptor seed=SERVICE |
| H.30 | Task lifecycle (6 tools) | 있음 | 0 tool | ❌ | EXEC-CORE | tool 6 + runner ABC 모두 executor |
| H.31 | Background execution + disk-buffered output | 있음 | 없음 | ❌ | EXEC-CORE + EXEC-INTERFACE | runner=core / store backend ABC=interface |
| H-extra | TaskRegistryStore impl | in-memory + file | (없음) | — | EXEC-CORE built-in (in-mem/file) + SERVICE (Postgres) | reference backend=executor / 운영 backend=service |

---

## I. Streaming / TTY rendering

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| I.32 | Tool result custom renderer | tool 별 UI.tsx | ExecutionTimeline + tool_review override | 🟡 | SERVICE | 웹 UI 는 service. Geny 가 web 에 맞는 표준 만들기 |
| I.33 | Spinner + progress hints | spinnerMode + ToolCallProgress | metadata 있으나 frontend wiring 미완 | 🟡 | BOTH | metadata schema=EXEC-CORE / wiring=SERVICE |
| I.34 | File diff preview | StructuredDiff | DiffViewer.tsx | ✅ | SERVICE | 동등 |

---

## J. Prompt caching / Model behavior

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| J.35 | Prompt caching breakpoints | 자동 | s05_cache (CacheStrategy) | ✅ | EXEC-CORE |
| J.36 | Extended thinking | ThinkingConfig | s08_think | ✅ | EXEC-CORE |
| J.37 | Streaming partial | ContentBlockDelta | s06 + s09 | ✅ | EXEC-CORE |

---

## K. Settings / Config

| # | Item | claude-code | Geny | 상태 | Layer | 비고 |
|---|---|---|---|---|---|---|
| K.38 | Settings hierarchy (user/project/local) | settings.json 3 단계 | YAML 4 단계 | 🟡 | EXEC-CORE + SERVICE | loader+section schema=EXEC-CORE / migrator + Geny 전용 section=SERVICE |
| K.39 | Permission via JSON | settings.json:permissions[] | 별도 YAML | 🟡 | EXEC-CORE | settings.json 통합 → executor |
| K.40 | Model override per-session | 있음 | session 단위 미노출 | 🟡 | BOTH | API=EXEC-CORE / session 컨트롤=SERVICE |
| K.41 | Telemetry opt-out | 있음 (settings.telemetry) | 미확인 | 🟡 | EXEC-CORE | section 표준 → executor |

---

## L. Notebook support

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| L.42 | NotebookEdit tool | 있음 | `notebook_edit_tool.py` (12KB, full IPYNB) | ✅ | EXEC-CORE |

---

## M. Cost tracking

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| M.43 | Per-turn cost / tokens | cost-tracker.ts | s07_token + frontend TokenMeter | ✅ | EXEC-CORE (집계) + SERVICE (UI) |
| M.44 | Budget gates | policyLimits | s04_guard:CostBudgetGuard | ✅ | EXEC-CORE |

---

## N. Scheduling / Cron

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| N.45 | CronCreate/Delete/List tools | 3 tool | 0 | ❌ | EXEC-CORE |
| N.46 | Background scheduled runner | 있음 | 없음 | ❌ | EXEC-CORE + EXEC-INTERFACE (store ABC) |

---

## O. Sandbox

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| O.47 | File access boundaries | settings.additionalWorkingDirectories | `sandbox.py:ToolSandbox` | ✅ | EXEC-CORE |
| O.48 | Network egress control (domain allowlist) | WebFetch allowlist | `network_egress` flag 만 | 🟡 | EXEC-CORE |

---

## P. Worktree support

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| P.49 | EnterWorktree / ExitWorktree | 2 tool | 0 | ❌ | EXEC-CORE |

---

## Q. LSP integration

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| Q.50 | LSPTool | 있음 | 없음 | ❌ | EXEC-CORE |

---

## R. Coordinator mode

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| R.51 | Multi-agent + 공유 scratchpad | coordinator/coordinatorMode.ts | Stage 12 + Stage 13 scaffold | 🟡 | EXEC-CORE |

---

## S. Plugins

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| S.52 | Bundled plugin system | `plugins/bundled/` | bundled skill 3종 만 | ❌ | EXEC-INTERFACE + SERVICE | plugin loader=EXEC-INTERFACE / 어떤 plugin 을 ship 할지=SERVICE |

---

## T. Auto-compaction

| # | Item | claude-code | Geny | 상태 | Layer |
|---|---|---|---|---|---|
| T.53 | Context fill 시 auto-summarise | autoCompact.ts | s19_summarize opt-in | 🟡 | EXEC-CORE |

---

## 전체 요약 (status)

| 상태 | Count | % |
|---|---|---|
| ✅ SHIPPED | 21 | 40% |
| 🟡 PARTIAL | 21 | 40% |
| ❌ MISSING | 9 (3 OUT_OF_SCOPE 제외) | 17% |
| 🚫 OUT_OF_SCOPE | 3 | — |
| **합계** | **53** | **100%** |

## 전체 요약 (Layer)

| Layer | 항목 수 (대략) | 의미 |
|---|---|---|
| **EXEC-CORE** (built-in) | ~32 | claude-code 의 framework 표준. 거의 모두 geny-executor 측 PR |
| **EXEC-INTERFACE** (ABC + register API) | ~8 | ABC 추가 / register API 노출 PR |
| **SERVICE** | ~8 | REST 어댑터 / 웹 UI / 도메인 backend / 운영 인프라 |
| **BOTH** | ~5 | 양 repo 동시 작업 (executor PR → Geny PR 순서) |
| **OUT_OF_SCOPE** | 3 | XAA / SSE-IDE / Anthropic-internal |

→ **다음 cycle 의 PR 무게중심은 geny-executor 레포** (~70%). Geny 는 register / wire / UI / REST 에 가까움.

---

## 가장 큰 영향도 격차 (다음 cycle 우선 검토)

| 격차 | 항목 | 주 작업 repo |
|---|---|---|
| 1 | A.5 / H.30 / H.31 — Task system | geny-executor (tool 6 + runner) + Geny (REST + UI) |
| 2 | F.25 — Slash commands | geny-executor (parser + 12 명령) + Geny (`/preset` register) |
| 3 | A.2 — built-in tool 14 (HIGH/MED) | geny-executor (모두) |
| 4 | N.45 / N.46 — Cron | geny-executor (tool 3 + daemon) + Geny (Postgres backend + UI) |
| 5 | P.49 / Q.50 — Worktree / LSP | geny-executor (모두) |

**Geny 가 ahead 인 항목 1건**: A.3 PartitionExecutor (이미 geny-executor 내부, claude-code 가 따라잡아야 할 것).

다음 문서 [`03_priority_buckets.md`](03_priority_buckets.md) 에서 의존성 + 영향도 + **양 repo PR 분포** 로 정렬.
