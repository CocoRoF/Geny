# 49. Phase 7-17 — Environments tab: filter / search / sort toolbar

## Scope

환경 카드 수가 10 개를 넘기면 "이름으로 찾기" / "에러 있는
환경만 보기" / "최근 업데이트 순" 같은 운영 작업이 스크롤·
Ctrl+F 에 의존하게 된다. Phase 7-16 에서 authoritative 카운트를
확보한 덕에 여기에 의미 있는 서버 지표를 태운 필터를 올릴 수
있게 됐다.

이 PR 은 EnvironmentsTab 헤더 아래에 단일 toolbar 한 줄을 추가한다.
구성 요소:
- 검색창 (name / description / id substring).
- 상태 chip 4 개: All / Has errors / In use / Idle.
- 태그 멀티선택 드롭다운 (태그가 실제로 존재하는 환경에만 노출).
- 정렬 셀렉트 6 옵션.
- 필터 1 개 이상 활성 시 Clear 버튼.
- 매치 0 개일 때 전용 empty state + clear 액션.

## PR Link

- Branch: `feat/phase7-17-envs-filter-search-sort`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- state: `searchQuery`, `statusFilter` (`'all'|'has_errors'|'has_sessions'|'idle'`),
  `selectedTags: Set<string>`, `sortKey`, `tagMenuOpen`.
- 외부 클릭 → 태그 메뉴 닫기 mousedown listener.
- `allTags` useMemo: 전체 환경의 tags union, 정렬된 배열.
- `filteredEnvs` useMemo: query/tags/status 필터 → sort. Sort 키별
  로직: updated asc/desc, name asc/desc, 그리고 authoritative
  session/error count desc (동률은 updated desc 타이브레이크).
- toolbar JSX: flex-wrap 한 줄. 좌측 검색/상태/태그, 우측 sort +
  clear. 모바일-ish 화면에서도 자연스럽게 줄바꿈.
- 카드 그리드 바로 위로 toolbar 렌더. 환경이 0 개일 땐 toolbar
  를 숨기는 게 empty state 와 충돌 없음.
- filter 결과가 0 개일 때 `FilterX` 아이콘 + "N 개 중 0 매치"
  메시지 + clear 버튼.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.searchPlaceholder`, `clearSearch`, `clearFilters`,
  `noFilterMatch`, `tagFilterAll`, `tagFilterActive`, `tagFilterClear`,
  `filterStatus.{all,has_errors,has_sessions,idle}`, `sort.*` 6 개
  일괄 추가. ko 도 완전 대응.

## Verification

- 검색창: "env-foo" 입력 → 이름/설명/id 에 포함된 항목만 렌더.
  Clear 버튼으로 즉시 해제.
- 상태 chip:
  - "Has errors" → authoritative `error > 0` 환경만.
  - "In use"    → `active > 0` 환경만.
  - "Idle"      → `active == 0` 환경만.
  - 서버 카운트 실패시엔 `clientCountsPerEnv` 로 폴백되므로 동일
    로직 유지.
- Tag 드롭다운: 현재 존재하는 태그 union 표시, 체크박스형 toggle.
  여러 태그 선택 시 AND (모두 포함) 의미.
- 정렬: "Most sessions" / "Most errors" 가 authoritative 카운트로
  정렬되는지 확인. 다른 키는 업데이트 시간/이름 기본.
- 필터 1+ 활성 시 우측 Clear 버튼 렌더. 눌러서 한 방에 초기화.
- 매치 0 건 empty state → "N 개 중 0 매치" + Clear 버튼 동작.

## Deviations

- 필터 상태는 localStorage persistence 없음 — 탭 재방문 시 리셋.
  "환경 뷰 상태 기억" 기능은 오히려 혼란 주기 쉬워 의도적으로
  세션-local. 필요 시 후속.
- URL query string 반영 (`?q=foo&status=has_errors`) 은 이번에
  제외. Next.js `useSearchParams` 로 붙일 수 있지만 범용 가치가
  낮고 deep-link 요구도 없음.
- 태그 드롭다운은 AND. OR 연산 토글을 한 번 고민했지만 UX 복잡도
  대비 실익이 적어 보류.
- 상태 chip 에 "Has deleted" 옵션은 추가하지 않음 — 카드 뱃지
  자체가 이미 드릴다운을 유도하고, 필터 chip 이 5 개로 늘면 한
  줄을 못 지킴.

## Follow-ups

- URL query 상태 동기화 (북마크 / 공유).
- "자주 쓰는 필터" 프리셋 저장.
- 태그 드롭다운 OR/AND 토글.
- 대량 선택 모드 (multi-select 카드 후 bulk delete/export).
