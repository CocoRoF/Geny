# Cycle 20260425_2 — Polish + Activation

**Created:** 2026-04-25
**Status:** Plan ready
**Goal:** Close the residual items the previous cycle (20260425_1) deferred — Phase 7 strategy activations (config tuning + flips), frontend admin UIs for permission/hook/skills, MCP prompts auto-bridge, dashboard extensions.

## Sprint matrix

| Sub-cycle | 주제 | PR 수 |
|---|---|---|
| **G12** | Phase 7 strategy activations on worker presets (preset config tuning + flip) | 1 |
| **G13** | Frontend admin UIs (permission / hook / skills read-only viewers) | 1 |
| **G14** | MCP prompts → Skills bridge auto-call from agent_session | 1 |
| **G15** | Dashboard extensions (mutation diff viewer + per-stage heatmap) | 1 |
| **합계** | | **4** |

## 결정 — bundling 정책

이전 cycle 의 G9.x / G10.x / G11.x 묶음 PR 패턴을 유지. 동일 영역 + 동일 패턴 작업은 한 PR 로 통합 (개별 sprint 묶기). 단일 PR 안에서 sprint id 별 commit message 섹션 + 테스트 분기로 fidelity 유지.

## Out of scope

- Phase 7 strategy 의 *deep* tuning (각 strategy 의 config schema 별 옵셔널 파라미터). 본 cycle 은 default 활성만, 운영 데이터 보고 후속 cycle 에서 튜닝.
- Hook / Permission / Skills 의 *editor* UI (현재 cycle 은 read-only viewer + 디렉토리 안내). 편집은 다음 cycle.
- 개별 sprint progress note (G6.2 ~ G11.3) — cosmetic, 사용자 요청 시 별도 doc PR.
