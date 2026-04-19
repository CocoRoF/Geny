# 15. Phase 5e — Curated/Global adapter scaffold

## Scope

Phase 5 의 마지막 계층. user-scoped curated knowledge
(`_curated_knowledge/*`) 와 cross-user global memory (`_global_memory/*`)
의 CRUD 쓰기 경로에 어댑터 호출 지점을 박는다. 동작 변화 없음.

## PR Link

- Branch: `feat/memory-phase5e-curated`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/adapters/curated_adapter.py` — 신규
- Curated (USER scope) — `try_curated_write_note(username, ...)`,
  `try_curated_update_note(username, ...)`, `try_curated_delete_note(username, ...)`.
- Global (GLOBAL scope) — `try_global_write_note(...)`,
  `try_global_update_note(...)`, `try_global_delete_note(...)`.
- 모두 `legacy_curated_enabled()` True → 즉시 None 반환. False → 공유
  `_maybe_warn()` 1회 + None.
- 반환 타입 `Optional[...]`: notes_adapter 와 동일하게 "양보" vs
  "처리 완료" 를 None 으로 구분.
- Curated 쓰기는 username 을 받아 향후 provider scope=USER 매핑에 사용.
- Global 쓰기는 username 없음 (글로벌 스코프).

`backend/service/memory/curated_knowledge.py` — `CuratedKnowledgeManager`
의 `write_note`, `update_note`, `delete_note` 에 동일 패턴 wire
- 메서드 진입 시 어댑터 호출 → 반환값이 None 아니면 그대로 반환 / None
  이면 기존 legacy 경로 (`self._writer.write_note` 등).
- import/실행 예외는 warning 로그 후 legacy fallback.
- `self.username` (no underscore) 으로 username 전달.

`backend/service/memory/global_memory.py` — `GlobalMemoryManager` 의
세 메서드에 동일 패턴 wire
- `write_note`, `update_note`, `delete_note`. promote 는 내부적으로
  `write_note` 를 호출하므로 wire 불필요 (자동 위임).

## Verification

- `python3 -m py_compile` OK (curated_adapter, curated_knowledge,
  global_memory).
- 기본 환경 (`MEMORY_LEGACY_CURATED` 미설정 = true): 6 경로 모두 legacy
  그대로. 추가 비용 = function call 1 회 + flag lookup.
- `MEMORY_LEGACY_CURATED=false`: 한 번만 warning 로그
  (`provider-backed curated/global memory is not yet implemented`),
  동작은 legacy.
- 외부 시그니처/반환값 불변. 컨트롤러/툴/스케줄러/agent_session 등
  10 + 호출 지점에서 직접 변경 없음 — manager 클래스 메서드를 인터셉트
  포인트로 잡았기 때문.

## Deviations

- plan/06 의 Phase 5e 는 curated/global 을 provider scope=USER/GLOBAL
  로 *완전히* 전환. 이 PR 은 호출 지점만. 본문 교체는 후속.
- 호출 지점을 controller/tools/scheduler 같은 caller 가 아닌 manager
  클래스 메서드 자체에 박은 이유: caller 가 10+ 곳에 흩어져 있어 각각
  wire 하면 면적이 너무 커지고 실수 위험이 높다. 메서드 한 곳에서
  인터셉트하면 모든 caller 가 자동 적용된다. 이 패턴은 Phase 5a~5d
  와 다르지만 (5a~5d 는 manager 메서드가 곧 단일 caller 였음),
  결과적인 면적은 동일하다.
- promote/create_link/reindex 같은 "복합" 동작은 내부적으로 write_note
  등을 호출하므로 별도 wire 없이 자동 위임된다. 단, 향후 본문 교체
  시 promote 가 단일 트랜잭션이 필요하다면 별도 어댑터 함수가 필요할
  수 있다.

## Follow-ups

- PR 다음 (5e-2): 6 함수 본문에 (i) registry → provider 해상, (ii)
  `provider.write(scope=USER|GLOBAL, ...)` 매핑, (iii) 성공 시 적절한
  값 반환을 구현. `legacy_curated_enabled()=False` 환경 검증.
- Phase 5 후속 통합 PR: 5 계층 어댑터 본문이 모두 채워지면 통합 smoke
  테스트 (`MEMORY_LEGACY_*=false` 일괄 + provider 백엔드 살아있는
  환경) 한 번 진행.
- Phase 6 (PR #16~): 프론트엔드 Environment / Builder 탭.
- Phase 7 (PR #17): `/api/agents/{id}/memory/*` 엔드포인트를 provider
  기반으로 재배선.
