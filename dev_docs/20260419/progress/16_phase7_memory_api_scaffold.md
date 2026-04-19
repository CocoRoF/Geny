# 16. Phase 7 — memory API provider routing scaffold (option B)

## Scope

plan/06 의 Phase 7 (옵션 B — 경로 유지, 내부만 교체) 의 첫 단계.
`/api/agents/{id}/memory/*` 엔드포인트를 provider 기반 구현으로
재배선하기 위한 인프라 — env 플래그, provider 룩업 헬퍼, 라우팅 결정
관측 로깅 — 를 한 번에 깐다. 동작 변화 없음.

## PR Link

- Branch: `feat/memory-phase7-api-provider`
- PR: (이 커밋 푸시 시 발행)

## Summary

`backend/service/memory_provider/config.py`
- `is_api_provider_enabled()` 신규. `MEMORY_API_PROVIDER` env 를
  `is_attach_enabled()` 와 동일한 truthy parser 로 처리. 기본 False.

`backend/controller/memory_controller.py`
- `_get_memory_provider(request, session_id) -> Optional[MemoryProvider]`
  헬퍼. `app.state.memory_registry` 에서 세션의 provider 를 안전 룩업.
  registry 없거나 세션 미프로비전이면 None. 예외 silently swallow —
  관측용이라 실패해도 caller 영향 없게.
- `_route_log(session_id, endpoint, request)` 신규. 플래그 활성 시
  "would route" 결정을 INFO 로그로 남김 — provider 부착 여부를 운영
  로그에서 즉시 확인 가능. 플래그 꺼져 있으면 no-op.
- 13개 per-session 엔드포인트에 `request: Request` 파라미터 추가 +
  진입 시 `_route_log(...)` 호출. 본문 동작은 그대로 legacy.
  대상: `get_memory_index`, `get_memory_stats`, `get_memory_tags`,
  `get_memory_graph`, `list_memory_files`, `read_memory_file`,
  `create_memory_file`, `update_memory_file`, `delete_memory_file`,
  `search_memory`, `search_memory_post`, `create_memory_link`,
  `reindex_memory`.
- `migrate_memory`, `promote_to_global` 는 wire 안 함 — 전자는 legacy
  파일 → 구조화 마이그레이션이라 provider 와 직교, 후자는 이미
  global_memory 모듈을 통해 Phase 5e adapter 의 영향권 안에 있음.

5 docker-compose 파일 + `.env.sample`
- `MEMORY_API_PROVIDER=${MEMORY_API_PROVIDER:-false}` 패스스루 추가.
- `.env.sample` 에 주석 블록 추가 (현재는 관측만 / 본문 교체 시 실제
  라우팅 활성화 명시).

## Verification

- `python3 -m py_compile` OK (memory_controller, config).
- 기본 환경 (`MEMORY_API_PROVIDER` 미설정 = false): `_route_log` 가
  no-op 으로 즉시 return → 응답 시간/동작 영향 없음.
- `MEMORY_API_PROVIDER=true`: 각 요청마다 INFO 로그에
  `memory.<endpoint> session=... would-route=provider|legacy (...)` 한 줄
  찍힘. 응답은 여전히 legacy.
- 응답 스키마/HTTP 코드 불변. 기존 frontend / API consumer 영향 없음.
- 13개 엔드포인트 모두 `Request` 의존성을 받지만 FastAPI 가 자동 주입하므로
  caller (HTTP) 입장에서는 변경 없음.

## Deviations

- plan/06 의 Phase 7 는 "내부 구현 교체" 가 최종 목표. 이 PR 은 그 앞
  단계로 (a) 결정 인프라 (provider 룩업, 플래그) 와 (b) 관측 (로깅) 만
  깐다. 본문 교체 PR 이 라우팅 분기를 채워 넣을 자리를 미리 확보.
- 본문을 함께 교체하지 않은 이유: 13개 엔드포인트의 응답 스키마
  (memory index dict, stats dataclass, search results 등) 가 기존
  frontend 와 byte-compatible 하게 직렬화되어야 한다. provider 의 read
  surface (notes(), search()) 가 동일 형태를 제공하는지 검증되기 전
  본문을 바꾸면 frontend 가 깨질 수 있다. 먼저 프로비전된 provider 가
  실제 운영에서 attach 되는지 로그로 확인 → 그 다음 한 엔드포인트씩
  본문 swap 하는 게 안전.
- `migrate_memory` 는 마이그레이션 도구라 routing 의 의미가 없다 (실행
  대상이 legacy 파일). `promote_to_global` 은 `global_memory` 모듈이
  Phase 5e adapter 를 통해 이미 routing 가능하므로 controller 에서
  추가 wire 불필요.

## Follow-ups

- PR 다음 (7-2): 첫 엔드포인트 본문 교체. `get_memory_index` 부터 —
  `provider.describe()` + `provider.list(layer=Layer.LONG_TERM)` 등으로
  index dict 재구성. 응답 스키마 byte-compatible 검증. 검증 후 한
  엔드포인트씩 swap.
- PR 다음 (7-3): write 엔드포인트 (`create/update/delete_memory_file`,
  `create_memory_link`) 본문 교체. Phase 5c notes_adapter 의 본문이
  채워진 후에 진행 (5c-2 에 종속).
- PR 다음 (7-4): search 엔드포인트 (`search_memory`,
  `search_memory_post`) 본문 교체. provider.retrieve() 호출 +
  `MemorySearchResult` 와 byte-compatible 직렬화.
- PR #18: 통합 docs + release notes.
