# Config System

> Dataclass-based configuration management — auto-discovery, DB+JSON dual storage, UI schema auto-generation

## Architecture Overview

```
ConfigManager (singleton)
    │
    ├── Load priority:  Cache → PostgreSQL → JSON file → Generate defaults
    ├── Save:           PostgreSQL (primary) + JSON (backup)
    │
    ├── sub_config/
    │   ├── general/          ── APIConfig, LimitsConfig, LTMConfig, ...
    │   └── channels/         ── DiscordConfig, SlackConfig, ...
    │
    └── @register_config decorator + auto-discovery (pkgutil)
```

---

## Core Types

### FieldType

| Value | Description |
|-------|-------------|
| `STRING` | Plain text input |
| `PASSWORD` | Masked input |
| `NUMBER` | Number (min/max support) |
| `BOOLEAN` | Toggle |
| `SELECT` | Dropdown |
| `MULTISELECT` | Multi-select |
| `TEXTAREA` | Multi-line text |
| `URL` | URL input (`http://` / `https://` validation) |
| `EMAIL` | Email (`@` validation) |

### ConfigField

```python
@dataclass
class ConfigField:
    name: str                                      # Field identifier
    field_type: FieldType                          # UI control type
    label: str                                     # Display label
    description: str = ""                          # Help text
    required: bool = False                         # Required flag
    default: Any = None                            # Default value
    placeholder: str = ""                          # Input placeholder
    options: List[Dict[str,str]] = []              # SELECT/MULTISELECT options
    min_value: Optional[float] = None              # NUMBER minimum
    max_value: Optional[float] = None              # NUMBER maximum
    pattern: Optional[str] = None                  # Regex validation
    group: str = "general"                         # UI group/section
    secure: bool = False                           # Masking toggle
    depends_on: Optional[str] = None               # Dependent field (option filtering)
    apply_change: Optional[Callable] = None        # (old, new) change callback
```

---

## BaseConfig ABC

Abstract base for all configuration classes.

### Required Methods

| Method | Return | Description |
|--------|--------|-------------|
| `get_config_name()` | `str` | Unique identifier (e.g., `"api"` → `api.json`) |
| `get_display_name()` | `str` | UI display name |
| `get_description()` | `str` | Config card description |
| `get_fields_metadata()` | `List[ConfigField]` | Field metadata (UI rendering/validation) |

### Optional Overrides

| Method | Default | Description |
|--------|---------|-------------|
| `get_category()` | `"general"` | Category (matches folder name) |
| `get_icon()` | `"settings"` | Frontend icon |
| `get_i18n()` | `{}` | Internationalization translations (`"ko"`, etc.) |

### Instance Methods

| Method | Description |
|--------|-------------|
| `to_dict()` | Serialize to dictionary |
| `validate()` → `List[str]` | Field validation, return error list |
| `apply_field_changes(old_values)` | Invoke `apply_change` callbacks for changed fields |

### Class Methods

| Method | Description |
|--------|-------------|
| `from_dict(data)` | Create instance from dictionary (ignore unknown fields) |
| `get_default_instance()` | Load defaults from .env / environment variables |
| `get_schema()` | Full schema dictionary for UI building |

### Validation Rules

- **required**: Error if `None` or empty string
- **NUMBER**: Check `min_value` / `max_value` range
- **SELECT**: Verify value is in `options`
- **URL**: Must start with `http://` or `https://`
- **EMAIL**: Must contain `@`
- **pattern**: Regex match

---

## @register_config Decorator

```python
_config_registry: Dict[str, Type[BaseConfig]] = {}

def register_config(cls):
    _config_registry[cls.get_config_name()] = cls
    return cls
```

Auto-registers on class import. **No manual registration needed** — just create `*_config.py` files in `sub_config/`.

### Auto-Discovery

`sub_config/__init__.py`'s `_discover_configs()`:

1. Traverse `sub_config/` subdirectories
2. Import category packages
3. Discover/import `*_config` modules via `pkgutil.iter_modules`
4. `@register_config` fires → registry registration

---

## ConfigManager

Thread-safe singleton. `RLock` protected.

### Load Priority (`load_config`)

```
1. In-memory cache (_configs)
    ↓ miss
2. PostgreSQL DB (persistent_configs table)
    ↓ miss
3. JSON file (variables/*.json) — auto-migrate to DB on discovery
    ↓ miss
4. Generate defaults (get_default_instance()) → save to DB + JSON
```

### Save Mechanism (`save_config`)

| Storage | Role |
|---------|------|
| PostgreSQL | **Primary** — individual rows per field (`config_name`, `config_key`, `config_value`, `data_type`) |
| JSON file | **Backup** — `variables/{config_name}.json` |
| In-memory | **Cache** — immediate return on next query |

### Key Methods

| Method | Description |
|--------|-------------|
| `load_config(config_class)` | Priority cascade load |
| `save_config(config)` | Save to DB + JSON + cache |
| `update_config(name, updates)` | Partial update + change detection + callbacks |
| `get_config(name)` | Get by name |
| `get_config_value(name, field, default)` | Get single field value |
| `get_all_configs()` | Full config list (schema + values + validation) |
| `reload_all_configs()` | Invalidate cache + full reload |
| `export_all_configs()` | Full backup dictionary |
| `import_configs(data)` | Restore from backup |
| `migrate_all_to_db()` | Batch JSON → DB migration |

### Global Access

```python
get_config_manager() → ConfigManager       # Lazy singleton
init_config_manager(config_dir, app_db)     # Initialize with custom parameters
```

---

## env_utils — Environment Variable Utilities

### Core Principle

- `.env` file is a **read-only fallback** — for initial default values only
- Config changes are NOT written to `.env` — **Config JSON/DB is the source of truth**
- `os.environ` is updated in real-time via `env_sync` callbacks

### Functions

| Function | Description |
|----------|-------------|
| `read_env(key)` | Read value in order: `.env` → `os.environ` → `None` |
| `read_env_defaults(field_to_env, type_hints)` | Build defaults dictionary from `.env` (auto type-casting) |
| `env_sync(env_key)` | `apply_change` callback factory — updates `os.environ` on value change |

### Usage Pattern

```python
@register_config
@dataclass
class MyConfig(BaseConfig):
    my_field: str = ""

    _ENV_MAP = {"my_field": "MY_ENV_VAR"}

    @classmethod
    def get_default_instance(cls):
        defaults = read_env_defaults(cls._ENV_MAP, cls.__dataclass_fields__)
        return cls(**defaults)

    @staticmethod
    def get_fields_metadata():
        return [
            ConfigField(
                name="my_field",
                field_type=FieldType.STRING,
                label="My Field",
                apply_change=env_sync("MY_ENV_VAR"),
            )
        ]
```

---

## Full Config Class Reference

### General Category

#### APIConfig (`"api"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `anthropic_api_key` | PASSWORD | `""` | `ANTHROPIC_API_KEY` | Anthropic API key (required, secure) |
| `anthropic_model` | SELECT | `"claude-sonnet-4-6"` | `ANTHROPIC_MODEL` | Default Claude model |
| `max_thinking_tokens` | NUMBER | `31999` | `MAX_THINKING_TOKENS` | Extended Thinking budget (0–128000) |
| `skip_permissions` | BOOLEAN | `True` | `CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS` | Skip confirmation dialogs |
| `app_port` | NUMBER | `8000` | `APP_PORT` | Backend server port (1–65535) |

#### LimitsConfig (`"limits"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `max_budget_usd` | NUMBER | `10.0` | `CLAUDE_MAX_BUDGET_USD` | Max API cost per session ($, 0–1000) |
| `max_turns` | NUMBER | `50` | `CLAUDE_MAX_TURNS` | Max agent turns per task (1–500) |
| `bash_default_timeout_ms` | NUMBER | `30000` | `BASH_DEFAULT_TIMEOUT_MS` | Default bash timeout |
| `bash_max_timeout_ms` | NUMBER | `600000` | `BASH_MAX_TIMEOUT_MS` | Max bash timeout |
| `disallowed_tools` | STRING | `"ToolSearch"` | — | Disabled Claude CLI tools (comma-separated) |

#### LTMConfig (`"ltm"`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | BOOLEAN | `False` | Enable FAISS vector search |
| `embedding_provider` | SELECT | `"openai"` | Embedding provider (openai/google/anthropic) |
| `embedding_model` | SELECT | `"text-embedding-3-small"` | Model (`depends_on=embedding_provider`) |
| `embedding_api_key` | PASSWORD | `""` | API key |
| `chunk_size` | NUMBER | `1024` | Chunk size (128–4096) |
| `chunk_overlap` | NUMBER | `256` | Chunk overlap (0–512) |
| `top_k` | NUMBER | `6` | Search result count (1–30) |
| `score_threshold` | NUMBER | `0.35` | Min similarity (0.0–1.0) |
| `max_inject_chars` | NUMBER | `10000` | Max prompt injection chars (500–30000) |

#### LanguageConfig (`"language"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `language` | SELECT | `"en"` | `GENY_LANGUAGE` | UI language (en/ko) |

#### TelemetryConfig (`"telemetry"`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `disable_autoupdater` | BOOLEAN | `True` | Disable auto-updater |
| `disable_error_reporting` | BOOLEAN | `True` | Disable error reporting |
| `disable_telemetry` | BOOLEAN | `True` | Disable telemetry |

#### GitHubConfig (`"github"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `github_token` | PASSWORD | `""` | `GITHUB_TOKEN` + `GH_TOKEN` | PAT (secure, syncs both env vars) |

#### SharedFolderConfig (`"shared_folder"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `enabled` | BOOLEAN | `True` | `GENY_SHARED_FOLDER_ENABLED` | Enable shared folder |
| `shared_folder_path` | STRING | `""` | `GENY_SHARED_FOLDER_PATH` | Absolute path (empty = `{STORAGE_ROOT}/_shared`) |
| `link_name` | STRING | `"_shared"` | `GENY_SHARED_FOLDER_LINK_NAME` | Symlink name in session folder |

#### UserConfig (`"user"`)

| Field | Type | Default | Env Var | Description |
|-------|------|---------|---------|-------------|
| `user_name` | STRING | `""` | `GENY_USER_NAME` | User name |
| `user_title` | STRING | `""` | `GENY_USER_TITLE` | Title/role |
| `department` | STRING | `""` | `GENY_USER_DEPARTMENT` | Department/team |
| `description` | TEXTAREA | `""` | `GENY_USER_DESCRIPTION` | Bio/specialty |

`get_user_context()` → Generates user info string for prompt injection.

### Channels Category

#### DiscordConfig (`"discord"`)

| Group | Field | Type | Default | Description |
|-------|-------|------|---------|-------------|
| connection | `enabled` | BOOLEAN | `False` | Enable |
| connection | `bot_token` | PASSWORD | `""` | Bot token |
| connection | `application_id` | STRING | `""` | App ID |
| server | `guild_ids` | TEXTAREA | `[]` | Server IDs |
| server | `allowed_channel_ids` | TEXTAREA | `[]` | Allowed channel IDs |
| server | `command_prefix` | STRING | `"!"` | Command prefix |
| permissions | `admin_role_ids` | TEXTAREA | `[]` | Admin role IDs |
| permissions | `allowed_user_ids` | TEXTAREA | `[]` | Allowed user IDs |
| behavior | `respond_to_mentions` | BOOLEAN | `True` | Respond to mentions |
| behavior | `respond_to_dms` | BOOLEAN | `False` | Respond to DMs |
| behavior | `auto_thread` | BOOLEAN | `True` | Auto-create threads |
| behavior | `max_message_length` | NUMBER | `2000` | Max message length |
| session | `session_timeout_minutes` | NUMBER | `30` | Session timeout (min) |
| session | `max_sessions_per_user` | NUMBER | `3` | Max sessions per user |
| session | `default_prompt` | TEXTAREA | `""` | Default system prompt |

#### SlackConfig (`"slack"`)

| Group | Field | Type | Default | Description |
|-------|-------|------|---------|-------------|
| connection | `enabled` | BOOLEAN | `False` | Enable |
| connection | `bot_token` | PASSWORD | `""` | xoxb- token |
| connection | `app_token` | PASSWORD | `""` | xapp- socket mode token |
| connection | `signing_secret` | PASSWORD | `""` | Signing secret |
| workspace | `workspace_id` | STRING | `""` | Workspace ID |
| workspace | `allowed_channel_ids` | TEXTAREA | `[]` | Channel IDs |
| workspace | `default_channel_id` | STRING | `""` | Default channel |
| behavior | `respond_to_mentions` | BOOLEAN | `True` | Respond to mentions |
| behavior | `respond_to_dms` | BOOLEAN | `True` | Respond to DMs |
| behavior | `respond_in_thread` | BOOLEAN | `True` | Respond in thread |
| behavior | `use_blocks` | BOOLEAN | `True` | Use Block Kit |
| behavior | `max_message_length` | NUMBER | `4000` | Max message length |
| commands | `enable_slash_commands` | BOOLEAN | `True` | Enable slash commands |
| commands | `slash_command_name` | STRING | `"/claude"` | Slash command name |

#### TeamsConfig (`"teams"`)

| Group | Field | Type | Default | Description |
|-------|-------|------|---------|-------------|
| connection | `enabled` | BOOLEAN | `False` | Enable |
| connection | `app_id` | STRING | `""` | Microsoft App ID |
| connection | `app_password` | PASSWORD | `""` | App password |
| connection | `tenant_id` | STRING | `""` | Azure AD tenant ID |
| connection | `bot_endpoint` | URL | `""` | Messaging endpoint URL |
| behavior | `use_adaptive_cards` | BOOLEAN | `True` | Use Adaptive Cards |
| behavior | `max_message_length` | NUMBER | `28000` | Max message length |
| graph | `enable_graph_api` | BOOLEAN | `False` | Enable Graph API |
| graph | `graph_client_secret` | PASSWORD | `""` | Graph API secret |

#### KakaoConfig (`"kakao"`)

| Group | Field | Type | Default | Description |
|-------|-------|------|---------|-------------|
| connection | `enabled` | BOOLEAN | `False` | Enable |
| connection | `rest_api_key` | PASSWORD | `""` | REST API key |
| connection | `admin_key` | PASSWORD | `""` | Admin key |
| connection | `bot_id` | STRING | `""` | Bot ID |
| connection | `channel_public_id` | STRING | `""` | Channel profile ID |
| skill_server | `skill_endpoint_path` | STRING | `"/api/kakao/skill"` | Skill endpoint |
| callback | `use_callback` | BOOLEAN | `True` | Use AI chatbot callback |
| response | `response_format` | SELECT | `"simpleText"` | Response format (simpleText/textCard) |
| response | `show_quick_replies` | BOOLEAN | `True` | Show quick reply buttons |
| response | `quick_reply_labels` | TEXTAREA | `["Continue","New Chat","Help"]` | Button labels |

---

## REST API

Router prefix: `/api/config`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/config` | Full config list (schema + values + validation, grouped by category) |
| `GET` | `/api/config/schemas` | Schemas only |
| `GET` | `/api/config/{name}` | Get specific config |
| `PUT` | `/api/config/{name}` | Update config (`{"values": {...}}`) |
| `DELETE` | `/api/config/{name}` | Reset to defaults |
| `POST` | `/api/config/export` | Full backup export |
| `POST` | `/api/config/import` | Restore from backup (`{"configs": {...}}`) |
| `POST` | `/api/config/reload` | Full reload (invalidate cache) |
| `GET` | `/api/config/{name}/validate` | Validate without saving |

---

## Design Patterns

1. **Source of Truth**: Config DB/JSON — `.env` is a read-only fallback for initial defaults
2. **env_sync callback**: Config change → `os.environ` updated immediately (no service restart needed)
3. **depends_on**: In LTMConfig, `embedding_model` options filtered by `embedding_provider` value
4. **Dual storage**: DB primary + JSON backup — auto-migrate from JSON to DB when found
5. **i18n**: All configs provide Korean translations via `get_i18n()`
6. **Auto-discovery**: Just add `*_config.py` files in `sub_config/` — registrationis automatic

---

## Related Files

```
service/config/
├── __init__.py              # Package entry point, auto-discovery trigger
├── base.py                  # BaseConfig ABC, ConfigField, FieldType, @register_config
├── manager.py               # ConfigManager (singleton, load/save/cache/migration)
├── variables/               # Runtime JSON storage (auto-generated)
│   ├── api.json
│   ├── limits.json
│   └── ...
└── sub_config/
    ├── __init__.py           # Auto-discovery walker
    ├── general/
    │   ├── api_config.py     # APIConfig
    │   ├── limits_config.py  # LimitsConfig
    │   ├── ltm_config.py     # LTMConfig
    │   ├── language_config.py
    │   ├── telemetry_config.py
    │   ├── github_config.py
    │   ├── shared_folder_config.py
    │   ├── user_config.py
    │   └── env_utils.py      # read_env, env_sync
    └── channels/
        ├── discord_config.py
        ├── slack_config.py
        ├── teams_config.py
        └── kakao_config.py

controller/config_controller.py  # REST API router
```
