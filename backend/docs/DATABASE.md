# Database Layer

> PostgreSQL database layer based on psycopg3 ConnectionPool. Provides model-based auto table creation, schema migration, and connection pool management

## Architecture Overview

```
AppDatabaseManager (high-level ORM-like API)
        │
        ▼
  DatabaseManager (ConnectionPool management)
        │
        ▼
  psycopg_pool.ConnectionPool
        │
        ▼
    PostgreSQL
```

All stores (SessionStore, ChatStore, ConfigManager, SessionLogger, Memory) follow a **dual storage strategy**: PostgreSQL as primary, JSON/files as backup.

---

## Connection Pool

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | Host |
| `POSTGRES_PORT` | `5432` | Port |
| `POSTGRES_DB` | `geny` | Database name |
| `POSTGRES_USER` | `geny` | User |
| `POSTGRES_PASSWORD` | `geny123` | Password |
| `AUTO_MIGRATION` | `true` | Auto schema migration |

### Pool Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_MIN_SIZE` | `2` | Minimum connections |
| `DB_POOL_MAX_SIZE` | `10` | Maximum connections |
| `DB_POOL_MAX_IDLE` | `300` (5min) | Max idle connection lifetime (seconds) |
| `DB_POOL_MAX_LIFETIME` | `1800` (30min) | Max connection lifetime (seconds) |
| `DB_POOL_RECONNECT_TIMEOUT` | `300` | Reconnect timeout (seconds) |
| `DB_POOL_TIMEOUT` | `30` | Connection acquire timeout (seconds) |

### Retry Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_MAX_RETRIES` | `3` | Maximum retry count |
| `DB_RETRY_DELAY` | `1.0` | Initial wait time (seconds) |
| `DB_RETRY_BACKOFF` | `2.0` | Exponential backoff multiplier |

Automatic retry on `OperationalError`, `InterfaceError`, `ConnectionError`, `TimeoutError`.

---

## DatabaseManager

psycopg3 `ConnectionPool` management class.

### Connection Management

| Method | Description |
|--------|-------------|
| `connect()` | Create PostgreSQL connection pool (`dict_row` factory) |
| `reconnect()` | Drain pool and reconnect |
| `disconnect()` | Close pool |
| `health_check(auto_recover)` | Run `SELECT 1` to verify connectivity |
| `get_connection(timeout)` | Context manager for acquiring connections |
| `get_pool_stats()` | Pool size, available connections, waiters |

### Query Execution

| Method | Return Type | Description |
|--------|-------------|-------------|
| `execute_query(query, params)` | `List[Dict]` or `None` | SELECT → row list, non-SELECT → auto-commit |
| `execute_query_one(query, params)` | `Dict` or `None` | Single row return |
| `execute_insert(query, params)` | `int` | INSERT → RETURNING id |
| `execute_update_delete(query, params)` | `int` | Affected row count |

### Schema Migration

Runs automatically at startup when `AUTO_MIGRATION=true`:

1. Compare registered model `get_schema()` columns with `information_schema.columns`
2. Execute `ALTER TABLE ADD COLUMN IF NOT EXISTS` for missing columns
3. Extends schema without data loss

---

## AppDatabaseManager

Model-based high-level ORM-like wrapper.

### Model Registration & Initialization

```python
app_db = AppDatabaseManager()
app_db.register_models(APPLICATION_MODELS)  # Register 6 models
app_db.initialize_database()                # Connect + create tables + migration
```

### CRUD Methods

| Method | Description |
|--------|-------------|
| `insert(model)` | INSERT + RETURNING id |
| `update(model)` | UPDATE by id |
| `delete(model_class, id)` | DELETE by id |
| `delete_by_condition(model_class, conditions)` | Conditional DELETE |
| `find_by_id(model_class, id)` | Find by id |
| `find_all(model_class, limit, offset)` | Find all (pagination) |
| `find_by_condition(model_class, conditions, ...)` | Conditional query |
| `update_config(config_name, key, value, ...)` | UPSERT (ON CONFLICT) |

### Query Operators

Used in `find_by_condition` `conditions` dictionary:

| Operator | Example | SQL |
|----------|---------|-----|
| `__like__` | `{"name__like__": "%test%"}` | `name LIKE '%test%'` |
| `__not__` | `{"status__not__": "deleted"}` | `status != 'deleted'` |
| `__gte__` | `{"count__gte__": 5}` | `count >= 5` |
| `__lte__` | `{"count__lte__": 10}` | `count <= 10` |
| `__gt__` / `__lt__` | `{"age__gt__": 18}` | `age > 18` |
| `__in__` | `{"status__in__": ["a","b"]}` | `status IN ('a','b')` |
| `__notin__` | `{"status__notin__": ["x"]}` | `status NOT IN ('x')` |

### Table-Based CRUD

Direct access by table name without model classes:

```python
app_db.insert_record("my_table", {"col1": "val1"})
app_db.find_records_by_condition("my_table", {"status": "active"})
```

### Introspection

```python
app_db.get_table_list()              # All table names
app_db.get_table_schema("sessions")  # Column definitions
app_db.execute_raw_query("SELECT ...")  # Raw query
```

---

## Database Models (6 Tables)

### sessions

Session metadata. Managed by `SessionStore`.

| Column | Type | Description |
|--------|------|-------------|
| `session_id` | `VARCHAR(255)` UNIQUE | Unique session ID |
| `session_name` | `VARCHAR(500)` | Session name |
| `status` | `VARCHAR(50)` | starting/running/idle/stopped/error |
| `model` | `VARCHAR(255)` | Model name |
| `role` | `VARCHAR(50)` | worker/developer/researcher/planner |
| `workflow_id` | `VARCHAR(255)` | Workflow ID |
| `graph_name` | `VARCHAR(255)` | Graph name |
| `max_turns` / `timeout` / `max_iterations` | numeric | Execution limits |
| `pid` | `INTEGER` | Process ID |
| `is_deleted` / `deleted_at` | BOOLEAN / VARCHAR | Soft delete |
| `total_cost` | `DOUBLE PRECISION` | Accumulated cost (USD) |
| `extra_data` | `TEXT` (JSON) | Overflow data |

**Cost tracking**: `db_increment_session_cost()` — `COALESCE(total_cost, 0) + $1` atomic increment.

### persistent_configs

Configuration value storage. Managed by `ConfigManager` + `db_config_helper`.

| Column | Type | Description |
|--------|------|-------------|
| `config_name` | `VARCHAR(255)` | Config group name (e.g. "api") |
| `config_key` | `VARCHAR(255)` | Field name (e.g. "anthropic_api_key") |
| `config_value` | `TEXT` | Value (JSON serialized) |
| `data_type` | `VARCHAR(50)` | string/number/boolean/list/dict |
| `category` | `VARCHAR(100)` | Category |

**UNIQUE**: `(config_name, config_key)` — supports UPSERT.

### chat_rooms

Chat room registry.

| Column | Type | Description |
|--------|------|-------------|
| `room_id` | `VARCHAR(255)` UNIQUE | Room ID |
| `name` | `VARCHAR(500)` | Room name |
| `session_ids` | `TEXT` | JSON array — participant session list |
| `message_count` | `INTEGER` | Message count |

### chat_messages

Chat message history.

| Column | Type | Description |
|--------|------|-------------|
| `message_id` | `VARCHAR(255)` UNIQUE | Message UUID |
| `room_id` | `VARCHAR(255)` | Room ID (FK) |
| `type` | `VARCHAR(50)` | user/agent/system |
| `content` | `TEXT` | Message content |
| `session_id` | `VARCHAR(255)` | Sender session ID |
| `session_name` | `VARCHAR(500)` | Sender session name |
| `duration_ms` | `INTEGER` | Response duration |

### session_logs

Per-session execution logs.

| Column | Type | Description |
|--------|------|-------------|
| `session_id` | `VARCHAR(255)` | Session ID |
| `level` | `VARCHAR(20)` | DEBUG/INFO/WARNING/ERROR/COMMAND/RESPONSE/GRAPH/... |
| `message` | `TEXT` | Log message |
| `metadata_json` | `TEXT` | Structured metadata (JSON) |
| `log_timestamp` | `VARCHAR(100)` | Log timestamp |

### session_memory_entries

Per-session memory entries (long-term + short-term).

| Column | Type | Description |
|--------|------|-------------|
| `entry_id` | `VARCHAR(255)` UNIQUE | Unique entry ID |
| `session_id` | `VARCHAR(255)` | Session ID |
| `source` | `VARCHAR(20)` | long_term / short_term |
| `entry_type` | `VARCHAR(30)` | text / message / event / summary |
| `content` | `TEXT` | Content |
| `filename` | `VARCHAR(500)` | Source filename |
| `heading` | `VARCHAR(500)` | Section heading |
| `topic` | `VARCHAR(255)` | Topic slug |
| `role` | `VARCHAR(50)` | user/assistant/system |
| `event_name` | `VARCHAR(100)` | Event name |
| `metadata_json` | `TEXT` | Metadata (JSON) |

---

## Dedicated DB Helpers

Domain-specific SQL query functions:

| Helper | Table | Key Functions |
|--------|-------|---------------|
| `session_db_helper` | `sessions` | register, update, soft_delete, restore, increment_cost |
| `chat_db_helper` | `chat_rooms`, `chat_messages` | create_room, add_message, batch, cascade_delete |
| `session_log_db_helper` | `session_logs` | insert, batch_insert, filtered_query, count, pagination |
| `memory_db_helper` | `session_memory_entries` | LTM (append, dated, topic, search), STM (message, event, summary, recent) |
| `db_config_helper` | `persistent_configs` | get/set config, group CRUD, UPSERT |

---

## Migrations

### Schema Migration

Runs automatically at startup when `AUTO_MIGRATION=true`. Compares model `get_schema()` definitions with actual DB columns and adds missing columns. Non-destructive to existing data.

### Data Migration

`config_cleanup.py` — Cleans double-escaped JSON config values:

```python
# Problem: '"\\"value\\""' → Fixed: '"value"'
run_cleanup_migration(app_db)
```

### JSON → DB Migration

Each store (SessionStore, ChatStore) auto-migrates existing JSON data to PostgreSQL when `.set_database()` is called. Existing records are skipped (idempotent).

---

## Startup Sequence

```
1. Create AppDatabaseManager
2. Register 6 models (register_models)
3. Connect + create tables + schema migration (initialize_database)
4. Data migration (run_cleanup_migration)
5. Connect ConfigManager to DB (set_database)
6. Connect SessionStore to DB → JSON data migration
7. Connect ChatStore to DB → JSON data migration
8. Connect SessionLogger to DB
9. Propagate DB to AgentSession memory
```

---

## Config Serialization Safety

`config_serializer.py` — Prevents JSON double serialization:

| Function | Description |
|----------|-------------|
| `safe_serialize(value, data_type)` | Prevents re-serialization of already-serialized values |
| `safe_deserialize(value, data_type)` | Recursive deserialization up to 10 levels deep |
| `normalize_config_value(value, data_type)` | Recovery utility |

---

## Related Files

```
service/database/
├── __init__.py                 # Public API: AppDatabaseManager, database_config
├── database_config.py          # Environment variable-based DB configuration
├── database_manager.py         # ConnectionPool management, query execution, migration
├── app_database_manager.py     # High-level ORM-like CRUD, model registration
├── config_serializer.py        # JSON serialization safety
├── db_config_helper.py         # persistent_configs CRUD
├── chat_db_helper.py           # chat_rooms/messages CRUD
├── session_db_helper.py        # sessions CRUD
├── session_log_db_helper.py    # session_logs CRUD
├── memory_db_helper.py         # session_memory_entries CRUD (LTM + STM)
├── migrations/
│   ├── __init__.py
│   └── config_cleanup.py       # Double-escape cleanup migration
└── models/
    ├── __init__.py              # APPLICATION_MODELS list
    ├── base_model.py            # BaseModel ABC (get_table_name, get_schema)
    ├── persistent_config.py     # PersistentConfigModel
    ├── session.py               # SessionModel
    ├── chat_room.py             # ChatRoomModel
    ├── chat_message.py          # ChatMessageModel
    ├── session_log.py           # SessionLogModel
    └── memory_entry.py          # MemoryEntryModel
```
