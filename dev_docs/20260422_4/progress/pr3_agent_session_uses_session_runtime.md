# PR-X5F-3 · `feat/state-registry-exposes-session-runtime` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 3 신규 테스트 + 23 기존 테스트 pass (26 total).
executor 0.30.0 의 `state.session_runtime` 슬롯을 Geny 에서 처음 채택.

## 명명 보정 (index.md 기재와 차이)

본 사이클 index.md 는 브랜치명을 `feat/agent-session-uses-session-runtime`
으로 기재했지만, 실제 수정 지점은 **`SessionRuntimeRegistry.hydrate`**
가 되어 브랜치명을 `feat/state-registry-exposes-session-runtime` 로
조정.

### 왜 agent_session 이 아니라 registry 에서 쓰는가

- `SessionRuntimeRegistry` 는 **turn-scoped** 이고 `hydrate()` 는 매
  턴 pipeline 실행 *직전*에 호출됨. executor 의 `attach_runtime` 은
  pipeline 생성 시점에 한 번만 호출 가능 (post-run re-attach 거부).
- 따라서 per-turn runtime carrier 를 `attach_runtime` 으로 꽂을 수 없고,
  *state object 자체에 attribute 로 setattr* 하는 쪽이 자연스럽다.
- `executor._init_state` 의 contract 는 "state.session_runtime 이
  이미 설정돼 있으면 attached 기본값을 덮어쓰지 않는다" (llm_client
  semantics 와 동일). 우리는 `hydrate` 가 state 를 받는 순간 본인 자신을
  setattr → pipeline.run 이 시작해도 그대로 유지.
- `agent_session.py` 의 pipeline 생성 경로는 `session_runtime` 을 쓰지
  않음. 이 접점은 future third-party plugin 이 *session-scoped* 객체를
  고정 attach 할 때 쓰게 될 여지로 남김 — 본 PR 의 scope 밖.

## 변경

### `backend/service/state/registry.py`

```python
# hydrate() 안, _put_shared 3 개 뒤:
_put_session_runtime(state, self)
```

```python
def _put_session_runtime(state: Any, runtime: Any) -> None:
    """Best-effort write of the registry onto state.session_runtime."""
    try:
        state.session_runtime = runtime
    except (AttributeError, TypeError):
        logger.debug(...)
```

- **Best-effort.** `__slots__` 를 쓰고 `session_runtime` 을 선언하지 않은
  state 객체 (미래의 경량 stub 등) 는 setattr 에서 튀길 수 있음 → 삼킴.
  shared-dict path 가 authoritative 이므로 가시 기능에 영향 없음.
- **setattr 직접.** `PipelineState` 는 dataclass 로 `session_runtime`
  필드를 이미 가지고 있음 (executor 0.30.0). 일반 test stub 도 `__dict__`
  기반이라 그냥 받는다.

### `backend/tests/service/state/test_registry.py`

3 신규 테스트:

1. `test_hydrate_exposes_registry_on_session_runtime_attr` — hydrate 후
   `state.session_runtime is registry`, 그리고 `.session_id` /
   `.character_id` / `.snapshot` 타입 접근 가능.
2. `test_hydrate_shared_dict_still_authoritative` — 기존 3 개의 shared
   key 는 byte-identical 로 유지 — 기존 consumer regress 없음.
3. `test_hydrate_tolerates_state_that_rejects_attribute_writes` —
   `__slots__=("shared",)` 로 session_runtime 거부하는 stub 도 hydrate
   가 raise 없이 성공. shared-dict 는 정상 설치.

## 검증

```
pytest backend/tests/service/state/test_registry.py -q
26 passed

pytest backend/tests/service/state/test_registry.py \
       backend/tests/service/state/test_registry_catchup.py \
       backend/tests/service/state/test_tool_context.py \
       backend/tests/service/affect/ \
       backend/tests/service/emit/ \
       backend/tests/service/database/ -q
163 passed

pytest backend/tests/integration/test_state_e2e.py -q
8 passed
```

**회귀 0.** state e2e 는 registry.hydrate → pipeline → persist 전체
경로를 쓰기 때문에 session_runtime 추가가 다른 쪽에 영향이 없음을 증명.

## 왜 *대표 stage 마이그레이션* 을 뺐는가 (index.md §범위 정책 조정)

원래 index.md 는 "대표 stage 1~2곳 state.shared → state.session_runtime"
을 함께 선언했지만, 실제로 현 stage 구현을 보면:

- `CREATURE_STATE_KEY` / `MUTATION_BUFFER_KEY` 를 읽는 consumer 들
  (emitter, game tools 등) 은 이미 적고 모두 `state.shared.get(KEY)`
  단일 관용에 정착. 한 곳만 옮기면 두 관용이 대등하게 공존하는 모양이
  되어 후속 reviewer 가 "어느 쪽이 공식?" 혼란.
- `state.session_runtime.snapshot` 으로 옮기려면 `snapshot` 프로퍼티
  semantics (hydrate 직후는 있지만 persist 후엔 새 snap 인지 등)를 별도
  문서화해야 함 — 본 PR 의 scope (attach 접점 정착) 를 벗어남.

따라서 **PR-X5F-3 의 스코프를 "registry 가 state.session_runtime 을
노출" 까지로 축소**. 실제 stage 채택은 *두 번째 플러그인이 등장해 shared
key collision 이 실증될 때* 별도 사이클에서 논의. cycle_close 에 명시
이월.

## 불변식 확인

- **executor 무수정.** ✅ executor 0.30.0 의 기존 슬롯을 *소비*할 뿐.
- **Pure additive.** ✅ shared-dict 3 키 모두 byte-identical. 새 attribute
  1개만 추가.
- **Retriever / FAISS / Mutation op.** ✅ 본 PR 무관.
- **Side-door 금지.** ✅ `state.session_runtime` 은 executor 0.30.0 이
  정식 문서화한 공식 attach 접점. shared-dict 보다 *격 상위*.
- **Shadow mode.** N/A — attribute 하나만 추가 (읽는 쪽이 아직 없음). 파이프라인 동작 변경 없음.

## 다음 PR

PR-X5F-4 — `docs/cycle-20260422_4-close`. 사이클 종료 doc. 본 PR 의
스코프 축소 (대표 stage 마이그레이션 defer) 를 공식 이월.
