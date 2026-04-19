# 33. Phase 6d-9 — ImportManifestModal: current-vs-incoming diff preview

## Scope

Phase 6d-7 (PR #... — ImportManifestModal) 은 파서/오버라이트 플로우만
제공했다. 붙여넣은 manifest 가 현재 저장된 것과 얼마나 다른지 확인할
방법이 없었다 — 복구가 어려운 destructive 액션인데도 "정말로 맞게
넣는 건지" 는 사용자가 JSON 을 직접 눈으로 비교해야 했다.

이번 PR 은 파싱에 성공한 incoming manifest 와 현재 저장본 사이의
diff 를 모달 안에서 바로 보여준다. 백엔드에 stored-vs-stored 비교만
있어서 blob-vs-stored 용도로는 동일 의미의 클라이언트 diff 헬퍼를
추가로 도입했다.

## PR Link

- Branch: `feat/frontend-phase6d9-import-preview`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/lib/environmentDiff.ts` — 신규
- `diffManifests(current, incoming): {added, removed, changed}` 순수
  함수. `EnvironmentService.diff` 파이썬 구현 (`_diff_recursive`) 과
  경로 포맷 (`a.b[0].c`) / 의미 (object key 추가/제거, list index 길이
  차이, scalar 변경) 을 1:1 로 맞췄다.
- 스칼라 비교는 `JSON.stringify` 동등성 — `undefined` / function 등은
  manifest 에 들어가지 않으므로 충분하다.

`frontend/src/components/modals/ImportManifestModal.tsx` — 수정
- `useEffect` 로 진입 시 `selectedEnvironment` 가 없거나 다른 envId 면
  `loadEnvironment(envId)` 를 백그라운드로 호출. 드로어에서 열린
  정상 경로에서는 이미 캐시되어 있어 no-op.
- `currentManifest` 가 로드되어 있고 파싱이 성공하면
  `diffManifests` 결과를 `useMemo` 로 계산.
- Parse hint 아래에 collapsible 박스 —
  `+{added} −{removed} ~{changed}` 카운트 요약과, 펼치면 섹션별로
  path 리스트 (섹션당 최대 20 개, 초과분은 "…외 N 건").
- `diffTotal === 0` 이면 "동일" 안내만 표시.
- `currentManifest` 로드 실패/미로드 상태에서는 "프리뷰 불가" 한 줄
  안내만 — 기존 오버라이드 버튼은 그대로 동작 (diff 는 정보성).

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `importManifest.diffTitle` / `diffIdentical` / `diffAdded` /
  `diffRemoved` / `diffChanged` / `diffMore` / `diffUnavailable` —
  en/ko 동수.

## Verification

- Diff 경로 포맷 parity: 백엔드는 `stages[0].config.temperature` 형태
  (dict → `.`, list → `[i]`) 로 생성한다. 프론트 헬퍼도 동일 —
  `stages` 배열 자체가 object 안 key 이므로 `stages[0].…` 으로 찍힘.
- Incoming manifest 파싱은 Phase 6d-7 에서 검증된 envelope 세 가지
  후보 (raw / `{manifest:…}` / `{data:{manifest:…}}`) 를 그대로 사용.
  성공 시에만 diff 가 계산된다 — 파싱 실패 → diff 섹션 자체 미노출.
- `currentManifest` 는 `selectedEnvironment.manifest` 에서 참조. 드로어
  unmount 가 `clearSelection` 을 호출하므로, 모달이 드로어보다 늦게
  닫히는 edge case 에서는 `loadEnvironment` 가 다시 채워준다.
- "정보성만, 차단 아님" 원칙을 지켰다. diff 계산/로드가 실패해도
  덮어쓰기 자체는 가능 — 기존 UX 를 회귀시키지 않는다.

## Deviations

- 변경된 경로의 before/after 값은 현재 숨겼다 — 경로 리스트만 보여준다.
  값이 거대한 stage config 이면 모달 높이가 폭주한다. 필요하면 각
  항목을 expand 시 값 blob 을 보여주는 방식으로 확장할 수 있다.
- Section 당 20 개 cap 은 데모 단계에서 충분. 대규모 manifest 에서
  완전한 path 목록을 보려면 Export → diff 모달 두 번째 슬롯에 붙이는
  것이 더 적절하다.
- 백엔드 `/api/environments/diff` 는 여전히 stored↔stored 용도다 —
  blob↔stored 전용 엔드포인트는 추가하지 않았다. 클라이언트 diff 로
  충분하고, 왕복 비용이 더 아까움.

## Follow-ups

- 변경된 경로 expand 시 before/after blob (JSON pretty) 공개.
- Import 직전에 "현재 manifest 를 자동 export" 하는 1-step backup
  토글 — Phase 6d-8 (manifest history) 와 묶어서.
- Plan 06 최종 통합 문서 PR 은 여전히 남아있음.
