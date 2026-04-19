# 32. Phase 7-5 — InfoTab env row → EnvironmentDetailDrawer

## Scope

Phase 7-4 (PR #77) 에서 `SessionInfo` 에 `env_id` 필드를 노출했지만,
값이 단순 문자열 UUID 로만 떴다. 디버깅 시 "이 env 가 어떤
manifest 인지" 를 확인하려면 Environments 탭을 별도로 열어 환경
목록에서 같은 id 를 찾아야 했다.

이 PR 은 InfoTab 의 Environment 행을 클릭 가능하게 만들어 곧바로
`EnvironmentDetailDrawer` 를 띄운다. 드로어가 이미 가진 메타데이터
/ manifest JSON / export / duplicate / delete 액션을 그대로 재사용.

## PR Link

- Branch: `feat/frontend-phase7-5-env-id-link`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/InfoTab.tsx` — 수정
- `EnvironmentDetailDrawer` import 및 `ExternalLink` lucide icon
  추가.
- 로컬 상태 `envDrawerId: string | null` — 열려 있는 드로어 id.
- 내부 `InfoField` 타입을 `{ label, value, onClick? }` 로 확장.
  Environment 행만 `env_id` 가 있으면 `onClick` 으로
  `setEnvDrawerId(data.env_id)` 를 건다. 레거시 프리셋 세션은
  `env_id === null` 이라 그냥 일반 text row.
- Fields 그리드 렌더러: `f.onClick` 이 있으면 `<button>` 으로 감싸고
  `ExternalLink` 아이콘을 오른쪽에 붙여 링크임을 시각적으로
  알린다. 없으면 기존 `<span>` 그대로.
- 컴포넌트 루트 끝부분에 `{envDrawerId && <EnvironmentDetailDrawer
  envId={envDrawerId} onClose={() => setEnvDrawerId(null)} />}` —
  portal 드로어가 위에 뜨고, 닫으면 InfoTab 상태만 비운다.

## Verification

- `EnvironmentDetailDrawer` 는 `createPortal` 로 `document.body`
  아래에 backdrop + aside 를 렌더한다. InfoTab 이 스크롤 컨테이너
  안에 있어도 z-40/z-50 이 tab shell 위를 덮는다 (기존
  EnvironmentsTab 에서 쓰는 경로와 동일).
- 드로어의 `useEffect` cleanup 은 `clearSelection()` 만 호출하므로
  InfoTab 에서 열었다 닫아도 사이드이펙트 없음 — InfoTab 은
  environment store 를 구독하지 않는다.
- `onCompare` 는 optional — 주지 않으면 해당 버튼이 렌더되지 않음
  (드로어 내부 L270 `{onCompare && (...)}`). 이번에는 비교 기능이
  자연스럽지 않아서 생략.
- 드로어 내부 "Open in Builder" 를 누르면 여전히
  `openInBuilder` → `setActiveTab('builder')` 로 동작 — 의도한
  거동, InfoTab 과 충돌 없음.

## Deviations

- Memory Provider 행은 링크화하지 않았다. 대응되는 detail 패널이
  없고, provider DSL 은 요약으로 충분하다.
- `ExternalLink` 아이콘은 11px 로 fields 그리드의 monospace 값과
  시각적으로 섞이게. 굳이 별도 row action 처럼 만들지 않음 — 클릭
  가능 영역을 라벨 아래 전체로 넓혀두는 편이 읽기 쉽다.
- 스타일 키 네임(예: `text-[var(--primary-color)]`) 은 다른
  clickable text 들이 이미 쓰는 토큰. 새 CSS 변수는 추가하지 않았다.

## Follow-ups

- InfoTab 이 점점 커지고 있다 (500+ 줄). Section 단위 (Meta /
  Prompts / CLI / Memory / Env) 로 분할 리팩터 — 7-6 후보.
- "이 env 를 기본값으로 둔 세션 목록" 을 드로어에서 역방향으로
  보여주는 UI — reverse lookup, 백엔드 쿼리 추가 필요.
- Plan 06 최종 통합 문서 PR 은 여전히 남아있음.
