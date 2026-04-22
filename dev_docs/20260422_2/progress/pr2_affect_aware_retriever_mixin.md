# PR-X6-2 · `feat/affect-aware-retriever-mixin` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 26 신규 테스트 pass (+ 11 X6-1 helper ≡ 37 affect
total). 기존 retriever 호출 경로 byte-identical (`index.md §불변식`).
Concrete retriever 배선은 X6-follow-up 이월.

X6 사이클 2단: **재랭크 레이어**. X6-1 이 저장층을 깔았고, 본 PR 은
"감정 벡터가 있으면 cosine 유사도로 re-rank, 없으면 text-only
통과" 라는 옵트-인 mixin 을 도입한다.

## 범위

### 1. `service.affect.retriever.AffectAwareRetrieverMixin`

`backend/service/affect/retriever.py` — 얇은 mixin 클래스.

**API 면.**

```python
class AffectAwareRetrieverMixin:
    affect_weight: float = 0.3          # 블렌드 가중치

    @staticmethod
    def cosine_similarity(a, b) -> Optional[float]: ...

    def blend_scores(
        self, text_score: float, affect_similarity: Optional[float],
    ) -> float: ...

    def rerank_by_affect(
        self,
        candidates: Sequence[Tuple[item, text_score, Optional[vec]]],
        query_emotion_vec: Optional[Sequence[float]],
    ) -> List[Tuple[item, blended_score]]: ...
```

- `candidates` 는 pre-scored 3튜플 — item / text score / 후보
  emotion vector (또는 None). 이게 필요한 이유: 저장층 (X6-1) 에서
  꺼낸 raw string 을 mixin 이 디코드하게 하면 책임이 섞인다. 호출부
  (concrete retriever) 가 `decode_emotion_vec` 로 사전 변환 →
  mixin 은 순수 산술만 담당.
- `rerank_by_affect` 는 sorted list 를 반환. Python `sort` 가
  stable 하므로 같은 blended score 끼리는 입력 순서가 유지됨.

**null-safe 계약.**

| 조건 | 결과 |
|---|---|
| `query_emotion_vec is None` or `[]` | text 점수 기준 정렬만 수행 (affect 신호 부재) |
| 개별 후보의 `cand_vec is None` | 해당 후보는 blended = text (패널티 없음) |
| 차원 불일치 | cosine → None → 해당 후보 text-only |
| 0-norm 벡터 | cosine → None → 해당 후보 text-only |

단 한 개의 깨진 레코드가 세션 검색을 마비시키지 않음. 임베더 차원
바꿔도 retrieval 이 raise 하지 않음.

### 2. 설계 결정

**왜 Mixin 패턴인가.**
- 기존 retriever (`SessionMemoryManager.search`,
  `VectorMemoryManager.search`, `SessionVectorStore.search` 등) 는
  각자 다른 데이터 형상을 반환 — 단일 베이스로 통합하려면 깊은
  리팩터가 필요. 본 사이클은 infra-only 라 그 범위를 넘는다.
- Mixin 은 "필요한 애만 상속" → 기존 호출 경로 byte-identical
  유지 (불변식 §2).

**왜 stdlib only (no numpy).**
- `service.memory.__init__` 가 numpy-bound submodule 을 eager
  import — CI / 샌드박스 무numpy 환경에서도 본 mixin 은 돌아야
  함 (X6-1 에서 helper 를 `service.affect` 로 분리한 이유와 동일).
- emotion vector 차원은 ≤ 32 가 현실적인 상한. 쿼리당 수십
  차원 × 수백 후보 = Python 수준에서 milliseconds 미만. LLM
  왕복 시간에 비하면 무시 가능.
- 성능 병목 증명 시 numpy / BLAS 로 교체 가능 — 계약은 그대로.

**왜 `(1 - w) * text + w * affect` 블렌드.**
- 단순성. min-max 정규화가 필요하면 호출부에서 text_score 를
  먼저 normalize 해야 — mixin 이 강제하지 않음.
- 기본 `w = 0.3` 은 텍스트 우위 유지. PR-X6-3 (실데이터 기반 튜닝)
  에서 조정 예정.
- `w = 0.0` 이면 mixin 이 상속된 상태에서도 동작적으로 opt-out —
  운영 중 A/B 토글 용도.

**왜 `service.affect.retriever` (not `service.memory.retriever_affect`).**
- X6-1 과 같은 이유: `service.memory.__init__` 의 eager numpy
  import 회피. `service.affect` 에 담으면 이 mixin 의 어떤
  테스트도 numpy 없이 돌 수 있고, 미래 concrete retriever 도
  선택적으로 import 가능.

### 3. 테스트 (`backend/tests/service/affect/test_retriever.py`, 26개)

**`cosine_similarity` (9)**
- identical → 1.0 / orthogonal → 0.0 / opposite → -1.0 /
  scale-invariant
- None / empty / dim-mismatch / zero-norm → None
- static 호출 가능

**`blend_scores` (5)**
- None affect → text passthrough
- default w=0.3 수식 확인
- instance override / w=0 text-only / w=1 affect-only

**`rerank_by_affect` (10)**
- null query / empty query → text-only 정렬
- tie-break / text-affect mix / null candidate 보호
- dim-mismatch candidate 보호 / 수치 정확성
- empty candidates / 입력 순서 안정성 (stable sort)
- 플레인 retriever 는 상속 없이 영향 받지 않음 (opt-in 증명)
- w=0 이면 text-only 정렬 유지

**통합 (2)**
- X6-1 `encode_emotion_vec` / `decode_emotion_vec` 왕복 후 본
  mixin 으로 rerank — 저장층 → 재랭크 end-to-end 경로 보증.

## 검증

```
pytest backend/tests/service/affect/ -q
37 passed in 0.07s
```

```
pytest backend/tests/service/plugin/ \
       backend/tests/service/database/ \
       backend/tests/service/affect/ -q
79 passed in 0.18s
```

## 불변식 확인

- **Retriever 호환성.** ✅ 기존 클래스 어느 것도 수정하지 않았음.
  새 파일 1개 (`retriever.py`) + 새 테스트 1개. Mixin 상속 없이는
  동작 변화 없음.
- **FAISS vector store 무영향.** ✅ `service/memory/vector_store.py`
  미변경.
- **Pure stdlib.** ✅ `math` 만 import. numpy 부재 환경에서 돌아감.

## 비범위 (index.md §비범위 상속)

- **Concrete retriever 배선.** 어느 retriever 를 먼저 mixin 대상으로
  할지, 그 retriever 가 DB 에서 `emotion_vec` 을 함께 SELECT 하도록
  쿼리 확장하는 작업 — X6-follow-up.
- **Query emotion vector 추출.** 유저 메시지 → 감정 벡터 추출은
  `AffectTagEmitter` (X3 PR-7) 의 존재를 활용할 확률이 높지만, emit
  타이밍과 retrieval 타이밍이 다르므로 별도 설계 필요.
- **튜닝.** `affect_weight` 기본값 결정은 데이터 필요 (PR-X6-3,
  Defer).
- **대시보드.** retrieval cost / mAP 측정은 PR-X6-4 (Defer).

## 사이클 완결도

본 PR merge 로 X6 사이클의 Ship 범위 (`index.md §PR 분해`) 완결:

- ✅ PR-X6-1 (storage) — DB schema 에 nullable affect 필드.
- ✅ PR-X6-2 (this) — retrieval blend layer, opt-in.
- ⏸ PR-X6-3 (tuning) — 데이터 필요, Defer.
- ⏸ PR-X6-4 (dashboard) — 데이터 필요, Defer.

다음 자연스러운 follow-up 후보 (별도 사이클):
1. Writer 경로: `AffectTagEmitter` 결과를
   `SessionMemoryEntryModel.emotion_vec` 에 실제로 적재.
2. Concrete retriever (e.g. `SessionMemoryManager.search`) 에 mixin
   상속 + 쿼리 확장.
3. 실사용 데이터 수집 후 PR-X6-3 / PR-X6-4 재활성.
