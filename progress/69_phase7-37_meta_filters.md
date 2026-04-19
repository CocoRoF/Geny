# 69. Phase 7-37 — "Has preset" / "Has tags" 메타 필터

## Scope

Phase 7-23 follow-up 로 남겨 두었던 항목. Environments 탭의 상태
필터 바는 현재 `all / has_errors / has_sessions / has_deleted / idle`
5 개로, 모두 세션 카운트 기반이다. 환경 자체의 메타 속성으로
거르는 수단이 없다 — "프리셋 기반으로 만들어진 환경만" 혹은 "태그가
붙어 있는 환경만" 이 대표적이다.

이 phase 는 동일 필터 바에 `has_preset` (base_preset 이 비어있지
않음) 과 `has_tags` (tags 배열이 비어있지 않음) 두 옵션을 추가한다.
backend 의 `EnvironmentSummaryResponse` 에 이미 `base_preset` 이
노출되어 있으므로 서버 변경 없음.

## PR Link

- Branch: `feat/phase7-37-meta-filters`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/types/environment.ts` — 수정
- `EnvironmentSummary` 에 `base_preset?: string` 추가. 백엔드는 이미
  해당 필드를 반환하지만 (기본값 `""`) 프런트 타입에는 누락되어
  있었다.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `StatusFilter` 에 `'has_preset' | 'has_tags'` 추가.
- `filteredEnvs` 의 status 가드에:
  - `has_preset` → `env.base_preset` 이 존재하고 비어있지 않으면 통과.
  - `has_tags` → `env.tags.length > 0` 이면 통과.
- 필터 바 버튼 리스트에 두 값 추가 (기존 순서 뒤 — 세션 카운트 계열
  다음에 메타 계열을 배치).

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.filterStatus.has_preset` — "Has preset" / "프리셋
  유래".
- `environmentsTab.filterStatus.has_tags` — "Has tags" / "태그 있음".

## Verification

- Environments 탭에 환경이 여러 개, 일부만 `base_preset` 이 있는
  상태: "Has preset" 클릭 시 해당 환경만 보임. 다시 클릭 = "All"
  은 기존처럼 별도 버튼.
- `base_preset=""` (백엔드 기본값) 도 `has_preset` 필터에서 제외됨.
- 일부 환경만 tags 보유: "Has tags" 클릭 → tags.length > 0 인
  환경만.
- 두 필터를 연속 클릭해도 단일 선택 방식 (기존 동작 유지, 라디오
  그룹).
- 검색 / 태그 필터 / 정렬과 조합: 메타 필터가 통과한 후 그 뒤
  기존 검색·정렬이 기본대로 작동.
- ko 로케일에서 "프리셋 유래" / "태그 있음" 라벨.

## Deviations

- `has_preset` 의 semantic: "이 환경이 프리셋에서 만들어졌다" 가
  아니라 "base_preset 메타 필드가 채워져 있다" 이다. 메타 필드는
  `create(from_preset)` 경로에서만 세팅되므로 실질적으로 동일.
- `has_tags` 는 "태그 필터와 중복 아니냐" 는 지적이 가능. 하지만
  태그 필터는 특정 태그로 좁히는 것이고, 이 필터는 "아무 태그라도
  붙어있는" 이라는 부분집합 정의. 사용자가 선택 태그를 일일이
  고르지 않아도 "정리 안 된 환경 숨기기" 가 가능.
- 필터 바가 7 개로 늘어나면서 가로로 빽빽해질 수 있는데, 기존
  반응형 wrap 이 커버. 별도 카테고리 헤더 (Session / Meta) 는 과잉.
- 기존 `type StatusFilter` union 을 그대로 확장했기 때문에 `sortKey`
  등의 처리에는 영향 없음. 타입 변화로 lint 에러 없음 확인.
- backend 변경 없음: `EnvironmentSummaryResponse.base_preset` 이 이미
  `""` 기본값으로 직렬화되어 내려온다. Phase 7-37 은 순수 프런트
  작업.

## Follow-ups

- "Has description" 필터 — 설명이 없는 환경을 찾아 정리하기 쉽게.
- "Recently updated" / "Never used" 같은 시간축 메타 필터.
- 여러 status 필터를 동시 선택 (OR / AND) — 현재는 단일 선택이라
  "프리셋 유래이면서 에러 발생" 같은 교차가 불가능.
