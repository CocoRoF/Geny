# 13. Phase 5c — Notes adapter scaffold

## Scope

Phase 5b 와 동일 패턴. Obsidian 스타일 마크다운 노트 (`StructuredMemoryWriter`
+ `MemoryIndexManager`) 의 네 쓰기 경로 — `write_note`, `update_note`,
`delete_note`, `link_notes` — 에 어댑터 호출 지점을 박는다. 동작 변화 없음.

## PR Link

- Branch: `feat/memory-phase5c-notes`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/adapters/notes_adapter.py` — 신규
- `try_write_note(...) -> Optional[str]` — 성공 시 filename, None 이면
  legacy 경로.
- `try_update_note(...) -> Optional[bool]` — 성공 시 True/False, None 이면
  legacy.
- `try_delete_note(...) -> Optional[bool]` — 동일 패턴.
- `try_link_notes(...) -> Optional[bool]` — 동일.
- 4 함수 모두 `legacy_notes_enabled()` True 면 즉시 None 반환, False 면
  공유 `_maybe_warn()` 1회 + None 반환.
- 반환 타입을 `bool` 이 아닌 `Optional[...]` 로 한 이유: 기존
  `StructuredMemoryWriter` API 의 반환값이 의미 있는 정보 (filename, 성공
  여부) 를 담고 있어, 어댑터가 "양보" vs "처리 완료(성공/실패)" 를 구분해
  돌려줘야 한다.

`backend/service/memory/manager.py` — 4개 메서드에 동일 패턴 적용
- 각 try_* 호출 → 반환값이 None 아니면 그대로 반환 / None 이면 legacy.
- import/실행 예외는 warning 로그 후 legacy fallback.
- 외부 시그니처/반환값 불변.

## Verification

- `python3 -m py_compile` OK (notes_adapter, manager).
- 기본 환경 (`MEMORY_LEGACY_NOTES` 미설정 = true): 네 경로 모두 legacy
  그대로. 추가 비용 = function call 1 회 + flag lookup.
- `MEMORY_LEGACY_NOTES=false`: 한 번만 warning 로그, 동작은 legacy.

## Deviations

- plan/06 의 Phase 5c 는 노트 저장을 provider `notes()` 핸들로 *완전히*
  전환. 이 PR 은 호출 지점만. 본문 교체는 후속.
- 4 함수로 분리한 이유: STM/LTM 과 달리 노트는 CRUD + 링크가 모두
  의미 단위로 다른 provider 호출에 매핑될 가능성이 높고 (예: store /
  update / delete / link 가 서로 다른 엔드포인트), 호출 지점에서 의도가
  드러나는 게 유지보수에 유리.

## Follow-ups

- PR 다음 (5c-2): 4 함수 본문에 `provider.notes(...)` 매핑 + 성공
  처리 로직. `legacy_notes_enabled()=False` 환경 검증.
- PR #14 (5d — Vector): `vector_memory.add` / 검색 호출 지점 wire
  (재인덱싱 동반).
- PR #15 (5e — Curated/Global): `_curated_knowledge/*`,
  `_global_memory/*` 호출 지점 wire.
