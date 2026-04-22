# PR-X6F-1 · `feat/affect-summary-from-mutation-buffer` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 14 신규 테스트 pass. 파이프라인 의존 없음.

X6F 사이클 개시. 본 PR 은 요약 함수 하나 — "MutationBuffer 에서
6-dim emotion vector 와 intensity 스칼라를 추출". 파이프라인 / DB /
retriever 어느 쪽과도 아직 연결되지 않는다. 이후 PR 이 쓰는/읽는
쪽을 각각 붙인다.

## 범위

### `service.affect.summary.summarize_affect_mutations`

```python
def summarize_affect_mutations(
    entries: Optional[Iterable[Any]],
) -> Tuple[Optional[List[float]], Optional[float]]:
```

- 입력: `MutationBuffer` 또는 `buf.items` 등 `(op, path, value)` 를
  각 엔트리에서 꺼낼 수 있는 iterable.
- 출력: `(vec, intensity)`.
  - `vec`: `[joy, sadness, anger, fear, calm, excitement]` 순서의
    6-dim float 리스트. mood 관련 기여가 하나도 없으면 `None`.
  - `intensity`: `[0.0, 1.0]` 범위 스칼라. 피크 `|v_i|` 를
    `MOOD_ALPHA=0.15` 로 나눈 후 1.0 클램프. `vec is None` 이면
    `None`.

**왜 고정 순서인가.**
- 튜브닝 embedder 가 아님 — AffectTagEmitter 의 고정된 태그 집합
  `("joy", "sadness", "anger", "fear", "calm", "excitement")` 에
  1:1 대응. Retriever 는 헤더 없이 그냥 cosine 비교 가능.
- 7번째 태그 추가 시 마이그레이션은 "기존 6-dim 에 0 컬럼
  추가" 또는 "기존 레코드를 그대로 두고 mixin 의 dim-mismatch
  fallback 에 의존".

**왜 stdlib only.**
- `service.affect` 는 numpy 없는 환경에서도 import 가능해야 한다 —
  retriever mixin 과 encode/decode helper 가 이미 그 계약을 깔아놨고,
  summary 도 같은 제약.
- `MutationBuffer` 실제 import 는 선택 — test 에서 쓰지만 본 모듈은
  duck-type 만 의존 (`getattr(m, "op" | "path" | "value", None)`).
- `geny_executor` / `PipelineState` import 금지 — emitter 의존 없이
  단독 호출 가능.

**왜 null-safe.**
- X6-1 의 저장 계약: `None` 은 "감정 미포착". 빈 버퍼 / mood 미포함
  버퍼 → `(None, None)` 그대로 반환. 0.0 / `[0,0,0,0,0,0]` 으로
  찍지 않음 (X6-2 mixin 이 null 과 non-null 을 다르게 대우).

### Intensity 공식

```
peak = max(|v_i|)
intensity = min(1.0, peak / MOOD_ALPHA)
```

- `AffectTagEmitter` 의 `strength=1.0` + `MOOD_ALPHA=0.15` → peak 0.15
  → intensity 1.0.
- `strength=0.5` → peak 0.075 → intensity 0.5.
- 여러 태그 스택 쌓여도 1.0 클램프.
- `MOOD_ALPHA=0` 방어선 있음 (division by zero 회피).

### Mutation 타입 계약

- `op == "add"` 만 소비. `"set" | "append" | "event"` 는 무시.
  이유: AffectTagEmitter 는 `mood.<tag>` 에 `"add"` 만 쏜다.
  "set" / "event" 가 같은 path 에 올 수 있어도 그건 다른
  emitter 의 의도 — 본 helper 는 해당 턴의 *감정 추가분* 만
  요약.
- `path` 는 `mood.` 접두사 필수. 알려진 6개 태그가 아니면 skip
  (unknown tag 방어).
- `value` 가 float 변환 실패하면 해당 엔트리 skip (단 한 엔트리가
  요약을 깨뜨리지 않도록).

## 테스트 (`backend/tests/service/affect/test_summary.py`, 14개)

- 태그 순서 canonical pin
- None / 빈 iterable → `(None, None)`
- mood 외 path 만 있는 경우 → `(None, None)`
- 단일 joy 태그 → vector slot 0 만 비영
- strength 1.0 → intensity 1.0 정확히
- 다중 태그 순서 / 누적 / 음수 delta / 인텐시티 클램프
- non-numeric value → skip (raise 없음)
- 알려지지 않은 mood 태그 → skip
- 실제 `MutationBuffer` 통합 — duck-type 이 진짜 타입과 호환
- X6-1 `encode_emotion_vec` / `decode_emotion_vec` 왕복 — 저장
  계약 동시 검증

**결과.** 14 pass, 0 fail. 전체 affect suite 51 pass.

## 검증

```
pytest backend/tests/service/affect/ -q
51 passed in 0.10s

pytest backend/tests/service/plugin/ backend/tests/service/database/ \
       backend/tests/service/affect/ backend/tests/service/state/ -q
253 passed in 1.02s
```

회귀 없음.

## 불변식 확인

- **Pure additive.** ✅ 신규 파일 `summary.py` + 신규 테스트 파일.
  기존 모듈 어느 것도 수정하지 않음.
- **Stdlib only.** ✅ `typing` 외 import 없음.
- **Mutation 은 4 op.** ✅ 본 helper 는 읽기만 — 새 op 도입 없음.
- **Side-door 금지.** ✅ MutationBuffer 를 public API 로 읽음.
  state.shared 직접 mutation 없음.

## PR-X6F-2 인수인계

- `summarize_affect_mutations` 는 pipeline context 밖에서 호출
  가능 — 어떤 Emitter 든 자기 버퍼를 이 함수에 넘겨 요약할 수
  있음.
- 반환 `vec` 은 이미 mixin / encode/decode 와 계약이 맞음 — 그대로
  DB INSERT 에 쏠 수 있도록 PR-X6F-2 가 db_stm_add_message 시그니처에
  optional `emotion_vec: Sequence[float] | None` 추가할 것.
- `intensity` 는 그대로 REAL 컬럼에 대응 — `emotion_intensity:
  float | None`.
