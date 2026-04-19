# 04. MEMORY_* env + docker-compose plumbing

## Scope

`plan/06` PR #4 — MemorySessionRegistry 가 실제로 provider 를 만들 수
있도록 env 경로를 뚫는다. 기본값은 여전히 **dormant** (legacy SessionMemoryManager
단독 소유). 명시적으로 `MEMORY_PROVIDER=...` 를 켤 때만 신규 경로가 붙는다.

## PR Link

- Branch: `feat/memory-env-plumbing`
- PR: (이 커밋 푸시 시 발행)

## Summary

신규: `backend/service/memory_provider/config.py`
- `build_default_memory_config()` — `MEMORY_PROVIDER` 이 unset/"disabled"/"off"/"none"
  이면 `None` 반환 (dormant). 그 외에는 `{provider, scope[, root|dsn|dialect|timezone]}`
  을 조립해 `MemoryProviderFactory.build` 에 그대로 넘길 수 있는 dict 를 돌려준다.
- `provider=file` 인데 `MEMORY_ROOT` 없으면 `MemoryConfigError` (기동 실패).
- `provider=sql` 인데 `MEMORY_DSN` 없으면 `MemoryConfigError`.
- 빈 문자열은 config 에서 제외해 factory 기본값이 살도록 함.

`service.memory_provider.__init__` 는 `build_default_memory_config` 를 재-export.

`backend/main.py` lifespan 변경
- PR #3 의 `MemorySessionRegistry(default_config=None)` 하드코딩을 제거.
- `build_default_memory_config()` 호출 → 반환값을 `default_config` 로 전달.
- 로그가 "dormant" 또는 `default provider='file' scope='session'` 형태로 분기.

docker-compose 5 개 파일에 6 개 env 패스스루 추가
- `docker-compose.yml`, `docker-compose.dev.yml`, `docker-compose.prod.yml`,
  `docker-compose.dev-core.yml`, `docker-compose.prod-core.yml`.
- 모두 `MEMORY_PROVIDER` 를 비우는 쪽으로 기본값 설정 → 기존 배포는 그대로 dormant.
- `MEMORY_SCOPE` 만 `session` 을 기본값으로 잡아 provider 가 켜진 경우에도 합리적 디폴트.

`.env.sample` — `MEMORY_*` 블록 추가 + 옵션 설명. 전부 주석 처리로 남겨서
활성화는 명시적 opt-in.

## Verification

- `python -m py_compile` OK.
- 스모크 (executor src + Geny backend 를 PYTHONPATH 에 올리고 env 조합 직접 주입):
  - `MEMORY_PROVIDER` unset → `None` ✅
  - `MEMORY_PROVIDER=disabled` → `None` ✅
  - `MEMORY_PROVIDER=ephemeral` → `{provider, scope}` ✅
  - `MEMORY_PROVIDER=file` (ROOT 없음) → `MemoryConfigError` ✅
  - `MEMORY_PROVIDER=file` + `MEMORY_ROOT=/tmp/mem` → `{provider, scope, root}` ✅
  - `MEMORY_PROVIDER=sql` + `MEMORY_DSN=...` + `DIALECT/TIMEZONE/SCOPE` → 전체 수집 ✅

## Deviations

- web (`geny-executor-web/backend/app/config.py`) 은 `MEMORY_PROVIDER` 미설정 시
  `ephemeral` 을 기본값으로 켠다. Geny 는 레거시 시스템이라 **명시적으로 opt-in**
  해야만 신규 경로가 살아난다 (dormant = 기본). 이 차이는 `config.py` 모듈
  docstring 과 `build_default_memory_config` docstring 에 명시.

## Follow-ups

- Phase 4: `AgentSessionManager.create_agent_session` 에서 레지스트리가 활성인 경우
  `provision(session_id) → attach_to_pipeline(pipeline, provider)` 호출.
- Phase 5a~e: 계층별 플래그 (`MEMORY_LEGACY_STM=on` 등) 추가 예정 — 이 config 파일에
  별도 section 으로 확장.
- `docs/memory-provider.md` 가이드 문서는 Phase 6 (UI) 에서 같이 작성.
