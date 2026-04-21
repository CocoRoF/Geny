# Plan 01 — 장기 상태관리 전략 심층 분석

**작성일.** 2026-04-21
**선행 분석.** `analysis/01_16stage_architecture_deepdive.md`, `analysis/05_gaps_risks_and_roadmap.md`
**판정 대상.** "16-STAGE 한 번의 실행 ≡ 하나의 Environment 구동" 이라는 관점에서,
Environment **다수 회 실행 사이**에 `CreatureState` (애정도/배고픔/피로/스트레스/관계 누적치/진행도)
같은 **장기 상태 (long-running state)** 를 어떻게 표현하고, 어떻게 유지하며,
어디서 갱신하고, 어디서 영속화할 것인가.

이 문서는 **네 가지 후보 전략을 끝까지 비교한 뒤, 권장안을 확정** 한다.
데이터 모델 · 마이그레이션 · 동시성 등 세부 계약은 `plan/02` 에서 다룬다.

---

## 0. 문제의 재정의

**유저 발화의 핵심 2문장.**

> "스테이지를 확장하지 않는다는 관점에서 어떻게 여러 번의 ENVIRONMENT(16STAGE) 실행 간의
> 강력한 State 를 유지할 수 있을까."
> "(혹은 이것을 유지하기 위해 PHASE A 에 추가적인 Stage 를 만들고, 그것을 이용해 Status 를
> 처리하는 방식은 어떤지)"

유저는 두 방향을 동시에 제시하고 있다:

- **R1.** 스테이지 확장 없이 → 어떻게 하나의 pipeline.run 이 끝난 후, 다음 pipeline.run 이
  시작되기 전까지의 "상태" 를 표현하고 주입할 것인가?
- **R2.** 만약 Phase A 에 stage 를 추가한다면, 그 stage 는 정확히 어떤 계약을 가져야 하는가?

본 분석의 결론을 미리 밝히면:

- **R1 이 옳다.** Phase A 추가 stage 는 `_run_phases` 의 하드코딩 때문에 **작동 자체가 불가능** 하거나,
  작동시키려면 executor 의 실행 모델을 재정의해야 한다. 그 비용이 이득을 크게 넘어선다.
- **전략 D (External Environment Wrapper) + 전략 A 의 1-line 선택적 확장** 이 권장안.
- Phase A 추가 stage 는 **원리적으로 금지** 하지 않지만, 장기 상태의 *정상 경로* 에는 사용하지 않는다.
  장기 상태는 pipeline 바깥 (Geny 의 AgentSession 레벨) 이 맞다.

---

## 1. 제약 — 코드가 강제하는 경계

### 1.1. `_run_phases` 는 order ∈ [1, 16] 만 실행

`core/pipeline.py:806-859`:

```python
async def _run_phases(self, input, state):
    # Phase A — 딱 order=1 하나만 하드코딩
    current = await self._run_stage(1, input, state)

    # Phase B — range(2, 14)
    while True:
        for order in range(self.LOOP_START, self.LOOP_END + 1):
            current = await self._try_run_stage(order, current, state)
        ...

    # Phase C — range(14, 17)
    for order in range(self.FINALIZE_START, self.FINALIZE_END + 1):
        current = await self._try_run_stage(order, current, state)
```

**귀결.**

- order = 0, 1.5, 17 로 stage 를 등록해도 `register_stage` 는 성공하지만
  `_run_phases` 는 **결코 실행하지 않는다** (dict 에만 남는다).
- 즉 "Phase A 에 추가 stage 를 만든다" 는 제안은 **executor 의 `_run_phases` 를
  변경해야만** 실현 가능하다. 이는 v1.0 의 실행 모델 자체를 깨는 행위다.

### 1.2. `describe()` 도 [1, 16] 만 iterate

`pipeline.py:788`:

```python
for order in range(1, 17):
    stage = self._stages.get(order)
```

**귀결.** UI 에 노출되는 슬롯은 16개로 고정. Phase A 확장 stage 는 UI 에서도 보이지 않는다.

### 1.3. `attach_runtime` 은 고정 6 kwargs

`pipeline.py:509-518`:

```python
def attach_runtime(
    self, *,
    memory_retriever=None, memory_strategy=None, memory_persistence=None,
    system_builder=None, tool_context=None, llm_client=None,
) -> None:
```

**귀결.** 새 주입점 (예: `creature_state_provider`) 을 깨끗하게 넣으려면 executor 가 kwarg 를
추가해야 한다 (I8). 1-line 변경이지만, executor 릴리즈 bump 를 요구한다.

### 1.4. `PipelineState.shared` 는 run 시작 때 리셋

`state.py:59`:

> "Resets to `{}` at the start of each run."

**귀결.** `shared` 는 **턴 안에서만 산다**. 턴 사이 state 보존은 shared 로 할 수 없다.
반드시 **외부 스토리지 + 턴 진입 시 재주입** 이 필요하다.

### 1.5. `ConversationPersistence.save/load(session_id, messages)` 는 **메시지 전용**

`stages/s15_memory/interface.py:22-41`:

```python
class ConversationPersistence(Strategy):
    async def save(self, session_id: str, messages: List[Dict[str, Any]]) -> None: ...
    async def load(self, session_id: str) -> List[Dict[str, Any]]: ...
    async def clear(self, session_id: str) -> None: ...
```

**귀결.** 기존 persistence 는 "메시지 로그" 를 위한 것. `CreatureState` 같은 **구조화된
세션 속성 벡터** 는 별도 persistence 를 가져야 한다 (의미도 수명도 다르다).

### 1.6. `MemoryUpdateStrategy.update(state)` 는 state 전체를 읽는다

s15 에서 `state.messages`, `state.final_text`, `state.events` 등을 읽어 메모리에 반영.
**state.shared['creature_state'] 를 읽어 mutation 을 추출** 하도록 확장하는 것은 가능하다.

---

## 2. 네 가지 후보 전략

R1/R2 를 모두 포괄해 네 가지 배치를 비교한다. 모두 "턴마다 일관된 CreatureState 가 존재한다"
는 기능 요구를 만족해야 하며, "누가 읽고, 누가 쓰고, 누가 영속화하느냐" 만 다르다.

### 전략 A — Pure `attach_runtime` 주입 (스테이지 내부에서 직접 Provider 호출)

```
             ┌───────────────────────────────┐
 Geny        │  CreatureStateProvider impl   │
 (Backend) ──┤  (DB / File / Cache)          │
             └──────────────┬────────────────┘
                            │ inject via attach_runtime
                            ▼
 Pipeline ─ Stage[*] ─ runtime.creature_state_provider.load()/save()
```

- **변경점.** `attach_runtime` 에 `creature_state_provider` kwarg 추가 (I8, 1-line).
- **읽기.** 각 stage 가 필요할 때 `runtime.creature_state_provider.load(session_id)` 호출.
- **쓰기.** 각 stage 가 직접 `.save(...)` 호출 or `.mutate(diff)` 호출.
- **Decay.** 외부 서비스 (TickEngine) 가 주기 호출.

**장점.**

- 16-STAGE 구조 손상 없음.
- 진입 장벽 낮음 (memory_persistence 와 동일 패턴).

**단점.**

- 여러 stage 가 provider 를 직접 잡으면 결합도↑. 누가 언제 save 하는지 **규약 없음** → 혼란.
- load 가 N 번 호출될 위험 (읽기 캐시 없음).
- 트랜잭션 경계 모호. stage 중간 실패 시 부분 save 가능성.

### 전략 B — Phase A 에 새 stage (s00 또는 s01b) 추가

```
 Phase A'(?) → s00_state_hydrate → s01_input → Loop … → Finalize → s16b_state_persist (?)
```

- **변경점.** executor `_run_phases` 수정 필수. 예: `PRE_INGRESS = range(0, 1)`,
  `POST_FINALIZE = range(17, 18)` 추가. **실행 루프의 상수 3종 (LOOP_*/FINALIZE_*) 자체가 바뀐다.**
- **읽기.** s00 이 load 를 독점. 다른 stage 는 `state.shared['creature_state']` 만 본다.
- **쓰기.** Loop 중인 stage 들이 `state.shared['creature_state_mutations']` 리스트에 diff 만 적재.
- **영속화.** s16b (또는 s15 확장) 이 mutation 적용 후 save.
- **Decay.** s00 진입 시 `now - last_tick_at` 기반 계산 → state 에 반영.

**장점.**

- 시퀀스가 선언적. UI 에 stage 로 노출 (describe() 에 추가).
- load-once / save-once 강제. 트랜잭션 경계 명확.
- 사이드도어 위험 원천 차단 (provider 는 s00/s16b 가 독점).

**단점.**

- **16-STAGE 테제 훼손.** 16 이 아니라 "18 단계 에이전트" 가 된다. 문서·UI·manifest·preset 전부 영향.
- `_run_phases` 의 방어적 기본값, `describe()` 범위, preset registry 키, manifest schema 까지
  모두 손봐야 함. 예전 manifest 의 roundtrip 호환이 깨질 수 있음.
- **이득의 대부분은 전략 D 가 0-line 으로 제공** (§3 참조) — "선언적 시퀀스" 만 포기하면 된다.
- Phase 경계의 의미 희석 (`analysis/04` §0.1 논증 그대로 적용).

### 전략 C — 기존 s01 / s15 의 Strategy slot 확장

- **읽기.** s01_input 의 artifact 에 "state hydration" 책임 추가. Strategy 로
  `StateHydrator` 를 새 slot 으로 등록.
- **쓰기.** s15_memory 의 `MemoryUpdateStrategy` 가 `state.shared['creature_state_mutations']`
  도 함께 flush. 또는 s15 에 `state_persistence` 새 slot 추가.
- **Decay.** s01 진입 시 계산.

**장점.**

- 0-line executor 변경 (기존 slot API 활용). 릴리즈 불필요.
- 16-STAGE 외관 보존.

**단점.**

- s01 의 본래 책임 (입력 정규화) 과 *다른 종류의 상태 하이드레이션* 이 한 artifact 에 섞임.
  Tool stage 가 Emitter 와 섞이는 것과 비슷한 아키텍처 냄새.
- s01 이 `CreatureState` 를 알게 됨 → executor 가 게임 로직을 알게 됨.
  *executor 는 게임을 모르고 싶다.*
- persistence 와 memory persistence 가 s15 안에서 혼거 → 트랜잭션 복잡도↑.



```
┌─────────────────────── Geny AgentSession ───────────────────────┐
│ 1. state_snapshot = await state_provider.load(session_id, ...)  │
│ 2. mutations = MutationBuffer()                                 │
│ 3. await pipeline.run(                                          │
│        input, state=PipelineState(                              │
│            shared={                                             │
│                'creature_state': state_snapshot,                │
│                'creature_state_mutations': mutations,           │
│            }))                                                  │
│ 4. await state_provider.apply(state_snapshot, mutations.diffs)  │
└─────────────────────────────────────────────────────────────────┘
```

- **변경점.** **0-line executor 변경.** Geny 쪽 AgentSession 이 pipeline.run 을
  *context manager* 로 감싸면 끝.
- **읽기.** wrapper 가 load → state.shared 주입. 모든 stage 는 state.shared 에서 읽는다
  (provider 직접 접근 없음).
- **쓰기.** 모든 stage 는 `mutations.append(diff)` 만 한다.
- **영속화.** pipeline.run 반환 후 wrapper 가 `state_provider.apply(snapshot, diffs)` 호출.
- **Decay.** 외부 TickEngine 서비스 (구조적 보완 — plan/03) 가 wrapper 와 독립 주기로 구동.

**장점.**

- 16-STAGE 불변. executor 0-line.
- 트랜잭션 경계 명확 (wrapper 가 begin/commit 담당).
- 테스트 용이 (wrapper 단독 테스트 가능, stage 는 state.shared 만 본다).
- *여러 개의* 장기 상태 (CreatureState, ProgressionState, ...) 로 확장할 때 wrapper 가 집합 주입.
- load-once / save-once 자연 강제.
- 전략 A 의 장점 (선언적 주입) 도 그대로 포함 (wrapper 내부가 provider 주입).

**단점.**

- stage 는 *읽기만* 가능 — stage 에서 직접 persistence 를 찌르는 권한이 없다
  (이것을 단점으로 볼지 장점으로 볼지는 철학의 문제, 이 분석은 장점으로 취급).
- "pipeline 외부의 마법" 이 새로 생김 → 문서화 책임↑. 다만 memory_persistence 도
  이미 `attach_runtime` 외부 객체로 주입되므로 *낯설지 않음*.

---

## 3. 비교 매트릭스

| 기준 | A (attach_runtime 직접) | B (Phase-A stage 신설) | C (s01/s15 slot 확장) | D (External Wrapper) |
|---|---|---|---|---|
| executor 수정 | 1-line (kwarg 추가) | **대규모** (_run_phases / describe / manifest schema) | 0-line | **0-line** |
| 16-STAGE 테제 보존 | ✅ | ❌ | ✅ | ✅ |
| 트랜잭션 경계 | ⚠️ 불명 | ✅ 명확 | ⚠️ 혼거 | ✅ 명확 |
| 로드/세이브 횟수 | N/N | 1/1 | 1/1 | 1/1 |
| Stage 결합도 | ⚠️ stage 가 provider 를 안다 | ✅ s00 독점 | ⚠️ s01/s15 가 게임을 안다 | ✅ stage 는 shared 만 읽음 |
| 게임 로직 누수 | ⚠️ executor 내부 | ⚠️ executor 내부 | ❌ executor 가 게임 앎 | ✅ Geny 쪽 격리 |
| 확장성 (N개의 장기 상태) | ⚠️ kwarg N개 증식 | ⚠️ stage 증식 | ❌ slot 증식 | ✅ wrapper 에 dict |
| 테스트 용이성 | 중 | 중 (stage 단위) | 중 | ✅ wrapper 단위 독립 |
| Decay 책임 분리 | 외부 | 내부 s00 | 내부 s01 | 외부 TickEngine |
| 사이드도어 유혹 | ⚠️ 재생 위험 | ✅ 원천 차단 | ⚠️ 혼거 | ✅ 원천 차단 |
| 런타임 hot-reload | ✅ | ❌ (stage 고정) | ✅ | ✅ |
| preset / manifest 호환 | ✅ | ❌ | ✅ | ✅ |
| 릴리즈 bump 필요 | ✅ (minor) | ✅ (major) | ❌ | ❌ |

---

## 4. 왜 B 를 버리는가 — 더 세게 논증

유저가 R2 로 명시적으로 꺼낸 방안이므로, 기각 사유를 세밀하게 기록한다.

### 4.1. 비용

- `_run_phases` 는 v1.0 로 락된 실행 모델이다. 변경은 semver major bump 상당.
- `LOOP_START / LOOP_END / FINALIZE_START / FINALIZE_END` 네 상수가 곳곳에서 *헌법* 처럼 인용되어
  있다 (bypass event 생성, describe 범위, manifest serialization, preset validation).
  이걸 전부 "18-STAGE" 로 이관하면, 영향 범위가 analysis/01 의 7겹 표면 모두를 훑는다.
- manifest snapshot 이 order ∈ [1..16] 을 전제로 직렬화되므로, 기존 세션들의 복원 호환성 테스트
  전부 재작성.

### 4.2. 이득

- "선언적 시퀀스" (UI 에 stage 로 보임) — 이건 진짜 가치일 수 있으나, 전략 D + EventBus 이벤트
  (`state.hydrated`, `state.persisted`) 로 99% 동일한 관찰성을 얻는다.
- "stage 내부에서 state 접근" — 전략 D 역시 state.shared 로 동일 접근. 차이는 **load 가
  누구 책임인가** 인데, D 에서도 이는 명확히 wrapper 책임이다.
- "트랜잭션 경계" — 전략 D 가 동일하게 제공.

### 4.3. 철학

16-STAGE 는 *에이전트의 한 턴* 을 묘사한다. 장기 상태는 *턴 간 연속성* 이다.
두 개념은 **직교적** 이다. 한 턴의 내부 파이프라인에 "턴 간 상태 로더" 를 심는 것은
범주 오류다. 턴 간 상태는 **턴 바깥** 에 있어야 한다.

비유하자면: HTTP 요청 처리 파이프라인 안에 "이 세션의 유저 프로필을 DB 에서 로드하는 단계" 를
넣지 않는다. 그건 미들웨어 (request scope context) 의 일이다. 전략 D 는 정확히 그
미들웨어 포지션이다.

---

## 5. 왜 A 만으로는 부족한가

전략 A 는 대부분의 "장기 상태" 를 구현할 수 있다. 단지 stage 가 provider 를 직접 잡는
패턴을 허용하면, 다음 문제가 재발한다:

### 5.1. analysis/02 §5 의 사이드도어 재생

현재 Geny 가 `_system_prompt` 를 3곳에서 직접 건드리는 이유는 "attach_runtime 범위를 초월
해야 해서" 가 아니라, *한 번 주입한 값을 턴 중간에 갱신하고 싶은* 요구였다.
전략 A 는 stage 가 provider 를 직접 잡을 수 있게 하므로, 비슷하게 *턴 중간에 재로드* 하는
anti-pattern 이 쉽게 재발한다.

### 5.2. 멀티 장기 상태 확장성

`CreatureState` 하나로 끝나지 않는다. 곧 `ProgressionState`, `RelationshipGraph`,
`InventoryState`, `QuestState` 가 온다. 전략 A 는 attach_runtime kwargs 를 하나씩 늘리는
방식이라, 6 → 7 → 10 → 15 ... kwargs 폭발.

### 5.3. "Who saves, when?" 규약 부재

전략 A 는 save 타이밍을 stage 결정에 맡긴다. s15 가 저장한다고 약속하더라도, 다른 stage 가
자기도 저장하면 (분석 02 의 사이드도어가 `_system_prompt` 를 그랬듯) 이중 저장이 난다.

**즉 전략 A 는 `CreatureStateProvider` 를 "stage 가 직접 잡는 객체" 가 아니라
"wrapper 내부 객체" 로 쓸 때에만 안전하다.** 그러면 전략 D 와 같아진다.

---

## 6. 권장안 — 전략 D (+ 전략 A 의 1-line optional extension)

### 6.1. 기본 설계

- **Geny** 가 `SessionRuntimeRegistry` 를 소유한다. `AgentSession._build_pipeline` 주변에서
  `registry = SessionRuntimeRegistry(session_id, character_id)` 를 만든다.
- `SessionRuntimeRegistry` 가 `creature_state_provider`, `progression_provider`, ... 같은
  모든 장기-상태 Provider 를 묶어서 가진다.
- `pipeline.run(input, state=...)` 호출 전에 `registry.hydrate_state(state)` 가 모든
  `state.shared[key]` 를 채운다.
- `pipeline.run` 종료 후 `registry.persist_state(state)` 가 모든 mutation 을 커밋한다.
- mutation 을 모으는 도구로 `MutationBuffer` 를 Geny 쪽에 정의. Stage 는 이 버퍼에 `append`
  만 한다 (state.shared 에 주입됨).

### 6.2. Executor 1-line (optional) 확장

**강제 아님.** 아래 1-line 은 *편의* 를 위해서만 한다. 없어도 전략 D 는 동작한다.

```python
# core/pipeline.py — attach_runtime
def attach_runtime(
    self, *,
    memory_retriever=None, memory_strategy=None, memory_persistence=None,
    system_builder=None, tool_context=None, llm_client=None,
    session_runtime=None,   # ← 추가. SessionRuntimeRegistry 를 state 에 전파하는 용도.
):
    ...
```

그리고 `_init_state` 에서 `state.session_runtime = session_runtime` 를 세팅.
Stage 가 provider 를 *직접* 잡을 필요가 있을 때 `state.session_runtime.creature_state_provider`
처럼 접근.

**이 확장은 X5 사이클** (Plugin Protocol / Registry) 에서 결정. X1~X4 는 0-line 으로 진행.

### 6.3. 데이터 흐름 다이어그램

```
┌────────────── session.start (SessionLifecycleBus.emit) ──────────────┐
│   1. registry.hydrate_state(state)                                   │
│      - state.shared['creature_state']       = await csp.load(...)    │
│      - state.shared['creature_state_mut']    = MutationBuffer()      │
│      - state.shared['progression']           = await pp.load(...)    │
│      - state.shared['progression_mut']       = MutationBuffer()      │
│                                                                      │
│   2. pipeline.run(input, state=state)                                │
│      ┌─ s01_input ─ s02_context ─ ... ─ s15_memory ─ s16_yield ─┐    │
│      │  stages read state.shared['creature_state']              │    │
│      │  stages append state.shared['creature_state_mut']        │    │
│      └──────────────────────────────────────────────────────────┘    │
│                                                                      │
│   3. registry.persist_state(state)                                   │
│      - await csp.apply(snapshot, mut.diffs)                          │
│      - await pp.apply(snapshot, mut.diffs)                           │
│      - emits 'state.persisted' event                                 │
└──────────────────────────────────────────────────────────────────────┘
                        │
                        ▼
              (decay happens *elsewhere*, via TickEngine)
```

### 6.4. 스테이지 사용 예

**읽기만 하는 stage** (e.g., s03_system) :

```python
creature = state.shared.get('creature_state')
if creature and creature.affection > 70:
    # PromptBlock 에 "특별한 친밀도 어조" 를 추가
    ...
```

**쓰는 stage** (e.g., s14_emit Emitter Chain 이 LLM 출력에서 "[joy]" 추출 후) :

```python
mut = state.shared['creature_state_mut']
mut.append({'affection': +2, 'last_emotion': 'joy', 'source': 'emit:joy_tag'})
```

**핵심 규약.** Stage 는 `CreatureStateProvider` 를 **직접 호출하지 않는다**.
오직 shared dict 의 `creature_state` (읽기) 와 `creature_state_mut` (쓰기) 만 본다.
이 규약 하나로 사이드도어 재생을 원천 차단.

### 6.5. Decay 는 왜 분리하는가

Decay (배고픔이 시간당 1씩 오르는 등) 는 **LLM 턴과 무관한** 시간 축 이벤트다.
- 유저가 접속하지 않아도 진행되어야 함.
- 한 턴 안에서 여러 번 적용될 필요 없음.
- wall-clock 에 의존 (테스트 어려움 증가).

→ **TickEngine** 이 독립 서비스로 수분~수시간 주기 돌면서 `csp.tick(character_id)` 호출.
   그 안에서 decay 공식 적용 + persist. pipeline 과 무관하게 돈다.

단, **턴 진입 시 "마지막 tick 이후 경과" 기반 보정** 은 hydrate_state 단계에서 한 번 한다
(접속 안 한 동안 tick 서비스가 쉬었더라도 catch-up). 이로써 *즉시성* 과 *결정성* 의
균형.

---

## 7. 본 권장안이 분석 05 의 격차와 어떻게 매핑되는가

| 격차 | 권장안에서의 해결 | 사이클 |
|---|---|---|
| I1. PipelineState 에 감정/관계/상태값 1급 필드 없음 | state.shared 에 표준 키로 수용. 1급 필드는 불필요 (분석 04 §B 참조). | X3 |
| I2. 감정 추출 결과 → 다음 턴 피드백 부재 | s14 Emitter 가 mut 에 diff append → 다음 턴 hydrate 에서 반영 | X3 |
| I3. PersonaBlock late-binding 불가 | `PersonaProvider` (plan/03 §3) 가 wrapper 에서 매 턴 resolve | X1 |
| I4. 세션 lifecycle 이벤트 체계 얄팍 | `SessionLifecycleBus` (plan/03 §2) | X2 |
| I5. Tick 엔진 통일 부재 | `TickEngine` (plan/03 §4) | X2 |
| I6. 이벤트 풀 카탈로그 표준 | 기획 트랙, 본 PLAN 밖 | — |
| I7. Progression / Phase 전환 훅 | `ManifestSelector` 가 wrapper 에서 CreatureState 기반 manifest 전환 | X4 |
| I8. attach_runtime kwargs 고정 | `session_runtime` 1-line (optional) | X5 |
| I9. 기분 기반 retrieval 가중 | `AffectAwareRetrieverMixin` — retriever 가 state.shared 읽음 | X6 |

---

## 8. 확정 판정

- **전략 D 채택.** pipeline.run 외부 wrapper 방식.
- **전략 B 기각.** `_run_phases` 변경을 정당화할 이득 없음.
- **전략 C 비추천.** 게임 로직의 executor 누수 위험. 단, executor *자체의* 기본 persistence
  (메시지 로그) 는 계속 s15 가 담당하며, 이것은 C 가 아니라 기존 설계.
- **전략 A 는 D 의 내부 구현 수단** 으로만 사용. stage 가 provider 를 직접 잡는 것은 금지.
- **executor 수정** 은 X5 까지 보류. X1~X4 는 0-line executor 변경.

Plan 02 에서 이 설계의 구체 계약을 확정한다.
