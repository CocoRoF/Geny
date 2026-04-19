# 43. Phase 7-11 — Linked sessions: status breakdown badges in header

## Scope

Phase 7-7 에서 드로어에 "Linked sessions ({n})" 섹션을 붙였지만,
n 이 크면 그 안에 running / error / idle 이 섞여 있어도 헤더만
보고는 triage 가 어렵다. 세션을 하나씩 스크롤해서 색 배지를 봐야
"지금 몇 개가 에러냐" 가 보인다.

이 PR 은 섹션 헤더 오른쪽에 상태별 미니 배지 (running / error /
other) 를 띄워, 드로어를 열자마자 환경에 붙은 세션의 건강 상태를
한눈에 확인할 수 있게 한다. 카운트가 0 인 상태 그룹은 배지 자체를
렌더하지 않아 노이즈를 줄인다.

## PR Link

- Branch: `feat/frontend-phase7-11-linked-sessions-status-breakdown`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- `linkedBreakdown` useMemo — `{running, error, other}` 카운트.
- 섹션 헤더를 `h4 + badges` 양단 정렬 (`flex items-center justify-
  between`) 로 개편.
- 각 배지:
  - running: green tint, `{count} running`
  - error: red tint, `{count} error`
  - other: neutral, `{count} other`
  - count 0 이면 해당 배지 miss.
- `title=` 로 "N running session(s)" 전체 문구를 tooltip 제공.
- 개별 세션 row 의 status badge 는 그대로 유지 — 헤더 breakdown 은
  aggregate, row badge 는 identity.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentDetail.statusRunning/Error/Other` — 배지 내 짧은 라벨
  ("running" / "실행중" 등).
- `environmentDetail.breakdownRunning/Error/Other` — tooltip 풀 문구
  ("{n} running session(s)" / "실행중 세션 {n} 개").

## Verification

- `linkedSessions.length === 0` 이면 breakdown 블록 자체가 렌더되지
  않음 — 기존 empty-state italic 메시지만 표시.
- `status === 'error'` 매칭 문자열은 SessionInfo.status 의 union
  타입에 포함돼 있음. 'idle' / 'stopped' / '기타' 는 모두 other
  bucket 으로 집계.
- 상태 변화 (실행 → 에러 등) 는 `useAppStore.sessions` 갱신이
  들어올 때 자동으로 재계산 — useMemo 의존성이 linkedSessions 를
  포함.
- badge 색 팔레트는 row status badge 와 동일하게 맞춰 시각적 "같은
  축" 임을 강조.

## Deviations

- "other" 는 세부 분할하지 않음 (idle vs stopped vs queued). 섹션
  헤더는 aggregate 용이고 세부는 row 에서 확인. 4+ 상태 배지는
  공간 대비 이득이 없음.
- drill-down filter (예: "error" 배지 클릭 → 에러 세션만 필터링)
  기능은 넣지 않음. 목록이 길지 않아 시각적 스캔으로 충분하다 판단.
- 총합 N 은 여전히 섹션 타이틀 "Linked sessions ({n})" 에 있으므로
  중복되지 않음. running + error + other ≠ n 이 될 수 없는지는
  bucket 이 mutually exclusive & exhaustive 이므로 보장.

## Follow-ups

- "error" 배지 클릭 시 세션 목록을 해당 상태로 필터링 — 세션 수가
  아주 많을 때 유용.
- running/error 개수에 live-dot 애니메이션 — 상태가 방금 바뀐
  세션을 부각.
- 환경 카드 (EnvironmentsTab) 의 badge 도 동일 breakdown 으로
  확장 — 현재는 단순 숫자 N.
