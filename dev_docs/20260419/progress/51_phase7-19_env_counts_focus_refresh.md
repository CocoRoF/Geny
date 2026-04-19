# 51. Phase 7-19 — TTL-gated visibility/focus refresh for env session counts

## Scope

Phase 7-18 이 mutation 경로는 막았지만, **다른 사람이 서버에서
세션을 만들거나** 같은 사용자가 다른 브라우저에서 변경을 가한
경우엔 Environments 탭의 카운트가 여전히 stale. 카드 하나하나
Refresh 버튼을 눌러야만 갱신된다.

이 PR 은 브라우저 tab 포커스 / 가시성 전환을 레버리지로
삼아 자동 재조회를 건다. 단, 재포커스 마다 API 를 때리면 과하므로
store 에 "마지막 fetch 시각" 을 기록하고 **10 초 TTL** 로 게이트.

## PR Link

- Branch: `feat/phase7-19-env-counts-focus-refresh`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/store/useEnvironmentStore.ts` — 수정
- state 추가: `sessionCountsFetchedAt: number | null` — 성공한
  fetch 의 `Date.now()` 타임스탬프.
- action 추가: `refreshSessionCountsIfStale(ttlMs)` — 타임스탬프가
  TTL 내면 no-op, 아니면 `refreshSessionCounts()` 위임.
- `refreshSessionCounts` 가 성공 시 fetchedAt 을 업데이트.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 새 useEffect: `visibilitychange` (document) + `focus` (window)
  리스너를 attach. 핸들러에서 `refreshSessionCountsIfStale(10_000)`
  호출.
- mount 시 초기 fetch 는 기존 useEffect 로 계속 수행.

## Verification

- 탭 최초 진입: 평소처럼 zero-arg `refreshSessionCounts` 로 초기
  fetch. `sessionCountsFetchedAt` 가 기록됨.
- 다른 브라우저 탭으로 이동 후 ≤ 10 초 내 복귀: visibility 이벤트
  가 발사되지만 TTL 내라 no-op — API 호출 없음.
- 다른 탭에서 10 초 이상 머문 뒤 복귀: visibility → fetch →
  카운트 최신화. 카드 뱃지가 자연스럽게 갱신.
- 창 alt-tab 후 재포커스: `focus` 핸들러가 동일한 TTL 체크로
  동작.
- 네트워크 단절 상태에서 focus: `refreshSessionCounts` 가 예외를
  삼키므로 TTL 타임스탬프도 갱신되지 않음 → 다음 focus 에
  재시도. stale 표시만 유지.

## Deviations

- TTL 을 10 초로 고정. localStorage 설정 노출은 과도하고, 환경
  수준 지표로는 10 초가 "현재상태-ish" 감각을 주기 충분.
- Drawer 의 단일-env `/sessions` endpoint 는 동일 TTL 을 태우지
  않았다. Drawer 는 mount 시 한 번, showDeleted 토글 시 한 번
  호출하므로 visibility-refresh 필요도가 낮고, 포커스 잃는 상황이
  드물다.
- Builder / Info 탭엔 넣지 않았다. 이 탭들은 카운트를 직접
  구독하지 않고, 필요 시 Environments 탭이 refresh 한 값을 공유
  구독한다.
- 포커스 시 `loadEnvironments()` 까지 재호출하지 않는다. 환경
  리스트는 mutation 에만 변경되고 외부 변경 빈도가 낮아, 카운트만
  재조회해도 충분.

## Follow-ups

- SSE/WS "환경 카운트 변경 이벤트" 채널이 생기면 TTL 대신 push
  기반 invalidation 으로 교체.
- TTL 값을 store config 로 꺼내 페이지별 customization 허용.
- Drawer 의 `/sessions` 도 focus-refresh 대응 (필요시).
