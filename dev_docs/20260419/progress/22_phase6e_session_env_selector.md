# 22. Phase 6e — session create modal: env_id selector

## Scope

PR #54 로 backend 의 `CreateAgentRequest` 가 이미 `env_id` 를 받고,
PR #63 로 frontend types 도 확장된 상태. 남은 건 UI 에서 env 선택
셀렉트 하나 붙여 실제로 env_id 를 payload 에 넣는 것. Builder 탭 (6d)
과 독립적으로 돌릴 수 있어 먼저 정리.

## PR Link

- Branch: `feat/frontend-phase6e-session-env-selector`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/CreateSessionModal.tsx` — 수정
- `useEnvironmentStore` import + 모달 mount 시 `loadEnvironments()`
  호출. store 가 이미 캐시 있으면 중복 요청해도 동일 state 로 수렴
  (loadEnvironments 는 idempotent — 단순 list refetch).
- 로컬 state `selectedEnvId` 추가, Tool Preset 블록 바로 아래에 "Environment"
  select 삽입. `InfoTooltip` 으로 사용 의미 (pipeline + tools 를 manifest
  가 정한 대로 사용) 설명.
- select 하단 `<small>` 헬퍼 텍스트:
  - 선택 안 했으면 "Uses the role-based preset pipeline (legacy path)."
  - 선택했으면 해당 env 의 description 이 있으면 그걸, 없으면
    기본 placeholder.
- submit 시 `selectedEnvId` 가 비어있으면 payload 에 포함 안 함 →
  backend 가 기존 legacy preset 경로 그대로 실행. 설정하면 PR #54 의
  env_id branch 로 진입.
- VTuber role 분기는 손대지 않음 — env 설정과 avatar / TTS 설정은
  독립적. VTuber + env 조합도 별 문제 없이 돌아가야 한다 (backend
  가 env 의 pipeline 을 사용할 뿐, VTuber 전용 cli_ 설정은 그대로).

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `createSession.environment*` 6 개 키 추가 (label, help, None 옵션,
  로딩 placeholder, legacy hint, selected hint). 양쪽 언어 동수.

## Verification

- `CreateAgentRequest.env_id` 타입 (PR #63) 이 `string | undefined` —
  빈 문자열이면 payload 에서 제외해야 한다. 현재 구현은 `if
  (selectedEnvId)` 체크로 필터링 → 준수.
- `useEnvironmentStore` 는 이미 Phase 6b 로 깔려 있어 추가 의존성
  없음. store 의 loading 플래그는 `isLoading` 하나 (fetch + mutation
  공용) — 모달에서 필드명 alias 로 받아 (`environmentsLoading`) 사용.
- 새 select 는 기존 Tool Preset select 와 동일 스타일 체계 (var(--bg-
  primary), border, focus shadow). 시각적으로 한 덩어리로 묶인다.
- 기존 legacy 흐름 (env 미선택 + tool preset 미선택 + VTuber 기본
  생성 3 종) 은 submit payload 가 달라지지 않으므로 regression 0.

## Deviations

- `memory_config` 필드는 UI 에 노출하지 않음. PR #54 로 type 에는
  포함되어 있지만 per-session MemoryProvider 는 아직 backend
  검증·롤아웃이 한 사이클 더 필요한 영역. UI 는 Phase 7-3 에서
  제공자 switch 가 안정된 뒤 추가한다.
- env list 는 role 과 무관하게 전체 표시. VTuber env / developer env
  같은 taxonomy 가 생기면 `tags` 기반 필터를 추가한다.
- 선택한 env 의 manifest summary (pipeline stages, tools snapshot
  요약) 는 display 하지 않음 — modal 이 이미 길다. 필요하면 drawer
  로 preview 띄우는 버튼을 나중에 추가.

## Follow-ups

- PR #23 (Phase 6d): Builder 탭 — stage editor + artifact picker +
  manifest diff preview. catalog API 본격 사용.
- PR #24 (Phase 7-3 frontend): `memory_config` override UI. provider
  switch UX 가 stabilize 된 후 모달에 섹션 추가.
- PR #25 (PR #18 in plan numbering): 통합 docs + release notes —
  plan/06 이 요청했던 최종 PR.
