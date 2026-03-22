# Database Layer

> psycopg3 ConnectionPool 기반 PostgreSQL 데이터베이스 계층. 모델 기반 자동 테이블 생성, 스키마 마이그레이션, 연결 풀 관리를 제공

## 아키텍처 개요

```
AppDatabaseManager (고수준 ORM 라이크 API)
        │
        ▼
  DatabaseManager (ConnectionPool 관리)
        │
        ▼
  psycopg_pool.ConnectionPool
        │
        ▼
    PostgreSQL
```

모든 저장소(SessionStore, ChatStore, ConfigManager, SessionLogger, Memory)는 **PostgreSQL을 주 저장소, JSON/파일을 백업 저장소**로 사용하는 이중 저장소 전략을 따른다.

---

## 연결 풀 (ConnectionPool)

### 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `POSTGRES_HOST` | `localhost` | 호스트 |
| `POSTGRES_PORT` | `5432` | 포트 |
| `POSTGRES_DB` | `geny` | 데이터베이스 이름 |
| `POSTGRES_USER` | `geny` | 사용자 |
| `POSTGRES_PASSWORD` | `geny123` | 비밀번호 |
| `AUTO_MIGRATION` | `true` | 자동 스키마 마이그레이션 |

### 풀 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DB_POOL_MIN_SIZE` | `2` | 최소 연결 수 |
| `DB_POOL_MAX_SIZE` | `10` | 최대 연결 수 |
| `DB_POOL_MAX_IDLE` | `300` (5분) | 유휴 연결 최대 수명 (초) |
| `DB_POOL_MAX_LIFETIME` | `1800` (30분) | 연결 최대 수명 (초) |
| `DB_POOL_RECONNECT_TIMEOUT` | `300` | 재연결 타임아웃 (초) |
| `DB_POOL_TIMEOUT` | `30` | 연결 획득 타임아웃 (초) |

### 재시도 설정

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DB_MAX_RETRIES` | `3` | 최대 재시도 횟수 |
| `DB_RETRY_DELAY` | `1.0` | 초기 대기 시간 (초) |
| `DB_RETRY_BACKOFF` | `2.0` | 지수 백오프 배수 |

`OperationalError`, `InterfaceError`, `ConnectionError`, `TimeoutError`에 대해 자동 재시도 적용.

---

## DatabaseManager

psycopg3 `ConnectionPool` 관리 클래스.

### 연결 관리

| 메서드 | 설명 |
|--------|------|
| `connect()` | PostgreSQL 연결 풀 생성 (`dict_row` 팩토리) |
| `reconnect()` | 풀 드레인 후 재연결 |
| `disconnect()` | 풀 종료 |
| `health_check(auto_recover)` | `SELECT 1` 실행으로 상태 확인 |
| `get_connection(timeout)` | Context manager로 연결 획득 |
| `get_pool_stats()` | 풀 크기, 가용 연결, 대기 수 반환 |

### 쿼리 실행

| 메서드 | 반환 타입 | 설명 |
|--------|----------|------|
| `execute_query(query, params)` | `List[Dict]` or `None` | SELECT → 행 리스트, 비SELECT → 자동 커밋 |
| `execute_query_one(query, params)` | `Dict` or `None` | 단일 행 반환 |
| `execute_insert(query, params)` | `int` | INSERT → RETURNING id |
| `execute_update_delete(query, params)` | `int` | 영향받은 행 수 |

### 스키마 마이그레이션

`AUTO_MIGRATION=true`일 때 시작 시 자동 실행:

1. 등록된 모델의 `get_schema()` 컬럼과 `information_schema.columns` 비교
2. 누락된 컬럼에 대해 `ALTER TABLE ADD COLUMN IF NOT EXISTS` 실행
3. 기존 데이터 손실 없이 스키마 확장

---

## AppDatabaseManager

모델 기반 고수준 ORM 라이크 래퍼.

### 모델 등록 및 초기화

```python
app_db = AppDatabaseManager()
app_db.register_models(APPLICATION_MODELS)  # 6개 모델 등록
app_db.initialize_database()                # 연결 + 테이블 생성 + 마이그레이션
```

### CRUD 메서드

| 메서드 | 설명 |
|--------|------|
| `insert(model)` | INSERT + RETURNING id |
| `update(model)` | UPDATE by id |
| `delete(model_class, id)` | DELETE by id |
| `delete_by_condition(model_class, conditions)` | 조건부 DELETE |
| `find_by_id(model_class, id)` | id로 조회 |
| `find_all(model_class, limit, offset)` | 전체 조회 (페이지네이션) |
| `find_by_condition(model_class, conditions, ...)` | 조건부 조회 |
| `update_config(config_name, key, value, ...)` | UPSERT (ON CONFLICT) |

### 쿼리 연산자

`find_by_condition`의 `conditions` 딕셔너리에서 사용:

| 연산자 | 예시 | SQL |
|--------|------|------|
| `__like__` | `{"name__like__": "%test%"}` | `name LIKE '%test%'` |
| `__not__` | `{"status__not__": "deleted"}` | `status != 'deleted'` |
| `__gte__` | `{"count__gte__": 5}` | `count >= 5` |
| `__lte__` | `{"count__lte__": 10}` | `count <= 10` |
| `__gt__` / `__lt__` | `{"age__gt__": 18}` | `age > 18` |
| `__in__` | `{"status__in__": ["a","b"]}` | `status IN ('a','b')` |
| `__notin__` | `{"status__notin__": ["x"]}` | `status NOT IN ('x')` |

### 테이블 기반 CRUD

모델 클래스 없이 테이블 이름으로 직접 접근:

```python
app_db.insert_record("my_table", {"col1": "val1"})
app_db.find_records_by_condition("my_table", {"status": "active"})
```

### 인트로스펙션

```python
app_db.get_table_list()              # 전체 테이블 목록
app_db.get_table_schema("sessions")  # 컬럼 정의
app_db.execute_raw_query("SELECT ...")  # 원시 쿼리
```

---

## 데이터베이스 모델 (6개 테이블)

### sessions

세션 메타데이터. `SessionStore`가 관리.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `session_id` | `VARCHAR(255)` UNIQUE | 세션 고유 ID |
| `session_name` | `VARCHAR(500)` | 세션 이름 |
| `status` | `VARCHAR(50)` | starting/running/idle/stopped/error |
| `model` | `VARCHAR(255)` | 사용 모델명 |
| `role` | `VARCHAR(50)` | worker/developer/researcher/planner |
| `workflow_id` | `VARCHAR(255)` | 워크플로우 ID |
| `graph_name` | `VARCHAR(255)` | 그래프 이름 |
| `max_turns` / `timeout` / `max_iterations` | 숫자 | 실행 제한 |
| `pid` | `INTEGER` | 프로세스 ID |
| `is_deleted` / `deleted_at` | BOOLEAN / VARCHAR | 소프트 삭제 |
| `total_cost` | `DOUBLE PRECISION` | 누적 비용 (USD) |
| `extra_data` | `TEXT` (JSON) | 오버플로우 데이터 |

**비용 추적**: `db_increment_session_cost()` — `COALESCE(total_cost, 0) + $1` 원자적 증가.

### persistent_configs

설정값 저장소. `ConfigManager` + `db_config_helper`가 관리.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `config_name` | `VARCHAR(255)` | 설정 그룹명 (e.g. "api") |
| `config_key` | `VARCHAR(255)` | 필드명 (e.g. "anthropic_api_key") |
| `config_value` | `TEXT` | 값 (JSON 직렬화) |
| `data_type` | `VARCHAR(50)` | string/number/boolean/list/dict |
| `category` | `VARCHAR(100)` | 카테고리 |

**UNIQUE**: `(config_name, config_key)` — UPSERT 지원.

### chat_rooms

채팅방 레지스트리.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `room_id` | `VARCHAR(255)` UNIQUE | 방 ID |
| `name` | `VARCHAR(500)` | 방 이름 |
| `session_ids` | `TEXT` | JSON 배열 — 참가 세션 목록 |
| `message_count` | `INTEGER` | 메시지 수 |

### chat_messages

채팅 메시지 이력.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `message_id` | `VARCHAR(255)` UNIQUE | 메시지 UUID |
| `room_id` | `VARCHAR(255)` | 방 ID (FK) |
| `type` | `VARCHAR(50)` | user/agent/system |
| `content` | `TEXT` | 메시지 내용 |
| `session_id` | `VARCHAR(255)` | 발신 세션 ID |
| `session_name` | `VARCHAR(500)` | 발신 세션 이름 |
| `duration_ms` | `INTEGER` | 응답 소요 시간 |

### session_logs

세션별 실행 로그.

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `session_id` | `VARCHAR(255)` | 세션 ID |
| `level` | `VARCHAR(20)` | DEBUG/INFO/WARNING/ERROR/COMMAND/RESPONSE/GRAPH/... |
| `message` | `TEXT` | 로그 메시지 |
| `metadata_json` | `TEXT` | 구조화 메타데이터 (JSON) |
| `log_timestamp` | `VARCHAR(100)` | 로그 시점 |

### session_memory_entries

세션별 메모리 항목 (장기 + 단기).

| 컬럼 | 타입 | 설명 |
|------|------|------|
| `entry_id` | `VARCHAR(255)` UNIQUE | 항목 고유 ID |
| `session_id` | `VARCHAR(255)` | 세션 ID |
| `source` | `VARCHAR(20)` | long_term / short_term |
| `entry_type` | `VARCHAR(30)` | text / message / event / summary |
| `content` | `TEXT` | 내용 |
| `filename` | `VARCHAR(500)` | 출처 파일명 |
| `heading` | `VARCHAR(500)` | 섹션 제목 |
| `topic` | `VARCHAR(255)` | 토픽 슬러그 |
| `role` | `VARCHAR(50)` | user/assistant/system |
| `event_name` | `VARCHAR(100)` | 이벤트 이름 |
| `metadata_json` | `TEXT` | 메타데이터 (JSON) |

---

## 전용 DB 헬퍼

각 도메인에 특화된 SQL 쿼리 함수:

| 헬퍼 | 테이블 | 주요 기능 |
|------|--------|----------|
| `session_db_helper` | `sessions` | register, update, soft_delete, restore, increment_cost |
| `chat_db_helper` | `chat_rooms`, `chat_messages` | create_room, add_message, batch, cascade_delete |
| `session_log_db_helper` | `session_logs` | insert, batch_insert, filtered_query, count, 페이지네이션 |
| `memory_db_helper` | `session_memory_entries` | LTM (append, dated, topic, search), STM (message, event, summary, recent) |
| `db_config_helper` | `persistent_configs` | get/set config, group CRUD, UPSERT |

---

## 마이그레이션

### 스키마 마이그레이션

`AUTO_MIGRATION=true` 시 시작 시 자동 실행. 모델의 `get_schema()` 정의와 실제 DB 컬럼을 비교하여 누락된 컬럼을 추가. 기존 데이터를 파괴하지 않음.

### 데이터 마이그레이션

`config_cleanup.py` — 이중 이스케이프된 JSON 설정값 정리:

```python
# 문제: '"\\"value\\""' → 정상: '"value"'
run_cleanup_migration(app_db)
```

### JSON → DB 마이그레이션

각 저장소(SessionStore, ChatStore)는 `.set_database()` 호출 시 기존 JSON 데이터를 PostgreSQL로 자동 마이그레이션. 이미 존재하는 레코드는 스킵 (멱등).

---

## 시작 순서

```
1. AppDatabaseManager 생성
2. 6개 모델 등록 (register_models)
3. 연결 + 테이블 생성 + 스키마 마이그레이션 (initialize_database)
4. 데이터 마이그레이션 (run_cleanup_migration)
5. ConfigManager에 DB 연결 (set_database)
6. SessionStore에 DB 연결 → JSON 데이터 마이그레이션
7. ChatStore에 DB 연결 → JSON 데이터 마이그레이션
8. SessionLogger에 DB 연결
9. AgentSession 메모리에 DB 전파
```

---

## Config 직렬화 안전장치

`config_serializer.py` — JSON 이중 직렬화 방지:

| 함수 | 설명 |
|------|------|
| `safe_serialize(value, data_type)` | 이미 직렬화된 값의 재직렬화 방지 |
| `safe_deserialize(value, data_type)` | 최대 10단계 깊이까지 재귀 역직렬화 |
| `normalize_config_value(value, data_type)` | 복구 유틸리티 |

---

## 관련 파일

```
service/database/
├── __init__.py                 # 공개 API: AppDatabaseManager, database_config
├── database_config.py          # 환경 변수 기반 DB 설정
├── database_manager.py         # ConnectionPool 관리, 쿼리 실행, 마이그레이션
├── app_database_manager.py     # 고수준 ORM 라이크 CRUD, 모델 등록
├── config_serializer.py        # JSON 직렬화 안전장치
├── db_config_helper.py         # persistent_configs CRUD
├── chat_db_helper.py           # chat_rooms/messages CRUD
├── session_db_helper.py        # sessions CRUD
├── session_log_db_helper.py    # session_logs CRUD
├── memory_db_helper.py         # session_memory_entries CRUD (LTM + STM)
├── migrations/
│   ├── __init__.py
│   └── config_cleanup.py       # 이중 이스케이프 정리 마이그레이션
└── models/
    ├── __init__.py              # APPLICATION_MODELS 리스트
    ├── base_model.py            # BaseModel ABC (get_table_name, get_schema)
    ├── persistent_config.py     # PersistentConfigModel
    ├── session.py               # SessionModel
    ├── chat_room.py             # ChatRoomModel
    ├── chat_message.py          # ChatMessageModel
    ├── session_log.py           # SessionLogModel
    └── session_memory_entry.py  # SessionMemoryEntryModel
```
