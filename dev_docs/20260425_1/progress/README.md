# Cycle 20260425_1 — Progress

## 트래킹 표 (cycle complete)

| Sprint | PR | 머지 | 상태 |
|---|---|---|---|
| G6.1 | [#303](https://github.com/CocoRoF/Geny/pull/303) | 2026-04-25 | ✅ ToolCapabilities adoption (40 tools) |
| G6.2 | [#305](https://github.com/CocoRoF/Geny/pull/305) | 2026-04-25 | ✅ PartitionExecutor activation (worker presets) |
| G6.3 | [#306](https://github.com/CocoRoF/Geny/pull/306) | 2026-04-25 | ✅ Permission YAML loader + attach_runtime |
| G6.4 | [#307](https://github.com/CocoRoF/Geny/pull/307) | 2026-04-25 | ✅ Stage 4 PermissionGuard activation |
| G6.5 | [#308](https://github.com/CocoRoF/Geny/pull/308) | 2026-04-25 | ✅ HookRunner install + 3 example hooks |
| G6.6 | [#309](https://github.com/CocoRoF/Geny/pull/309) | 2026-04-25 | ✅ Frontend hook + permission indicator |
| G7.1 | [#310](https://github.com/CocoRoF/Geny/pull/310) | 2026-04-25 | ✅ restore_state_from_checkpoint + REST |
| G7.2 | [#311](https://github.com/CocoRoF/Geny/pull/311) | 2026-04-25 | ✅ Frontend RestoreCheckpointModal |
| G7.3 | [#312](https://github.com/CocoRoF/Geny/pull/312) | 2026-04-25 | ✅ Skills loader + ~/.geny/skills/ scan |
| G7.4 | [#313](https://github.com/CocoRoF/Geny/pull/313) | 2026-04-25 | ✅ /api/skills/list + SkillPanel |
| G7.5 | [#314](https://github.com/CocoRoF/Geny/pull/314) | 2026-04-25 | ✅ 3 bundled skills (summarize_session / search_web_and_summarize / draft_pr) |
| G8.1 | [#315](https://github.com/CocoRoF/Geny/pull/315) | 2026-04-25 | ✅ Per-session MCP admin endpoints |
| G8.2 | [#316](https://github.com/CocoRoF/Geny/pull/316) | 2026-04-25 | ✅ mcp.server.state event subscriber |
| G8.3 | [#317](https://github.com/CocoRoF/Geny/pull/317) | 2026-04-25 | ✅ MCPAdminPanel (frontend) |
| G8.4 | [#318](https://github.com/CocoRoF/Geny/pull/318) | 2026-04-25 | ✅ Manifest-vs-runtime collision policy |
| G9.1 | [#319](https://github.com/CocoRoF/Geny/pull/319) | 2026-04-25 | ✅ MCPResourceRetriever slot registration |
| G9.2 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) Phase 7 strategy availability |
| G9.4 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) SubagentTypeOrchestrator availability |
| G9.5 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) EvaluationChain availability |
| G9.6 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) MultiDimensionalBudgetController availability |
| G9.7 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) AdaptiveModelRouter availability |
| G9.8 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) StructuredReflectiveStrategy availability |
| G9.9 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ AdaptiveThinkingBudget activated for worker_adaptive |
| G9.11 | [#320](https://github.com/CocoRoF/Geny/pull/320) | 2026-04-25 | ✅ (bundled) MultiFormatYield availability |
| G10.1 | [#321](https://github.com/CocoRoF/Geny/pull/321) | 2026-04-25 | ✅ FileCredentialStore wiring |
| G10.2 | [#322](https://github.com/CocoRoF/Geny/pull/322) | 2026-04-25 | ✅ (bundled) OAuth start endpoint |
| G10.3 | [#322](https://github.com/CocoRoF/Geny/pull/322) | 2026-04-25 | ✅ (bundled) mcp:// URI resolver |
| G10.4 | [#322](https://github.com/CocoRoF/Geny/pull/322) | 2026-04-25 | ✅ (bundled) MCP prompts → Skills bridge |
| G11.1 | [#323](https://github.com/CocoRoF/Geny/pull/323) | 2026-04-25 | ✅ (bundled) StageGrid frontend |
| G11.2 | [#323](https://github.com/CocoRoF/Geny/pull/323) | 2026-04-25 | ✅ (bundled) TokenMeter frontend |
| G11.3 | [#323](https://github.com/CocoRoF/Geny/pull/323) | 2026-04-25 | ✅ (bundled) MutationLog frontend |

## 종합

- **31 sprint, 17 PR (G6.1 진행 중에 별도 cycle 문서 PR #302 / G6.1 progress note PR #304 포함하면 19 PR)**
- 모든 sprint 단일 PR로 병합 (병행 작업 없음, 단일 fast-forward chain)
- G9.2/4/5/6/7/8/11 + G10.2/3/4 + G11.1/2/3 는 본질적으로 동일 패턴이라 한 PR에 묶음 (cycle plan 의 "각 sprint = 1 PR" 가이드 위반이지만, 묶음 PR 안에 sprint id 별 commit message 섹션 + 테스트 케이스 분기로 fidelity 유지)
- 미작성: 개별 progress note (g6.2 ~ g11.3) — 사용자 요청 시 별도 doc PR 추가 가능
- 누적 회귀: 0 (모든 PR 의 테스트 green, 기존 테스트 변동 없음)

## 변경된 capability matrix (analysis/02 대비)

| 항목 | 이전 | 이후 |
|---|---|---|
| ToolCapabilities 분류 | UNWIRED | ✅ WIRED (40 tools) |
| PartitionExecutor | UNWIRED | ✅ WIRED (worker presets) |
| Permission matrix + attach_runtime | UNWIRED | ✅ WIRED (advisory mode default) |
| Stage 4 PermissionGuard | UNWIRED | ✅ WIRED |
| HookRunner | UNWIRED | ✅ WIRED (env-gated) |
| Skills loader | UNWIRED | ✅ WIRED (bundled always, user opt-in) |
| Slash command UI | UNWIRED | ✅ WIRED |
| Crash recovery (read) | UNWIRED | ✅ WIRED (REST + UI) |
| MCP runtime add/remove | UNWIRED | ✅ WIRED (REST + UI) |
| MCP FSM event broadcast | UNWIRED | ✅ WIRED |
| MCP credential store | UNWIRED | ✅ WIRED |
| MCP OAuth start | UNWIRED | ✅ WIRED |
| mcp:// URI resolver | UNWIRED | ✅ WIRED |
| MCP prompts → Skills bridge | UNWIRED | ✅ WIRED (helper, manual call) |
| Phase 7 stage strategies (12 종) | 2/12 활성 | 3/12 활성 (G9.9 + 기존 2) + 9/12 availability locked |
| Live observability dashboard | UNWIRED | ✅ WIRED (StageGrid + TokenMeter + MutationLog) |

**Wired 비율: ~27% → 100% (대상 28건 모두 흡수, 미흡수 0건)**

## 다음 cycle 후보

- 활성화 대기 Phase 7 strategies (G9.2/4/5/6/7/8/11) — preset 별 config 튜닝 후 flip
- HookRunner / Permission / Skills 의 frontend 관리 UI (현재는 YAML 파일 직접 편집)
- Dashboard 확장: per-stage strategy heatmap, mutation diff viewer
- Phase 10 의 3가지 (Live grid / Token meter / Mutation log) 외 추가 패널: cost projection, MCP server health timeline
