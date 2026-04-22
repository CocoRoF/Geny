# PR-X6F-3 · `feat/affect-tag-emitter-stashes-summary` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 6 신규 emitter 테스트 + 확장된 summary 모듈
pass. AffectTagEmitter 가 마침내 X6 infra 의 "쓰기 쪽 trigger" 를
붙임.

`AffectTagEmitter` 가 emit 시점에 6-dim affect vector + intensity 를
계산해 `state.shared[AFFECT_TURN_SUMMARY_KEY]` 에 남긴다. 이후 어떤
pipeline 캡처 로직이든 이 key 를 읽어 `db_stm_add_message(emotion_vec=,
emotion_intensity=)` 로 넘기면 DB 에 적재된다.

## 범위

### 1. `service.affect.summary` 확장

**신규 상수.**
```python
AFFECT_TURN_SUMMARY_KEY: str = "affect_turn_summary"
```

**신규 dataclass.**
```python
@dataclass(frozen=True)
class AffectTurnSummary:
    emotion_vec: Tuple[float, ...]
    emotion_intensity: float
```

- Frozen → state.shared 에 얹은 값은 read-only 스냅샷. 실수로
  변형하려 하면 `FrozenInstanceError` 로 시끄럽게 알림.
- `emotion_vec` 을 `Tuple[float, ...]` 로 고정 — list 였으면 다른
  코드가 append 해서 감지 안 되는 버그를 만들기 쉬움.

**신규 함수.**
```python
def stash_affect_summary(
    shared: Any,
    entries: Optional[Iterable[Any]],
) -> Optional[AffectTurnSummary]:
```
- mood 기여가 하나도 없으면 `None` 반환 + `shared` 미변경.
- 있으면 `AffectTurnSummary` 를 만들어 `shared[AFFECT_TURN_SUMMARY_KEY]`
  에 저장하고 반환.
- Null-safe 전파: `entries is None` / 빈 iterable / mood path 전무
  → 모두 `None` 반환.

### 2. `AffectTagEmitter.emit()` 배선

`backend/service/emit/affect_tag_emitter.py` 변경:
- 추가 import: `from service.affect.summary import stash_affect_summary`.
- apply loop 끝난 직후 stash 호출:
  ```python
  stashed = stash_affect_summary(state.shared, buf)
  ```
- `EmitResult.metadata["summary_stashed"]` 플래그 추가 — observability.
- 기존 early-return 경로 (no matches / no buffer) 는 무수정. 스냅샷이
  없으면 stash 도 없음 — X6F-4 (retriever adoption) 의 null-safe
  contract 와 자연스럽게 맞물림.

### 3. 왜 이 접점에서 stash 하는가

**시점.** Stage 14 emit 단계에서, AffectTagEmitter 가 mood 기여를
모두 buffer 에 넣은 *직후*. 다른 emitter 가 이후에도 mood.* 에 add
할 수 있지만, 현재 체인에서는 AffectTagEmitter 가 유일한 mood 기여자
이므로 실질적인 race condition 없음. 다중 기여가 생기면
`stash_affect_summary` 를 나중 emitter 에서도 호출해 덮어쓸 수
있음 (last-writer-wins).

**왜 새 emitter 가 아니라 기존 emitter 에 꽂는가.**
- 신규 emitter 는 `MUTATION_BUFFER_KEY` / `state.shared` 접근을
  다시 스케폴딩해야 함.
- "tag 파싱 → mutation push → summary stash" 가 한 트랜잭션처럼
  엮이는 게 자연스럽다 — 분리하면 두 emitter 순서 의존이 생김.
- 실제 계산은 `stash_affect_summary` 에 위임 — emitter 파일은
  4줄만 증가.

**왜 `state.shared` 인가 (emit event 아니고).**
- Geny 의 `SessionLifecycleBus` 는 emit event 를 async handler 로
  흘리는데, 메모리 쓰기는 *같은 턴 안에서 순차적으로* 일어나야 함.
  이벤트 버스는 eventual 전달이라 지연이 걸릴 수 있음.
- `state.shared` 는 파이프라인 State 에 직접 붙어 있어 즉시 가시.
- 기존 패턴 (`MUTATION_BUFFER_KEY`, `CREATURE_STATE_KEY`,
  `SESSION_META_KEY`) 과 동일한 관용 — 일관성.

## 테스트 (6개 신규, 기존 emitter 테스트 21개 무수정 통과)

`backend/tests/service/emit/test_affect_tag_emitter.py` 끝에 추가:

1. `test_emit_stashes_turn_summary_on_shared` — 단일 joy 태그 emit
   후 `AffectTurnSummary` 가 shared 에 있고 vector slot 0 에 기대값.
2. `test_no_tags_leaves_shared_untouched` — 빈 턴은 shared 에 키를
   만들지 않음 (stale summary 방지).
3. `test_stashed_summary_is_frozen_snapshot` — `FrozenInstanceError`
   로 read-only 계약 pin.
4. `test_summary_shape_matches_db_writer_kwargs` — summary 필드가
   `_coerce_emotion_vec` + `db_stm_add_message` 에 무변환 전달
   가능 (재인코드 후 decode == 원본).
5. `test_multi_tag_summary_accumulates_all_mood_paths` — joy/fear/calm
   다중 태그의 delta 가 6-dim 벡터의 각 슬롯에 정확히 대응.
6. `test_no_mutation_buffer_does_not_stash_summary` — buffer 없는
   에지 (classic 모드) 에서 stash 없음 + `reason="no_mutation_buffer"`
   metadata 유지.

**결과.**
```
pytest backend/tests/service/emit/test_affect_tag_emitter.py \
       backend/tests/service/affect/ -q
78 passed in 0.30s

pytest plugin/ database/ affect/ state/ emit/ -q
303 passed in 1.13s
```

## 불변식 확인

- **Retriever 호환성.** ✅ retriever 코드 미수정. mixin 은 여전히
  subclass 가 와야만 동작.
- **FAISS 무영향.** ✅ 본 PR 은 SQL 도 건드리지 않음 — shared 에
  객체를 하나 더 얹을 뿐.
- **Mutation 4 op.** ✅ 기존 mood.* `"add"` 에만 의존 — 새 op 도입
  없음.
- **Side-door 금지.** ✅ `state.shared[KEY] = value` 는 이미 공식
  패턴 (CREATURE_STATE_KEY / MUTATION_BUFFER_KEY 와 동일).
- **Shadow mode.** N/A — 본 PR 은 쓰기 직전 단계의 *read-only*
  스냅샷을 만들 뿐. 파이프라인 동작 변경 없음.

## 남은 작업 — "last mile" (의도적 보류)

본 PR 을 merge 해도 DB 에 `emotion_vec` 이 *실제로 적재되지는 않음*.
다음 3 스텝이 필요:

1. `ShortTermMemory.add_message` 가 `emotion_vec` / `emotion_intensity`
   kwargs 를 수용 + `db_stm_add_message` 에 전달.
2. `SessionMemoryManager.record_message` 도 동일 전달.
3. `AgentSessionManager` 어딘가 (assistant turn 종료 직후, but
   AffectTagEmitter 가 stash 한 후) 에서 `state.shared.pop(KEY,
   None)` → 읽어 `record_message` 에 전달.

세 레이어 동시 수정이라 "한 PR = 한 방향" 원칙 위반. 본 사이클
`cycle_close.md` 에 별도 사이클 / 후속 PR 로 명시 이월.

## PR-X6F-4 인수인계

`stash_affect_summary` 는 **write path** 용이지만, PR-X6F-4 의
retriever adoption 은 **read path** — 즉 본 PR 과 독립. PR-X6F-4 는
`db_stm_search` 확장 + mixin 상속만 다루면 되고, 실제 emotion_vec
가 DB 에 찬 상태인지 여부는 무관 (null-safe fallback 덕분).

그래서 PR-X6F-3 와 PR-X6F-4 는 merge 순서가 자유롭다.
