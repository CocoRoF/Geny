# 38. Phase 7-6 — Environment card: "N sessions bound" badge

## Scope

Phase 7-4 에서 `SessionInfo.env_id` 를 노출했지만, 역방향 즉
"이 환경을 쓰고 있는 세션이 몇 개냐" 는 Environments 탭에서 바로 보
이지 않았다. 환경 정리 / 안전 삭제 판단에 매번 수동 크로스 체크가
필요했다.

이 PR 은 Environments 탭 카드 헤더에 small badge 를 붙여, 현재
로드된 세션 목록을 기준으로 환경별 바인딩 개수를 표시한다. 백엔드
변경 없이 `useAppStore.sessions` 의 `env_id` 필드만으로 집계.

## PR Link

- Branch: `feat/frontend-phase7-6-env-session-count`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- `useAppStore.sessions` 구독 + `useMemo` 로 `Record<envId, count>` 계산
  (`env_id` 가 truthy 인 세션만 세기).
- `EnvironmentCard` prop 에 `sessionCount: number` 추가. 헤더 우상단에
  `Users` lucide icon + 숫자 badge — count > 0 일 때만 렌더링.
- `environments.map` 호출부에서 `sessionsPerEnv[env.id] ?? 0` 을 전달.
- 추가 import: `useAppStore`, `useMemo`, `Users`.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentsTab.sessionCountTooltip` — badge 에 `title=` 로 걸려있어
  mouseover 시 "{n} active session(s) bound" / "바인딩된 활성 세션 {n} 개"
  를 보여준다.

## Verification

- `SessionInfo.env_id` 는 Phase 7-4 (PR #77) 에서 이미 optional field 로
  추가. 레거시 프리셋 세션은 `env_id === null` 이므로 집계에서 자동
  제외된다.
- `useAppStore.sessions` 는 앱 전역에서 이미 로드/구독되고 있어 (sidebar,
  session list 등) 추가 fetch 호출이 필요 없다. badge 는 session list 가
  갱신될 때 자동 업데이트.
- 0 개인 경우 badge 자체를 렌더하지 않음 — 기존 카드 시각 리듬 유지.
- 기존 카드 hover/click 동작 / tag row / updated 타임스탬프 — 모두
  변경 없음. badge 만 헤더에 새로 자리.

## Deviations

- "Active sessions" 는 현재 탭이 로드한 `sessions` 기준. 삭제된
  세션 (`deletedSessions`) 은 세지 않는다. 환경 회수 안전성 판단은
  라이브 세션만 기준이 맞다.
- 백엔드 reverse-lookup endpoint 는 만들지 않았다. 1–2 개 환경 × 수십
  세션 규모에서는 클라이언트 집계가 O(n) 로 충분하고, 수백 세션 /
  탭 간 캐시 동기화 이슈가 커지면 그때 endpoint 를 고려한다.
- Badge 는 숫자만 — 어떤 세션인지 drill-down 은 하지 않는다. 필요 시
  드로어에 "Linked sessions" 섹션을 추가하는 편이 자연스럽다
  (Phase 7-7 후보).

## Follow-ups

- Phase 7-7 (tentative): EnvironmentDetailDrawer 에 "이 환경을 쓰는
  세션" 섹션 — 리스트 + 클릭 시 세션 상세.
- 백엔드 `GET /api/environments/{id}/sessions` endpoint — reverse
  lookup 의 authoritative 버전. 삭제된 세션 포함 여부 별도 결정.
- Badge 색상 토큰 통일 — 현재 green tint 는 success color 계열이지만,
  "정보성" 뉘앙스가 더 맞을 수도. 디자인 리뷰 시 재검토.
