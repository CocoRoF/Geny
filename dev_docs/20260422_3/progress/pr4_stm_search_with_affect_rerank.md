# PR-X6F-4 · `feat/stm-search-with-affect-rerank` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 13 신규 테스트 pass (121 affect+emit+db total).
`AffectAwareRetrieverMixin` 이 마침내 실제 DB row 와 맞물린 구체
retriever 를 얻음.

## 범위

X6F 사이클의 **read path**. PR-X6-1 이 컬럼을 만들고, PR-X6-2 가 블렌딩
메커니즘을 제공했으니 이제 둘을 잇는 실제 retriever 를 추가한다.

### 1. `db_stm_search` 컬럼 확장

`backend/service/database/memory_db_helper.py`:

**import.**
```python
from service.affect import decode_emotion_vec, encode_emotion_vec
```

**SELECT 변경.**
```python
SELECT entry_id, content, role, metadata_json, entry_timestamp,
       emotion_vec, emotion_intensity
FROM session_memory_entries
...
```

**row dict 확장.**
```python
entries.append({
    "entry_id": ...,
    "content": ...,
    "role": ...,
    "metadata": meta,
    "entry_timestamp": ...,
    "emotion_vec": decode_emotion_vec(row.get("emotion_vec")),
    "emotion_intensity": row.get("emotion_intensity"),
})
```

기존 키 5개는 **미변경**, 신규 2개만 추가 → 기존 호출자 무영향.
corrupt vec 은 `decode_emotion_vec` 가 `None` 으로 삼킴 → 한 개의
잘못된 row 가 세션의 retrieval 전체를 죽이지 않음.

### 2. `STMAffectAwareRetriever` 구체 클래스

`backend/service/affect/stm_retriever.py` (신규):

```python
class STMAffectAwareRetriever(AffectAwareRetrieverMixin):
    def __init__(self, db_manager, *, affect_weight=None): ...
    def search(
        self,
        session_id: str,
        query_text: str,
        *,
        query_emotion_vec: Optional[Sequence[float]] = None,
        max_results: int = 10,
    ) -> List[Tuple[Dict[str, Any], float]]:
```

내부 흐름:
1. `db_stm_search(...)` 호출 → rows 또는 None.
2. recency 기반 descending text score `[1.0, (n-1)/n, ..., 1/n]` 부여
   (기존 "id DESC" 정렬을 mixin 이 소비할 수 있는 연속 scalar 로 번역).
3. 각 row 의 `emotion_vec` (이미 decoded) 와 함께 candidate triple
   구성.
4. `rerank_by_affect(candidates, query_emotion_vec)` 에 위임.

### 3. 왜 `service.affect` 안에 두는가 (`service.memory` 아니고)

`service.memory.__init__` 는 `vector_memory` (numpy 의존) 를 즉시
import — sandbox 에서 못 씀. X6-1 부터 유지해 온 stdlib-only import
규율을 이어서 간다. nullable 로 남긴 retriever 는 "nothing to do"
일 때 조용히 text 만 반환 → memory 스택이 없는 환경에서도 동작 가능.

나중에 last-mile 이 붙은 뒤 `ShortTermMemory.search_affect_aware` 를
이 retriever 위에 얇게 wrapping 해도 됨 — 그 순간엔 memory 스택이
이미 import 된 상태.

### 4. 삼중 graceful degradation

| 조건 | 동작 |
|------|------|
| `query_emotion_vec = None` | text score 내림차순 그대로 (mixin null path) |
| 모든 후보 `emotion_vec = None` | text score unchanged — `blend_scores(text, None) = text` |
| 부분 커버리지 (legacy + X6F-3 wired rows 혼재) | 있는 쪽만 blended, 없는 쪽은 text score — 같은 스케일이므로 비교 가능 |
| dim mismatch (4-dim ↔ 6-dim) | `cosine_similarity → None` → 해당 row 는 text fallback |

legacy DB 에서 점진적으로 affect 데이터가 차 오르는 상황을 가정한 설계.

## 테스트 (13 신규)

`backend/tests/service/affect/test_stm_retriever.py`:

**`db_stm_search` 컬럼 확장 pin (5개).**
1. `test_db_stm_search_selects_emotion_columns` — SQL query 에
   `emotion_vec` / `emotion_intensity` 포함.
2. `test_db_stm_search_decodes_emotion_vec_per_row` — JSON → list
   round-trip.
3. `test_db_stm_search_handles_null_emotion_vec` — NULL 보존.
4. `test_db_stm_search_corrupt_vec_decodes_to_none` — 깨진 JSON 은
   `None`, intensity (스칼라) 는 별개로 살아있음.
5. `test_db_stm_search_preserves_existing_dict_shape` — 기존 5개 키
   그대로, 2개만 추가.

**Retriever 삼중 fallback pin (5개).**
6. `test_retriever_no_query_vec_preserves_recency_order`
7. `test_retriever_empty_query_vec_treated_as_none`
8. `test_retriever_all_null_candidate_vecs_yields_text_only_order`
9. `test_retriever_partial_coverage_null_vec_rows_fall_back_to_text`
10. `test_retriever_dim_mismatch_falls_back_to_text_score`

**Promotion signal (1개).**
11. `test_retriever_promotes_affect_matching_row` — 오래된 joy row
    vs 최근 anger row + query=joy + weight=0.9 → 오래된 joy 가 위로.

**플러밍 (2개).**
12. `test_retriever_empty_search_returns_empty_list`
13. `test_retriever_swallows_db_errors_into_empty_list`

**추가.**
14. `test_retriever_honors_affect_weight_override` — 생성자 override /
    default 0.3.

**결과.**
```
pytest tests/service/affect/test_stm_retriever.py \
       tests/service/database/test_memory_db_affect.py \
       tests/service/affect/ -q
81 passed in 0.12s

pytest tests/service/emit/ tests/service/affect/ tests/service/database/ -q
121 passed in 0.23s
```

(state/ / memory/ 는 기존 numpy-sandbox 수집 실패와 동일 — 본 PR 과
무관.)

## 불변식 확인

- **기존 `db_stm_search` 호출자 무영향.** ✅ 반환 dict 에 키 2개만
  추가. 기존 5개 키 이름/타입/순서 무변.
- **Mixin 행동 무변.** ✅ `AffectAwareRetrieverMixin` 소스 미수정 —
  순수 consumer 로서 inherit 만.
- **FAISS/pgvector 미도입.** ✅ JSON TEXT 컬럼 그대로.
- **Side-door 금지.** ✅ retriever 는 순수 consumer — 자체 INSERT /
  UPDATE 없음.
- **Shadow mode.** N/A — opt-in. 호출자가 `STMAffectAwareRetriever`
  를 명시적으로 사용할 때만 affect 가 개입. 기존 `ShortTermMemory.search`
  경로 완전 불변.

## 남은 작업 — Last-mile (다음 사이클 이월)

지금 상태로 끝까지 가면 실제 affect 기반 retrieval 이 작동하려면:

1. `ShortTermMemory.add_message` 가 `emotion_vec` / `emotion_intensity`
   kwargs 를 수용 (PR-X6F-2 DB writer 와 연결).
2. `SessionMemoryManager.record_message` 도 동일.
3. `AgentSessionManager` (혹은 assistant turn 캡처 로직) 가
   `state.shared[AFFECT_TURN_SUMMARY_KEY]` 를 읽어 `record_message`
   에 전달 + 소비 후 `shared.pop`.
4. Retrieval caller (RAG block / memory injection 파이프) 에서
   `STMAffectAwareRetriever(...).search(query_emotion_vec=<current turn vec>)`
   로 교체.

네 지점을 한 PR 로 묶으면 "한 PR = 한 방향" 원칙 위배 → 별도 사이클
이월. 이 사이클은 PR-X6F-5 cycle_close 로 마감.

## PR-X6F-3 와의 독립성

X6F-3 는 **write path 준비 (stash)**, X6F-4 는 **read path 소비
(retrieve)**. 둘은 서로 import 하지 않고, DB 데이터가 실제로 적재되기
전까지는 둘 다 *dormant 하게 안전* — retriever 는 `None` 만 보고 text
fallback 으로 흐르고, stash 는 아무도 안 읽음. last-mile PR 하나가
두 쪽을 동시에 "hot" 으로 전환한다.
