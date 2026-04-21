# Plan 05 — 사이클 · PR 분해 (X1..X6)

**작성일.** 2026-04-21
**선행.** `plan/01` (전략 D), `plan/02` (CreatureState 계약), `plan/03` (구조적 보완),
`plan/04` (다마고치 레이어링).
**본 문서의 책임.** `analysis/05` 의 로드맵 X1..X6 을 **사이클 단위** → **PR 단위** →
**파일·라인 수준** 으로 분해. 각 사이클의 브랜치명, 의존, 회귀 위험, 롤아웃 순서, 릴리즈
연계까지 확정.

**실행 원칙.** 각 사이클은 *자체 `dev_docs/YYYYMMDD_N/` 폴더* 에 분석 + 계획 + 진행 을
작성한 뒤 착수. 본 문서는 그 사이클들의 **사전 청사진** 이며, 사이클 진입 시 반드시 *재검증*.

---

## 0. 의존 그래프 (최종)

```
                  ┌─────────────────────────────────────────────┐
                  │   X1 : PersonaProvider & 사이드도어 철거    │
                  └──────────────┬──────────────────────────────┘
                                 │
                  ┌──────────────┴────────────┐
                  ▼                           ▼
      ┌──────────────────────┐    ┌───────────────────────────┐
      │ X2 : Bus + TickEngine│    │  (X1 단독으로도 PR가능)   │
      └──────┬───────────────┘    └───────────────────────────┘
             │
             ▼
   ┌─────────────────────────────┐
   │ X3 : CreatureState MVP      │ (X1 ∧ X2 필요)
   │ + 4 Tools + AffectTagEmitter│
   │ + Mood/Bond/Vitals Blocks   │
   └──────────┬──────────────────┘
              │
              ▼
   ┌─────────────────────────────┐
   │ X4 : Progression + Manifest │
   │   전환 + EventSeed          │
   └──────────┬──────────────────┘
              │
              ▼
   ┌─────────────────────────────┐
   │ X5 : Plugin Protocol &      │  (executor 0.30.0 bump — optional)
   │   Registry; session_runtime │
   └──────────┬──────────────────┘
              │
              ▼
   ┌─────────────────────────────┐
   │ X6 : AffectAware retrieval  │
   │   + 비용 최적화              │
   └─────────────────────────────┘
```

**핵심 선후.** X1 과 X2 는 병렬 가능. X3 은 X1 ∧ X2. X4 은 X3. X5/X6 은 X4 이후 순차.

---

## 1. X1 — PersonaProvider & 사이드도어 철거

### 1.1. 범위

- `backend/service/persona/` 트리 신설.
- `DynamicPersonaSystemBuilder` 운영 경로화.
- `_system_prompt` 3곳 사이드도어 제거.
- Mood/Relationship/Vitals Block 의 *자리만* (no-op) 만들어 X3 대비.

### 1.2. PR 분해

| PR | 브랜치 | 타깃 리포 | 핵심 파일 | 회귀 위험 |
|---|---|---|---|---|
| PR-X1-1 | `feat/persona-provider-skeleton` | Geny | `backend/service/persona/{provider.py,blocks.py,dynamic_system_builder.py}` 신설 | 낮음 (opt-in, 경로 미사용) |
| PR-X1-2 | `feat/character-persona-provider` | Geny | `backend/service/persona/character_provider.py` | 낮음 |
| PR-X1-3 | `refactor/remove-system-prompt-sidedoors` | Geny | `vtuber_controller.py:49-54`, `agent_controller.py:304`, `agent_session_manager.py:673`, `agent_session.py:_build_pipeline` | **중** (행동 동등성 확인 필수) |
| PR-X1-4 | `test/persona-e2e` | Geny | 통합/스냅샷 테스트 | 낮음 |

### 1.3. 파일 수준 변경 (PR-X1-3 상세)

- `vtuber_controller.py` — `pipeline._system_prompt = ...` 삭제. 대신
  `persona_provider.select_character(cid)` 호출.
- `agent_controller.py` — `/system_prompt` 엔드포인트를
  `persona_provider.set_static_override(text)` 호출로 대체. 응답 스키마는 그대로
  (`{"ok": true}`) — 호출자 호환.
- `agent_session_manager.py` — "resume 시 VTuber context append" 코드를
  `persona_provider.append_recent_context(text)` 로 라우팅.
- `agent_session.py:_build_pipeline` —
  `system_builder = DynamicPersonaSystemBuilder(persona_provider, static_builder=...)` 주입.

### 1.4. 테스트 스냅샷

- `tests/persona/test_sidedoor_removed.py`: `grep _system_prompt backend/` 결과 파일이 없음을
  보장.
- `tests/persona/test_character_switch.py`: 캐릭터 A → B 교체 시 다음 턴부터 state.system 이
  B 의 persona 로 구성되는지.
- 기존 `tests/vtuber/*` 회귀 전부 통과.

### 1.5. 롤아웃

- feature flag: `GENY_PERSONA_V2` (default=true). 2 주 후 flag 제거.
- 모니터링: prompt cache miss rate 스파이크 시 롤백.

### 1.6. 릴리즈 영향

- **executor 수정 없음.** v0.29.0 유지.
- Geny 만 버전 올림.

### 1.7. 산출 문서

- `dev_docs/<date>_X1/analysis/01_sidedoor_audit.md` — 3곳의 현 호출 관계 재확인.
- `dev_docs/<date>_X1/plan/01_persona_provider_design.md` — Protocol / Block 세부.
- `dev_docs/<date>_X1/progress/pr1..pr4_*.md` — PR 별.

---

## 2. X2 — SessionLifecycleBus + TickEngine

### 2.1. 범위

- `SessionLifecycleBus` 7 이벤트 구현.
- `TickEngine` 구현 + 기존 `thinking_trigger`, `avatar_state_manager` 이식.

### 2.2. PR 분해

| PR | 브랜치 | 타깃 | 핵심 파일 | 회귀 위험 |
|---|---|---|---|---|
| PR-X2-1 | `feat/session-lifecycle-bus` | Geny | `backend/service/lifecycle/bus.py`, `handlers/`, 단위 테스트 | 낮음 |
| PR-X2-2 | `refactor/lifecycle-emit-from-session-manager` | Geny | `agent_session_manager.py`, `websocket/*.py` 에서 bus emit | 중 |
| PR-X2-3 | `feat/tick-engine` | Geny | `backend/service/tick/engine.py`, fake clock 테스트 | 낮음 |
| PR-X2-4 | `refactor/thinking-trigger-on-tick-engine` | Geny | `service/thinking/trigger.py` 이식 | **중** (기존 동작 동등성) |
| PR-X2-5 | `refactor/avatar-state-on-tick-engine` | Geny | `service/vtuber/avatar_state_manager.py` 이식 | 중 |
| PR-X2-6 | `feat/websocket-idle-detection` | Geny | WebSocket idle / abandoned 감지 | 중 |

### 2.3. 주요 리스크와 완화

- **thinking_trigger 시점 변동.** Tick 기반으로 바뀌면서 *정확한 시각* 이 달라질 수 있음.
  완화: 테스트 시나리오에서 "± jitter 1s" 허용. 통계 기반 동등성.
- **avatar_state_manager 의 짧은 주기.** 2s tick 이 과도하면 CPU 낭비. 완화: 유저 *활성*
  상태에서만 고빈도, 비활성 시 30s 로 드롭.

### 2.4. 롤아웃

- PR-X2-1..3 은 독립 병합 가능.
- PR-X2-4/5 는 기존 서비스를 *대체* 하므로 한 번에 배포 → 즉시 검증.
- 2 주 소프트 롤백 가능 구조 유지 (deprecated 코드 삭제 지연).

### 2.5. executor 영향

- 없음.

### 2.6. 완료 판정

- `lifecycle_event_total{event="*"}` 메트릭의 모든 이벤트가 non-zero 로 집계됨.
- `tick_handler_duration_ms{name="thinking_trigger"}` p95 가 구 구현 대비 ±20% 이내.

### 2.7. 산출 문서

- `dev_docs/<date>_X2/analysis/01_lifecycle_events_current_state.md`
- `dev_docs/<date>_X2/analysis/02_tick_cadences_inventory.md`
- `dev_docs/<date>_X2/plan/01_bus_contract.md`
- `dev_docs/<date>_X2/plan/02_tick_engine_contract.md`
- `dev_docs/<date>_X2/progress/pr1..pr6_*.md`

---

## 3. X3 — CreatureState MVP

### 3.1. 범위 (Plan 02 + 04 §1–§5/§9 의 MVP)

- `backend/service/state/` 트리 (schema / provider / registry / decay).
- `SessionRuntimeRegistry` 가 `AgentSession` 에 주입, hydrate/persist 운영.
- `FeedTool`, `PlayTool`, `GiftTool`, `TalkTool`.
- `AffectTagEmitter`.
- MoodBlock / RelationshipBlock / VitalsBlock 의 X1 no-op 을 *실제 구현* 으로 전환.
- VTuberEmitter 를 mood 기반 표정 선택으로 업그레이드.
- TickEngine 에 `decay` spec 등록 (15 분 주기).

### 3.2. PR 분해

| PR | 브랜치 | 핵심 파일 | 종속 |
|---|---|---|---|
| PR-X3-1 | `feat/state-schema` | `backend/service/state/schema/*` | — |
| PR-X3-2 | `feat/state-provider-sqlite` | `provider/interface.py`, `provider/sqlite_creature.py`, SQL migration | PR-X3-1 |
| PR-X3-3 | `feat/session-runtime-registry` | `registry.py`, `hydrator.py` | PR-X3-2 |
| PR-X3-4 | `feat/decay-and-tick-registration` | `decay.py`, TickEngine spec 등록 | PR-X3-2, X2-3 |
| PR-X3-5 | `feat/agent-session-integrates-state` | `service/langgraph/agent_session.py` run_turn 주변 | PR-X3-3 |
| PR-X3-6 | `feat/game-tools-basic` | `service/game/tools/{feed,play,gift,talk}.py` + `GenyToolProvider` 등록 | PR-X3-5 |
| PR-X3-7 | `feat/affect-tag-emitter` | `service/emit/affect_tag_emitter.py`, s14 체인 등록 | PR-X3-5 |
| PR-X3-8 | `feat/mood-rel-vitals-blocks-live` | X1 의 no-op 블록을 실제 구현으로 | PR-X3-5 |
| PR-X3-9 | `feat/vtuber-emitter-mood-aware` | `service/vtuber/emitter.py` mood 기반 표정 | PR-X3-5 |
| PR-X3-10 | `test/state-e2e` | 10 §10.3 시나리오 S1~S4 E2E | PR-X3-5..9 |

### 3.3. 파일 목록 (X3-1/2/3 만 예시)

```
backend/service/state/
├── __init__.py                     (X3-1)
├── schema/
│   ├── creature_state.py           (X3-1)
│   ├── mutation.py                 (X3-1)
│   └── mood.py                     (X3-1)
├── provider/
│   ├── interface.py                (X3-2)
│   ├── sqlite_creature.py          (X3-2)
│   └── migrations/
│       └── 0001_initial.sql        (X3-2)
├── registry.py                     (X3-3)
├── hydrator.py                     (X3-3)
└── decay.py                        (X3-4)
```

### 3.4. 롤아웃 전략

- **Shadow mode.** PR-X3-5 까지는 provider.apply 를 **log-only** 로 동작 (실제 DB write 안 함).
  2~3 일간 기존 세션 관측. 로그 검증 후 PR-X3-5 의 feature flag 제거.
- `GENY_GAME_FEATURES` 환경변수로 "게임 기능 off" (shared['creature_state'] 미주입) 경로 유지.
  초기 롤아웃은 일부 유저만.

### 3.5. 데이터 · 마이그레이션

- SQL migration 파일 `0001_initial.sql` 이 `creature_state` 테이블 생성.
- 기존 유저에게는 데이터 없음 → 첫 접속 시 default 인스턴스 자동 생성.

### 3.6. 릴리즈 영향

- **executor 수정 없음.**
- Geny 는 game feature minor bump.

### 3.7. 위험

- **mutation flood.** LLM 이 태그 남발 → mutation 폭주. 완화: `max_tag_mutations_per_turn = 3`.
- **decay 과속.** 수치 튜닝 실수로 24h 내 모든 캐릭터가 limbo 상태. 완화: shadow mode +
  dry-run 분석.
- **persistence 실패.** 유저 응답은 이미 전송됨, mutation 은 증발. 다음 턴의 hydrate 에서
  "뭔가 놓친" 상태. 완화: mutation 의 일부는 `recent_events` 로 idempotent 하게 재제출 가능.

### 3.8. 완료 판정

- 10 §10.3 S1~S4 시나리오 전부 Pass.
- `state_persist_duration_ms` p95 < 100ms.
- `state_conflict_total` 비율 < 0.1%.

### 3.9. 산출 문서

- `dev_docs/<date>_X3/analysis/{01_contract_recheck.md, 02_db_schema_risks.md}`
- `dev_docs/<date>_X3/plan/{01_rollout.md, 02_balance_table.md}`
- `dev_docs/<date>_X3/progress/pr1..pr10_*.md`

---

## 4. X4 — Progression & Manifest 전환 + EventSeed

### 4.1. 범위

- `ManifestSelector` 와 life_stage 전환 그래프.
- `EventSeedPool` 과 6~10개 시드 샘플.
- `ProgressionBlock` (X1 에서 자리만).
- Manifest 를 stage 별로 선언 (`manifests/infant_*.yaml`, `child_*.yaml`, ...).

### 4.2. PR 분해

| PR | 브랜치 | 핵심 |
|---|---|---|
| PR-X4-1 | `feat/manifest-selector` | `service/progression/selector.py`, `trees/default.py` |
| PR-X4-2 | `feat/stage-manifests-infant-child-teen` | `manifests/` 파일 신설 |
| PR-X4-3 | `feat/progression-block-live` | `persona/blocks.py` 의 ProgressionBlock 를 실제 구현 |
| PR-X4-4 | `feat/event-seed-pool` | `service/game/events/{pool.py,seeds/*.py}` |
| PR-X4-5 | `feat/selector-integrated-into-session-build` | `agent_session.py` 세션 시작 시 선택 |
| PR-X4-6 | `test/progression-e2e` | 14일 시뮬레이션 E2E |

### 4.3. 롤아웃

- Manifest 전환은 **세션 시작 시에만** — 턴 중간 전환 금지 (UX 혼란).
- 전환 알림은 이벤트 시스템에 남기고, UI 가 "어른이 되었다" 연출.

### 4.4. 위험

- **전환 누락.** 조건 predicate 가 너무 빡빡하면 성장 정체. 완화: 데이터 기반 분포 모니터.
- **Manifest drift.** 여러 stage manifest 의 설정이 덩어리째 갈라지면 유지보수 폭발.
  완화: 공통 include 지원 (manifest anchor) 또는 preset 기반.

### 4.5. 산출 문서

- `dev_docs/<date>_X4/analysis/01_growth_tree_design.md`
- `dev_docs/<date>_X4/plan/01_manifest_layout.md`
- ...

---

## 5. X5 — Plugin Protocol & Registry (옵션: executor bump)

### 5.1. 범위

- `GenyPlugin` Protocol — slot injection + PromptBlock + Emitter + Tick + SessionListener 의
  **번들**.
- Plugin Registry (Geny-side entry-point 혹은 명시 등록).
- **optional**: executor `attach_runtime(session_runtime=...)` 추가 (0.30.0).

### 5.2. PR 분해

| PR | 브랜치 | 리포 |
|---|---|---|
| PR-X5-1 | `feat/geny-plugin-protocol` | Geny |
| PR-X5-2 | `feat/plugin-registry-and-loader` | Geny |
| PR-X5-3 | `refactor/tamagotchi-as-plugin` | Geny (X3-X4 를 GenyPlugin 에 재포장) |
| PR-X5-4 | `feat/attach-runtime-session-runtime-kwarg` | **geny-executor** |
| PR-X5-5 | `chore/pin-executor-0.30.0` | Geny |

### 5.3. executor bump 는 정말 필요한가

- 현재 전략 D 로 이미 모든 장기 상태가 동작.
- `session_runtime` kwarg 는 *편의* — stage 가 Provider 를 직접 잡고 싶은 경우 1~2 %.
- X5 시점에 플러그인 생태계가 실제로 요구하면 bump. 아니면 연기.

### 5.4. 산출 문서

- `dev_docs/<date>_X5/analysis/01_plugin_shape_candidates.md`
- `dev_docs/<date>_X5/plan/01_protocol_design.md`

---

## 6. X6 — AffectAware Retrieval & 비용 최적화

### 6.1. 범위

- `AffectAwareRetrieverMixin` 도입.
- memory schema 에 `emotion_vec`, `emotion_intensity` 필드 추가 (nullable 옵션).
- prompt cache 튜닝 (Plan 04 §2.4 의 bucket 전략 실측/조정).

### 6.2. PR 분해

| PR | 브랜치 |
|---|---|
| PR-X6-1 | `feat/memory-schema-emotion-fields` |
| PR-X6-2 | `feat/affect-aware-retriever-mixin` |
| PR-X6-3 | `tune/prompt-cache-bucketing` |
| PR-X6-4 | `chore/retrieval-cost-dashboard` |

### 6.3. 이 사이클의 "연구" 성격

- 실 데이터 없이는 파라미터 튜닝 불가. X4 까지의 사용량 데이터로 fitting.
- 필요 시 별도 미니-사이클로 쪼갬.

---

## 7. 릴리즈 타임라인 (제안)

| 시점 | 사이클 | executor 버전 | Geny 버전 | 비고 |
|---|---|---|---|---|
| T+0 주 | X1 PR 연속 | 0.29.0 | minor↑ | 병렬 가능 |
| T+0 주 | X2 PR 연속 | 0.29.0 | minor↑ | X1 과 병렬 |
| T+3 주 | X3 시작 | 0.29.0 | minor↑ | X1 ∧ X2 후 |
| T+6 주 | X3 MVP 완료 | 0.29.0 | — | shadow → live |
| T+9 주 | X4 | 0.29.0 | minor↑ | |
| T+14 주 | X5 | 0.29.0 또는 0.30.0 | major↑ (옵션) | plugin protocol 결정 |
| T+16 주 | X6 | 0.29.0 or 0.30.0 | minor↑ | |

**이 표는 인력 1~2 명 기준의 *가이드* 일 뿐.** 매 사이클 진입 시 재평가.

---

## 8. 각 사이클이 깨지 말아야 할 것 (불변식)

모든 사이클을 관통하는 *반드시 지켜야 할 규약*:

1. **executor 는 게임을 모른다.** executor 코드에 `creature`, `affection`, `tamagotchi` 등
   문자열 금지. 어떤 사이클이든 executor 에 게임 어휘가 섞이면 PR 반려.
2. **Stage 는 Provider 를 직접 잡지 않는다.** 항상 state.shared 경유. 위반은 lint rule
   (`grep` 기반 CI) 로 차단.
3. **Mutation 은 4 op 제한.** 규칙 확장 금지.
4. **Decay 는 TickEngine 에만.** Pipeline 내 decay 호출 금지.
5. **Side-door 재생 금지.** `_system_prompt` 류 직접 변이 영원히 금지.
6. **Manifest 전환은 세션 경계에서만.** 턴 중간 교체 금지.
7. **Shadow mode 로 먼저.** state-변경형 변경은 전부 log-only → live 순서.

---

## 9. 각 사이클의 *백아웃* 원칙

- 각 사이클은 *적어도 2 주* 간 이전 구현을 주석/deprecated 형태로 유지 가능해야 함.
- 이를 위해 "한 PR 당 한 방향의 변경" 원칙. 대규모 재작성 PR 은 *원칙적으로* 금지.
- X3 의 DB migration 은 역마이그레이션 스크립트를 항상 함께 제공.

---

## 10. 사이클별 KPI 최소 집합

| 사이클 | KPI |
|---|---|
| X1 | side-door count == 0 / prompt cache hit ≥ baseline ±5% |
| X2 | lifecycle event full-coverage / tick handler p95 within ±20% |
| X3 | 시나리오 S1~S4 pass / persist p95 < 100ms / conflict rate < 0.1% |
| X4 | life-stage 분포가 시뮬레이션 기대치 대비 ±30% 이내 |
| X5 | plugin 3개 (tamagotchi / vtuber / curation) 를 GenyPlugin 으로 선언 성공 |
| X6 | retrieval mAP@10 기존 대비 ≥ +5% / 토큰 소모 ≤ 기존 ±10% |

---

## 11. 문서 생성 규칙 (각 사이클 착수 시)

본 문서가 아무리 상세해도, 실제 사이클 진입 시 환경 / 코드 / 의존 / 툴은 달라져 있다.
각 사이클 X* 는 반드시 다음 순서로 *자체 dev_docs 폴더* 를 먼저 만든다:

1. `analysis/01_*.md` — 본 PLAN 의 전제를 *현재 코드 기준으로 재검증*.
2. `analysis/02_*.md` (필요 시) — 새로 발견된 격차.
3. `plan/01_*.md` — 본 PLAN 의 해당 절을 *현재 코드 기준 PR 단위로* 재기술.
4. `progress/prN_*.md` — PR 단위 진행.
5. `index.md` — 상기 4 를 묶어 사이클 요약.

본 문서와의 관계는 `analysis/01` 의 *"ref"* 섹션에 기재 — "본 사이클의 사전 청사진은
`dev_docs/20260421_6/plan/05_cycle_and_pr_breakdown.md §N` 이다" 식으로.

---

## 12. 미결 (OPEN QUESTIONS)

본 PLAN 이 남긴, 각 사이클 진입 시 해결이 필요한 질문들:

1. **멀티 character 동시 소유.** 한 유저가 3마리 기르는 시나리오에서 UI·세션 동시성.
   — X3 이후 UX/product decision.
2. **결제 / 재화.** EventSeed 중 일부가 결제 아이템으로 이어지는 구조? — 사업적 결정, 본 PLAN 밖.
3. **LLM 이 AffectTag 를 쓰도록 학습 유도.** SystemBuilder 에 얼마나 강하게 지시? A/B 실험 필요.
4. **사용자간 공유 / SNS.** CreatureState 의 일부를 친구에게 보이기? privacy / consent 설계.
5. **Executor 의 preset 방식으로 Plugin 을 선언** 하는 것이 더 나은가? X5 에서 결정.

---

## 13. 요약

- **분석 (analysis/01~05)** — 아키텍처를 코드로 *확정*.
- **Plan 01** — 장기 상태 전략 D 선정.
- **Plan 02** — CreatureState 의 전 계약.
- **Plan 03** — X1/X2 의 구조적 보완.
- **Plan 04** — X3/X4 이후의 게임 레이어링.
- **Plan 05 (본 문서)** — 모든 사이클의 PR 단위 분해.

**이 5개 plan + 5개 analysis 문서가 본 사이클 (`20260421_6`) 의 산출물의 전부.**
구현 착수는 반드시 유저의 명시적 허가 + 각 사이클별 자체 dev_docs 생성 후.
