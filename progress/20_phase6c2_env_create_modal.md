# 20. Phase 6c-2 — Environment create modal

## Scope

PR #65 의 read-only 카드 그리드에 `+ New Environment` 버튼과 모달을
붙인다. 모달은 backend `service/environment/schemas.py` 가 받는 세 모드
(`blank` / `from_session` / `from_preset`) 를 1:1 노출.

## PR Link

- Branch: `feat/frontend-phase6c2-env-create-modal`
- PR: (이 커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/CreateEnvironmentModal.tsx` — 신규
- `createPortal` 로 `document.body` 에 렌더 (기존 `CreateSessionModal`
  과 동일 패턴).
- mode 선택은 라디오-카드 3 개 (blank / from_session / from_preset).
  각 모드에 해당하는 hint 텍스트를 라벨 아래 보여준다 — 사용자가
  선택 결과를 예측할 수 있게.
- 공통 필드: name (필수), description (선택), tags (쉼표 구분).
- 조건부 필드:
  - `from_session` → session select (`useAppStore().sessions` 그대로
    사용, id/이름 표기).
  - `from_preset` → preset select. hardcoded 리스트는 backend 의
    `_PRESET_FACTORIES` (service.py:43) 를 그대로 복사 — minimal /
    chat / agent / evaluator / geny_vtuber. 런타임 fetch 안 함
    (preset 목록 API 가 아직 없음; 생겼을 때 전환).
- `canSubmit` 이 name 비어있음 / 선택 미완 / 제출 중을 한꺼번에 막는다.
- submit → `useEnvironmentStore.createEnvironment(payload)`. store 가
  이미 성공 시 `loadEnvironments()` 재조회를 돌린다 → 모달은 그냥
  `onClose()` 만 호출.

`frontend/src/components/tabs/EnvironmentsTab.tsx` — 수정
- 헤더 우측에 `New Environment` primary 버튼 추가 (기존 Refresh 옆).
- 빈 상태에도 "Create your first environment" 버튼 노출 — ToolSetsTab
  과 동일한 UX.
- `showCreate` 로컬 state + 조건부 `<CreateEnvironmentModal />` 렌더.

`frontend/src/lib/i18n/en.ts` + `ko.ts` — 수정
- `environmentsTab.newEnvironment`, `environmentsTab.createFirst` 추가.
- `createEnvironment.*` 블록 추가 (title, mode labels/hints, form labels,
  preset option labels). 양쪽 언어 동수 키.

## Verification

- submit payload 는 `CreateEnvironmentPayload` 타입 준수 — backend
  Pydantic 스키마 (mode + 조건부 필드) 와 일치. mode 별 필수 필드는
  모달에서 선행 validate → 400 방지.
- `document` 존재 가드 (`typeof document === 'undefined'`) — SSR 렌더
  중에 잠깐 거치는 path 에서 safe.
- preset 목록은 hardcoded — backend 에서 factory 가 바뀌면 여기서도
  수동 업데이트 필요. 지금은 5 개 + 추가 계획 없음.
- tags 는 쉼표 split + trim + 빈 문자열 필터. 공백 입력 시 tag 필드
  자체를 payload 에서 생략.

## Deviations

- tag 입력을 자유 텍스트 + 쉼표 split 으로 받는다 (chip UI 안 씀).
  간단함 + 기존 Geny input 패턴 (session name, description) 과 동일.
  나중에 Builder 탭에서 tag chip editor 가 필요해지면 공용 컴포넌트
  로 만든다.
- preset 선택에 describe 텍스트를 옵션 라벨 안에 인라인으로 넣는다
  ("Agent — full 16-stage pipeline"). 별도 설명란 추가하면 modal 이
  길어진다. 정말 상세한 설명이 필요하면 Builder 탭에서 제공.
- `base_preset` 필드 (schemas 의 `EnvironmentMetadata.base_preset`) 는
  modal 이 설정하지 않음 — backend 가 `from_preset` 모드일 때 자동
  으로 채워준다. UI 에서 굳이 편집할 이유 없음.
- 성공 후 자동으로 해당 env detail 을 열지는 않음. 지금은 detail 뷰가
  없기 때문. Phase 6c-3 에서 detail drawer 가 들어오면
  `onCreated(id)` → drawer open 으로 엮는다 (이미 prop 으로 열려 있음).

## Follow-ups

- PR #21 (Phase 6c-3): Environment detail drawer. 카드 클릭 → slide-over,
  manifest preview, delete/duplicate 버튼.
- PR #22 (Phase 6d): Builder 탭 — stage editor + artifact picker +
  manifest preview. catalog API 본격 사용.
- PR #23 (Phase 6e): agent 생성 흐름에 env_id 선택 UI 통합.
