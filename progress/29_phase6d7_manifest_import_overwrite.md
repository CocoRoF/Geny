# 29. Phase 6d-7 — Manifest import / overwrite UX

## Scope

Backend 에는 이미 `PUT /api/environments/{id}/manifest`
(`environmentApi.replaceManifest`) 가 있지만, UI 에서는 manifest 전체를
파일로 주입할 경로가 없었다. Export 는 drawer 에 있으므로 대칭으로
"기존 env 에 manifest 덮어쓰기" action 을 추가한다.

## PR Link

- Branch: `feat/frontend-phase6d7-manifest-import-overwrite`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportManifestModal.tsx` — 신규
- `createPortal` 모달 (CreateEnvironmentModal / ImportEnvironment 와
  스타일 맞춤). Props: `{ envId, envName, onClose, onImported? }`.
- 입력 경로 2 종: (1) 파일 드롭 / file input, (2) JSON paste textarea.
  파일을 읽으면 `rawText` 에 채워넣는다 (그 자리에서 파싱되므로 상태가
  하나로 유지됨).
- 파싱은 `useMemo` 에서 `JSON.parse` → `extractManifest` 순. envelope
  관대하게 처리: `{version, stages}` 를 만족하는 첫 후보를 찾을 때까지
  raw object / `.manifest` / `.data.manifest` / `.data` 순서로 시도한다
  (export 응답 형태가 `{data: {manifest: ...}}` 든 `{manifest: ...}` 든
  raw manifest 든 받을 수 있도록).
- Parse 성공 시 초록 "Parsed OK — manifest v{v}, {n} stage(s)" 안내.
  실패 시 빨간 에러 + textarea border 빨강. 실패 상태면 Overwrite 버튼
  disabled.
- 덮어쓰기 확인 문구를 상단 노란 경고 박스로 상시 노출 — 모달 열자마자
  irreversible 임이 시각적으로 드러남.
- 확정 시 `replaceManifest(envId, parsed)` 호출, 성공하면 `onImported()`
  콜백 → drawer 에서 `loadEnvironment(envId)` 재로드.

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- footer actions 에 "Import manifest…" 버튼 추가 (Export 바로 뒤).
  Lucide `Upload` 아이콘.
- 버튼 클릭 시 `showImportManifest` 토글 → ImportManifestModal 오픈.
  `onImported` 에서 drawer 를 닫지 않고 env 재조회만 실행 — 사용자가
  변경된 manifest preview 를 drawer 에서 바로 확인할 수 있음.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `environmentDetail.importManifest` — drawer footer 버튼.
- `importManifest.*` 블록 신규 (13 keys): title, subtitle (`{name}`),
  warning, dropHint, chooseFile, loadedFile (`{name}`), jsonLabel,
  jsonPlaceholder, jsonHint, parsedOk (`{version}`, `{count}`),
  overwriteButton, importing, failed. 양쪽 언어 키 동수.

## Verification

- Import 경로가 기존 `environmentApi.importEnv` (new env 생성) 와
  충돌하지 않음 — 이 모달은 명시적으로 `replaceManifest(envId, ...)`
  만 호출한다. 파일을 선택해도 새 env 가 생기지 않는다.
- Envelope 관대 파싱: 사용자가 drawer 의 Export 버튼으로 내보낸 파일
  (`{data: {...}}` 래핑) 과, 직접 백엔드 response body 에서 복사한
  raw manifest 모두 그대로 붙여넣으면 통과.
- 빈 textarea 상태는 에러도 안내도 아님 (중립) — drop-zone 안내만 표시.
  사용자가 "아직 입력하지 않음" 을 빨간 텍스트로 보면 오인할 수 있음.
- `replaceManifest` 성공 시 store 가 updated `selectedEnvironment` 를
  반영하므로 `loadEnvironment` 를 한 번 더 부르는 것은 중복이지만,
  drawer 가 envId 기반으로만 subscribing 하고 있어서 안전 차원에서
  유지. 비용은 GET 한 번.

## Deviations

- 서버 측 validation 에 의존함 — 프론트는 `{version, stages[]}` 의
  minimal shape 만 체크하고 manifest 내부 stage 개수 / schema 정합성은
  검사하지 않는다. Manifest 는 복잡한 타입 구조고, 서버 (`Environment
  Service`) 가 어차피 `pydantic` 검증 + `Pipeline.from_manifest` 스트릭트
  모드로 최종 검증하므로 프론트 중복 체크는 가치 낮음.
- Diff 를 import 전에 미리 보여주는 기능은 없음. 현재 환경 vs. 들어올
  manifest 를 비교하고 싶으면 일단 Export → 새 env 로 import → diff
  모달로 확인. 빈도 낮아 보여 이번 PR 엔 포함 안 함.
- "덮어쓰기 전에 자동 백업" 토글 없음. 사용자는 Export 를 수동으로
  먼저 눌러야 한다. Warning 박스에 명시.

## Follow-ups

- Phase 6d-8 (tentative): backup/restore — "앞선 manifest 로 1-step
  되돌리기" history. 현재는 export 해두지 않으면 덮어쓴 manifest 를
  복구할 수 없다.
- Phase 6d-9 (tentative): import preview — diff 모달 로직을 재사용해
  Overwrite 전에 added/removed/changed 를 인라인으로 보여주기.
- Phase 7-3: CreateSessionModal 의 `memory_config` override UI.
