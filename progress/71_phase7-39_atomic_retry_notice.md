# 71. Phase 7-39 — "Atomic off for this retry" 공지 배너

## Scope

Phase 7-29 의 원클릭 "Retry without atomic" 는 사용자가 atomic 롤백
후 한 버튼으로 재시도할 수 있게 한다. 그러나 재시도 후 결과
리포트가 나오기까지 "왜 이번에는 atomic 이 꺼졌는지" 에 대한
안내가 없었다. Phase 7-29 follow-up 으로 명시된 항목.

4.5 초 자동 dismiss 되는 warning 톤 배너를 추가해 "이번 재시도는
부분 성공 허용" 이라는 점을 명시. submitError 배너와 동일 블록 위에
배치.

## PR Link

- Branch: `feat/phase7-39-atomic-retry-toast`
- PR: (커밋 푸시 시 발행)

## Summary

`frontend/src/components/modals/ImportEnvironmentModal.tsx` — 수정
- `useEffect` import 추가 (언마운트 시 타이머 clear).
- 상태 2 개 추가:
  - `atomicNotice: boolean` — 배너 표시 플래그.
  - `atomicNoticeTimer: ref` — auto-dismiss setTimeout 핸들.
- `handleRetryWithoutAtomic()` 에 `setAtomicNotice(true)` + 4500ms
  타임아웃 예약. 기존 `handleConfirm(false)` 경로는 그대로.
- 언마운트 cleanup `useEffect` — 타이머 누수 방지.
- submit feedback 블록 위에 새 warning 배너 (`--warning-color` 톤,
  rgba 0.1 배경). `AlertTriangle` 아이콘 + 메시지 텍스트.

`frontend/src/lib/i18n/en.ts`, `ko.ts` — 수정
- `importEnvironment.atomicDisabledNotice` 메시지 추가.
  - en: "Atomic rollback is off for this retry. Partial success is
    allowed — successful entries stay even if later ones fail."
  - ko: "Atomic 롤백이 이번 재시도에서만 꺼집니다. 일부 성공을
    허용 — 뒤 entry 가 실패해도 먼저 성공한 것은 유지됩니다."

## Verification

- 번들 import + atomic 체크 + 일부러 fail 엔트리 섞어서 전송 →
  atomic 롤백 발생 → Footer 에 "Retry without atomic" 노출.
- 해당 버튼 클릭 → submit feedback 바로 위에 warning 배너가 나타나고,
  `handleConfirm(false)` 가 즉시 실행되어 네트워크 탭에
  `?atomic=false` 요청이 확인됨.
- 4.5 초 후 배너 자동 사라짐. 그 전에 모달 닫으면 타이머가 clear
  되어 경고 없음 (useEffect cleanup).
- atomic 체크박스는 이 배너와 관계 없이 UI 상태 반영 (재시도 직후
  체크박스도 off 로 동기화).
- 일반 import flow (atomic 쓰지 않거나 성공) 에서는 배너 안 보임.
- ko 로케일 메시지 확인.

## Deviations

- Toast 라이브러리 (sonner, react-hot-toast 등) 를 쓰지 않고 inline
  배너 방식으로 구현. 프로젝트 전체가 inline 피드백 패턴을 쓰고
  있어 외부 의존 추가 불필요. 또한 배너가 submit feedback 과 같은
  정보 계층에 머물러 사용자 시선이 한 곳에 모인다.
- 4500 ms 는 "메시지를 읽고 체크박스를 확인할 정도" 로 충분하면서도
  리포트가 준비되는 동안 시야에 머물게 한 길이. 토스트 관습보다
  약간 길다.
- `--warning-color` (amber) 톤을 사용. primary 톤은 정보성, danger
  톤은 실패 의미라 재시도 중이라는 semantic 에 부적합.
- 메시지에 "partial success is allowed" 문구를 넣어 "일부 성공 시
  결과 리포트에 원상복구 없이 그대로 남음" 을 명시. atomic 의미를
  처음 만나는 사용자도 이해할 수 있도록 atomic 이라는 용어 없이도
  결론이 전달되게 작성.

## Follow-ups

- 배너를 닫기 위한 명시적 X 버튼 (현재는 시간 지나면 자동 사라짐).
- 처음 retry 시에만 노출하고 두 번째 이후에는 생략하는 "1 회
  안내" 모드 — 반복 세션에서 noise 감소.
- atomic 재활성화 시 동일한 방식으로 "Atomic is back on" 배너 —
  상호 대칭.
