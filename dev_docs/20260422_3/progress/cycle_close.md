# Cycle 20260422_3 — X6F 종료 정리

**Date.** 2026-04-22
**Shipped.** PR-X6F-1, PR-X6F-2, PR-X6F-3, PR-X6F-4 (4 PR merge —
index.md §범위 정책 상 Ship 범위 완결)

## 정착한 것

| PR | 브랜치 | 내용 |
|---|---|---|
| PR-X6F-1 | `feat/affect-summary-from-mutation-buffer` | 순수 헬퍼 `service.affect.summary` — `summarize_affect_mutations` (MutationBuffer-style entries → 6-dim emotion_vec + scalar intensity). stdlib-only, null-safe, emit pipeline 무의존. |
| PR-X6F-2 | `feat/memory-db-writes-affect-fields` | `db_stm_add_message` / `db_stm_add_event` 가 `emotion_vec` / `emotion_intensity` kwargs 수용 → INSERT 2컬럼 확장. `_coerce_emotion_vec` 가 list/str/None 셋 경우 모두 정규화. 기존 caller 무영향 (NULL/NULL 저장). |
| PR-X6F-3 | `feat/affect-tag-emitter-stashes-summary` | `AffectTagEmitter.emit()` 가 mutation apply 직후 `stash_affect_summary(state.shared, buf)` 호출 → `state.shared[AFFECT_TURN_SUMMARY_KEY]` 에 frozen `AffectTurnSummary(emotion_vec, emotion_intensity)` 기록. `EmitResult.metadata["summary_stashed"]` 플래그 노출. |
| PR-X6F-4 | `feat/stm-search-with-affect-rerank` | `db_stm_search` SELECT 가 emotion_vec / emotion_intensity 까지 내려주고 per-row decode. 신규 `STMAffectAwareRetriever` 가 `AffectAwareRetrieverMixin` 상속 + text score + affect rerank 블렌딩. triple graceful fallback. |

**테스트 성장치 (X6 누계 위에):**

- `tests/service/affect/test_summary.py` +14 tests (X6F-1)
- `tests/service/database/test_memory_db_affect.py` +16 tests (X6F-2)
- `tests/service/emit/test_affect_tag_emitter.py` +6 tests (X6F-3)
- `tests/service/affect/test_stm_retriever.py` +13 tests (X6F-4)
- **X6F 총 +49 tests, 회귀 없음.**

**주요 스위프 결과.**
```
pytest tests/service/emit/ tests/service/affect/ tests/service/database/ -q
121 passed
```
(memory/ state/ 수집 실패는 pre-existing numpy-sandbox 문제. 본
사이클과 무관.)

## 의도적으로 미이식 (index.md §비범위 재확인)

본 사이클은 **양 끝단 (writer helper + DB 확장 + emitter stash + read
retriever)** 을 서로 *독립 작동 가능*한 상태로 정착시킨다. 중간 배선
— 파이프라인 내 STM write / retrieval 호출 경로 교체 — 은 끝내 의도적
보류.

### Last-mile: pipeline write 배선

현 상태로는:
- `AffectTagEmitter` 가 `state.shared[AFFECT_TURN_SUMMARY_KEY]` 에
  summary 를 남긴다. ✅
- `db_stm_add_message(emotion_vec=, emotion_intensity=)` 가 kwargs
  를 받는다. ✅
- 하지만 `ShortTermMemory.add_message` / `SessionMemoryManager.record_message`
  는 아직 kwargs 경로가 없음 → state.shared 에 쌓이는 요약이 DB 에
  닿지 못함.

이걸 잇는 PR 은 세 레이어 동시 수정 (`agent_session_manager` 가
shared key 를 읽어서 `record_message` 로 전달, `record_message` 가
`add_message` 로 전달, `add_message` 가 `db_stm_add_message` 로
전달) 이라 "한 PR = 한 방향" 원칙 위반. 별도 사이클로 이월.

### Last-mile: retrieval 호출 교체

`STMAffectAwareRetriever` 는 import 가능한 상태지만 실제 RAG /
memory injection 블록에서 아직 호출되지 않음 — 호출자 쪽 정리도
별도 PR.

### PR-X6-3 / PR-X6-4 재활성 조건

X6 cycle_close.md §다음 사이클 에 이미 명시:

1. Last-mile writer 배선 merge 완료
2. 실제 세션 데이터에 `emotion_vec` 이 수 주 동안 적재
3. 운영 로그 기반 cache miss / latency / mAP 측정
4. 그 위에 PR-X6-3 (bucket tuning) / PR-X6-4 (dashboard) 진입

이 사이클은 조건 1 을 위한 **infra 최종 완성** 지점. 조건 2~4 는
별도.

## PR 간 독립성 (merge 순서 자유)

| 페어 | 관계 |
|---|---|
| X6F-1 ↔ X6F-2 | X6F-2 가 X6F-1 의 summarize 결과를 kwargs 로 받지만, X6F-2 자체는 generic list/str kwargs 만 쓰므로 X6F-1 없이도 작동. |
| X6F-2 ↔ X6F-3 | X6F-3 가 X6F-2 출력 형식에 맞춘 summary 를 만들지만, 실제 DB 쓰기는 last-mile 후에나 발생 — 현재는 dead-but-safe. |
| X6F-3 ↔ X6F-4 | write path (stash) ↔ read path (retrieve). 서로 import 없음. DB 가 비어 있어도 retriever 는 text-only fallback. |

모든 페어가 merge 순서 자유 → 롤백 안전성도 역방향으로 동일.

## 불변식 체크

X6F PR 을 통해 깨지지 않은 것:

1. **executor 는 게임을 모른다.** → X6F 는 Geny 리포만 수정. ✅
2. **Pure additive schema.** → X6-1 에서 이미 확보. X6F 는 INSERT
   2개 컬럼 확장 (동일 컬럼), SELECT 1개 확장. ✅
3. **Retriever 호환성.** → `STMAffectAwareRetriever` 는 *신규* 클래스.
   기존 `ShortTermMemory.search` 경로 bit-identical. ✅
4. **FAISS vector store 무영향.** → 본 사이클 SQL / emitter / helper
   / retriever 구현만. vector_store.py 미변경. ✅
5. **Mutation 4 op.** → `add` 경로만 소비. 새 op 도입 없음. ✅
6. **Side-door 재생 금지.** → `state.shared[KEY]=...` 는 기존 패턴
   (MUTATION_BUFFER_KEY / CREATURE_STATE_KEY 와 동일 관용). ✅
7. **Stage 는 Provider 를 직접 잡지 않는다** / **Decay 는 TickEngine
   에만** / **Manifest 전환은 세션 경계** — 본 사이클 관여 지점 없음.
   N/A. ✅

## 산출물 요약

```
backend/service/affect/summary.py              # X6F-1 + X6F-3
backend/service/affect/stm_retriever.py        # X6F-4
backend/service/database/memory_db_helper.py   # X6F-2 + X6F-4 (SELECT 확장)
backend/service/emit/affect_tag_emitter.py     # X6F-3 (stash 호출)
backend/tests/service/affect/test_summary.py             # X6F-1 (14)
backend/tests/service/database/test_memory_db_affect.py  # X6F-2 (16)
backend/tests/service/emit/test_affect_tag_emitter.py    # X6F-3 (+6)
backend/tests/service/affect/test_stm_retriever.py       # X6F-4 (13)
dev_docs/20260422_3/index.md
dev_docs/20260422_3/progress/pr1_affect_summary_helper.md
dev_docs/20260422_3/progress/pr2_memory_db_writes_affect.md
dev_docs/20260422_3/progress/pr3_affect_tag_emitter_stashes_summary.md
dev_docs/20260422_3/progress/pr4_stm_search_with_affect_rerank.md
dev_docs/20260422_3/progress/cycle_close.md    # this
```

## 다음 사이클

plan/05 청사진 기준 X1~X6 커버리지는 20260422_2 종료 시점에 이미
완결. 본 사이클은 그 위의 **활성화 레이어** — X6F 사이클 종료로
"infra + hot path 준비" 까지 확보.

자연스러운 follow-up 후보 (별도 사이클로 진입):

1. **X6F-follow-up — pipeline 배선.** `ShortTermMemory.add_message`
   → `record_message` → `AgentSessionManager` 가 `state.shared[AFFECT_TURN_SUMMARY_KEY]`
   을 꺼내 전달. 네 레이어 동시 수정. 여기까지 하면 비로소 DB 에
   `emotion_vec` 이 실제로 차오르기 시작.
2. **X6F-follow-up — RAG 호출 교체.** 기존 memory injection 블록
   중 하나를 `STMAffectAwareRetriever` 로 전환. 검색 입력에 현재 턴의
   `query_emotion_vec` 을 공급.
3. **(조건부) X6-3 / X6-4 재활성.** 1 + 2 merge 후 수 주 운영 데이터
   확보 시 prompt cache bucketing / cost dashboard.
4. **(선택) X5-4 / X5-5.** attach_runtime kwarg 가 *정말로 필요해지는*
   지점이 생길 때. 지금 요구 지점 없음.

본 사이클 종료.
