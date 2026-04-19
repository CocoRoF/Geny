# 60. Phase 7-28 — Diff JSON export + atomic bulk import

## Scope

Import/export 표면에 대한 두 follow-up:

1. **Phase 7-23 follow-up** — DiffModal 의 비교 결과를 JSON 으로
   다운로드. 현재는 화면으로만 볼 수 있어서 리뷰/문서화에 수동
   복사가 필요.
2. **Phase 7-25 follow-up** — `/import-bulk` 에 `?atomic=true`
   쿼리 플래그 추가. 하나라도 실패하면 이미 생성된 env 를 모두
   삭제 (하드 delete) 해서 부분 성공 상태를 남기지 않는다.
   ImportEnvironmentModal 의 번들 경로에 체크박스로 노출.

두 개 모두 기존 기능에 옵션 하나씩 추가. PR 은 bundle 해서 낸다.

## PR Link

- Branch: `feat/phase7-28-diff-export-atomic-bulk`
- PR: (커밋 푸시 시 발행)

## Summary

`backend/controller/environment_controller.py` — 수정
- `import_environments_bulk` 에 `atomic: bool = False` 쿼리 파라미터
  추가.
- 실패 entry 감지 시 atomic 모드면 `fail_cause` 를 기록하고 이후
  entries 는 `not processed (atomic batch aborted)` 로 마킹.
- 루프 종료 후 atomic 이면 이미 성공한 env 들을 `svc.delete(new_id)`
  로 rollback, 결과 entry 를 `rolled back (...)` 으로 재작성.
- 응답 shape 은 기존 그대로. atomic 실패 시 `succeeded=0`.

`frontend/src/lib/environmentApi.ts` — 수정
- `importEnvBulk(body, opts?: { atomic?: boolean })` signature 확장.
  `atomic=true` 면 `?atomic=true` 쿼리 파라미터 부착.

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- 번들 경로에만 노출되는 "Atomic batch" 체크박스 (신규 state
  `atomic: boolean`). 기본 false.
- 제출 시 두 번째 인자로 `{ atomic }` 전달.

`frontend/src/components/modals/EnvironmentDiffModal.tsx` — 수정
- Footer 에 "Export JSON" 버튼 추가 (결과가 있을 때만 표시).
- 다운로드 payload 는 `{ version, generated_at, left, right, summary,
  added, removed, changed }` 구조. 파일명: `env-diff-<LEFT>__<RIGHT>-<STAMP>.json`.
- slug 함수로 파일명 안전화 (영숫자/`-_` 만, 32 자 컷).

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규: `diff.exportJson`, `importEnvironment.atomicLabel`,
  `importEnvironment.atomicHint`.

## Verification

### Diff export

- 두 환경 비교 → 결과 노출된 상태에서 Footer 의 "Export JSON"
  클릭 → 다운로드 파일에 left/right/summary/added/removed/changed
  가 JSON 으로 저장됨.
- 결과 이전 상태 (compare 전) 에는 버튼이 노출되지 않음.
- 파일명이 두 env 이름 slug + ISO timestamp 조합.
- ko 로케일에서 "JSON 내보내기" 로 표시.

### Atomic bulk import

- 번들 프리뷰 상태에서 "Atomic batch" 체크박스 등장 (단일 env 경로
  에는 없음).
- 체크 켜고 정상 번들 import → 전부 성공 (기존과 동일).
- 중간 entry 하나 의도적으로 malformed (manifest 제거) 로 만들고
  체크 켠 상태에서 import → 해당 entry 는 실제 에러, 이미 성공한
  entries 는 `rolled back (...)` 으로 표시, 남은 entries 는
  `not processed (atomic batch aborted)`. 서버에도 해당 envs 가
  존재하지 않음 (Environments 그리드 확인).
- 체크 끄고 동일 번들 → 기존 per-entry independent 동작.

## Deviations

- rollback 은 hard-delete (`svc.delete`) 를 사용. Geny 의 env 저장
  은 파일 시스템이라 soft-delete 개념이 없음. 세션이 해당 env 에
  이미 바인딩되어 있는 경우는 이 부분에서 dangling 이 발생할 수
  있지만, atomic import 는 "방금 만든" env 를 지우는 거라 실사용
  상 bind 된 세션이 있을 수 없다.
- 프론트는 atomic 결과를 특별히 다르게 렌더하지 않음. 기존 per-entry
  report 그대로 쓰고, 에러 메시지 prefix 로 `rolled back (...)`
  가 보이는 것으로 충분.
- DiffModal 의 JSON payload 는 다운로드 용도라 형태를 간결히 유지.
  Diff API 원본 응답 (backend) 은 약간 더 상세 (entry 의
  change_type 등) 이지만 프론트에서 쓰는 shape 만 내보냄.
- 파일명 slug 가 32 자 컷이라 동명 env 이름이 겹칠 가능성. 타임스탬프
  가 들어가므로 충돌은 실질 없음.

## Follow-ups

- atomic import 가 실패한 경우 "Retry without atomic" 같은 one-click
  re-submit 액션. 현재는 체크박스를 수동으로 끄고 다시 제출해야 함.
- DiffModal 의 JSON 이 아닌 human-readable markdown export (리뷰
  노트에 붙여넣기 편한 포맷).
- 세 개 이상 env 비교 (multi-diff matrix) — Phase 7-23 의 다른
  follow-up.
