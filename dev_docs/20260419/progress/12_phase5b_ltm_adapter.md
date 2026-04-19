# 12. Phase 5b — LTM adapter scaffold

## Scope

PR #57 (Phase 5a STM) 와 동일 패턴으로 long-term memory 의 세 쓰기
경로 (`append`, `write_dated`, `write_topic`) 에 어댑터 호출 지점을
박는다. 동작 변화 없음. `MEMORY_LEGACY_LTM` 플래그가 끄여 있어도
provider 본문은 아직 비어 있어 legacy 경로로 양보한다.

## PR Link

- Branch: `feat/memory-phase5b-ltm`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/adapters/ltm_adapter.py` — 신규
- `try_append(session_id, text, heading=None) -> bool`
- `try_write_dated(session_id, text) -> bool`
- `try_write_topic(session_id, topic, text) -> bool`
- 모두 `legacy_ltm_enabled()` True 면 즉시 False, False 면 1회 warning
  로그 후 False 반환. 공유 `_maybe_warn()` 헬퍼로 세 경로가 같은 메시지
  사용.
- 모듈 docstring 에 향후 `provider.write(layer=Layer.LONG_TERM, ...)`
  매핑 단계 명시.

`backend/service/memory/manager.py` — `remember`, `remember_dated`,
`remember_topic` 에 동일 패턴 적용
- 각각 try_* 어댑터 호출 → True 면 return / False 면 legacy 경로.
- import/실행 예외는 warning 로그 후 legacy fallback.
- 외부 시그니처/반환값 불변. caller 영향 없음.

## Verification

- `python3 -m py_compile` OK (ltm_adapter, manager).
- 기본 환경 (`MEMORY_LEGACY_LTM` 미설정 = true): 세 경로 모두 legacy
  그대로. 추가 비용 = function call 1 회 + flag lookup.
- `MEMORY_LEGACY_LTM=false`: 한 번만 warning 로그
  (`provider-backed LTM is not yet implemented`), 동작은 legacy.
- `remember*` 메서드의 외부 시그니처/반환값 불변.

## Deviations

- plan/06 의 Phase 5b 는 LTM 쓰기 경로를 provider 의
  `Layer.LONG_TERM` 로 *완전히* 전환하는 것을 목표로 한다. 이 PR 은
  Phase 5a 와 동일한 이유 (provider write surface 미확정) 로 호출 지점
  + 어댑터 모듈만 깐다. 본문 교체는 후속 PR.
- LTM 은 STM 과 달리 세 가지 경로 (append/dated/topic) 가 있어
  어댑터도 세 함수로 분리. 하나의 `try_write(kind, ...)` 디스패처로
  통합하지 않은 이유: 각 함수가 향후 다른 provider 호출
  (`write(layer=LONG_TERM)` vs `write_dated` vs `write_topic` 등)로
  분기될 가능성이 높고, 호출 지점에서 의도가 명확히 드러나는 것이
  유지보수에 유리.

## Follow-ups

- PR 다음 (5b-2): 세 `try_*` 함수 본문을 (i) registry 에서 provider
  해상, (ii) `provider.write(layer=Layer.LONG_TERM, kind=...)` 로
  매핑, (iii) 성공 시 True 반환을 구현. `legacy_ltm_enabled()=False`
  환경에서 `remember*` 동작 검증.
- PR #13 (5c — Notes): 동일 패턴으로 `IndexEntry` marker 저장 호출
  지점에 `notes_adapter` wire.
- PR #14 (5d — Vector): `vector_memory.add` 호출 지점 wire (큰 작업,
  re-indexing 동반).
- PR #15 (5e — Curated/Global): `_curated_knowledge/*`,
  `_global_memory/*` 호출 지점 wire.
