# 45. Phase 7-13 — EnvironmentDetailDrawer: copy env id button

## Scope

드로어 헤더에 env id 가 모노스페이스로 노출되지만, 터미널이나
docker-compose yaml 에 id 를 붙여넣으려면 마우스 드래그 selection →
Cmd+C 가 필요했다. 길쭉한 UUID 가 truncate 되어 끝자락이 잘려
보이는 상황이면 selection 도 까다롭다.

이 PR 은 id 텍스트 자체를 버튼으로 만들어, 한 번 클릭으로
`navigator.clipboard.writeText(envId)` 를 수행하고 1.2 초 동안
Check 아이콘 + "Copied!" tooltip 으로 피드백한다.

## PR Link

- Branch: `feat/frontend-phase7-13-copy-env-id`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- lucide import 에 `Check` 합류.
- `copiedId: boolean` state + `handleCopyId` — clipboard write 후
  1200ms 간 `copiedId` 를 true 로 유지.
- 헤더의 `<span>{envId}</span>` 을 `<button>` 으로 교체. 우측에
  `Copy` 아이콘 (idle) / `Check` 아이콘 (copied, success color).
- title tooltip 은 `copyId` ↔ `idCopied` 로 상태 반영.
- try/catch 로 clipboard API 거부 상황을 조용히 swallow — 사용자는
  여전히 드래그 selection 으로 복사 가능.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `environmentDetail.copyId: 'Copy environment id' / '환경 id 복사'`
- `environmentDetail.idCopied: 'Copied!' / '복사됨!'`

## Verification

- Clipboard API 는 modern evergreen 브라우저에서 standard. HTTP 가
  아닌 secure context (localhost 포함) 에서만 동작 — 개발 환경
  기본 접근과 일치.
- 상태 복귀 타이머는 1200ms 로 하여 연속 클릭 시에도 feedback 이
  겹치지 않는다 (새 setTimeout 이 덮어써지고 결과적으로 1.2s 유지).
- `setTimeout` cleanup 을 명시하지 않음 — 드로어가 unmount 되는
  순간에 fire 돼도 setState 는 memoryleak 가 아니라 React 경고
  (setState on unmounted)만 유발할 수 있으나 최신 React 는 silent.
  필요 시 `useEffect` cleanup 으로 타이머 clear 하는 follow-up 가능.
- Copy 버튼은 truncate 된 상황에서도 항상 클릭 가능 — `<span>
  {envId}</span>` 은 그대로 truncate, Copy icon 은 `shrink-0`.

## Deviations

- 드로어 외 위치 (InfoTab 의 env_id 링크 row, Environments 탭 카드)
  에는 아직 copy 버튼을 추가하지 않았다. 드로어는 id 가 가장 크게
  노출되는 지점이라 가치가 가장 높고, 다른 surface 는 후속으로.
- "copy manifest JSON" 버튼은 scope 밖 — manifest 는 이미 Download
  버튼으로 export 된다.
- `window.isSecureContext` 체크를 생략했다. clipboard write 가 throw
  하면 try/catch 가 swallow 해주므로 실제 사용자 경험상 fallback 이
  필요 없다.

## Follow-ups

- InfoTab 의 env row 에도 복사 아이콘 (env_id row onClick 은 이미
  drawer 를 열지만 텍스트 옆에 작은 copy 버튼 병치).
- session_id 복사 버튼 — 세션 헤더나 InfoTab 에.
- clipboard API 거부 시 fallback: `document.execCommand('copy')` 또는
  텍스트 선택 + 토스트 "Press Ctrl+C to copy".
- useEffect cleanup 으로 1200ms 타이머 clear — unmount safety.
