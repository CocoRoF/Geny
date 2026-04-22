# Cycle 20260422_4 — X5F 종료 정리

**Date.** 2026-04-22
**Shipped.** PR-X5F-1, PR-X5F-R (executor 리포), PR-X5F-2, PR-X5F-3
(Geny 리포) — 총 4 PR merge. `state.session_runtime` 정식 attach
접점 정착.

## 정착한 것

| PR | 리포 | 브랜치 | 내용 |
|---|---|---|---|
| PR-X5F-1 | `geny-executor` #47 | `feat/attach-runtime-session-runtime-kwarg` | `Pipeline.attach_runtime(session_runtime=...)` 7번째 kwarg + `PipelineState.session_runtime: Optional[Any]` 필드. 기존 `llm_client` 패턴 복제 — post-run re-attach 거부, pre-populated state wins. 9 신규 테스트, 682 unit tests green. |
| PR-X5F-R | `geny-executor` #48 | `chore/release-0.30.0` | pyproject / `__version__` 0.29.0 → 0.30.0. CHANGELOG entry. User 가 PyPI 업로드 (propagation ~1분). |
| PR-X5F-2 | `Geny` #248 | `chore/pin-executor-0.30.0` | `backend/requirements.txt` pin 을 `>=0.29,<0.30` → `>=0.30,<0.31`. Cycle index.md + PR-X5F-1 회고 doc 동봉. |
| PR-X5F-3 | `Geny` #249 | `feat/state-registry-exposes-session-runtime` | `SessionRuntimeRegistry.hydrate` 가 `state.session_runtime = self` 세팅 → stages 가 registry 와 그 `snapshot` / `session_id` / `character_id` 를 타입 있는 attr 로 접근 가능. best-effort (slotted state 관용), shared-dict path byte-stable. 3 신규 테스트 (26 total). |

**테스트 성장치.**

- `geny-executor/tests/unit/test_pipeline_session_runtime.py` +9 tests
- `Geny/backend/tests/service/state/test_registry.py` +3 tests
- **X5F 총 +12 tests, 회귀 0.**

**주요 스위프.**
```
# executor
pytest tests/unit/ -q
682 passed, 1 skipped

# Geny
pytest backend/tests/service/state/test_registry.py -q
26 passed
pytest backend/tests/integration/test_state_e2e.py -q
8 passed
pytest backend/tests/service/affect/ backend/tests/service/emit/ backend/tests/service/database/ -q
121 passed
```

## 의도적으로 미이식 (index.md §범위 정책 조정)

원 index.md 는 PR-X5F-3 에 "대표 stage 1~2곳 마이그레이션" 을 포함했으나,
실제 구현 지점을 보며 다음과 같이 축소했다. 이 축소는 PR-X5F-3 commit
message + progress doc 에 공식화됐고 본 close doc 로 사이클 레벨에서
재확인.

### Stage/Emitter 의 `state.shared` → `state.session_runtime` 점진 이전

현재 상태:

- `state.session_runtime` 은 registry 로 이미 세팅됨 (read-only 가시).
- 그러나 실제 stage / emitter 코드는 여전히 `state.shared[CREATURE_STATE_KEY]`
  / `state.shared[MUTATION_BUFFER_KEY]` 로 읽음.
- 이 두 경로는 동일 객체를 가리키므로 어느 쪽으로 읽어도 결과 동일.

한 consumer 만 migrate 하면 "어느 쪽이 공식인가" 가 코드 내에서 모호.
전체 consumer group 을 한 번에 옮기는 편이 리뷰어 / 미래 작성자 대상
신호가 분명. **두 번째 플러그인이 등장해 shared key namespacing 이
실증될 때 별도 사이클**로 진입.

### "완전한 dead shared-dict" 전환

- 단기: 두 경로 공존. 기존 consumer 는 shared-dict 경로 유지.
- 중기: 두 번째 플러그인 사례 확보 후 전 stage / emitter `state.session_runtime.<attr>`
  으로 이전 — 이 시점에 같은 사이클에서 shared-dict 경로 deprecation
  policy 결정.
- 장기: shared-dict 관용을 registry-internal 구현 디테일로 격하. 외부
  consumer 는 session_runtime 만.

## 불변식 체크

X5F PR 을 통해 깨지지 않은 것:

1. **executor 는 게임을 모른다.** → executor 0.30.0 의 `session_runtime`
   타입은 `Any`. Tamagotchi / Mood / CreatureState 등 도메인 어휘 import
   없음. ✅
2. **Pure additive — executor.** → 기존 kwarg 6개 + 필드 모두 보존,
   신규 1개만 추가. 682 unit tests 무수정 통과. ✅
3. **Pure additive — Geny.** → shared-dict 3 키 byte-identical. hydrate
   는 attr 하나만 추가. 기존 consumer 전부 무영향. ✅
4. **Retriever 호환성.** → 본 사이클 retriever 무관. X6 / X6F 인프라
   모두 호환. ✅
5. **FAISS vector store 무영향.** → 본 사이클 SQL / state 영역만. ✅
6. **Mutation 4 op.** → 본 사이클 mutation 무관. ✅
7. **Side-door 재생 금지.** → `session_runtime` 은 executor 가 정식
   문서화한 공식 attach 접점. shared-dict 보다 격 상위. ✅
8. **Stage 는 Provider 를 직접 잡지 않는다.** → stage 는 여전히 read-only
   consumer. `state.session_runtime.xxx` 는 attribute access 이지 instantiate
   아님. ✅
9. **Shadow mode.** → 본 PR 들은 *writer* 만 배치. Reader 는 아직 없음 —
   파이프라인 동작 변경 없음 (A/B 할 것도 없음). ✅

## 산출물 요약

```
# executor (외부 리포)
pull #47 — attach_runtime(session_runtime=) feature + 9 tests
pull #48 — 0.30.0 release (CHANGELOG + pyproject)
PyPI:  geny-executor 0.30.0

# Geny
backend/requirements.txt              # executor pin move 0.29 → 0.30
backend/service/state/registry.py     # _put_session_runtime + hydrate call
backend/tests/service/state/test_registry.py  # +3 tests
dev_docs/20260422_4/index.md
dev_docs/20260422_4/progress/pr1_executor_session_runtime_kwarg.md
dev_docs/20260422_4/progress/pr2_pin_executor_030.md
dev_docs/20260422_4/progress/pr3_agent_session_uses_session_runtime.md
dev_docs/20260422_4/progress/cycle_close.md   # this
```

## 다음 사이클

plan/05 §5 의 X5 Ship 범위는 **이 사이클 종료 시점에 100% 완결**:

- PR-X5-1 ~ X5-3 (GenyPlugin Protocol / Registry / Tamagotchi refactor) —
  이전 사이클 Ship ✅
- PR-X5-4 (X5F-1 + X5F-R 로 대체) — 본 사이클 Ship ✅
- PR-X5-5 (X5F-2 로 대체) — 본 사이클 Ship ✅

자연스러운 follow-up 후보 (별도 사이클로 진입):

1. **두 번째 플러그인 사례 추가.** non-Tamagotchi 도메인의 GenyPlugin
   을 하나 작성 (예: "weather-affected mood" / "calendar-aware persona"
   같은 작은 스코프). 이 시점에 `state.session_runtime` attr schema
   collision / coordination 문제가 실증됨 — 그 PR 에 shared-dict 이전
   스코프도 같이 해결 가능.
2. **X6F last-mile.** 20260422_3 cycle_close §다음 사이클 에서 이월됐던
   `ShortTermMemory.add_message` → `record_message` → `AgentSessionManager`
   write-path 배선. `session_runtime` 이 이미 있으므로 `state.session_runtime`
   를 통해 `AFFECT_TURN_SUMMARY_KEY` 를 더 깔끔하게 소비할 수 있을 가능성.
3. **(조건부) X6-3 / X6-4 재활성.** 여전히 운영 데이터 필요 — 상태 불변.

본 사이클 종료.
