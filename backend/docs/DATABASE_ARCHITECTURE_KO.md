# Geny 플랫폼 — 데이터베이스 아키텍처 레퍼런스

> 작성일 2026-03-21 · 데이터베이스 레이어 종합 분석

---

## 1. 개요

Geny는 **PostgreSQL**을 주요 데이터 저장소로 사용하며, **psycopg3** 드라이버를
통해 커넥션 풀링된 `DatabaseManager` 싱글톤으로 접근합니다.
ORM 유사 레이어는 `AppDatabaseManager`가 제공하며, 모델 기반 및 테이블명 기반
CRUD와 함께 자동 재시도, 복구, 스키마 마이그레이션, 커넥션 풀링을 지원합니다.

### 아키텍처 다이어그램

```
┌────────────────────────────────────────────────────────────────┐
│  Controllers (FastAPI)                                          │
│  agent_controller / command_controller / chat_controller        │
└──────────┬────────────────────────────────────────────────┬─────┘
           │                                                │
    ┌──────▼──────────┐                           ┌─────────▼───────┐
    │  DB 헬퍼         │                           │  Session Logger  │
    │  session_db      │                           │  (인메모리 +     │
    │  session_log_db  │                           │   파일 + DB)     │
    │  memory_db       │                           └─────────────────┘
    │  chat_db         │
    │  db_config       │
    └──────┬──────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  AppDatabaseManager                  │
    │  - 모델 기반 CRUD (insert/update/    │
    │    delete/find)                       │
    │  - 자동 테이블 생성                    │
    │  - 자동 마이그레이션 (ALTER TABLE)     │
    │  - 자동 재시도 + 복구                  │
    └──────┬──────────────────────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  DatabaseManager                     │
    │  - psycopg3 ConnectionPool           │
    │  - 헬스 체크 / 재연결                  │
    │  - 스키마 비교 + ALTER TABLE           │
    │  - execute_query / execute_insert /   │
    │    execute_update_delete              │
    └──────┬──────────────────────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  PostgreSQL                          │
    │  (DatabaseConfig 싱글톤 경유)          │
    └─────────────────────────────────────┘
```

---

## 2. 설정

**파일:** `service/database/database_config.py`

| 환경 변수            | 기본값        | 설명                           |
|--------------------|--------------|---------------------------------|
| `POSTGRES_HOST`    | `localhost`  | PostgreSQL 호스트               |
| `POSTGRES_PORT`    | `5432`       | PostgreSQL 포트                 |
| `POSTGRES_DB`      | `geny`       | 데이터베이스 이름                |
| `POSTGRES_USER`    | `geny`       | 데이터베이스 사용자              |
| `POSTGRES_PASSWORD`| `geny123`    | 데이터베이스 비밀번호            |
| `AUTO_MIGRATION`   | `true`       | 자동 스키마 마이그레이션 활성화  |

커넥션 풀 설정 (`DatabaseManager`에서 환경 변수로 설정 가능):

| 환경 변수                    | 기본값  | 설명                              |
|----------------------------|---------|------------------------------------|
| `DB_POOL_MIN_SIZE`         | `2`     | 최소 풀 커넥션 수                   |
| `DB_POOL_MAX_SIZE`         | `10`    | 최대 풀 커넥션 수                   |
| `DB_POOL_MAX_IDLE`         | `300`   | 유휴 커넥션 유지 시간 (초)           |
| `DB_POOL_MAX_LIFETIME`     | `1800`  | 최대 커넥션 수명 (초)               |
| `DB_POOL_RECONNECT_TIMEOUT`| `300`   | 최대 재연결 시도 시간               |
| `DB_POOL_TIMEOUT`          | `30`    | 커넥션 획득 대기 시간               |
| `DB_MAX_RETRIES`           | `3`     | CRUD 재시도 횟수                    |
| `DB_RETRY_DELAY`           | `1.0`   | 초기 재시도 지연 (초)               |
| `DB_RETRY_BACKOFF`         | `2.0`   | 재시도 백오프 배수                   |

**싱글톤:** 모듈 레벨에서 `database_config = DatabaseConfig()`.

---

## 3. Database Manager 레이어

### 3.1 DatabaseManager (`service/database/database_manager.py`)

저수준 커넥션 풀 관리자. 주요 책임:

1. **커넥션 풀** — 설정 가능한 min/max 크기, 유휴 타임아웃, 수명, 재연결을 갖춘
   `psycopg_pool.ConnectionPool`.
2. **헬스 체크** — `_check_connection()` 콜백이 `SELECT 1`로 커넥션 검증.
3. **커넥션 생명주기** — `_configure_connection()`으로 타임존 설정,
   `_reset_connection()`으로 더러운 트랜잭션 롤백.
4. **쿼리 실행:**
   - `execute_query(sql, params)` → `List[Dict]` (SELECT)
   - `execute_query_one(sql, params)` → `Dict | None`
   - `execute_insert(sql, params)` → `int` (ID 반환)
   - `execute_update_delete(sql, params)` → `int` (영향받은 행 수)
5. **스키마 마이그레이션** — `run_migrations(models_registry)`:
   - 각 모델별: `get_schema()` 대비 실제 DB 컬럼 비교
   - 누락된 컬럼에 대해 `ALTER TABLE ADD COLUMN IF NOT EXISTS`
   - **참고:** 컬럼 추가만 지원하며, 이름 변경/삭제/타입 변경은 미지원
6. **재시도 데코레이터** — 커넥션 오류 시 지수 백오프를 위한 `@with_retry`

**싱글톤:** `get_database_manager()`가 모듈 레벨 `_db_manager` 반환.

### 3.2 AppDatabaseManager (`service/database/app_database_manager.py`)

`DatabaseManager` 위에 구축된 고수준 ORM 유사 인터페이스.

**초기화 흐름:**
```
register_models(APPLICATION_MODELS)
  → initialize_database(create_tables=True)
    → connect()
    → create_tables()     # 각 모델에 대해 CREATE TABLE IF NOT EXISTS
    → run_migrations()    # 누락 컬럼에 대해 ALTER TABLE ADD COLUMN
```

**모델 기반 CRUD:**
- `insert(model)` → 모델로부터 INSERT 생성, `{"result": "success", "id": N}` 반환
- `update(model)` → ID 기반 UPDATE 생성
- `delete(model_class, id)` → ID 기반 DELETE
- `delete_by_condition(model_class, conditions)` → WHERE 조건 DELETE
- `find_by_id(model_class, id)` → 단일 모델 인스턴스
- `find_all(model_class, limit, offset)` → 페이지네이션된 목록
- `find_by_condition(model_class, conditions, ...)` → 필터링된 목록

**쿼리 연산자** (조건 키의 접미사):
- `__like__`, `__notlike__`, `__not__`
- `__gte__`, `__lte__`, `__gt__`, `__lt__`
- `__in__`, `__notin__`

**자동 복구:** 모든 CRUD가 `_with_auto_recovery()`로 래핑 — 커넥션 관련
예외 시 지수 백오프로 재시도, 자동 재연결.

---

## 4. 모델 시스템

### 4.1 BaseModel (`service/database/models/base_model.py`)

모든 DB 모델의 추상 베이스 클래스. 서브클래스가 정의해야 할 항목:

- `get_table_name() → str` — 테이블 이름
- `get_schema() → Dict[str, str]` — 컬럼 정의 (이름 → SQL 타입)
- `get_indexes() → List[tuple]` — 선택적 인덱스 정의

**자동 생성 기능:**
- `get_create_table_query(db_type)` — `id SERIAL PRIMARY KEY`, `created_at`,
  `updated_at` 자동 컬럼이 포함된 `CREATE TABLE IF NOT EXISTS`
- `get_insert_query(db_type)` — 파라미터화된 INSERT
- `get_update_query(db_type)` — ID 기반 파라미터화된 UPDATE
- `to_dict()` / `from_dict()` — 직렬화
- `now()` — 타임존 인식 현재 시각

### 4.2 모델 레지스트리

**파일:** `service/database/models/__init__.py`

```python
APPLICATION_MODELS = [
    PersistentConfigModel,
    SessionModel,
    ChatRoomModel,
    ChatMessageModel,
    SessionLogModel,
    SessionMemoryEntryModel,
]
```

**새 모델 추가 방법:**
1. `service/database/models/my_model.py`에서 `BaseModel` 상속하여 생성
2. `get_table_name()`, `get_schema()` 구현, 선택적으로 `get_indexes()`
3. `__init__.py`에서 임포트하고 `APPLICATION_MODELS`에 추가
4. 다음 시작 시: 테이블 자동 생성 + 자동 마이그레이션

### 4.3 현재 테이블

#### `sessions` (SessionModel)

| 컬럼             | 타입                    | 기본값         |
|-----------------|------------------------|---------------|
| id              | SERIAL PRIMARY KEY     | auto          |
| session_id      | VARCHAR(255) NOT NULL  | UNIQUE        |
| session_name    | VARCHAR(500)           | ''            |
| status          | VARCHAR(50)            | 'starting'    |
| model           | VARCHAR(255)           | ''            |
| storage_path    | TEXT                   | ''            |
| role            | VARCHAR(50)            | 'worker'      |
| workflow_id     | VARCHAR(255)           | ''            |
| graph_name      | VARCHAR(255)           | ''            |
| max_turns       | INTEGER                | 100           |
| timeout         | DOUBLE PRECISION       | 1800.0        |
| max_iterations  | INTEGER                | 100           |
| pid             | INTEGER                | 0             |
| error_message   | TEXT                   | ''            |
| is_deleted      | BOOLEAN                | FALSE         |
| deleted_at      | VARCHAR(100)           | ''            |
| registered_at   | VARCHAR(100)           | ''            |
| extra_data      | TEXT                   | ''            |
| created_at      | TIMESTAMP WITH TZ      | auto          |
| updated_at      | TIMESTAMP WITH TZ      | auto          |

**인덱스:** session_id, status, role, is_deleted

**`extra_data` JSON blob:** `_COLUMN_FIELDS` 집합에 없는 필드는
`_split_fields()`를 통해 `extra_data`에 JSON 직렬화됩니다 (쓰기 시).
읽기 시 JSON이 최상위 키로 병합됩니다 (`_merge_extra()`).

#### `session_logs` (SessionLogModel)

| 컬럼            | 타입                    | 기본값  |
|----------------|------------------------|--------|
| id             | SERIAL PRIMARY KEY      | auto   |
| session_id     | VARCHAR(255) NOT NULL   |        |
| level          | VARCHAR(20) NOT NULL    | 'INFO' |
| message        | TEXT                    | ''     |
| metadata_json  | TEXT                    | '{}'   |
| log_timestamp  | VARCHAR(100)            | ''     |
| created_at     | TIMESTAMP WITH TZ       | auto   |
| updated_at     | TIMESTAMP WITH TZ       | auto   |

**인덱스:** session_id, level, log_timestamp, (session_id, level) 복합

#### `session_memory_entries` (SessionMemoryEntryModel)

| 컬럼              | 타입                    | 기본값        |
|------------------|------------------------|--------------|
| id               | SERIAL PRIMARY KEY      | auto         |
| entry_id         | VARCHAR(255) NOT NULL   | UNIQUE       |
| session_id       | VARCHAR(255) NOT NULL   |              |
| source           | VARCHAR(20) NOT NULL    | 'long_term'  |
| entry_type       | VARCHAR(30) NOT NULL    | 'text'       |
| content          | TEXT                    | ''           |
| filename         | VARCHAR(500)            | ''           |
| heading          | VARCHAR(500)            | ''           |
| topic            | VARCHAR(255)            | ''           |
| role             | VARCHAR(50)             | ''           |
| event_name       | VARCHAR(100)            | ''           |
| metadata_json    | TEXT                    | '{}'         |
| entry_timestamp  | VARCHAR(100)            | ''           |
| created_at       | TIMESTAMP WITH TZ       | auto         |
| updated_at       | TIMESTAMP WITH TZ       | auto         |

**인덱스:** session_id, source, entry_type, (session_id, source) 복합, role, entry_timestamp

#### `persistent_configs` (PersistentConfigModel)

UPSERT를 지원하는 키-값 설정 저장소.

#### `chat_rooms` (ChatRoomModel)

멀티 에이전트 협업을 위한 채팅방 메타데이터.

#### `chat_messages` (ChatMessageModel)

채팅방 내 개별 채팅 메시지.

---

## 5. DB 헬퍼 모듈

### 5.1 session_db_helper.py

모델 ORM 레이어를 거치지 않고 세션 CRUD를 제공합니다 (성능 및 UPSERT
유연성을 위해 원시 SQL 사용).

**핵심 설계:** `_COLUMN_FIELDS` 집합이 전용 컬럼에 매핑되는 필드를 정의합니다.
나머지는 쓰기 시 `_split_fields()`를 통해 `extra_data`에 JSON 병합되고,
읽기 시 `_merge_extra()`로 복원됩니다.

| 함수                              | 설명                                    |
|----------------------------------|----------------------------------------|
| `db_register_session()`          | UPSERT (INSERT ON CONFLICT DO UPDATE)  |
| `db_update_session()`            | extra_data 병합을 포함한 부분 UPDATE       |
| `db_soft_delete_session()`       | is_deleted=True, status=stopped 설정     |
| `db_restore_session()`           | is_deleted=False 설정                    |
| `db_permanent_delete_session()`  | 행 DELETE                               |
| `db_get_session()`               | session_id 기반 SELECT                  |
| `db_list_active_sessions()`      | is_deleted=FALSE인 세션 SELECT           |
| `db_list_deleted_sessions()`     | is_deleted=TRUE인 세션 SELECT            |
| `db_session_exists()`            | EXISTS 확인                              |
| `db_migrate_sessions_from_json()`| sessions.json에서 일괄 마이그레이션        |
