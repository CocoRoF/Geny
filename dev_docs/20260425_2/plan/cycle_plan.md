# Cycle 20260425_2 — Polish + Activation Plan

**Baseline:** `main` @ post-PR #324 (cycle 20260425_1 closed)
**Pin:** `geny-executor[web]>=1.0.0,<2.0.0`
**Total PRs:** 4

---

## G12 — Phase 7 strategy activations (1 PR)

**Goal:** Move 6 of the 7 availability-locked strategies from "registered" to "active" on `worker_adaptive`. Defer adopting `multi_format` (s21) because its output contract requires a frontend renderer change too.

**Strategy flips** (worker_adaptive only — vtuber/worker_easy stay on safe defaults):

| Stage | Slot | Old | New | Config addition |
|---|---|---|---|---|
| s06 api | router | `passthrough` | `adaptive` | thresholds: opus when first turn / sonnet otherwise / haiku for tool_use-only turns |
| s09 parse | parser | `default` | `default` (keep) | structured_output needs schema — no flip yet |
| s12 agent | orchestrator | `single_agent` | `single_agent` (keep) | subagent_type needs SubagentTypeRegistry seeded with worker descriptors — defer |
| s14 evaluate | strategy | `binary_classify` | `evaluation_chain` | wrap binary_classify + signal_based as a 2-evaluator chain |
| s16 loop | controller | `standard` | `multi_dim_budget` | dimensions: iterations / cost_usd / walltime_seconds |
| s18 memory | strategy | `append_only` | `structured_reflective` | reflection schema: insights / tags / importance |

**Tests:** assert each entry's strategy field flipped on worker_adaptive; vtuber stays on its current values.

**Risk mitigation:** all six new strategies are strict supersets of their predecessors at default config — `evaluation_chain` defaults to wrapping the original strategy, `multi_dim_budget` defaults to single iteration dimension (= `standard`), `structured_reflective` falls back to `append_only` shape when no schema is provided. So flipping with empty config is behaviour-equivalent; the gain is that operators can now tune via `strategy_configs` without another deploy.

---

## G13 — Frontend admin viewers (1 PR)

**Goal:** Read-only viewers for the YAML configs the host now consumes. No editing yet — operators still hand-edit `~/.geny/{permissions,hooks}.yaml` + drop SKILL.md files. The viewers tell them *what's loaded* without tailing logs.

- New endpoints (read-only):
  - `GET /api/permissions/list` → 4-source breakdown (user / project / local / env) with each rule's tool/pattern/behavior/source/reason
  - `GET /api/hooks/list` → current `HookConfig.entries` keyed by event, plus the env opt-in status (`GENY_ALLOW_HOOKS`)
  - (skills already covered by G7.4 `/api/skills/list`)
- New panel: `frontend/src/components/admin/AdminPanel.tsx` — three sections, each one async-loading from the matching endpoint. Mounted on a new "Admin" sub-section of `SessionToolsTab` (or its own tab) — TBD by component layout.

**Tests:** controller-level direct-handler tests for both new endpoints.

**Risk:** None — viewers only. Rule files keep their handcrafted edit path.

---

## G14 — MCP prompts → Skills auto-bridge (1 PR)

**Goal:** When the executor's `MCPManager` finishes connecting servers, automatically call `bridge_mcp_prompts(skill_registry, mcp_manager)` so MCP-supplied prompts become `/<skill-id>` slash commands without operator intervention.

**Wiring:** `agent_session._build_pipeline` → after `attach_runtime` and after `install_credential_store`, look up the skill registry built by G7.3 and call `bridge_mcp_prompts` if both are present. Idempotent.

**Test:** stub MCPManager that returns 2 fake prompts → bridge registers 2 skills → `list_skills()` includes them.

---

## G15 — Dashboard extensions (1 PR)

**Goal:** Add 2 panels to the G11 Dashboard tab.

- **MutationDiffViewer**: clicking a row in `MutationLog` opens a modal showing before / after JSON side-by-side with `diff` highlighting. Pure derivation off the same row data — no new endpoint.
- **StageStrategyHeatmap**: a 21-stage grid showing which stages have non-default strategies bound (red = default, green = override). Reads pipeline introspection via a new `GET /api/agents/{id}/pipeline/introspect` endpoint that wraps `pipeline.introspect_all()`.

**Tests:** controller test for the introspect endpoint; frontend components no automated tests (visual only).

---

## 검증 매트릭스

| Cycle | pass 조건 |
|---|---|
| G12 | 6 manifest assertions green / vtuber regression 0 |
| G13 | 2 endpoint tests green / Admin panel renders 3 sections |
| G14 | bridge auto-call adds skills when MCP prompts exist / no-op without MCP |
| G15 | introspect endpoint round-trips / MutationDiff modal opens with row click |

## Rollback

각 PR 단독 revert 가능. G12 의 strategy flips 는 default config 가 behaviour-preserving 이라 revert 시 차이 없음.
