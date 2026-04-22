# Cycle 20260422_3 — X6F · AffectAware 활성화 follow-up

**사이클 시작.** 2026-04-22 (X6 infra Ship 종료 직후).
**선행.** 20260422_2 (X6, 2 PR merged, infra-only).
**문제 제기.** X6 `cycle_close.md §다음 사이클` 에서 명시:
> 자연스러운 follow-up 후보: writer bridge + retriever adoption.

## 목표

X6 가 깐 저장소 컬럼 (`emotion_vec` / `emotion_intensity`) 과
재랭크 mixin 은 현재 **dead code** — 쓰는 쪽도 없고 읽는 쪽도
subclass 가 없다. 이 사이클은 그 양쪽 끝을 잇는다:

- **쓰기 경로.** `AffectTagEmitter` 가 emit 시점에 생성하는 mood
  mutation 에서 6-dim emotion vector 를 유도해 state.shared 에
  stash → memory record INSERT 가 이를 읽어 DB 에 적재.
- **읽기 경로.** 기존 STM search 함수를 `AffectAwareRetrieverMixin`
  으로 감싸 실사용 시도.

여기까지 하면 "감정 기반 검색" 의 end-to-end 회로가 처음으로 닫힘
— 이후 운영 데이터가 쌓이면 PR-X6-3 / PR-X6-4 (tuning / dashboard)
가 활성화 조건을 만족하게 됨.

## 범위 정책 — *작게 쪼갠 infra-only PR 집합*

plan/05 §9 "한 PR = 한 방향" 원칙을 지키려면 writer bridge 하나도
여러 레이어에 걸쳐 쪼개야 한다:

- PR-X6F-1 : 요약 헬퍼 (순수 함수) — pipeline 의존 없음.
- PR-X6F-2 : SQL INSERT 확장 — caller 변경 없음.
- PR-X6F-3 : emitter 가 state.shared 에 stash — consumer 없음.
- PR-X6F-4 : retriever 하나 adoption — 읽기 경로 개통.

각 PR 은 merge 후에도 "다른 쪽이 안 붙어 있어도 동작" 하는 구조 —
PR 2 만 merge 되어 있어도 기존 INSERT 는 영향 없고 새 kwargs 는
아직 아무도 안 부름.

**실제 pipeline 내 AffectTagEmitter → STM add_message 배선** (state.shared
에서 summary 를 꺼내 `record_message` 에 넘기는 마지막 연결) 은
의도적으로 *남긴다*. `agent_session_manager` 와 `memory.manager`,
`short_term` 세 레이어를 동시에 건드려야 해서 단일 PR 범위를 넘는다.
PR-X6F-3 까지 오면 summary 가 state.shared 에 나타나므로, 그 시점
이후 별도 사이클 (또는 본 사이클 내 후속 PR) 에서 pipeline 호출 경로를
정리해야 한다.

## PR 분해

| PR | 브랜치 | 상태 |
|---|---|---|
| PR-X6F-1 | `feat/affect-summary-from-mutation-buffer` | **Ship** — 순수 헬퍼 |
| PR-X6F-2 | `feat/memory-db-writes-affect-fields` | **Ship** — SQL INSERT 확장 (additive) |
| PR-X6F-3 | `feat/affect-tag-emitter-stashes-summary` | **Ship** — emitter 가 state.shared 에 기록 |
| PR-X6F-4 | `feat/stm-search-with-affect-rerank` | **Ship** — retriever adoption |
| PR-X6F-5 | (추후 사이클) pipeline 배선 | **Defer** — 세 레이어 동시 수정 필요 |

## 불변식 (plan/05 §8 + 20260422_2/index.md §불변식 상속)

- **Pure additive schema.** ✅ 이미 X6-1 에서 확보. 본 사이클은
  INSERT 쪽만 확장 — SELECT 기본 경로는 무변화.
- **Retriever 호환성.** ✅ 기존 retriever 어느 것도 behavior 변경
  없음. PR-X6F-4 는 *새 함수* 를 추가 (옛 함수 유지).
- **FAISS 벡터 스토어 무영향.** ✅ 본 사이클 SQL / emitter / helper
  만 손댐.
- **Side-door 재생 금지.** ✅ Emitter 는 이미 공식 표면 (state.shared).
  helper / search 는 opt-in API.
- **Mutation 은 4 op.** ✅ 본 사이클은 mutation 읽기만 — 새 op
  도입 없음.

## 비범위

- **Pipeline 내 STM write 배선.** `record_message(...)` → emotion
  kwargs 전달 경로. 3 레이어 수정 필요, 별도 PR.
- **PR-X6-3 / X6-4 재활성.** 여전히 운영 데이터 필요.
- **Vector store (FAISS) 감정 메타.** 여전히 범위 밖.

## 산출 문서

- `progress/pr1_affect_summary_helper.md`
- `progress/pr2_memory_db_writes_affect.md`
- `progress/pr3_affect_tag_emitter_stashes_summary.md`
- `progress/pr4_stm_search_affect_rerank.md`
- `progress/cycle_close.md`
