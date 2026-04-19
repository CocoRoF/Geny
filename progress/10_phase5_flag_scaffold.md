# 10. Phase 5 — per-layer legacy flags scaffolding

## Scope

`plan/06` 에서 Phase 5 는 계층별 5개 PR (`MEMORY_LEGACY_STM`,
`_LTM`, `_NOTES`, `_VECTOR`, `_CURATED`) 로 구성된다. 이 PR 은 그 5개
플래그의 공통 인프라 — env 파싱, 기본값 (모두 legacy on), 진단 로깅,
adapters 패키지 뼈대 — 를 한 번에 깔아두고 이후 PR #11~#15 가 각 레이어를
개별적으로 routed 하도록 한다.

## PR Link

- Branch: `feat/memory-phase5-flags`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/flags.py` — 신규
- `legacy_stm_enabled()`, `legacy_ltm_enabled()`, `legacy_notes_enabled()`,
  `legacy_vector_enabled()`, `legacy_curated_enabled()`. 모두 env 기본값
  `true`.
- `_ON_VALUES = {1, true, yes, on}`, `_OFF_VALUES = {0, false, no, off}`;
  parser 가 두 집합을 명시적으로 처리해 `MEMORY_LEGACY_STM=no` 같은 조합도
  의도대로 해석.
- `snapshot()` — 모든 레이어 플래그를 dict 로 반환. 기동 로깅에서 한 줄로
  상태 찍을 때 사용.

`backend/service/memory_provider/adapters/__init__.py` — 빈 패키지 초기화.
Phase 5a-5e 각 PR 이 여기에 `stm_adapter.py` 등을 추가.

`backend/main.py`
- MemorySessionRegistry 로깅 뒤에 `snapshot()` 을 호출해 레이어별 on/off
  상태를 한 줄로 출력. 운영자가 기동 로그에서 플래그 상태를 즉시 확인.

docker-compose 5 파일 + `.env.sample`
- `MEMORY_LEGACY_{STM,LTM,NOTES,VECTOR,CURATED}=${…:-true}` 패스스루 추가.
- `.env.sample` 에 블록 + 주석.

## Verification

- `python3 -m py_compile` OK (flags, adapters, main.py).
- 파서 동작 (로직 검증): `"1"/"true"/"yes"/"on"` → True,
  `"0"/"false"/"no"/"off"` → False, 기타 → default (True). 기본값 미지정시
  모두 legacy on 이므로 기존 동작 불변.
- 기동 로그: 기본 환경에서 `MEMORY_LEGACY_* flags: stm=on ltm=on notes=on
  vector=on curated=on` 가 찍혀야 함.

## Deviations

- plan/06 는 Phase 5 를 5 개 PR 로 제안. 이 PR 은 그 앞에 들어가는 "0번째"
  공통 인프라 PR 로, 이후 PR 들이 각자 한 레이어씩만 건드리도록 면적을
  최소화한다. 기능 동작 변화는 없음.
- web 의 legacy flag 대응물이 존재하지 않음 — Geny 전용. web 은 Phase 2
  부터 provider 가 유일한 경로라 flag 자체가 불필요하다.

## Follow-ups

- PR #11 (Phase 5a — STM): `adapters/stm_adapter.py` 추가. legacy_stm=false
  일 때 `SessionMemoryManager.record_execution` 의 STM 쓰기 경로가 provider
  `notes()/store()` 로 전환.
- PR #12 (5b — LTM): `adapters/ltm_adapter.py`. `GenyMemoryStrategy` 반영
  경로가 provider 의 `Layer.LONG_TERM` 으로.
- PR #13 (5c — Notes): `adapters/notes_adapter.py`. `IndexEntry` 기반
  marker 저장을 provider `notes()` 핸들로.
- PR #14 (5d — Vector): `adapters/vector_adapter.py`. faiss 인덱스를 provider
  `vector_chunks` 로 (재인덱싱 필요; migration 스크립트 동반).
- PR #15 (5e — Curated/Global): `adapters/curated_adapter.py`. `_curated_knowledge/*`,
  `_global_memory/*` → provider scope=USER/GLOBAL.
- Phase 7 (PR #17): `/api/agents/{id}/memory/*` 엔드포인트를 provider 기반
  구현으로 재배선. 옵션 B (경로 유지, 내부만 교체).
