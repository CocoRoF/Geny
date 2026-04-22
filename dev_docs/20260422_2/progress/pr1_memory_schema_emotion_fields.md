# PR-X6-1 · `feat/memory-schema-emotion-fields` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 17 신규 테스트 pass. 기존 쓰기/읽기 경로 무영향
(`index.md §불변식`). Retriever mixin 은 PR-X6-2 이월.

X6 사이클 개시. `index.md §범위 정책` 에 따라 본 사이클은 infra-only —
실 데이터 인입 / 튜닝은 별도 follow-up 으로 분리한다. 본 PR 은 감정
검색의 1단: **저장소 확장**. Retriever (2단) 는 PR-X6-2.

## 범위

### 1. `SessionMemoryEntryModel` — 2개 nullable 컬럼 추가

`backend/service/database/models/session_memory_entry.py`:

- `emotion_vec: Optional[str] = None` — JSON-encoded `list[float]`
  (e.g. `'[0.12, -0.34, ...]'`). 임베더의 차원 수는 모델이 규정하지
  않음 — 저장 시점에 쓰는 쪽이 결정, 읽는 쪽 (PR-X6-2) 이 차원 불일치
  시 fallback.
- `emotion_intensity: Optional[float] = None` — 스칼라 강도 0.0..1.0
  범위 가이드 (강제 아님).

`get_schema()` 엔트리:

```python
"emotion_vec": "TEXT DEFAULT NULL",
"emotion_intensity": "REAL DEFAULT NULL",
```

**왜 nullable + DEFAULT NULL:**
- 기존 행 무변화 — `ALTER TABLE ADD COLUMN` 이 NULL 로 뒷채움.
- NULL 이 "감정 미포착" 을 의미, 0.0 / `[0, 0, ...]` 와 구분됨.
  중립 감정은 향후 follow-up 에서 non-null zero vector 로 명시 가능.
- Retriever (PR-X6-2) 에서 NULL 쪽이 하나라도 있으면 text-only
  ranking 으로 폴백 — `affect-null-safety` 불변식.

**왜 TEXT + JSON (not pgvector / FLOAT8[]):**
- SQLite / PostgreSQL 양쪽 공통 타입. CI 는 SQLite, prod 는 postgres.
- 백엔드별 DDL 분기 없이 `ALTER TABLE ADD COLUMN` 한 줄.
- 성능 튜닝 필요 증명 시 pgvector 전환은 별도 마이그레이션.
  지금은 "있다" 가 중요하지 "빠르다" 가 중요하지 않다.

### 2. `service.affect` — encode/decode 헬퍼

`backend/service/affect/__init__.py` (신규 패키지):

- `encode_emotion_vec(vec: Sequence[float] | None) -> str | None`
- `decode_emotion_vec(raw: str | None) -> list[float] | None`

**설계 노트:**
- **허용적 디코드.** 깨진 JSON / 비리스트 / 비수치 원소 → 모두
  `None` 반환 (예외 없음). 단일 포이즌 레코드가 세션 검색을 죽이지
  않음.
- **Shape 강제 없음.** 차원 검증은 retriever 책임 — 임베더 교체 시
  저장층을 건드리지 않게.
- **빈 시퀀스 = 부재.** `[]` 를 저장하지 않고 `None` 반환 —
  0-dim 벡터는 ranking utility 0.

**왜 `service.affect` 에 두는가 (not `service.memory.affect`):**
- `service.memory.__init__` 는 `VectorMemoryManager` 를 eager import
  하며 numpy 를 끌어온다. CI / 샌드박스 환경에서 numpy 가 없으면
  affect 테스트까지 덩달아 collection 단계에서 죽는다.
- Retriever mixin (PR-X6-2) 도 이 헬퍼를 소비하는데, retriever 는
  `service.memory` 하위가 될 가능성이 높아 circular import 위험.
- `service.affect` 는 stateless 한 직렬화 헬퍼만 들어가는 얇은
  모듈 — pure stdlib, 의존성 최소.

### 3. 테스트

**`backend/tests/service/database/test_session_memory_entry_model.py`**
(6개):
- `test_default_init_leaves_affect_fields_null` — `__init__` 기본값
  NULL.
- `test_affect_fields_round_trip_through_init` — 생성자 대입/조회
  왕복.
- `test_schema_declares_affect_columns_as_nullable_text_and_real` —
  `get_schema()` 출력에 TEXT+NULL / REAL+NULL 포함.
- `test_schema_preserves_all_pre_existing_columns` — 20개 기존 컬럼
  누락 없음 (schema 회귀 방지).
- `test_create_table_query_includes_affect_columns` — postgresql /
  sqlite 양쪽 DDL 에 신규 컬럼 반영.
- `test_affect_columns_cross_backend_types` — `FLOAT8[]` / `VECTOR` /
  `ARRAY` / `DOUBLE PRECISION` 같은 백엔드별 타입 사용 금지 pin.

**`backend/tests/service/affect/test_affect.py`** (11개):
- encode: None pass-through / empty sequence → None / float round-trip
  / int → float coerce.
- decode: None / "" / valid / malformed JSON / non-list JSON /
  non-numeric elements → None; 숫자 문자열 `["1.5"]` → `[1.5]` 허용.

총 17 pass, 0 fail, 0 skip.

## 검증

```
PYTHONPATH=.../Geny pytest backend/tests/service/affect/ \
  backend/tests/service/database/ -q
17 passed in 0.04s
```

기존 표면 회귀 — 인접 디렉터리 (plugin, database 하위) 스위프:

```
backend/tests/service/plugin/ backend/tests/service/database/ \
  backend/tests/service/affect/ → 53 passed
```

`service.memory.__init__` 는 sandbox 환경에서 numpy 부재로
이전부터 collection-fail — 본 PR 무관, `main` 에서도 동일 재현.

## 비범위 (plan/05 §6.3 상속 · index.md §비범위)

- **쓰기 경로 브릿지.** `AffectTagEmitter` (X3 PR-7) 결과가 메모리
  레코드에 실제로 흘러들어가게 하는 wiring — X6-follow-up.
- **Retriever mixin.** PR-X6-2 (`feat/affect-aware-retriever-mixin`).
- **Vector store 메타데이터 확장.** FAISS `ChunkMeta` 감정 차원 — out
  of scope (플랜대로).
- **Prompt cache bucketing / cost dashboard.** 데이터 필요, Defer.

## 불변식 확인

- **Pure additive schema.** ✅ 신규 컬럼 2개 모두 `DEFAULT NULL`,
  기존 INSERT 무수정.
- **기존 SELECT 영향 없음.** ✅ 기존 쿼리는 새 컬럼을 참조하지 않음.
  `SELECT *` 사용처는 있으나 ORM 매핑은 `Optional[str/float]` 필드
  로 자동 수용.
- **백엔드 호환성.** ✅ `TEXT` / `REAL` 은 SQLite / PostgreSQL 둘 다
  네이티브 지원.

## PR-X6-2 인수인계

- `service.affect.decode_emotion_vec` 는 "never raises, returns None
  on any failure" 를 계약으로 확정. Retriever 는 이 계약을 믿고 try
  / except 없이 호출해도 됨.
- `emotion_vec` 이 JSON 리스트라는 내부 포맷은 캡슐화됨 — mixin 은
  `List[float] | None` 만 소비.
- 차원 불일치 / NULL 한쪽 → text-only fallback 원칙은 mixin 구현 시
  본 PR 의 docstring 과 `index.md §불변식` 에 맞출 것.
