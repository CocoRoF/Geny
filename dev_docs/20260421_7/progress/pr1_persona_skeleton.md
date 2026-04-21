# PR-X1-1 · `feat/persona-provider-skeleton` — 진행 기록

**Date.** 2026-04-21
**Status.** Implemented, tests passing. Awaiting push + merge.

## 적용된 변경

### 신규 모듈
- `backend/service/persona/__init__.py` — public re-export.
- `backend/service/persona/provider.py` — `PersonaProvider` Protocol + `PersonaResolution`.
- `backend/service/persona/dynamic_builder.py` — `DynamicPersonaSystemBuilder` (PromptBuilder).
- `backend/service/persona/blocks.py` — no-op `MoodBlock`/`RelationshipBlock`/`VitalsBlock`/`ProgressionBlock`.

### 신규 테스트
- `backend/tests/service/persona/__init__.py`
- `backend/tests/service/persona/test_provider_protocol.py` (4 cases)
- `backend/tests/service/persona/test_dynamic_builder.py` (7 cases)
- `backend/tests/service/persona/test_blocks_stub.py` (3 cases)

14 case all pass (`pytest backend/tests/service/persona/ -x`, 0.11s).

## plan 과의 차이

| 항목 | plan/01 | 실구현 | 사유 |
|---|---|---|---|
| 테스트 위치 | `backend/tests/persona/` | `backend/tests/service/persona/` | 기존 `backend/tests/<mirror_of_source>/` 컨벤션 준수 |
| `PersonaProvider.resolve` signature | `async def` | `def` (sync) | `PromptBuilder.build` 는 sync. `SystemStage.execute` 가 await 없이 호출. async 경계 우회 필요해져서 포기. persona resolve 는 in-memory 조회 (state.shared + 캐싱된 MD) 만 하면 되므로 sync 충분. |

plan/01 문서 자체도 이 2항을 반영하도록 동시 수정.

## 회귀 위험

0 (경로 미사용 — skeleton 만 추가. `AgentSession._build_pipeline` 는 여전히 고정 `ComposablePromptBuilder` 사용. PR-X1-3 에서 교체).

## 다음 PR

**PR-X1-2 · `feat/character-persona-provider`** — `CharacterPersonaProvider` (default impl).
