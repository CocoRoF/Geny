# 17. Phase 6a — frontend Environment types + API client

## Scope

plan/06 의 Phase 6 (frontend Environment / Builder 탭) 의 첫 단계.
타입 정의 + API 클라이언트만 깐다. UI 컴포넌트 / 라우팅은 후속 PR.

## PR Link

- Branch: `feat/frontend-phase6a-env-types-api`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/types/environment.ts` — 신규
- `EnvironmentManifest`, `StageManifestEntry`, `StageToolBinding`,
  `StageModelOverride`, `ToolsSnapshot`, `EnvironmentMetadata`.
- Request/response: `CreateEnvironmentPayload` (mode = blank /
  from_session / from_preset), `UpdateEnvironmentPayload`,
  `UpdateStageTemplatePayload`.
- View shapes: `EnvironmentSummary`, `EnvironmentDetail`,
  `EnvironmentDiffResult`.
- Catalog: `ArtifactCapability`, `ArtifactInfo`, `StageCatalogEntry`,
  `CatalogResponse`.
- 모든 필드는 backend `service/environment/schemas.py` 와
  `geny_executor.EnvironmentManifest` 에 byte-compatible.

`frontend/src/lib/environmentApi.ts` — 신규
- `environmentApi` 객체: `list`, `get`, `create`, `update`, `delete`,
  `duplicate`, `replaceManifest`, `updateStage`, `exportEnv`,
  `importEnv`, `diff`, `markPreset`, `unmarkPreset`.
- `catalogApi` 객체: `full`, `stage`, `artifact`, `introspection`,
  `artifactByStage`.
- `apiCall` 헬퍼: `lib/api.ts` 의 패턴을 그대로 따름 — `getToken()`
  으로 Bearer 헤더 주입, 에러 응답에서 `detail/message/error` 파싱,
  204/empty body 안전 처리.
- `geny-executor-web` 의 `api/environment.ts` 와 함수명/파라미터
  shape 1:1 매핑 — 향후 web 의 컴포넌트를 포팅할 때 call site 변경
  최소화.

`frontend/src/types/index.ts` — `CreateAgentRequest` 확장
- `env_id?: string` — Phase 3 (PR #54) 에서 backend 가 받는 필드.
  agent 생성 시 EnvironmentManifest 기반 pipeline 채택.
- `memory_config?: Record<string, unknown>` — 동일 PR 의 per-session
  MemoryProvider override.
- 기존 필드 불변. legacy preset 경로 (env_id 없을 때) 그대로.

## Verification

- 새 파일 모두 TypeScript 문법 유효 (import 대상 경로 존재 확인:
  `@/types/environment`, `@/lib/authApi.getToken`).
- `node_modules` 가 없는 환경이라 `tsc --noEmit` 풀 검증은 불가. 본
  PR 의 임포트는 모두 기존 path alias `@/` 를 사용하고, 참조 대상
  파일 (`authApi.ts`, `types/environment.ts`) 이 모두 존재하므로
  컴파일은 통과해야 함. CI / 로컬 dev 빌드에서 확인 권장.
- 런타임 영향 없음 — 새로 추가된 모듈은 아직 어디서도 import 되지
  않음. 기존 페이지/컴포넌트 동작 불변.
- backend 의 `/api/environments/*` 와 `/api/catalog/*` 는 PRs #52-#53
  으로 이미 mount 되어 있으므로 클라이언트가 호출 가능한 상태.

## Deviations

- web 의 `api/environment.ts` 에는 `fetchSessionHistory`,
  `fetchAllHistory`, `fetchRunDetail`, `fetchRunEvents` 같은 history
  helper 가 함께 들어 있다. 이들은 environment 와 별개 도메인이라
  포팅 대상에서 제외 — Geny 가 history API 를 별도로 가지면 그 때
  `historyApi` 로 분리한다.
- web 은 `apiFetch` 라는 공용 fetch wrapper 를 쓰지만 Geny 는
  `lib/api.ts:apiCall` 패턴이라 그대로 따라간다 (web 의 wrapper 는
  axios-like, Geny 는 fetch 직접). 함수 시그니처는 동일.
- 타입은 `Pipeline` / `PipelineStageConfig` 같은 상세 모델은 포팅
  안 함 — Builder UI 가 들어올 때 stage editor 와 함께 도입하는 게
  자연스럽다. 지금은 endpoint 호출에 필요한 shape 만.

## Follow-ups

- PR #18 (Phase 6b): Environment list/detail 뷰 (read-only). 새 라우트
  `/environments` 추가, `environmentApi.list/get` 사용.
- PR #19 (Phase 6c): Environment create/edit 모달 + duplicate/delete.
- PR #20 (Phase 6d): Builder 탭 (stage editor). Catalog API + manifest
  editor.
- PR #21 (Phase 6e): agent 생성 흐름에 env_id 선택 UI 통합. session
  생성 모달에 "Use Environment" 옵션 추가.
- PR #22 (PR #18 in plan numbering): 통합 docs + release notes.
