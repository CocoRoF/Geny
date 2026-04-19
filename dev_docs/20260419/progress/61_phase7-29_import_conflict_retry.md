# 61. Phase 7-29 — Import conflict warning + Retry without atomic

## Scope

ImportEnvironmentModal 위에 두 개의 UX 개선:

1. **Name conflict 경고** — 현재 modal 은 import 시 기존 env 와
   이름이 겹쳐도 조용히 중복을 만든다. 번들/단일 경로 모두에서
   "이 이름 이미 있음" 을 프리플라이트로 알려 주고, bundle 은 입력
   칸을 노란 border + AlertTriangle 배지로 마킹한다.
2. **Atomic rollback 재시도** — Phase 7-28 이후 atomic=true 로 실패한
   결과 화면 (모든 entry 가 `rolled back (...)` / `not processed (...)`
   표시) 에서 "Retry without atomic" 버튼을 노출. 체크박스를 수동으로
   끄고 번들 JSON 을 다시 붙여넣는 동선을 한 번의 클릭으로 단축.

Phase 7-28 의 자연스러운 QoL 연장선. 새 API 나 엔드포인트 없음 —
프론트 한 파일 + i18n 두 파일.

## PR Link

- Branch: `feat/phase7-29-import-conflict-retry`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- store 에서 `environments` 를 destructure 해서 `existingNames`
  (lowercase Set) 계산.
- `bundleConflicts = { conflicts: Record<number, bool>, count }` 및
  `singleConflict` / `singleConflictName` memo 추가.
- `atomicRollback` memo — `bundleResult` 의 성공 0건 + 실패 전부
  `rolled back` / `not processed` 프리픽스면 true.
- 번들 프리뷰 `<li>` 에 conflict 시 입력 border 노란색 전환 + 우측
  `AlertTriangle` 배지 (title = conflictBadge).
- 번들 프리뷰 하단에 `bundleConflicts.count > 0` 이면 노란색
  banner (`conflictBannerBundle`) 노출.
- 단일 경로 name override 아래에 `singleConflict` 면 banner
  (`conflictBannerSingle`) 노출.
- `handleConfirm(atomicOverride?: boolean)` 로 시그니처 확장.
  override 가 주어지면 state 의 `atomic` 대신 override 사용.
- Footer 에 `bundleResult && atomicRollback` 이면 "Retry without atomic"
  버튼 추가. 눌리면 `setAtomic(false)` + `setBundleResult(null)` +
  `handleConfirm(false)` 호출. submitting 중에는 "Retrying without
  atomic…" 라벨.
- 기존 footer 의 단일 버튼을 Fragment 로 감싸 atomic-retry 버튼이
  Done 버튼 왼쪽에 병치되도록.

`frontend/src/lib/i18n/en.ts` / `ko.ts` — 수정
- 신규 키: `importEnvironment.conflictBadge`,
  `conflictBannerSingle`, `conflictBannerBundle`,
  `retryWithoutAtomic`, `retryingWithoutAtomic`.

## Verification

### Conflict 경고

- 기존 환경 이름이 `My Env` 인 상태에서 번들 JSON 에 같은 이름 entry
  가 있으면 해당 row 입력창 border 노랑 + 오른쪽에 경고 아이콘.
- 해당 entry 이름을 다른 값으로 바꾸면 배지가 즉시 사라짐.
- 여러 entry 가 동시에 겹치면 하단 banner 에 "N entry(ies) clash…"
  문구 노출.
- 단일 경로에서 파일 이름이 기존 env 와 겹치면 name override 하단에
  "An environment named \"X\" already exists." 경고.
- nameOverride 를 채우면 경고가 overriding name 기준으로 재평가됨
  (override 가 충돌이면 경고, override 가 깨끗하면 경고 사라짐).

### Retry without atomic

- atomic 켠 채로 malformed entry 가 섞인 번들 import → 결과 화면에
  모든 entry 가 `rolled back (…)` / `not processed (…)` 로 표시.
- Footer 의 "Retry without atomic" 버튼을 클릭 → bundleResult 즉시
  초기화, atomic=false 로 같은 번들이 다시 import 됨 → 정상 entry 는
  성공, malformed entry 만 실패.
- atomic 없이 일부만 실패한 일반 결과 (successes > 0) 화면에는 retry
  버튼이 뜨지 않음.
- atomic 켜고 전부 성공 → result 는 성공 목록만, retry 없음.
- 재시도 중에는 버튼 라벨이 "Retrying without atomic…" 로 바뀌고
  disabled 처리.

### i18n

- ko 로케일에서 banner/badge/retry 라벨이 모두 한국어로 표시.

## Deviations

- Conflict 판정은 이름만 사용 (대소문자 무시). 실제로 파일 시스템
  저장에서 이름 중복은 허용되지만, UX 상 "같은 이름의 두 env" 는
  사람 입장에서 헷갈려서 경고만 하고 진행은 막지 않음 (blocking 이
  아닌 warning).
- `handleConfirm` 이 optional override 를 받는 방식으로 바뀌었기 때문에
  footer 기존 버튼을 `() => handleConfirm()` 로 래핑. 래핑 안 하면
  React 가 MouseEvent 를 첫 인자로 전달해 `atomic=true` 를 덮어쓰는
  regression 이 생긴다.
- `atomicRollback` 판정은 에러 문자열 프리픽스 (`rolled back` /
  `not processed`) 매칭으로 결정. 백엔드 포맷이 바뀌면 retry 버튼이
  안 뜰 수 있음 — 동일 포맷을 쓰는 테스트를 추가하는 대신, 현재는
  Phase 7-28 의 `environment_controller.py` 와 인라인으로 맞췄다.

## Follow-ups

- Retry 시에 atomic 체크박스도 자동으로 꺼졌음을 사용자에게 토스트로
  알리기 (지금은 조용히 꺼짐).
- Conflict 경고에 "Auto-suffix" (e.g. `My Env (2)`) 제안 버튼을 더해
  클릭 한 번으로 이름 오버라이드를 채워 주기.
- Phase 7-28 의 남은 follow-up: human-readable markdown diff export,
  multi-diff matrix.
