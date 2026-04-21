# Cycle 20260421_7 — X1 : PersonaProvider & `_system_prompt` 사이드도어 철거

**Date.** 2026-04-21
**Scope.** Geny backend only. **Executor 수정 없음.**
**상위 설계.** [`dev_docs/20260421_6/plan/03_structural_completions.md §2`](../20260421_6/plan/03_structural_completions.md), [`plan/05 §1`](../20260421_6/plan/05_cycle_and_pr_breakdown.md).

## 목표

- `PersonaProvider` Protocol 도입, `DynamicPersonaSystemBuilder` 로 **매 턴 persona resolve** 가능하게.
- `agent._system_prompt = ...` 직접 쓰기 **전부 철거** (발견된 5 사이트).
- X3 (CreatureState) 에서 들어올 `MoodBlock / RelationshipBlock / VitalsBlock / ProgressionBlock` 의 **자리를 no-op stub 으로** 미리 마련.

## 핵심 수정점 (사이클 진입 재검증 결과)

- 사이드도어 수는 **5** (상위 plan 예측 3). `controller/agent_controller.py:482, 520` 의 restore 경로 포함.
- 파일 경로 정정: `backend/controller/` (service 아님).
- `ComposablePromptBuilder` / `PersonaBlock` 등은 **executor 소유**. Geny 는 소비자. 재사용만.

## Documents

- [analysis/01_x1_sidedoor_recheck.md](analysis/01_x1_sidedoor_recheck.md) — 5 사이드도어 실측.
- [plan/01_x1_execution_plan.md](plan/01_x1_execution_plan.md) — 4 PR 상세 실행 계획.
- `progress/` — PR 별 진행.

## PR 목록

1. PR-X1-1 · `feat/persona-provider-skeleton` — Protocol + DynamicBuilder + no-op blocks.
2. PR-X1-2 · `feat/character-persona-provider` — default impl.
3. PR-X1-3 · `refactor/remove-system-prompt-sidedoors` — 5 사이트 철거.
4. PR-X1-4 · `test/persona-e2e` — 통합 시나리오.

## Out

- X3 의 Mood/Bond/Vitals 실구현 — 본 사이클에서는 no-op stub 만.
- `agent.process.system_prompt` (Claude Code CLI) 동기화 — 별도 채널, 유지.
- Legacy 코드 완전 삭제 — 2주 후 별도 PR.

## Relation

- 선행: `20260421_6` (분석+PLAN).
- 병렬 가능: `20260421_8` (X2 — Bus + TickEngine).
- 후속: `20260421_9` (X3 — CreatureState MVP) 가 `PersonaProvider.resolve` 내에서 `state.shared['creature_state']` 를 소비.
