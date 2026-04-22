# Cycle 20260422_2 — X6 · AffectAware Retrieval + 비용 최적화

**사이클 시작.** 2026-04-22 (X5 종료 직후).
**선행.** X5 (`dev_docs/20260422`, 3 PR merged).
**사전 청사진.** `dev_docs/20260421_6/plan/05_cycle_and_pr_breakdown.md §6`.

## 목표

X3 의 `AffectTagEmitter` 는 emit 시점에 추출된 감정 태그를 creature
mood mutation 으로만 흘려보낸다. **메모리 레코드에는 감정 정보가
남지 않는다**. 이 사이클은 두 개의 infra 조각을 추가해 "감정
기반 검색" 이 가능한 토대를 만든다:

- `SessionMemoryEntryModel` 에 nullable 감정 필드 (`emotion_vec`,
  `emotion_intensity`) 추가 — 기존 행은 NULL, 신규 쓰기 경로에서
  선택적으로 채움.
- `AffectAwareRetrieverMixin` 도입 — 기존 retrieval 결과를 감정
  유사도로 재랭크하는 얇은 레이어.

## 범위 정책 — 본 사이클은 *infra-only*

plan/05 §6.3 "연구 성격" 명시: **실사용 데이터 없이는 튜닝 파라미터
산출 불가**. X1-X5 가 깐 경로에는 아직 감정 태그가 실제로 메모리에
적재되지 않는다 (태그는 AffectTagEmitter 에서 mood mutation 만
만들고 사라짐). 따라서:

- **Ship (infra 추가)**: PR-X6-1, PR-X6-2.
- **Defer (데이터 필요)**: PR-X6-3, PR-X6-4.

## PR 분해

plan/05 §6.2 표 그대로, Ship/Defer 구분만 명시:

| PR | 브랜치 | 상태 |
|---|---|---|
| PR-X6-1 | `feat/memory-schema-emotion-fields` | **Ship** — 순수 추가, 기존 읽기/쓰기 무영향 |
| PR-X6-2 | `feat/affect-aware-retriever-mixin` | **Ship** — infra-only, 실제 호출측 배선은 추후 |
| PR-X6-3 | `tune/prompt-cache-bucketing` | Defer — 실 사용량 데이터 필요 |
| PR-X6-4 | `chore/retrieval-cost-dashboard` | Defer — 실 대시보드 인프라 + 데이터 필요 |

## 불변식 (plan/05 §8 상속)

본 사이클이 새로 깨뜨리지 말아야 할 것:

- **Pure additive schema.** 기존 행을 건드리지 않음. 신규 컬럼은
  nullable + 기본값 NULL. 모든 기존 INSERT/SELECT 코드는 수정 없이
  동작.
- **Retriever 호환성.** 기존 retriever 호출 경로는 byte-identical 결과.
  Mixin 은 opt-in — 상속받지 않으면 동작 변화 없음.
- **FAISS 벡터 스토어 무영향.** 본 사이클은 SQL 메모리 테이블과 mixin
  만 손댐. FAISS index 포맷/경로 무변화.

## 비범위

- **실 데이터 인입 경로.** 감정 필드를 *채우는* 쓰기 경로 확장 —
  `AffectTagEmitter` 와 메모리 쓰기 사이에 브릿지가 필요. 별도 PR
  (X6-follow-up) 로 분리.
- **Vector store metadata 확장.** `ChunkMeta` 에 감정 차원 추가는
  FAISS 측 마이그레이션 동반. 본 사이클 SQL-only.
- **Prompt cache bucketing.** §6.3 대로 이월.
- **Retrieval cost dashboard.** 동일하게 이월.

## 산출 문서

- `progress/pr1_memory_schema_emotion_fields.md`
- `progress/pr2_affect_aware_retriever_mixin.md`
- `progress/cycle_close.md`
