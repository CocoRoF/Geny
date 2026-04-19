# 26. Phase 6d-4 — Builder strategies + chains inline editor

## Scope

PR #71 (6d-3) 로 stage config 가 form 편집 가능해졌다. 남아있는 read-only
영역이 `strategies` (slot → impl 매핑) 와 `chain_order` (chain → ordered impls).
둘 다 `StageIntrospection.strategy_slots` / `strategy_chains` 가 available
impls 와 per-impl JSON schema 를 이미 노출하므로, 같은 JsonSchemaForm 을
재활용해 UI 에서 편집 가능하게 만든다. backend `PATCH stages/{order}` 는
`strategies`, `strategy_configs`, `chain_order` 필드를 모두 받으므로 저장
경로도 그대로 이어진다.

## PR Link

- Branch: `feat/frontend-phase6d4-strategies-chains-editor`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/environment/StrategyEditors.tsx` — 신규
- `StrategiesEditor` + `ChainsEditor` 두 presentational 컴포넌트를
  export. 둘 다 Builder 의 StageDraft 상태와 분리된 props-driven
  구조.
- `StrategiesEditor`: 각 slot 에 대해
  - 현재 impl 의 dropdown (`available_impls` 기반). `impl_descriptions`
    가 있으면 옵션 라벨에 병기.
  - slot.required 이면 "required" 배지.
  - `impl_schemas[currentImpl]` 이 있으면 해당 schema 로 `JsonSchemaForm`
    을 렌더해 중첩 config 를 편집. config 값은
    `strategy_configs[slotName]` 에서 가져옴.
  - slot.description / impl description 을 helper 로 표시.
- `ChainsEditor`: 각 chain 에 대해
  - 현재 ordered impls 를 번호 붙은 리스트로 렌더. 각 항목 옆에
    up/down (reorder) + trash (remove) 액션.
  - 하단에 남은 available_impls dropdown → 선택 시 append.
  - chain.description helper 로 표시.
  - empty state: "(empty chain)" 문구.

`frontend/src/components/tabs/BuilderTab.tsx` — 수정
- `StageDraft` 확장: `strategies: Record<string, string>`,
  `strategyConfigs: Record<string, Record<string, unknown>>`,
  `chainOrder: Record<string, string[]>` 추가.
- `stageDraftFromEntry` — 원본 manifest stage 의 해당 필드들을
  deep clone. strategies 는 빈 객체, strategyConfigs 는 내부 객체도
  clone, chainOrder 는 배열도 clone.
- `isDirty` 검사에 3 필드 포함 — deep comparison 은 `JSON.stringify`
  로 단순 처리 (프로파일 상 성능 이슈 없음).
- `handleSave` payload 에 `strategies`, `strategy_configs`, `chain_order`
  포함. backend 가 `exclude_none=True` 로 받으므로 빈 객체여도 payload
  명시.
- 기존 `<pre>` read-only 블록 제거 → StrategiesEditor / ChainsEditor
  를 자리에 삽입. 조건: `activeIntrospection` 이 로드된 상태
  (문자열 'loading'/'error' 가 아닌 객체) 일 때만 렌더. schema 가
  없는 artifact 는 편집기 자체가 표시되지 않음.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `builderTab.chainEmpty`, `builderTab.chainAddPick` 추가 (chain
  본체 편집 시 표시되는 두 라벨). 기존 strategies/chains/chainsEmpty
  키는 재사용.

## Verification

- 편집 루프: slot dropdown 변경 → `strategies[slotName]` 갱신 → 재렌더
  시 새 impl 의 `impl_schemas` 로 form 이 자동 교체. `strategyConfigs[
  slotName]` 은 이전 impl 의 값이 남아있을 수 있음 — backend 가 모르는
  키를 그대로 보관하는 편이 사용자 실수(impl 실수로 바꿈) 복구에 유리.
  최초 저장 시 backend validation 이 잘라낼 수도 있고, 그렇지 않으면
  다음 impl 로 돌아갔을 때 값 재사용 가능.
- chain reorder: 끝단 인덱스에서 up/down 클릭은 disabled. remove 후
  길이가 0 이 되면 "(empty chain)" 표시 + add dropdown 에 전체
  available_impls 다시 노출.
- `activeIntrospection` 은 artifact 바뀔 때 `schemaByKey` 재조회 —
  Builder 의 schema 캐시 로직 그대로. strategies/chains 도 이 응답
  에 같이 담겨 오므로 별도 요청 없음.
- `updateStage` payload 경로: store → `environmentApi.updateStage(envId,
  order, { ... })` → PATCH `/api/environments/{id}/stages/{order}`.
  backend `UpdateStageTemplateRequest` 가 이미 3 필드 모두 accept.
  (`service/environment/schemas.py` 기준)
- 편집 후 Revert 버튼: draft 전체를 `stageDraftFromEntry(selectedStage)`
  로 재생성 → strategies / chainOrder 도 원복. 이미 구현된 revert
  경로가 자동으로 커버.

## Deviations

- strategy config 의 per-impl 미이주 — slot 의 impl 을 A → B 로
  바꿔도 `strategyConfigs[slotName]` 은 초기화되지 않는다 (위 설명).
  backend 가 알 수 없는 키를 반려하면 명시적으로 "Clear config"
  버튼을 추가. 지금은 드물고 관측되면 별도 PR.
- chain 내부 impl config 편집 미지원. `ChainIntrospection.impl_schemas`
  는 있지만 chain 은 `chain_order: Record<string, string[]>` 만
  저장하고 impl 별 config 는 다른 경로에 있음. 실제 사용처가 나오면
  추가.
- drag & drop reorder 미구현. ArrowUp/ArrowDown 버튼으로 충분 —
  16 stage × 몇 개 chain 수준에서는 UX 문제 없음. 큰 chain 이 생기면
  dnd-kit 도입 고려.
- `available_impls` 에 없는 legacy impl 이 current 에 남아있는 경우
  dropdown 에 "(legacy)" 접미어로 표시 — 사용자 선택 가능하되 왜
  표시되는지 힌트.

## Follow-ups

- Phase 6d-5: `environmentApi.diff` 기반 env-vs-env diff 뷰.
- Phase 6d-6: tools snapshot (adhoc / mcp_servers / allowlist /
  blocklist) 편집기. 지금은 manifest preview 로만 보임.
- Phase 6d-7: stage "Clone from default" — 사용자가 실수로 stage
  설정을 깨뜨렸을 때 artifact 기본값으로 되돌리는 UX. backend helper
  필요.
- drag & drop chain reorder — 실제 chain 길이가 길어진 tenant 가
  생기면.
