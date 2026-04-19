# 34. Phase 6d-8 — ImportManifestModal: auto-backup before overwrite

## Scope

Phase 6d-9 (PR #79) 는 import 전에 diff 만 보여줬다. 실수로 엉뚱한
manifest 를 덮어쓴 뒤에는 여전히 서버 저장소에서 복구할 방법이
없다. 백엔드에 snapshot 이력 시스템을 도입하기엔 범위가 크므로,
클라이언트 측 1-step safety net 만 먼저 붙인다.

이 PR 은 ImportManifestModal 에 "Download current manifest as backup
before overwrite" 체크박스 (기본 on) 를 추가한다. Submit 시점에
`exportEnvironment(envId)` 결과를 타임스탬프가 찍힌 파일로 로컬에
다운로드한 뒤에만 `replaceManifest` 를 호출한다. 백업 실패 → 오버라이트
차단 후 인라인 에러.

## PR Link

- Branch: `feat/frontend-phase6d8-import-backup`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportManifestModal.tsx` — 수정
- 로컬 모듈 함수 `triggerDownload(filename, content)` 추가 —
  `EnvironmentDetailDrawer` 와 동일한 Blob/anchor 트릭을 그대로
  복제 (모달이 드로어 독립적으로 동작해야 하므로 import 금지).
- 스토어에서 `exportEnvironment` 구조분해 추가.
- 상태 `backupBeforeImport: boolean` (기본 true).
- `handleConfirm` 진입부에서 체크박스가 켜져 있으면 `exportEnvironment` +
  `triggerDownload(env-${safeName}-backup-${ISO timestamp}.json, ...)` 를
  먼저 실행. 실패 시 에러 배너만 표시 + `setSubmitting(false)` + return.
  성공했을 때만 기존 `replaceManifest` 호출 — 기존 성공 경로는 그대로.
- 파일 이름 정규화는 드로어의 export 경로와 동일
  (`[^a-zA-Z0-9_-]+ → _`). 백업 전용 suffix 로 overwrite 이전의
  원본인지 한눈에 구분된다.
- UI: diff 프리뷰 블록과 error 배너 사이에 compact 체크박스 카드 —
  `Download` lucide icon + 1줄 label + 1줄 help.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `importManifest.backupLabel` / `backupHelp` / `backupFailed` 3개
  en/ko 동수.
- `backupFailed` 는 `{msg}` 인터폴레이션 — 실제 네트워크/권한 에러
  메시지를 그대로 노출.

## Verification

- "백업 실패 → 오버라이트 차단" 정책: 체크가 켜져 있는데 export 가
  throw 하면 `setSubmitError` + early return 이라 `replaceManifest` 에
  도달하지 않는다. 체크가 꺼져 있으면 이 분기를 통째로 스킵 —
  사용자가 명시적으로 backup 을 포기한 경우 기존 빠른 경로 유지.
- `exportEnvironment` 는 기존 드로어의 Export 버튼이 이미 쓰는 API —
  `environmentApi.exportEnv` → `GET /api/environments/{id}/export`.
  별도 엔드포인트 추가 없음.
- Filename 포맷: `env-${safeName}-backup-${ISO}.json`. Colon 이
  파일시스템에서 걸릴 수 있어 `[:.]` → `-` 로 치환. 드로어의 단순
  export (`env-${safeName}.json`) 와 구분되도록 `-backup-` 세그먼트를
  끼움.

## Deviations

- 체크박스 기본값은 on — "안전 기본값" 원칙. 빠른 반복이 필요한
  파워유저는 매번 해제해야 하지만, destructive 액션에서는 수용할
  수 있는 마찰이다.
- 서버측 이력/auto-restore 는 여전히 없음. 이번 PR 은 오롯이 클라이언트
  백업. 다음 단계 (manifest history) 에서 backend storage + revert
  엔드포인트를 얹어야 한다.
- 기본 override 액션 버튼 라벨은 바꾸지 않았다 — "Overwrite manifest"
  그대로. 백업은 pre-step 이라 주 액션 의미가 변하지 않는다.

## Follow-ups

- Phase 6d-10 (tentative): drag-and-drop 백업 JSON 을 다시 import
  필드로 떨어뜨리면 자동 restore 로 인식 — "실수했다" 원클릭 복구.
- 서버 side snapshot/list/restore API — 팀 내 공유 복구가 필요할 때.
- Plan 06 최종 통합 문서 PR 은 여전히 남아있음.
