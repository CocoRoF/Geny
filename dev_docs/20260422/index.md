# Cycle 20260422 — X5 · GenyPlugin Protocol & Registry

**사이클 시작.** 2026-04-22 (X4 종료 직후)
**선행.** X4 (cycle 20260421_10, 6 PR, 493/493 pass) — Progression +
Manifest 전환 + EventSeed 까지 전부 `AgentSessionManager` 내부에서
직접 wiring.
**사전 청사진.**
- `dev_docs/20260421_6/analysis/04_plugin_extensibility_and_proposed_extension_points.md §9`
- `dev_docs/20260421_6/plan/05_cycle_and_pr_breakdown.md §5`

## 목표

X1~X4 에서 도입한 확장 표면 (PersonaProvider, MoodBlock / VitalsBlock /
RelationshipBlock / ProgressionBlock, AffectTagEmitter, game tools,
TickEngine registrations, SessionLifecycleBus listeners, EventSeedPool,
ManifestSelector) 을 `GenyPlugin` Protocol 로 *번들화* 해, 새 기능을
Geny 코어 수정 없이 **플러그인 모듈 추가** 로 도입할 수 있게 한다.

- **한 개 플러그인 = 한 개 생태계 조각.** "tamagotchi" 는 state +
  blocks + seeds + tools + decay ticker + progression selector 의
  번들; "live2d" 는 avatar state + affect emitter 의 번들.
- **17번째 stage 금지** (analysis 04 §9). stage 를 안 늘리고, 기존 7개
  확장 표면 (attach_runtime, s03 PromptBlock, s14 Emitter, TickEngine,
  Tool, SessionLifecycleBus, ManifestSelector) 에 얹는다.
- **Geny 코어는 PluginRegistry 만 안다.** 각 Plugin 의 `contribute_*`
  결과를 해당 확장 표면에 분배한다. Plugin 은 서로를 모른다.

## PR 분해

`plan/05 §5.2` 기준 5 PR. executor bump (X5-4/5-5) 는 "정말 필요하면"
전용 (plan/05 §5.3) — 현 MVP 는 ToolContext.metadata / shared dict 로
이미 다 지나가므로 **선연기**.

| PR | 브랜치 | 리포 |
|---|---|---|
| PR-X5-1 | `feat/geny-plugin-protocol` | Geny |
| PR-X5-2 | `feat/plugin-registry-and-loader` | Geny |
| PR-X5-3 | `refactor/tamagotchi-as-plugin` | Geny (X3-X4 를 GenyPlugin 로 재포장) |
| PR-X5-4 | `feat/attach-runtime-session-runtime-kwarg` | **geny-executor** (defer 기본) |
| PR-X5-5 | `chore/pin-executor-0.30.0` | Geny (X5-4 선행 필수) |

## 불변식

- **Plugin contribute_* 는 순수 함수에 가깝게.** stateful 초기화는
  Plugin `__init__` 시점 (Registry 생성 단계) 에 끝내고, per-session
  호출 (`contribute_prompt_blocks(session_ctx)` 등) 은 side-effect 없이
  값만 반환.
- **Plugin 끼리의 이름 충돌 금지.** `PluginRegistry.register` 가
  중복 name 에 raise. discovery path 는 "먼저 등록된 것 우선" 이
  아니라 "우선순위 미정 → 에러" — 조용히 replace 가 가장 잡기 어려운
  버그.
- **Plugin 결과 누락은 조용히 빈 리스트.** 어떤 훅 (`contribute_*`) 도
  optional — 구현 안 한 훅은 기본 빈 리스트를 리턴. Registry 가
  이 케이스를 *정상* 으로 처리.
- **executor 수정 최소 (0~1 줄).** 원칙적으로 0줄. ToolContext.metadata
  로 해결 안 되는 슬롯이 생기면 그때 X5-4 로 bump.

## 비범위 (X6 이월)

- AffectAwareRetrieverMixin — X6.
- entry-point 자동 discovery — optional, MVP 는 명시 등록만.
- plugin hot-reload / 런타임 교체 — 불필요.

## 산출 문서

- `plan/`  — 필요 시 Protocol 의 최종 확정 signature.
- `progress/pr1..pr5_*.md` — PR 진행 기록.
