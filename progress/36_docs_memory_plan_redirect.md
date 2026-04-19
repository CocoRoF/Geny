# 36. docs/MEMORY_UPGRADE_PLAN.md — historical banner

## Scope

[`progress/35_rollout_verification_summary.md`](35_rollout_verification_summary.md)
§Deviations 에서 남긴 follow-up: "옛 `docs/MEMORY_UPGRADE_PLAN.md`
를 plan 시리즈로 리다이렉트 또는 삭제 + 안내". 1617줄짜리 문서라
완전 삭제는 히스토리컬 근거를 잃게 된다. 대신 상단에 superseded
배너를 붙여 "현재 기준 문서" 가 아님을 명확히 하고, 실제 기준인
`plan/03` + `plan/06` + `progress/index.md` 로 유도한다.

## PR Link

- Branch: `docs/memory-upgrade-plan-redirect`
- PR: (이 커밋 푸시 시 발행)

## Summary

`docs/MEMORY_UPGRADE_PLAN.md` — 수정
- 기존 첫 블록 (제목 + 메타) 위에 historical banner 추가:
  - superseded 경고.
  - `plan/03_memory_migration.md` / `plan/06_rollout_and_verification.md`
    / `progress/index.md` 로의 경로 링크.
  - "보존하지만 현재 동작 기준은 아니다" 명시.
- 본문은 손대지 않음 — 원본 설계안을 히스토리컬 아티팩트로 유지.

## Verification

- 링크 경로: `docs/` 와 `plan/`, `progress/` 는 repo 루트에서 형제
  디렉토리. `../plan/...`, `../progress/...` 상대경로가 맞다.
- Banner 는 GitHub 렌더링에서 blockquote 로 강조된다 — "현재 문서"
  로 오인될 여지를 줄인다.
- 파일 크기는 변하지 않은 것과 다름없다 (~+11 줄). 링크 검색 / 기존
  북마크 안전.

## Deviations

- 완전 삭제 / `plan/` 로의 이관은 하지 않았다. 초기 설계와 이후 실제
  구현이 어느 지점에서 분기했는지 참고자료로 남기는 편이 낫다.
- 다른 `docs/` 하위 문서 (예: `MEMORY_MODEL_LIGHTWEIGHT_PLAN.md`) 도
  비슷한 검토가 필요할 수 있으나, 이번 PR 에서는 memory upgrade 건만
  처리 — 타 문서는 v0.20.0 통합과 직접 연결이 약하다.

## Follow-ups

- `docs/STORAGE_MEMORY_INTERACTION_REVIEW.md` 등 memory 관련 문서
  일괄 검토 — 더 이상 유효하지 않은 가정이 없는지.
- Plan 06 summary 의 남은 follow-up: reverse lookup / performance QA /
  server-side snapshot 은 별도 사이클에서 처리.
