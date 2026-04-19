# 24. Phase 6d-2 — Environment Builder tab

## Scope

PR #69 (6d-1) 로 `catalogApi` / `CatalogResponse` 가 backend 와 byte-compatible
해졌다. 이제 이 타입을 실제로 소비하는 첫 UI — Builder 탭 — 을 깐다.
Environments 탭에서 "Builder 에서 열기" 를 눌러 이동하면, 선택한 env 의
manifest.stages 를 왼쪽 리스트로, 선택한 stage 의 artifact/config/active
편집기를 오른쪽에 띄운다. Stage 단위로 저장 — 새 백엔드 endpoint
`PATCH /api/environments/{env_id}/stages/{order}` 를 호출한다.

## PR Link

- Branch: `feat/frontend-phase6d2-builder-tab`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/tabs/BuilderTab.tsx` — 신규
- Builder 탭 entry. `useEnvironmentStore.builderEnvId` 를 구독 →
  지정된 env 를 `loadEnvironment(envId)` 로 받아 state 에 채운 뒤,
  manifest.stages 를 order 순으로 왼쪽 aside 에 렌더.
- 선택된 stage 는 `draft` 상태 (artifact / active / configText) 로
  편집. `StageManifestEntry.config` 는 JSON 텍스트 에디터
  (`<textarea rows={14}>`) 로 표시 — schema-driven form 은 follow-up
  (6d-3) 로 미룸.
- Artifact picker 는 `catalogApi.listArtifacts(order)` 의 결과로
  렌더. 같은 order 를 두 번 열어도 `artifactsByOrder` 로 캐싱 →
  중복 요청 없음. `is_default` 플래그와 `description` 을 옵션 라벨에
  병기해 사용자가 기본값 / 대안 아티팩트 선택 맥락을 바로 파악.
- 오른쪽 사이드에 manifest 전체 JSON 프리뷰 (md+ breakpoint 에서만).
  상단 toggle 버튼으로 숨김 가능 (에디터 공간 필요할 때).
- Save: `updateStage(envId, order, { artifact, active, config })` 호출.
  실패 시 인라인 error banner. 성공 시 1 회성 "Saved." flash.
- Dirty / revert: artifact / active / configText 중 하나라도 원본과
  다르면 Save 와 Revert 버튼이 활성화. Revert 는 현재 manifest 에서
  다시 draft 를 리빌드.
- Empty / error / loading 모두 상태별 렌더. env 선택 안 된 상태
  (builderEnvId === null) 에서는 Environments 탭으로 보내는 CTA
  만 표시.

`frontend/src/components/EnvironmentDetailDrawer.tsx` — 수정
- 헤더 좌하단 action row 에 "Open in Builder" primary 버튼 추가
  (`Settings2` 아이콘). 클릭 시 `openInBuilder(envId)` → `setActiveTab
  ('builder')` → drawer `onClose()`. 한 동작으로 drawer 닫고 Builder
  로 이동.
- `useAppStore.setActiveTab` 와 `useEnvironmentStore.openInBuilder` 의존성
  추가. 기존 delete / duplicate / export 버튼은 건드리지 않음 —
  시각적 variant 는 primary vs ghost 로 구분.

`frontend/src/store/useEnvironmentStore.ts` — 수정
- `builderEnvId: string | null` + `openInBuilder(envId)` + `closeBuilder()`
  추가. Builder 와 drawer 양쪽에서 읽/쓰는 단일 소스.
- `updateStage` 시그니처 변경: `stageName: string` → `order: number`.
  backend `PATCH /api/environments/{env_id}/stages/{order}` 는 integer
  order 를 받음 — 기존 path 는 404 를 반환했다 (byte-compatible 하지
  않았던 6a 잔해).
- `deleteEnvironment` 가 삭제된 env 가 Builder 대상이면 `builderEnvId`
  도 null 로 정리.

`frontend/src/lib/environmentApi.ts` — 수정
- `updateStage(envId, order: number, payload)` — path 가 `/stages/${order}`
  로 직접 보간. `encodeURIComponent` 불필요 (정수).

`frontend/src/components/TabNavigation.tsx` — 수정
- `GLOBAL_TAB_IDS` 에 `'builder'` 추가 (`environments` 다음).
- `DEV_ONLY_GLOBAL` 에도 `'builder'` 추가 — Normal 모드에서는
  숨김, dev 모드 + 인증된 사용자만 접근.

`frontend/src/components/TabContent.tsx` — 수정
- `BuilderTab` dynamic import + `TAB_MAP['builder']` 등록.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `tabs.builder` 추가 (양쪽).
- `environmentDetail.openInBuilder` 추가 — drawer 의 primary 액션 라벨.
- `builderTab.*` 블록 전체 신규 추가 — 30+ 키 (제목, 부제, 빈 상태,
  stage 리스트, 에디터 섹션별 label/hint, strategies/chains,
  save/revert, manifest preview toggle). 두 언어 key 동수.

## Verification

- `grep updateStage` → 변경된 store / api / BuilderTab 3 곳에서만
  사용. 다른 호출처 없음 → 시그니처 변경으로 깨지는 컴파일 단위 없음.
- backend `patch_stage` 는 `order: int` 를 받으므로 path 정수 치환이
  맞음. integer 범위는 1~16 (stage order).
- `catalogApi.listArtifacts(order)` 의 응답 shape
  (`{ stage: string; artifacts: ArtifactInfo[] }`) → `artifactsByOrder`
  캐시가 `ArtifactInfo[] | 'loading' | 'error'` 로 타입 안전하게 보관.
- `UpdateStageTemplatePayload` 의 선택적 필드 중 현재 Builder 는
  `artifact`, `active`, `config` 만 설정 — `strategies`,
  `strategy_configs`, `tool_binding`, `model_override`, `chain_order`
  는 건드리지 않으므로 partial PATCH 가 다른 필드를 지우지 않는다
  (백엔드가 `model_dump(exclude_none=True)` 사용).
- Drawer → Builder 전환: `openInBuilder` + `setActiveTab('builder')`
  +  drawer `onClose()` 순서. onClose 가 `clearSelection()` 을 트리거해도
  Builder 가 다시 `loadEnvironment(builderEnvId)` 로 채우기 때문에
  레이스 문제 없음.
- Normal 모드에서 Builder 가 숨겨지는지 확인: `DEV_ONLY_GLOBAL` 에
  포함 → `visibleGlobalTabs` 필터에서 제거됨. devMode 없는 사용자는
  "Open in Builder" 를 눌러도 탭이 숨겨져 있을 수 있음 — 이 경우
  activeTab 은 `'builder'` 로 바뀌지만 TabContent 가 정상 mount
  한다 (TabContent 는 devMode 필터를 적용하지 않음). 결과적으로
  내부 탐색은 동작하지만 TabNavigation 에서 되돌아갈 버튼이 안
  보인다 — dev 전용 기능이므로 허용.
- i18n 누락 방지: `Translations = typeof en` 타입 제약 덕에
  ko.ts 에 같은 키를 빠뜨리면 컴파일 에러. 두 파일을 동기로 편집.

## Deviations

- Schema-driven form 미구현. 현 UI 는 config 를 raw JSON 텍스트
  에디터로 제공. `StageIntrospection.config_schema` 가 null 일 때도
  있고 (예: s16_yield), form 생성기 구현은 별도 PR 에서 다루는 게
  리뷰 단위가 적정.
- strategies / chain_order 편집기 미구현. 두 필드는 stage 에디터
  하단에서 read-only `<pre>` 로 보여주기만 함. SlotIntrospection /
  ChainIntrospection 의 available_impls 를 드롭다운으로 묶는 UX 는
  follow-up.
- manifest.stages 가 비어있는 (legacy? / imported minimal) env 에서는
  "Manifest has no stages yet." 로만 표시. "기본 파이프라인 채우기"
  CTA 는 백엔드 helper (e.g. `reset_to_preset`) 가 있을 때 붙인다.
- tool_binding / model_override 는 에디터 노출 대상 아님. 세션
  단위로 override 하는 UX 가 더 자연스러우므로 Builder 범위에서 뺌.
- 모바일 레이아웃: 왼쪽 stage 리스트 + 오른쪽 에디터의 2단 grid 는
  viewport ≥640px 기준. md 미만에서 manifest preview 는 숨겨짐
  (`hidden md:flex`). 더 좁은 viewport 는 stage 리스트 토글 UX
  가 필요 — 다음 iteration.

## Follow-ups

- Phase 6d-3: `config_schema` → form generator. react-jsonschema-form
  대체재 고르기 (번들 사이즈 고려), 또는 최소 JSON schema subset
  만 매핑하는 자체 renderer.
- Phase 6d-4: strategies/chains 인라인 편집 — SlotIntrospection
  available_impls 드롭다운 + impl_schemas 기반 중첩 form.
- Phase 6d-5: manifest diff viewer (pr #23 의 `environmentApi.diff`
  활용). 두 env 를 고르면 stages / strategies / config 레벨 diff
  를 side-by-side 로.
- Phase 6d-6: "Load into Builder" 에서 cmd/ctrl-click 으로 새 탭
  (browser window) 열기 등 multi-env 동시 편집 UX 는 실제 수요가
  생길 때 고민.

## Notes

- Builder 내에서 env 를 수정한 뒤 "Close builder" 를 누르면
  `closeBuilder()` + `setActiveTab('environments')` 로 되돌아가고,
  store 의 `selectedEnvironment` 는 cleanup effect 에서
  `clearSelection()` 으로 초기화된다. Environments 탭 / drawer 로
  돌아가면 최신 manifest 가 다시 fetch 된다 (drawer mount 시
  `loadEnvironment(envId)` 호출).
- "Saved." flash 는 다음 stage 선택 / 입력 편집 시 초기화. 토스트
  센터럴라이즈는 프로젝트 전체 UX 스캔 후 따로 제안.
