# 11. Phase 5a — STM adapter scaffold

## Scope

Phase 5a 의 첫 단계. `MEMORY_LEGACY_STM` 가 PR #56 에서 깔린 인프라 위에
실제 호출 지점과 어댑터 모듈을 추가한다. 이 PR 자체는 동작 변화가 없다 —
어댑터는 항상 legacy 경로로 양보 (`return False`) 한다. 다음 PR 이
`provider.notes()/store()` 쓰기 경로가 확정되면 이 함수의 본문만
교체하면 된다.

## PR Link

- Branch: `feat/memory-phase5a-stm`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/adapters/stm_adapter.py` — 신규
- `try_record_message(session_id, role, content, metadata) -> bool`.
- `legacy_stm_enabled()` 가 True 면 즉시 False 반환 → caller 가 legacy
  `ShortTermMemory.add_message` 를 호출.
- False 인 경우에도 현재는 (provider STM API 미확정) 한 번만 warning
  로그를 남기고 False 반환. 운영자가 플래그를 끈 의도와 실제 동작이
  다름을 명확히 알린다.
- 모듈 docstring 에 향후 채울 단계 (provider 해상, `notes().store()`
  매핑, True 반환 시 caller skip) 를 명시.

`backend/service/memory/manager.py` — `record_message` 한 곳만 수정
- 기존 `self._stm.add_message(role, content, metadata=meta)` 호출 직전에
  `try_record_message(...)` 호출.
- 어댑터가 True 반환 → return (legacy skip). False → legacy 경로 그대로.
- 어댑터 import/실행 예외는 warning 로그 후 legacy fallback (방어적).
- `meta` 변수로 한 번만 계산해 두 경로가 동일한 값을 받도록 함.

## Verification

- `python3 -m py_compile service/memory_provider/adapters/stm_adapter.py
  service/memory/manager.py` OK.
- 기본 환경 (`MEMORY_LEGACY_STM` 미설정 = true): adapter 가 즉시 False
  반환 → 기존 동작 그대로. 추가 비용 = function call 1 회 + flag lookup.
- `MEMORY_LEGACY_STM=false` 설정: adapter 가 False 반환 + 1 회 warning
  로그 (`provider-backed STM is not yet implemented`). 동작은 여전히
  legacy. 운영자가 의도 vs 실제 차이를 즉시 인지 가능.
- `record_message` 의 외부 시그니처/반환값 불변. 기존 caller 영향 없음.

## Deviations

- plan/06 의 Phase 5a 는 STM 쓰기 경로를 provider 로 *완전히* 전환하는
  것을 목표로 한다. 이 PR 은 그 앞 단계로 (a) 호출 지점과 (b) 어댑터
  모듈만 깐다. 이유: provider STM API surface (`notes().store()` vs 다른
  엔드포인트, role/metadata 매핑 스키마) 가 아직 확정되지 않았다. 이
  단계에서 호출 지점을 박아두면 본문 교체 PR 이 `manager.py` 를 다시
  건드리지 않아도 된다.
- 어댑터가 fail-open (예외 시 legacy fallback) 인 이유: STM 쓰기는
  세션의 모든 메시지마다 실행되므로 어댑터 버그가 세션 전체를
  망가뜨려서는 안 된다.

## Follow-ups

- PR 다음 (5a-2): `try_record_message` 본문에 (i) `MemorySessionRegistry`
  에서 session_id → provider 해상, (ii) `provider.notes(...).store(...)`
  로 role/content/metadata 직렬화, (iii) 성공 시 True 반환을 구현.
  `legacy_stm_enabled()=False` 환경에서 STM 쓰기 검증.
- PR #12 (Phase 5b — LTM): 동일 패턴으로 `adapters/ltm_adapter.py` +
  `remember()/remember_dated()` 호출 지점 wire.
- PR #13 (5c — Notes): `IndexEntry` marker 저장의 호출 지점 wire.
- PR #14 (5d — Vector): `vector_memory` faiss 호출 지점 wire (큰 작업,
  re-indexing 동반).
- PR #15 (5e — Curated/Global): `_curated_knowledge/*`, `_global_memory/*`
  호출 지점 wire.
