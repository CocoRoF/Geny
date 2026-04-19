# 41. Phase 7-9 — ImportEnvironmentModal (create new env from blob)

## Scope

Store 에는 `importEnvironment(data)` action 이 있었고 백엔드도
`POST /api/environments/import` 를 제공하고 있었지만, 이 경로를
부를 수 있는 UI surface 가 없었다 — 오직 ImportManifestModal
(기존 env 의 manifest 를 덮어쓰기) 만 노출되어 있어, "Export 한
백업을 새 환경으로 복원" 하는 당연한 흐름이 끊겨 있었다.

이 PR 은 Environments 탭 툴바에 Import 버튼 + 전용 모달을 추가해
그 gap 을 메운다. 백엔드 endpoint 는 이미 존재하므로 프런트만
수정.

## PR Link

- Branch: `feat/frontend-phase7-9-import-env-modal`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 신규
- 드롭존 (drag-over 시각 피드백 포함, Phase 7-8 패턴 재사용) + 파일
  선택 + JSON paste 3-way 입력.
- `extractEnvPayload` — 다음 shape 을 받아들임:
  - raw env record (`{id, name, manifest|snapshot, ...}`)
  - export envelope (`{data: {...}}`, export response 그대로)
  - envelope 가 있으면 `data` 우선 선택.
  `manifest` (v2) 또는 `snapshot` (legacy) 중 하나는 필수.
- parsed 성공 시 녹색 배지에 mode / version / stage count / name 을
  표시.
- 이름 덮어쓰기 필드 (optional) — 비어있으면 원본 name 유지.
- "Generate new id" 토글 (기본 on) — 켜져있으면 payload 에서 `id`
  필드를 제거해 백엔드가 새 id 를 배정. 끄면 원본 id 를 그대로
  사용하므로 "삭제된 동일 id env 의 자리로 복원" 하는 흐름에만
  의미가 있음.
- `importEnvironment` 호출 → 성공 시 `onImported(id)` + `onClose`.
  EnvironmentsTab 이 `setOpenEnvId(id)` 를 받아 방금 만든 env 의
  drawer 를 즉시 연다.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- lucide `Upload` import.
- `showImport` state.
- 툴바에 "Import…" 버튼 — Compare 와 New Environment 사이.
- `ImportEnvironmentModal` 렌더 블록.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.importEnvironment: 'Import…' / '가져오기…'`
- `importEnvironment.*` 블록 — title, subtitle, dropHint, chooseFile,
  loadedFile, jsonLabel/Placeholder/Hint, parsedOk, nameOverride*,
  regenerateId*, importButton, importing, failed.

## Verification

- `importEnv` API 래퍼는 `{data}` 로 래핑해 `POST /api/environments/
  import` 에 던진다 (`environmentApi.ts:97`). 백엔드
  `import_json(data)` 는 `data` dict 에서 `manifest`/`snapshot` 을 복원
  하고 `id` 가 없으면 `_fresh_id()` 로 부여 — 프런트 "regenerate id"
  토글과 일관.
- `useEnvironmentStore.importEnvironment` 는 성공 후 `loadEnvironments()`
  를 호출하므로 카드 목록이 자동 갱신.
- 모달 parse 는 v2 manifest 와 v0.7 snapshot 둘 다 허용 — 백엔드의
  "both shapes accepted" 정책과 대칭.
- Import 후 `onImported(id)` → `setOpenEnvId(id)` 로 곧바로
  EnvironmentDetailDrawer 가 열려 결과 확인이 가능.
- 빈 입력 / 잘못된 JSON / manifest/snapshot 누락 3 가지 parse-fail
  케이스는 빨간 경고 박스로 표시. Import 버튼은 ready 가 아니면
  disabled.

## Deviations

- 다중 파일 import 는 scope 밖. `files[0]` 만 사용.
- 파일을 브라우저 바깥에서 드롭하면 자동으로 모달이 열리는 global
  drag-handler 는 넣지 않았다. 모달이 열린 상태에서만 드롭존 활성.
- 백엔드가 이미 `setdefault(created_at)` / `updated_at = now` 를
  처리하므로 프런트에서 타임스탬프 손보는 로직은 넣지 않았다.
- 같은 id 로 이미 존재하는 환경이 있을 때 백엔드 거동 (overwrite vs
  error) 은 `import_json` 구현에 맡긴다. 프런트는 "regenerate id"
  기본값으로 이 이슈를 우회하도록 유도.

## Follow-ups

- CreateEnvironmentModal 의 `mode` 에 `'import'` 를 추가해 단일
  모달로 통합할지 검토 — 현재는 모달이 2 개 분리돼 있지만 mental
  model 로는 "새 환경 만드는 방법 4 가지" 가 자연스러운 편.
- 드롭존에 파일 타입 검증 (dataTransfer.items 로 MIME 가드).
- 대용량 (수 MB) 백업을 붙여넣을 때 textarea 가 무거워지는 현상 —
  paste 영역을 monaco-lite 또는 virtualized textarea 로 교체.
- Import 성공 후 toast / snackbar 피드백 — 현재는 drawer 가 곧바로
  열려서 충분하지만, 대시보드 전환 없이 import 하는 경우도 고려.
