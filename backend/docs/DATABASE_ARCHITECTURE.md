# Geny Platform — Database Architecture Reference

> Generated 2026-03-21 · Comprehensive analysis of the database layer

---

## 1. Overview

Geny uses **PostgreSQL** as its primary data store, accessed via the
**psycopg3** driver through a connection-pooled `DatabaseManager` singleton.
The ORM-like layer is provided by `AppDatabaseManager`, which supports
model-based and table-name-based CRUD with automatic retry, recovery,
schema migration, and connection pooling.

### Architecture Diagram

```
┌────────────────────────────────────────────────────────────────┐
│  Controllers (FastAPI)                                          │
│  agent_controller / command_controller / chat_controller        │
└──────────┬────────────────────────────────────────────────┬─────┘
           │                                                │
    ┌──────▼──────────┐                           ┌─────────▼───────┐
    │  DB Helpers      │                           │  Session Logger  │
    │  session_db      │                           │  (in-memory +   │
    │  session_log_db  │                           │   file + DB)    │
    │  memory_db       │                           └─────────────────┘
    │  chat_db         │
    │  db_config       │
    └──────┬──────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  AppDatabaseManager                  │
    │  - Model-based CRUD (insert/update/  │
    │    delete/find)                       │
    │  - Auto table creation               │
    │  - Auto migration (ALTER TABLE)      │
    │  - Auto retry + recovery             │
    └──────┬──────────────────────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  DatabaseManager                     │
    │  - psycopg3 ConnectionPool           │
    │  - Health checks / reconnection      │
    │  - Schema diff + ALTER TABLE         │
    │  - execute_query / execute_insert /   │
    │    execute_update_delete              │
    └──────┬──────────────────────────────┘
           │
    ┌──────▼──────────────────────────────┐
    │  PostgreSQL                          │
    │  (via DatabaseConfig singleton)      │
    └─────────────────────────────────────┘
```

---

## 2. Configuration

**File:** `service/database/database_config.py`

| Env Variable       | Default       | Description                    |
|-------------------|---------------|--------------------------------|
| `POSTGRES_HOST`   | `localhost`   | PostgreSQL host                |
| `POSTGRES_PORT`   | `5432`        | PostgreSQL port                |
| `POSTGRES_DB`     | `geny`        | Database name                  |
| `POSTGRES_USER`   | `geny`        | Database user                  |
| `POSTGRES_PASSWORD`| `geny123`    | Database password              |
| `AUTO_MIGRATION`  | `true`        | Enable auto schema migration   |

Connection pool settings (env-configurable in `DatabaseManager`):

| Env Variable             | Default | Description                         |
|-------------------------|---------|-------------------------------------|
| `DB_POOL_MIN_SIZE`      | `2`     | Minimum pool connections            |
| `DB_POOL_MAX_SIZE`      | `10`    | Maximum pool connections            |
| `DB_POOL_MAX_IDLE`      | `300`   | Idle connection retention (seconds) |
| `DB_POOL_MAX_LIFETIME`  | `1800`  | Max connection lifetime (seconds)   |
| `DB_POOL_RECONNECT_TIMEOUT` | `300` | Max reconnection attempt time     |
| `DB_POOL_TIMEOUT`       | `30`    | Connection acquisition wait time    |
| `DB_MAX_RETRIES`        | `3`     | CRUD retry count                    |
| `DB_RETRY_DELAY`        | `1.0`   | Initial retry delay (seconds)       |
| `DB_RETRY_BACKOFF`      | `2.0`   | Retry backoff multiplier            |

**Singleton:** `database_config = DatabaseConfig()` at module level.

---

## 3. Database Manager Layer

### 3.1 DatabaseManager (`service/database/database_manager.py`)

Low-level connection pool manager. Key responsibilities:

1. **Connection Pool** — `psycopg_pool.ConnectionPool` with configurable
   min/max size, idle timeout, lifetime, reconnection.
2. **Health Checks** — `_check_connection()` callback validates connections
   with `SELECT 1`.
3. **Connection Lifecycle** — `_configure_connection()` sets timezone,
   `_reset_connection()` rolls back dirty transactions.
4. **Query Execution:**
   - `execute_query(sql, params)` → `List[Dict]` (SELECT)
   - `execute_query_one(sql, params)` → `Dict | None`
   - `execute_insert(sql, params)` → `int` (returns ID)
   - `execute_update_delete(sql, params)` → `int` (affected rows)
5. **Schema Migration** — `run_migrations(models_registry)`:
   - For each model: compare `get_schema()` vs actual DB columns
   - `ALTER TABLE ADD COLUMN IF NOT EXISTS` for any missing columns
   - **Note:** Only supports ADDING columns, not renaming/removing/altering types
6. **Retry Decorator** — `@with_retry` for exponential backoff on connection errors

**Singleton:** `get_database_manager()` returns module-level `_db_manager`.

### 3.2 AppDatabaseManager (`service/database/app_database_manager.py`)

High-level ORM-like interface built on top of `DatabaseManager`.

**Initialization Flow:**
```
register_models(APPLICATION_MODELS)
  → initialize_database(create_tables=True)
    → connect()
    → create_tables()     # CREATE TABLE IF NOT EXISTS for each model
    → run_migrations()    # ALTER TABLE ADD COLUMN for missing columns
```

**Model-based CRUD:**
- `insert(model)` → generates INSERT from model, returns `{"result": "success", "id": N}`
- `update(model)` → generates UPDATE by ID
- `delete(model_class, id)` → DELETE by ID
- `delete_by_condition(model_class, conditions)` → DELETE by WHERE
- `find_by_id(model_class, id)` → single model instance
- `find_all(model_class, limit, offset)` → paginated list
- `find_by_condition(model_class, conditions, ...)` → filtered list

**Query Operators** (suffix on condition keys):
- `__like__`, `__notlike__`, `__not__`
- `__gte__`, `__lte__`, `__gt__`, `__lt__`
- `__in__`, `__notin__`

**Auto-recovery:** All CRUD wrapped in `_with_auto_recovery()` — retries
with exponential backoff on connection-related exceptions, auto-reconnects.

---

## 4. Model System

### 4.1 BaseModel (`service/database/models/base_model.py`)

Abstract base class for all DB models. Subclasses define:

- `get_table_name() → str` — table name
- `get_schema() → Dict[str, str]` — column definitions (name → SQL type)
- `get_indexes() → List[tuple]` — optional index definitions

**Auto-generated features:**
- `get_create_table_query(db_type)` — `CREATE TABLE IF NOT EXISTS` with
  `id SERIAL PRIMARY KEY`, `created_at`, `updated_at` auto-columns
- `get_insert_query(db_type)` — parameterized INSERT
- `get_update_query(db_type)` — parameterized UPDATE by ID
- `to_dict()` / `from_dict()` — serialization
- `now()` — timezone-aware current time

### 4.2 Model Registry

**File:** `service/database/models/__init__.py`

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

**How to add a new model:**
1. Create `service/database/models/my_model.py` inheriting `BaseModel`
2. Implement `get_table_name()`, `get_schema()`, optionally `get_indexes()`
3. Import in `__init__.py` and add to `APPLICATION_MODELS`
4. On next startup: table auto-created + auto-migrated

### 4.3 Current Tables

#### `sessions` (SessionModel)

| Column          | Type                    | Default       |
|----------------|-----------------------|---------------|
| id             | SERIAL PRIMARY KEY     | auto          |
| session_id     | VARCHAR(255) NOT NULL  | UNIQUE        |
| session_name   | VARCHAR(500)           | ''            |
| status         | VARCHAR(50)            | 'starting'    |
| model          | VARCHAR(255)           | ''            |
| storage_path   | TEXT                   | ''            |
| role           | VARCHAR(50)            | 'worker'      |
| workflow_id    | VARCHAR(255)           | ''            |
| graph_name     | VARCHAR(255)           | ''            |
| max_turns      | INTEGER                | 100           |
| timeout        | DOUBLE PRECISION       | 1800.0        |
| max_iterations | INTEGER                | 100           |
| pid            | INTEGER                | 0             |
| error_message  | TEXT                   | ''            |
| is_deleted     | BOOLEAN                | FALSE         |
| deleted_at     | VARCHAR(100)           | ''            |
| registered_at  | VARCHAR(100)           | ''            |
| extra_data     | TEXT                   | ''            |
| created_at     | TIMESTAMP WITH TZ      | auto          |
| updated_at     | TIMESTAMP WITH TZ      | auto          |

**Indexes:** session_id, status, role, is_deleted

**`extra_data` JSON blob:** Any field not in `_COLUMN_FIELDS` set
(defined in `session_db_helper.py`) gets JSON-serialized into `extra_data`.
On read, the JSON is merged back into top-level keys (`_merge_extra()`).

#### `session_logs` (SessionLogModel)

| Column         | Type                    | Default |
|---------------|------------------------|---------|
| id            | SERIAL PRIMARY KEY      | auto    |
| session_id    | VARCHAR(255) NOT NULL   |         |
| level         | VARCHAR(20) NOT NULL    | 'INFO'  |
| message       | TEXT                    | ''      |
| metadata_json | TEXT                    | '{}'    |
| log_timestamp | VARCHAR(100)            | ''      |
| created_at    | TIMESTAMP WITH TZ       | auto    |
| updated_at    | TIMESTAMP WITH TZ       | auto    |

**Indexes:** session_id, level, log_timestamp, (session_id, level) composite

#### `session_memory_entries` (SessionMemoryEntryModel)

| Column          | Type                    | Default      |
|----------------|------------------------|-------------|
| id             | SERIAL PRIMARY KEY      | auto         |
| entry_id       | VARCHAR(255) NOT NULL   | UNIQUE       |
| session_id     | VARCHAR(255) NOT NULL   |              |
| source         | VARCHAR(20) NOT NULL    | 'long_term'  |
| entry_type     | VARCHAR(30) NOT NULL    | 'text'       |
| content        | TEXT                    | ''           |
| filename       | VARCHAR(500)            | ''           |
| heading        | VARCHAR(500)            | ''           |
| topic          | VARCHAR(255)            | ''           |
| role           | VARCHAR(50)             | ''           |
| event_name     | VARCHAR(100)            | ''           |
| metadata_json  | TEXT                    | '{}'         |
| entry_timestamp| VARCHAR(100)            | ''           |
| created_at     | TIMESTAMP WITH TZ       | auto         |
| updated_at     | TIMESTAMP WITH TZ       | auto         |

**Indexes:** session_id, source, entry_type, (session_id, source) composite, role, entry_timestamp

#### `persistent_configs` (PersistentConfigModel)

Key-value configuration store with UPSERT support.

#### `chat_rooms` (ChatRoomModel)

Chat room metadata for multi-agent collaboration.

#### `chat_messages` (ChatMessageModel)

Individual chat messages within rooms.

---

## 5. DB Helper Modules

### 5.1 session_db_helper.py

Provides session CRUD without going through the model ORM layer (uses
raw SQL for performance and UPSERT flexibility).

**Key Design:** `_COLUMN_FIELDS` set defines which fields map to dedicated
columns. Everything else is JSON-merged into `extra_data` via `_split_fields()`
on write and `_merge_extra()` on read.

| Function                         | Description                              |
|---------------------------------|------------------------------------------|
| `db_register_session()`         | UPSERT (INSERT ON CONFLICT DO UPDATE)    |
| `db_update_session()`           | Partial UPDATE with extra_data merge     |
| `db_soft_delete_session()`      | Set is_deleted=True, status=stopped      |
| `db_restore_session()`          | Set is_deleted=False                     |
| `db_permanent_delete_session()` | DELETE row                               |
| `db_get_session()`              | SELECT by session_id                     |
| `db_list_active_sessions()`     | SELECT WHERE is_deleted=FALSE            |
| `db_list_deleted_sessions()`    | SELECT WHERE is_deleted=TRUE             |
| `db_session_exists()`           | EXISTS check                             |
| `db_migrate_sessions_from_json()`| Bulk migrate from sessions.json         |

### 5.2 session_log_db_helper.py

| Function                         | Description                              |
|---------------------------------|------------------------------------------|
| `db_insert_log_entry()`         | Single log entry INSERT                  |
| `db_insert_log_entries_batch()` | Batch INSERT (loop-based)                |
| `db_get_session_logs()`         | Paginated SELECT with level filter       |
| `db_count_session_logs()`       | COUNT for pagination                     |
| `db_list_session_log_summaries()` | GROUP BY session_id summary            |
| `db_session_has_logs()`         | EXISTS check                             |
| `db_delete_session_logs()`      | DELETE all logs for session              |

### 5.3 memory_db_helper.py

| Function                   | Description                              |
|---------------------------|------------------------------------------|
| `db_ltm_append()`         | Long-term memory text entry              |
| `db_ltm_write_dated()`    | Dated LTM entry (memory/YYYY-MM-DD.md)   |
| `db_ltm_write_topic()`    | Topic-specific LTM entry                 |
| `db_ltm_load_all()`       | Load all LTM for a session               |
| `db_ltm_load_dated()`     | Load by date range                       |
| `db_stm_append_message()` | Short-term memory message                |
| `db_stm_append_event()`   | Short-term memory event                  |
| `db_stm_load_recent()`    | Load recent STM entries                  |

### 5.4 chat_db_helper.py

Chat room and message persistence (not relevant to cost tracking).

### 5.5 db_config_helper.py

Config CRUD using `persistent_configs` table with UPSERT.

---

## 6. Migration System

### Automatic Migration (Schema Diff)

When `AUTO_MIGRATION=true` (default), on startup:

1. `AppDatabaseManager.initialize_database()` calls `run_migrations()`
2. `DatabaseManager._run_schema_migrations(models_registry)`:
   - For each registered model:
     - Gets expected schema from `model.get_schema()`
     - Gets actual columns from `information_schema.columns`
     - Identifies missing columns
     - Executes `ALTER TABLE ADD COLUMN IF NOT EXISTS` for each
3. **Only supports adding columns** — does not handle:
   - Column removal
   - Type changes
   - Constraint modifications
   - Data migration

### Manual Migration

**File:** `service/database/migrations/config_cleanup.py`

Contains `cleanup_escaped_configs()` — a data-fix migration for
double-escaped JSON in `persistent_configs`.

### Migration Pattern for New Features

To add new columns to an existing table:

1. Add column to the model's `get_schema()` dict
2. If the column field is used by DB helpers, add it to `_COLUMN_FIELDS`
3. Restart the server — auto-migration runs `ALTER TABLE ADD COLUMN`
4. No manual SQL needed

---

## 7. Startup Initialization Flow

**File:** `main.py` (lifespan)

```python
# 1. Create AppDatabaseManager
app_db = AppDatabaseManager()

# 2. Register all application models
app_db.register_models(APPLICATION_MODELS)

# 3. Initialize (connect + create tables + auto-migrate)
app_db.initialize_database()

# 4. Set DB reference for session logging
set_log_database(app_db)

# 5. Migrate sessions from legacy JSON if needed
db_migrate_sessions_from_json(app_db, json_data)
```

---

## 8. Key Design Patterns

### 8.1 extra_data JSON Blob

The `sessions` table uses an `extra_data TEXT` column as an overflow
JSON store. Any field not in the predefined `_COLUMN_FIELDS` set is
transparently serialized into `extra_data` on write and merged back on
read. This allows adding new metadata without schema changes.

**Trade-off:** Fields in `extra_data` cannot be indexed or queried
efficiently. Frequently queried fields should be promoted to dedicated
columns.

### 8.2 Dual Write (Logger)

`SessionLogger._write_entry()` writes to:
1. File (`logs/{session_id}.log`) — always
2. In-memory cache (`_log_cache`) — always
3. Database (`session_logs` table) — when DB available

### 8.3 Graceful Degradation

All DB helpers check `_is_db_available()` before operations and return
safe defaults (`False`, `None`, `[]`) when DB is unavailable. The
application continues to function with file-based storage as fallback.

---

## 9. Current Gaps (Relevant to Cost Tracking)

1. **No cost columns in `sessions` table** — cost data is not persisted
   in the DB at all.
2. **`extra_data` does not contain cost** — nothing writes cost info to
   the sessions table.
3. **No dedicated cost table** — no aggregation or history table exists.
4. **Auto-migration only adds columns** — sufficient for adding
   `total_cost` to `sessions`, but a separate cost history table would
   need to be registered as a new model.
