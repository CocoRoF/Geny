# 03. 메모리 서브시스템 → `MemoryProvider` 이관

## 목표 (3 계단)

1. **공존 단계**: 레거시 `SessionMemoryManager` 와 executor `MemoryProvider` 가 한 세션에 동시 존재. 신규 REST 표면은 프로바이더를 기반으로, 기존 `/api/agents/{id}/memory/*` 는 매니저 기반.
2. **점진 치환 단계**: 각 계층(STM / LTM / Notes / Vector / Curated / Global) 을 프로바이더로 개별 이관. 모든 전환은 feature flag 로 토글.
3. **정리 단계**: 레거시 코드 경로 제거, REST 통합.

## 신규 모듈

### 3-A. `backend/service/memory_provider/` (신규)

```
backend/service/memory_provider/
├── __init__.py
├── config.py         # env → MemoryProviderFactory config dict
├── exceptions.py     # MemoryConfigError, MemorySessionNotFoundError
├── registry.py       # MemorySessionRegistry
└── adapters/         # (Phase 5) 레거시 매니저 ↔ 프로바이더 어댑터
    ├── __init__.py
    ├── legacy_stm_adapter.py
    ├── legacy_ltm_adapter.py
    └── ...
```

web 의 `MemorySessionRegistry` 를 그대로 포팅하되 네임스페이스를 `backend.service.memory_provider` 로 맞춘다.

### 3-B. `backend/app/config` 확장 (또는 `backend/service/config/settings.py`)

Geny 는 자체 `ConfigManager` 가 있으므로, `MEMORY_*` env 를 읽는 helper 를 `ConfigManager` 에 통합하거나 별도 `MemorySettings` 를 둔다.

```python
class MemorySettings:
    provider: str  # "ephemeral" | "file" | "sql" | "composite"
    dsn: str
    dialect: str
    root: str
    timezone: str
    scope: str = "session"

    def to_factory_config(self) -> dict: ...
```

## REST 표면

### Phase 2 (공존 진입 지점)

| Verb | Path | 기존 유무 | 비고 |
|------|------|---------|------|
| GET | `/api/sessions/{id}/memory` | **신규** | MemoryDescriptorResponse |
| POST | `/api/sessions/{id}/memory/retrieve` | **신규** | MemoryRetrievalRequest/Response |
| DELETE | `/api/sessions/{id}/memory` | **신규** | clear (provider release) |

### Phase 7 정리

- `/api/agents/{id}/memory/*` 14 개 엔드포인트 운명 결정:
  - 옵션 A: 유지 (레거시 UI 호환)
  - 옵션 B: 프로바이더 기반으로 재구현 (`notes()` 핸들 사용)
  - 옵션 C: deprecate → 301 리다이렉트 / 410 Gone
- 권장: **옵션 B**. 경로 유지, 내부만 교체.

## 데이터 마이그레이션

### 3-C. 스키마 매핑

Geny DB 테이블 → executor SQL 프로바이더 테이블 매핑:

| Geny 테이블 | 이관 대상 | executor 테이블 (프로바이더가 관리) | 방법 |
|-------------|----------|-----------------------------------|------|
| `session_memory_entries` (STM+LTM 혼합) | STM + LTM 분리 | `stm_entries`, `ltm_entries` | 배치 SQL 변환 |
| `_index.json` (파일) | Notes index | `index_entries` | 파일 파싱 → upsert |
| `vectordb/index.faiss` (파일) | Vector | `vector_chunks` (pgvector 또는 SQLite FAISS) | 재인덱싱 (임베딩 재생성 가능) |
| `_curated_knowledge/*` | 파일 → 프로바이더 | `notes` (scope=USER) | CLI 배치 |
| `_global_memory/*` | 파일 → 프로바이더 | `notes` (scope=GLOBAL) | CLI 배치 |

### 3-D. 마이그레이션 스크립트 (`scripts/migrate_memory_to_provider.py`)

- 인자: `--session-id`, `--dry-run`, `--layer stm|ltm|notes|vector|all`.
- 멱등성 보장 (중복 키 업서트).
- 진행 로그 + 실패 시 롤백 (transaction 단위).

## feature flag (Phase 5)

| flag | 기본값 | 효과 |
|------|-------|------|
| `MEMORY_PROVIDER_ENABLED` | false (Phase 2) → true (Phase 4) | Registry 활성화 |
| `MEMORY_PROVIDER_ATTACH` | false → true (Phase 4) | Stage 2 에 attach |
| `MEMORY_LEGACY_STM` | on → off (Phase 5a) | 레거시 매니저 쓰기/읽기 |
| `MEMORY_LEGACY_LTM` | on → off (Phase 5b) | |
| `MEMORY_LEGACY_NOTES` | on → off (Phase 5c) | |
| `MEMORY_LEGACY_VECTOR` | on → off (Phase 5d) | |
| `MEMORY_LEGACY_CURATED` | on → off (Phase 5e) | |

## 이관시 남기는 것

- `backend/service/memory/reflect_utils.py` — LLM 콜 래퍼. 유지 (프로바이더는 `Capability.REFLECT` 선언만 하며 실제 LLM 콜은 Geny 가 주도).
- `CurationEngine` / `CurationScheduler` — 유지. 읽기 경로만 프로바이더로 스위치.
- `record_execution()` 의 자동태그 휴리스틱 — 프로바이더 write 전 전처리기로 재배치.

## 수용 기준

- Phase 2 종료: 신규 3 엔드포인트 동작 + Registry 가 `ephemeral` 로 기동.
- Phase 4 종료: Stage 2 attach 완료. 기존 매니저와 동시 동작.
- Phase 5 각 단계 종료: 해당 계층 읽기/쓰기가 프로바이더 쪽에서도 동일 결과.
- Phase 7 종료: `/api/agents/{id}/memory/*` 가 프로바이더 기반으로 재구현.
