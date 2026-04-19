# 28. Phase 6d-6 — Tools snapshot editor

## Scope

`EnvironmentManifest.tools` (`adhoc`, `mcp_servers`, `global_allowlist`,
`global_blocklist`) 는 여태 manifest JSON 프리뷰에서 읽기 전용으로만
보였다. Builder 에 두번째 뷰 ("Tools") 를 추가해서 이 네 필드를 편집
가능하게 한다. 저장은 stage 단위가 아니라 `PUT /api/environments/{id}/manifest`
로 manifest 전체를 넘긴다 (`useEnvironmentStore.replaceManifest`).

## PR Link

- Branch: `feat/frontend-phase6d6-tools-snapshot-editor`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/environment/ToolsEditor.tsx` — 신규
- `ToolsDraft` text-form state (`adhocText`, `mcpServersText`,
  `allowlistText`, `blocklistText`) 와 변환 헬퍼
  (`toolsDraftFromSnapshot`, `validateToolsDraft`, `toolsSnapshotsEqual`,
  `emptyTools`) export.
- Allowlist / Blocklist: 1 줄 1 패턴 textarea. 공백 라인은 저장 시 제거.
  상단 우측에 현재 라인 수 카운터.
- Ad-hoc / MCP servers: JSON array textarea. `JSON.parse` 실패 혹은
  `Array.isArray` 실패 / 원소가 객체 아니면 inline 에러 메시지 + 빨간
  border. 부모 save 버튼은 `hasErrors` 면 disabled.
- 라벨 / placeholder / 카운터 문구 모두 `labels` prop 으로 주입 (i18n
  키는 BuilderTab 쪽에서 해석 → 컴포넌트는 pure).

`frontend/src/components/tabs/BuilderTab.tsx` — 수정
- 헤더에 pill-style view switcher 추가: "Stages | Tools" — 기본값 stages.
  Lucide `Boxes` / `Wrench` 아이콘.
- `builderView === 'tools'` 일 때: stage list aside 를 숨기고, 전체 폭의
  `<main>` 에 `<ToolsEditor>` 를 렌더. 오른쪽 manifest preview 는 동일하게
  `showPreview` 토글에 따라 유지.
- manifest 가 바뀔 때마다 (env reload, stage save 로 인한 manifest
  교체) `toolsDraft` 를 `toolsDraftFromSnapshot(env.manifest.tools)` 로
  재동기화. dirty 체크는 `toolsSnapshotsEqual(validation.snapshot,
  manifestTools)` 역결과로 판단.
- Save 시 `replaceManifest(envId, { ...manifest, tools: snapshot })` 호출.
  성공 시 초록 "Tools snapshot saved." flash, 실패 시 빨간 에러 박스.
- Revert 는 draft 를 manifest 기준으로 되돌림.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `builderTab.viewStages` / `viewTools` — switcher.
- `builderTab.toolsTitle` / `toolsSubtitle` — Tools view 헤더.
- `builderTab.allowlist` / `allowlistHint` / `blocklist` / `blocklistHint`
  / `adhocTools` / `adhocToolsHint` / `mcpServers` / `mcpServersHint`
  — 섹션 라벨 + 설명.
- `builderTab.patternsPlaceholder` / `jsonArrayPlaceholder` /
  `entriesCount` (`{count}` interpolation).
- `builderTab.toolsSave` / `toolsSaved` / `toolsSaveFailed` — save
  버튼 + 성공/실패 메시지.
- 양쪽 언어 키 동수.

## Verification

- `EnvironmentManifest.tools?` 타입은 이미 `types/environment.ts` 에
  존재 (6b 단계). 백엔드 `PUT /api/environments/{id}/manifest` 는
  manifest 전체 payload 를 받는 기존 엔드포인트 — 따로 엔드포인트 추가
  없음.
- 저장은 manifest 전체를 보내기 때문에 stage 편집 중 Tools 뷰로 넘어가
  저장해도 `env.manifest` 는 selectedEnvironment 최신값을 기반으로 spread
  되어 stage 편집 드래프트가 덮어써지지 않는다 (stage 쪽은 별도
  `updateStage` 경로로 저장되므로 충돌 없음).
- JSON 검증: `Array.isArray` + 각 원소 객체 체크 → primitive / string 배열
  을 서버로 올려버리는 실수 방지.
- Dirty 판정: `JSON.stringify(a.adhoc ?? [])` vs `b.adhoc ?? []` — key
  ordering 이 다르면 false positive 가 날 수 있으나 draft 는 항상 서버가
  돌려준 snapshot 에서 파생되므로 ordering 이 보존된다. 사용자가 JSON 을
  pretty-print 순서만 바꾸면 dirty=true 가 되지만 저장 시 서버가 재정렬
  하면 다음 load 에서 clean 으로 복귀.

## Deviations

- MCP 서버 / adhoc 항목을 form 으로 분해해 렌더하지 않음. 각 entry 의
  스키마가 backend MCP 설정 변화에 따라 움직이기 때문에 (MCPServerConfig
  + ad-hoc tool 정의 는 둘 다 지금도 확장 중) JSON textarea 로 남겨두고
  검증만 추가. 서버가 shape 검증하므로 UX 상 충분.
- Allowlist / Blocklist 는 `split('\n')` 기반. 패턴 자체에 개행이 들어갈
  일은 없으므로 (tool 이름은 identifier 계열) 안전.
- "모두 지우기" / "기본값 복원" 같은 편의 버튼 없음. 비어있는 상태로
  저장하고 싶으면 textarea 를 비우면 됨 — 저장 전에 revert 한 번으로
  되돌릴 수 있으므로 추가 UI 없이도 실수 방지 가능.
- Metadata (env name / description / tags) 편집은 이번 PR 에 포함 안 함.
  Environments 탭 drawer 에서 이미 편집 가능하며, Builder 에 이중 surface
  를 두면 중복되므로 스킵.

## Follow-ups

- Phase 6d-7: manifest import/export UI — drawer 에는 export 만 있고
  새 env import 는 `createEnvironment` 경로. "기존 env 에 manifest
  덮어쓰기" UX (파일 업로드 → replaceManifest) 가 아직 없다.
- MCP 서버 form 편집기: 백엔드 `MCPServerConfig` shape 이 안정되면
  ad-hoc / mcp_servers 를 실제 form 으로 분해해 각 entry 를 add/remove
  할 수 있게. JsonSchemaForm 재사용 가능.
- Tools 뷰에서도 env rename / tag 편집이 가능한 "Metadata" 서브 뷰 추가
  여부는 사용 빈도 보고 판단.
