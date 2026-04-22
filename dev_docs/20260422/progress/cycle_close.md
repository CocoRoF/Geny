# Cycle 20260422 — X5 종료 정리

**Date.** 2026-04-22
**Shipped.** PR-X5-1, PR-X5-2, PR-X5-3 (3 PR merge)

## 정착한 것

| PR | 브랜치 | 내용 |
|---|---|---|
| PR-X5-1 | `feat/geny-plugin-protocol` | `GenyPlugin` runtime_checkable Protocol + `PluginBase` no-op defaults. 6 `contribute_*` 훅 (prompt_blocks / emitters / attach_runtime / tickers / tools / session_listeners). `SessionContext = Mapping[str, Any]`. |
| PR-X5-2 | `feat/plugin-registry-and-loader` | `PluginRegistry` — register / duplicate name raise / `collect_*` fan-out / `apply_tickers` / `apply_session_listeners`. `DuplicatePluginError`, `AttachRuntimeKeyConflict`, `UnknownLifecycleEventError`. |
| PR-X5-3 | `refactor/tamagotchi-as-plugin` | `TamagotchiPlugin` — 4 live block + EventSeedPool 을 plugin 으로 재포장. `AgentSessionManager.__init__` 이 registry 경유로 블록을 전달. |

**테스트 성장치:** plugin suite 0 → 36 tests. 회귀 없음.

## 의도적으로 미이식 (의미 있는 이월)

X5 의 원래 ambition 은 state/blocks/seeds/tools/decay/selector 를 한
`TamagotchiPlugin` 으로 묶는 것이지만, 각 요소별로 배선 코드가 여러
모듈에 흩어져 있어서 "한 PR = 한 방향" 원칙 (plan/05 §9) 을 지키려면
쪼개야 한다:

- **CreatureStateProvider / DecayService** → `main.py` + `agent_session.py`
  공동 수정 필요. `attach_runtime(state_provider=)` 경유로 이동하려면
  executor bump 선행 — PR-X5-4 관할.
- **AffectTagEmitter** → emit chain 배선 리팩터 (현재
  `install_affect_tag_emitter(pipeline)` 직접 호출). 별도 follow-up.
- **ManifestSelector** → character-driven collaborator. Protocol 6 훅에
  맞지 않음. 7 번째 훅 추가 여부는 X6 범위 재평가 때 결정.
- **Game tools** → `ToolLoader` 가 manifest-driven. Live
  `register_tool` API 부재라 `contribute_tools` 결과 소비처 없음.

## PR-X5-4 / PR-X5-5 — 공식 선연기

plan/index §비범위 와 plan/05 §5.3 명시:

> executor bump (X5-4 / 5-5) 는 "정말 필요하면" 전용 … 현 MVP 는
> ToolContext.metadata / shared dict 로 이미 다 지나가므로 **선연기**.

지금 MVP 경로에 executor 수정 필요 지점 없음. attach_runtime 에
새 kwarg 슬롯이 실제로 요구되는 순간 (예: plugin 이 state provider 를
pipeline 단계에서 읽어야 할 때) X5-4 재개.

태스크 트래커상 `#223`, `#224` 는 pending 유지 — 필요 발생 시 즉시
진입 가능한 상태.

## 불변식 체크 (plan/05 §8)

X5 PR 을 통해 깨지지 않은 것:

1. executor 는 게임을 모른다 → X5 는 Geny 리포만 수정. ✅
2. Stage 는 Provider 를 직접 잡지 않는다 → Plugin / Registry 는
   stage 레이어에 침투 안 함. state.shared 경유 그대로. ✅
3. Mutation 은 4 op → 영향 없음. ✅
4. Decay 는 TickEngine 에만 → DecayService 위치 무변화. ✅
5. Side-door 재생 금지 → Plugin 은 공식 확장 표면으로만 기여. ✅
6. Manifest 전환은 세션 경계 → 영향 없음. ✅
7. Shadow mode 우선 → X5 는 state 변경형 변경 없음 (구조만). N/A. ✅

## 다음 사이클 — X6

`plan/05 §6` 의 4 PR 골격:

- PR-X6-1 `feat/memory-schema-emotion-fields`
- PR-X6-2 `feat/affect-aware-retriever-mixin`
- PR-X6-3 `tune/prompt-cache-bucketing`
- PR-X6-4 `chore/retrieval-cost-dashboard`

§6.3 의 "연구 성격" 경고: *PR-X6-3 / PR-X6-4 는 실사용 데이터가
필요하다*. X1-X5 구축분만으로는 튜닝 파라미터를 못 뽑음. X6-1 /
X6-2 는 infra 추가형이라 데이터 없이도 가능.

다음 스텝: X6 사이클 진입 — 사이클 index 작성 후 PR-X6-1 부터
정식 개시.
