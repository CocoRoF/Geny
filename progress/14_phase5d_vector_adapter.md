# 14. Phase 5d — Vector adapter scaffold

## Scope

Phase 5a~5c 와 동일 패턴. FAISS 기반 의미 검색 인덱싱 경로
(`VectorMemoryManager.index_text`) 에 어댑터 호출 지점을 박는다.
동작 변화 없음. 5계층 중 가장 무거운 계층 — 본문 교체 시
re-embedding/migration 스크립트가 동반되어야 한다.

## PR Link

- Branch: `feat/memory-phase5d-vector`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/adapters/vector_adapter.py` — 신규
- `try_index_text(session_id, text, source_file, *, replace=False) -> Optional[int]`
- async 함수. legacy `VectorMemoryManager.index_text` 가 async 이기
  때문에 호출 지점에서 `await` 호환을 유지.
- `legacy_vector_enabled()` True → 즉시 None 반환. False → 1회 warning
  후 None.
- 반환 타입 `Optional[int]`: 성공 시 indexed chunk 수 (legacy
  `index_text` 의 반환과 일치), None 이면 legacy fallback.

`backend/service/memory/manager.py` — `record_execution` 의 vector 인덱싱
한 곳 수정
- 기존 `await self._vmm.index_text(entry, source)` 한 줄을 (i) 어댑터
  `await try_index_text(...)` → 결과가 None 아니면 handled=True, (ii)
  handled=False 일 때만 legacy `await self._vmm.index_text(...)` 호출
  로 분리.
- 어댑터 import/실행 예외는 warning 로그 후 legacy fallback (방어적).
- 외부 호출 인자/시그니처 불변.

## Verification

- `python3 -m py_compile` OK (vector_adapter, manager).
- 기본 환경 (`MEMORY_LEGACY_VECTOR` 미설정 = true): 어댑터가 즉시 None
  반환 → 기존 FAISS 인덱싱 그대로. 추가 비용 = async function call 1
  회 + flag lookup.
- `MEMORY_LEGACY_VECTOR=false`: 한 번만 warning 로그
  (`provider-backed vector indexing is not yet implemented`), 동작은
  legacy.
- 어댑터/legacy 모두 실패해도 외부 try/except 블록이 잡아 record_execution
  은 계속 진행 (non-critical 로 마킹된 영역).

## Deviations

- plan/06 의 Phase 5d 는 vector 저장을 provider `vector_chunks` 로
  *완전히* 전환 + faiss 인덱스 마이그레이션. 이 PR 은 호출 지점만.
  본문 + migration 스크립트는 후속 PR.
- vector 계층에는 search 경로도 있으나 (`build_memory_context_async`
  의 `self._vmm.search(query)`) 이 PR 은 *쓰기* 경로만 wire. 이유:
  쓰기와 읽기를 동시에 전환하면 인덱스 분기 (legacy FAISS vs provider
  vector store) 동안 데이터가 섞여 검색 품질이 비정상화될 위험. 쓰기
  먼저 안정화 후 읽기 전환이 안전.
- 단일 호출 지점이라 어댑터 함수도 1개 (다른 계층은 2~4개). 향후
  `index_memory_files` (전체 재인덱싱) 가 provider 로 옮겨가면
  `try_index_files` 함수가 추가될 것.

## Follow-ups

- PR 다음 (5d-2): `try_index_text` 본문에 (i) registry → provider
  해상, (ii) `provider.vector_chunks(...).index(...)` 매핑, (iii)
  성공 시 chunk count 반환.
- 그 다음 (5d-3): faiss → provider 마이그레이션 스크립트 + 검증.
  기존 세션의 `_vector_store/index.faiss` 를 읽어 provider 의
  vector_chunks 로 옮기는 일회성 도구.
- 그 다음 (5d-4): 검색 경로 (`self._vmm.search`) 도 어댑터로 wire.
- PR #15 (5e — Curated/Global): 마지막 계층.
