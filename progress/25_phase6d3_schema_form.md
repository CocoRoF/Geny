# 25. Phase 6d-3 — Builder config schema-driven form

## Scope

PR #70 (6d-2) 에서 Builder 탭이 config 를 raw JSON textarea 로만 편집했다.
Artifact 의 `config_schema` 는 이미 `catalogApi.artifactByStage(order, name)`
응답에 들어 있으므로, schema 가 있을 때는 자동 생성된 form 을 기본으로
제공하고, schema 가 없거나 form 이 표현 못 하는 필드가 있을 때는 JSON
모드로 넘어갈 수 있는 toggle 을 둔다.

## PR Link

- Branch: `feat/frontend-phase6d3-config-schema-form`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/environment/JsonSchemaForm.tsx` — 신규
- JSON Schema subset renderer. properties 를 훑어 각 필드별로
  primitive 타입 input (string/number/integer/boolean), enum select,
  array-of-primitives 입력 (쉼표 구분), flat object nested render
  를 생성. 표현 불가능한 구조 (nested objects, arrays of objects,
  oneOf/anyOf) 는 raw JSON textarea 로 fallback.
- props: `{ schema, value, onChange }`. onChange 는 완성된 object
  를 emit — 상위에서 JSON.stringify 해 draft 에 반영.
- string 필드의 format/이름 heuristic 으로 `system_prompt`,
  `user_prompt` 류는 자동 multiline textarea.
- nullable type (`["string", "null"]`) 인 필드에서 빈 입력을 null
  로 변환. integer/number 빈 입력도 null.
- required 필드는 `*` 표시, description 은 field 아래 helper 로 출력.

`frontend/src/components/tabs/BuilderTab.tsx` — 수정
- schema 캐시 `schemaByKey: Record<"${order}:${artifactName}",
  StageIntrospection | 'loading' | 'error'>` 추가. 사용자가 stage
  / artifact 바꾸면 lazy fetch 해 캐싱.
- config editor 를 dual-mode 로 분기: schema 가 있으면 Form 을
  기본으로, 없으면 JSON textarea 고정. Form ↔ JSON 토글 버튼으로
  전환 가능. JSON 이 invalid 하면 Form 모드로 들어갈 수 없음
  (JSON 이 파싱되어야 object 를 form 에 넘길 수 있기 때문).
- Form 에서 편집한 값은 `JSON.stringify(next, null, 2)` 로 draft
  text 에 직렬화 → 저장 시에도 기존 JSON 경로와 동일하게 처리
  → draft dirty 검사 / config invalid 검사 로직 변경 없음.
- 헤더 오른쪽에 schema 로딩 / 없음 / 에러 상태 인디케이터 — 사용자
  가 현재 왜 Form 토글이 없는지 바로 파악 가능.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `builderTab.{config, configForm, configJson, configHint, configFormHint,
  schemaLoading, schemaFailed, schemaNone}` 추가 / 수정. 기존
  `config: 'Config (JSON)'` → `config: 'Config'` 로 변경 — form
  모드에서 "JSON" 라벨이 오해를 부름. 기존 `configHint` 의 "Form
  based editing lands in a follow-up" 문구 제거 (이번 PR 으로 구현).

## Verification

- 16 stage 모두 `config_schema` 가 nullable (`Optional[Dict]`).
  backend 응답이 null 인 stage (예: s16_yield) 에서도 JSON
  fallback 이 정상 동작.
- 기존 raw JSON 편집 흐름 그대로 유지. `configInvalid` 배너,
  save disabled, 저장 payload 가 `JSON.parse(draft.configText)` 로
  동일 경로를 통과.
- Form edit → JSON.stringify → parse → 다음 렌더에서 form
  value 갱신. 한 필드 변경시 다른 필드 cursor jump 없음 (form
  renderer 가 controlled input 구성).
- enum + string/number 조합 (temperature 0~2 range 등) 에서 min/max
  속성 반영 — invalid 값 입력 시 HTML5 validation 으로 시각적 힌트.
- `activeIntrospection` 이 문자열 ('loading' / 'error') 인 경우와
  object 인 경우를 분기하는 타입 가드 포함. 문자열 케이스에서는
  schema 없음으로 취급 → JSON mode 로 잠금.
- 스토어 / API 변경 zero — 본 PR 은 순수 UI 추가.

## Deviations

- arrays-of-objects, oneOf/anyOf/allOf 는 미지원. 해당 필드가 오면
  JSON textarea 로 fallback 한다. catalog 전반을 훑어봤을 때
  이 형태 필드는 제한적이며, 관측되면 개별 마이그레이션 PR 로 확장.
- `default` 값 자동 주입 미구현. backend 가 이미 artifact 생성
  시 default 를 config 에 박아주므로 (see `StageIntrospection.config`),
  form 은 존재하는 값만 렌더해도 충분. 빈 config + schema 조합
  에서 default 로 선제 채우는 UX 는 "Apply defaults" 버튼으로
  별도 제공 (follow-up).
- 타입 체크: JSX element 반환 타입을 `JSX.Element` 로 명시하지
  않음 (React 19 + TS5 env 에서 `JSX` 글로벌 네임스페이스를
  항상 쓰지 못함). 추론으로 둠.
- Number field 의 `value` 를 빈 문자열 ↔ number 간 전환할 때
  React 가 controlled/uncontrolled warning 을 낼 수 있음 — 빈
  값도 `''` 로 유지하되 state 에는 null 로 저장해 서버 측 JSON
  이 `null` 로 직렬화되도록 함.

## Follow-ups

- Phase 6d-4: strategies/chains 인라인 편집. SlotIntrospection /
  ChainIntrospection 의 `available_impls` + `impl_schemas` 를
  같은 JsonSchemaForm 으로 재사용.
- Phase 6d-5: `environmentApi.diff` 기반 side-by-side diff 뷰.
  두 env 를 선택하면 manifest 레벨 diff 출력.
- Phase 6d-6: tools snapshot 편집기 — EnvironmentManifest.tools
  (adhoc / mcp_servers / allowlist / blocklist) 를 ToolSets 탭과
  독립적으로 편집할 수 있게. 지금은 read-only 프리뷰에만 뜬다.
- "Apply defaults" — schema 의 default 값 주입 버튼. 빈 config
  상태에서 유용.
