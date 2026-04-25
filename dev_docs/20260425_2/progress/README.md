# Cycle 20260425_2 — Progress (complete)

## 트래킹 표

| Sprint | PR | 머지 | 상태 |
|---|---|---|---|
| G12 (Phase 7 activations) | [#326](https://github.com/CocoRoF/Geny/pull/326) | 2026-04-25 | ✅ s06/s14/s16/s18 flipped to Phase-7 strategies on worker_adaptive |
| G14 (MCP prompts auto-bridge) | [#327](https://github.com/CocoRoF/Geny/pull/327) | 2026-04-25 | ✅ agent_session_manager auto-builds SkillRegistry + bridges MCP prompts |
| G13 (Frontend admin viewers) | [#328](https://github.com/CocoRoF/Geny/pull/328) | 2026-04-25 | ✅ /api/{permissions,hooks}/list + AdminPanel |
| G15 (Dashboard extensions) | [#329](https://github.com/CocoRoF/Geny/pull/329) | 2026-04-25 | ✅ /api/agents/{id}/pipeline/introspect + StageStrategyHeatmap + MutationDiffViewer |

## 종합

- **4 sprint, 4 PR (cycle docs PR #325 포함하면 5 PR)**
- 모든 sprint 단일 PR로 병합 — bundling 없이 깔끔하게.
- 누적 회귀: 0 (모든 PR 의 테스트 green, 기존 테스트 변동 없음)

## 변경된 capability matrix (cycle 20260425_2 후)

| 항목 | 이전 cycle | 이후 |
|---|---|---|
| Phase 7 strategies activated on worker_adaptive | 3/12 | **7/12** (G12 + G9.9 + S7.1 + S7.11) |
| Permission rules viewer (frontend) | UNWIRED | ✅ WIRED (read-only) |
| Hooks viewer (frontend) | UNWIRED | ✅ WIRED (read-only + env opt-in status) |
| Skills viewer (frontend) | partial (chips in CommandTab) | ✅ WIRED (Admin tab section) |
| MCP prompts → Skills auto-bridge | helper only | ✅ WIRED (auto-call on session boot) |
| Pipeline introspection endpoint | UNWIRED | ✅ WIRED |
| Stage strategy heatmap | UNWIRED | ✅ WIRED |
| Mutation diff viewer | UNWIRED | ✅ WIRED (modal) |

## 잔여 (next cycle 후보)

1. **Phase 7 잔여 5종** (s09 structured_output / s12 subagent_type / s21 multi_format / 그리고 deferred 2종) — 각자 config schema 또는 frontend renderer 변경이 필요해 별도 sprint.
2. **Editor UI** — 현재는 Admin viewer 가 read-only. Permission/Hook/Skill YAML 편집 폼 + validation + save endpoint.
3. **MutationDiff highlight** — 현재 두 JSON 블록 side-by-side 만. monaco-editor diff mode 같은 라이브러리 도입.
4. **Cost projection** — TokenMeter 가 누적 totals 만. 남은 turn 추정 기반 projection 추가.
5. **Live executor 통합 테스트** — fastapi 가 없는 test venv 에서 skip 된 endpoint 들 (admin / introspect / mcp admin / oauth 등) 의 CI 실행.
