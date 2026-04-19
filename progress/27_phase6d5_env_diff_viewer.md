# 27. Phase 6d-5 — Environment diff viewer

## Scope

Phase 3 에서 backend `POST /api/environments/diff` 가 이미 깔려있고
(Phase 3 controller), `environmentApi.diff(envIdA, envIdB)` 도 이미
구현되어 있었지만 UI 호출처가 없었다. Environments 탭 헤더에 "Compare"
버튼, detail drawer 에 "Compare with…" quick action, 그리고 diff 결과를
added/removed/changed 3 버킷으로 렌더하는 모달을 깐다.

## PR Link

- Branch: `feat/frontend-phase6d5-env-diff-viewer`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/EnvironmentDiffModal.tsx` — 신규
- `createPortal` 모달. 두 개의 env select (좌 / 우) + swap 버튼 +
  Compare 버튼. 결과는 `EnvironmentDiffResult` 의 `added`, `removed`,
  `changed` 를 각각 섹션으로 렌더.
- `changed` 항목은 path + before/after 를 side-by-side 2 컬럼 그리드로.
  좁은 뷰포트에서는 1 컬럼 stack (md+ 에서만 2 col).
- 같은 env 를 양쪽에 고르면 Compare 버튼 disabled. 두 env 가 완전히
  동일하면 "No changes" 성공 메시지.
- props: `{ onClose, initialLeft?, initialRight? }` — drawer 에서
  "Compare with…" 누르면 initialLeft 미리 채워진 상태로 진입.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 헤더 actions 에 "Compare" 버튼 추가 (refresh 와 newEnvironment
  사이). 환경이 2 개 미만이면 disabled.
- drawer 에서 `onCompare` 콜백을 받아 modal 을 `{ left: openEnvId }`
  로 열고 drawer 는 닫음.

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- optional prop `onCompare?: () => void` 추가. 제공되면 footer
  action row 에 "Compare with…" 버튼이 나타난다. EnvironmentsTab
  은 이 콜백을 전달, 다른 caller 는 미사용 — 기존 사용처 regression
  없음.
- `ArrowLeftRight` icon 사용.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `environmentsTab.compare` — 목록 헤더 "Compare" 버튼.
- `environmentDetail.compareWith` — drawer quick-compare 액션.
- `diff.*` 블록 신규 (title, subtitle, left/right, pickEnv, compare,
  running, failed, idle, noChanges, added/removed/changed,
  before/after). 양쪽 언어 키 동수.

## Verification

- `environmentApi.diff(envIdA, envIdB)` 는 Phase 6a 로 이미 구현되어
  있었음 (POST /api/environments/diff, body `{env_id_a, env_id_b}`).
  응답 타입 `EnvironmentDiffResult` 의 shape (`added: string[],
  removed: string[], changed: {path, before, after}[]`) 과 1:1 렌더.
- store 상태 오염 없음 — diff 결과는 모달 local state 로만 보관
  (다음 오픈 시 재계산). 빈번한 fetch 아니므로 캐싱 불필요.
- `initialLeft` 프리셋: drawer `onCompare` → EnvironmentsTab 이
  modal 을 `{ left: openEnvId }` 로 열고 drawer 를 close. 모달 오픈
  직후 사용자는 right 만 고르고 Compare 누르면 됨.
- Typography / border token 체계 (var(--bg-*), var(--text-*),
  var(--danger-color), var(--success-color)) 를 일관되게 사용 —
  기존 ConfirmModal / CreateEnvironmentModal 과 시각적으로 묶인다.

## Deviations

- 결과에 "Open the left env in Builder / drawer" 류 바로가기 버튼은
  없음. diff 결과를 본 뒤 수정하려면 모달 닫고 env 를 다시 선택해야
  한다. 실수요가 생기면 각 path 옆에 "jump to stage N" 링크 추가
  가능.
- `changed.before` / `changed.after` 의 렌더: primitive 면 문자열,
  object/array 면 JSON 들여쓰기. 긴 JSON 은 `whitespace-pre-wrap
  break-all` 로 래핑 — 너무 길면 보기 불편하지만 UX 적으로 명시적
  truncation 보다는 자연스러운 wrap 이 낫다고 판단. 추후 collapsible
  로 개선 가능.
- diff 결과를 export / share 하는 기능 없음. 내부 디버그 용도면
  브라우저 스크린샷으로 충분.

## Follow-ups

- Phase 6d-6: tools snapshot 편집기 — EnvironmentManifest.tools
  (adhoc / mcp_servers / global_allowlist / global_blocklist) 를
  Builder 내에서 편집 가능하게.
- Phase 6d-7: manifest import / export UI — 현 모달의 drawer 에는
  export 만 있음. 새 env import 는 존재하나 "기존 env 에 manifest
  덮어쓰기" UX 가 빠져있음.
- diff 결과 clickable path — stage N 관련 path 는 Builder 해당
  stage 로 점프. 구현 시 diff 모달 내부에서 openInBuilder 호출.
