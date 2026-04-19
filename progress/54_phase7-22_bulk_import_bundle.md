# 54. Phase 7-22 — Bulk-import bundle detection in ImportEnvironmentModal

## Scope

Phase 7-21 이 Environments 탭에 bulk export 를 추가했지만,
가져오기 측에선 여전히 단일 env JSON 만 받는다. 같은 모달이
번들 포맷 (`{ version, exports: [{env_id, data}] }`) 을 감지하고,
각 entry 를 순차 import 해 주도록 확장한다.

## PR Link

- Branch: `feat/phase7-22-bulk-import-bundle`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- `ParseResult` 타입을 discriminated union 으로 변경:
  `{ kind: 'single' } | { kind: 'bundle' }`.
- 헬퍼 `classifySingleEnv(obj)` 분리 — 단일 env 객체를 파싱해
  manifest/snapshot 모드 메타 반환. 번들 entry 파싱에 재사용.
- `extractEnvPayload` 가 root 에 `exports: []` 가 있으면 번들로
  인식하고 각 entry 를 `classifySingleEnv` 로 검증.
- `handleConfirm` 이 kind 에 따라 분기:
  - `single`: 기존 경로 그대로.
  - `bundle`: 엔트리를 serial 하게 `importEnvironment` 호출,
    success/failure 를 집계한 `BundleResult` 를 state 에 저장.
- 파싱 성공 배너를 분기 렌더:
  - single: 기존 single-env summary.
  - bundle: "Detected bulk bundle vN — M environment(s)" + entry
    리스트 preview (이름/모드/stage count).
- Import 완료 후 `bundleResult` 가 있으면 per-entry 성공/실패
  리스트 패널 노출, footer 버튼은 "Done" 으로 변경.
- Name override 필드는 bundle 모드에선 숨김 (다수 env 에 단일
  override 가 어울리지 않음).
- 버튼 라벨이 bundle 모드에선 `Import N environments` /
  `Importing N…` 로 전환.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `importEnvironment.{bundleDetected, importBundleButton,
  importingBundle, bundleReport}` 신설.
- `common.done` 신설.

## Verification

- 7-21 로 export 한 `envs-bulk-*.json` 을 드래그 드롭:
  - "Detected bulk bundle v1 — N environment(s)" 배너와 entry
    preview 리스트가 뜬다.
  - 버튼 라벨이 "Import N environments" 로 변경.
  - Name override 필드는 숨김.
- Import 실행: 순차적으로 create 요청이 나가고, 종료 후 per-entry
  결과 리스트가 성공/실패 섹션으로 나뉘어 렌더. footer 의 버튼이
  "Done" 으로 전환. 클릭 시 모달 닫힘.
- 실패가 일부 있는 경우: 실패 항목만 error 아이콘 + 원 에러 메시지
  로 표시. 성공 항목은 새 env id 까지 함께 노출.
- 단일 env JSON 을 기존처럼 드롭: kind = 'single' 로 파싱되어 기존
  UX 유지 (name override, regenerate id 토글).
- 빈 번들 (`exports: []`) 은 "Bundle contains 0 entries" 에러로
  표시.
- `{ version: "1" }` 같이 version 만 있고 exports 가 없는 root: 번들
  감지 분기를 지나가서 일반 single-env 파싱으로 fallthrough → 정상
  "Missing environment body" 에러.

## Deviations

- 번들 entry 마다 고유 name override 를 제공하지 않는다. 실 사용
  빈도가 낮아 UI 복잡도 대비 가성비가 낮음. 필요하면 별도 PR 에서
  per-entry 편집 모드 추가.
- 실패한 entry 만 골라 retry 하는 버튼은 도입하지 않음. 재시도가
  필요하면 원본 JSON 을 편집해 다시 드롭 — 드물고, UI 상태관리가
  번거롭다.
- `regenerateId` 플래그는 bundle 에도 그대로 적용된다 (기본 on).
  복구 목적으로 원 id 를 보존하고 싶다면 체크 해제 후 import.
- 서버측 `/api/environments/import` 를 serial 호출하므로 N 개
  import 시 대략 N × single-import-latency. 100+ 개 번들은 현실
  사용 범위 밖이라 충분. 배치 endpoint 추가는 향후 과제.

## Follow-ups

- `/api/environments/import-bulk` 엔드포인트로 batch 처리 추가
  (트랜잭션성 rollback 포함).
- 번들 entry 별 name 편집 UI.
- Import 결과에서 성공 entry 카드로 직접 링크 (드로어 오픈).
