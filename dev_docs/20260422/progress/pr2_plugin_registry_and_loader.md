# PR-X5-2 · `feat/plugin-registry-and-loader` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 28 plugin 전용 + 138 adjacent (lifecycle / tick /
persona / plugin) pass.

PR-X5-1 에서 `GenyPlugin` Protocol 을 찍었다면, 본 PR 은 그걸 담는
컨테이너 + 확장 표면으로의 fan-out 을 구현한다. analysis 04 §9 원칙:
"Registry 는 surface 를 알고, Plugin 끼리는 서로를 모른다."

## 범위

### 1. `backend/service/plugin/registry.py` — `PluginRegistry`

**Registration**

- `register(plugin)` — 구조적 `isinstance(plugin, GenyPlugin)` 검증,
  빈 `name` 거부, 중복 `name` → `DuplicatePluginError` raise.
- `plugins` property — 등록 순서 보장된 read-only tuple 스냅샷.
- `__len__` / `__contains__("name")` / `get("name")` 편의.

이름 중복에 조용히 replace 안 함 — plan/index §불변식 "조용히
replace 가 가장 잡기 어려운 버그" 원칙 준수.

**Per-session collection** (SessionContext 인자)

- `collect_prompt_blocks(ctx) -> Sequence[PromptBlock]` — 등록 순서
  대로 flat.
- `collect_emitters(ctx) -> Sequence[Emitter]` — 동일.
- `collect_attach_runtime(ctx) -> Mapping[str, Any]` — **키 충돌시
  `AttachRuntimeKeyConflict` raise**. 메시지에 경합한 두 플러그인
  이름을 모두 담아 디버깅 용이. Namespacing 의무는 plugin author
  측.

**Registry-global collection** (인자 없음)

- `collect_tickers()` — flat `Sequence[TickSpec]`.
- `collect_tools()` — flat `Sequence[Any]`.
- `collect_session_listeners() -> Mapping[LifecycleEvent, Sequence[SessionListener]]`
  — plugin 이 `Mapping[str, ...]` 으로 낸 키를 `LifecycleEvent` 로
  변환. 알 수 없는 이벤트 이름은 `UnknownLifecycleEventError` —
  typo 로 listener 가 조용히 fire 안 되는 사태 차단.

**Apply helpers** (registry-global surface)

- `apply_tickers(engine: TickEngine)` — `engine.register` 가 이미
  중복 name 을 `ValueError` 로 raise 하므로 별도 방어 불필요.
- `apply_session_listeners(bus: SessionLifecycleBus)` — 매
  (event, listener) 쌍을 `bus.subscribe(...)` 로 등록. Token 은
  유지 안 함 (registry 가 bus 보다 오래 산다고 가정; 필요시
  리턴값 추가는 non-breaking).

Per-session surface (prompt_blocks, emitters, attach_runtime) 은
apply helper 를 제공하지 않는다 — `CharacterPersonaProvider` 구성,
`Pipeline.attach_runtime`, s14 `EmitterChain` 수정은 session builder
가 소유. Registry 가 `PipelineState` 나 Provider 생성자에 커플되지
않게 선긋기.

### 2. 에러 타입

- `DuplicatePluginError(ValueError)` — 동명 플러그인 재등록.
- `AttachRuntimeKeyConflict(ValueError)` — attach_runtime 키 충돌.
- `UnknownLifecycleEventError(ValueError)` — 알 수 없는 이벤트 이름.

전부 `ValueError` 서브클래스 — 기존 try/except ValueError 경로와
호환. 동시에 구체 타입으로 잡고 싶을 때는 개별 캐치 가능.

### 3. `backend/service/plugin/__init__.py`

네 심볼 추가 재노출: `PluginRegistry`, `DuplicatePluginError`,
`AttachRuntimeKeyConflict`, `UnknownLifecycleEventError`.

## 테스트 — `backend/tests/service/plugin/test_registry.py`

19 신규 + 기존 9 protocol 테스트 = 28 개 전부 pass. 신규 커버:

**Registration (5)**
- `test_register_accepts_plugin_and_tracks_order`
- `test_register_duplicate_name_raises`
- `test_register_empty_name_raises`
- `test_register_non_plugin_raises` — dict 만 있는 가짜 객체 거부
- `test_plugins_property_is_read_only_snapshot` — 이후 등록은
  이미 꺼낸 스냅샷에 영향 없음

**Per-session collection (5)**
- `test_collect_prompt_blocks_preserves_registration_order`
- `test_collect_emitters_flat_list`
- `test_collect_attach_runtime_merges_non_conflicting_keys`
- `test_collect_attach_runtime_conflict_raises_with_owners` — 메시지에
  두 plugin name 포함
- `test_collect_attach_runtime_empty_for_empty_registry`

**Registry-global collection (4)**
- `test_collect_tickers_flat_list`
- `test_collect_tools_flat_list`
- `test_collect_session_listeners_groups_by_event`
- `test_collect_session_listeners_unknown_event_raises`

**Apply helpers — 실제 surface 통합 (3)**
- `test_apply_tickers_registers_on_engine` — engine.register 직후
  동명으로 재등록 시도 → `ValueError` 확인으로 실제 등록 검증
- `test_apply_tickers_duplicate_names_across_plugins_raise_via_engine`
- `test_apply_session_listeners_subscribes_and_dispatches` —
  `asyncio.run` 으로 실제 bus.emit → handler 호출 검증
- `test_apply_session_listeners_multiple_plugins_same_event_all_fire`
  — 여러 플러그인이 같은 이벤트 구독 시 전부 fire

**Structural 호환 (1)**
- `test_registry_accepts_structural_plugin` — `PluginBase` 미상속
  duck-typed 플러그인도 등록됨

## 주변 회귀

```
pytest backend/tests/service/lifecycle/ backend/tests/service/tick/ \
       backend/tests/service/persona/ backend/tests/service/plugin/
```

→ 138 passed. 기존 bus/tick/persona 테스트 모두 무영향.

## 설계 선택

### Collect 와 apply 를 분리

"register → apply 전부" 식의 거대 메서드를 만들지 않은 이유:

1. `apply_tickers` / `apply_session_listeners` 는 registry-global
   surface 라서 "프로세스 시작 시 1번" 경로. 반면 prompt_blocks /
   emitters / attach_runtime 은 per-session — session builder 가
   `CharacterPersonaProvider(live_blocks=reg.collect_prompt_blocks(ctx))`
   같이 *생성자 인자* 로 취해가야 한다. registry 가 provider 를
   알 필요 없음.
2. 테스트 용이성: collect 만 불러도 반환값을 검증할 수 있어, apply
   side 를 모킹하지 않아도 됨.
3. 확장성: 다른 surface (예: manifest selector 계층) 가 추가될 때
   `collect_*` 만 추가하면 되고, 호출측이 원하는 모양으로 wire up.

### Unknown event 에서 raise (경고가 아니라)

`log.warning` + 무시 도 가능한 선택이었지만, listener 하나가
조용히 구독 안 되면 그 이벤트가 영영 fire 안 되는 걸 런타임까지
못 알아차림. 반면 시작 시 raise 면 배포 단계에서 잡힘.

### Token 유지 안 함

`apply_session_listeners` 는 subscription token 을 보관/리턴하지
않는다. MVP 에서 unsubscribe 유스케이스가 없고, registry 는
bus 보다 수명이 길거나 같다고 가정. 추후 필요 시 리턴값에
`Sequence[SubscriptionToken]` 을 추가해도 기존 caller 무영향.

## 의도적 이월

- **Tool 실시간 등록 경로** — executor 의 `ToolLoader` 는 현재
  manifest 기반이라 live `register_tool` 이 없음. `collect_tools()`
  는 값만 수집하므로 PR-X5-3 에서 tamagotchi 번들을 재포장할 때
  (또는 그 이후 tool registry 리팩터에서) wire up.
- **AgentSessionManager 와의 배선** — PR-X5-3. 지금은 registry 만
  독립 유닛으로 쓸 수 있는 상태. 세션 구축 경로에 실제로 꽂는 건
  tamagotchi/live2d 번들을 플러그인화하는 다음 PR 에서 한 번에.
- **Entry-point discovery** — plan/index 비범위. X6 이월.
- **Hot reload / unregister** — 불필요.

## 다음 PR

PR-X5-3 `refactor/tamagotchi-as-plugin` — X3/X4 에서 `AgentSessionManager`
내부에 직접 wire 한 tamagotchi 생태계 (CreatureStateProvider,
live blocks, game tools, TickEngine decay, SessionLifecycleBus
listener, EventSeedPool, ManifestSelector) 를 단일 `TamagotchiPlugin` 로
재포장하고 `PluginRegistry` 에 등록. 기존 471+ 테스트 full pass
유지가 완료 조건.
