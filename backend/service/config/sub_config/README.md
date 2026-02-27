# Sub-Config Organization Policy

## Overview

All configuration classes in Geny Agent are organized under the `sub_config/` directory using a **category-based folder structure**. Each folder name directly becomes the **category name** displayed in the Settings UI.

## Directory Structure

```
service/config/
├── base.py                  # BaseConfig, ConfigField, FieldType, @register_config
├── manager.py               # ConfigManager (load/save/validate)
├── __init__.py              # Package entry point (auto-discovery trigger)
├── variables/               # Runtime JSON storage (auto-generated, do not edit)
│   ├── discord.json
│   ├── slack.json
│   └── teams.json
└── sub_config/              # All config definitions live here
    ├── __init__.py           # Auto-discovery mechanism
    └── <category_name>/      # Folder name = category name
        ├── __init__.py       # Category docstring (optional)
        └── <name>_config.py  # One config class per file
```

### Example

```
sub_config/
├── channels/                 # Category: "channels"
│   ├── __init__.py
│   ├── discord_config.py     # DiscordConfig
│   ├── slack_config.py       # SlackConfig
│   └── teams_config.py       # TeamsConfig
├── security/                 # Category: "security"
│   ├── __init__.py
│   └── auth_config.py        # AuthConfig
└── general/                  # Category: "general"
    ├── __init__.py
    └── app_config.py         # AppConfig
```

## Rules

### 1. One Config Per File

Each `*_config.py` file must contain **exactly one** `@register_config` dataclass that inherits from `BaseConfig`.

```python
# sub_config/channels/discord_config.py

from ...base import BaseConfig, ConfigField, FieldType, register_config

@register_config
@dataclass
class DiscordConfig(BaseConfig):
    ...
```

### 2. File Naming Convention

- Config files must end with `_config.py` (e.g., `discord_config.py`, `auth_config.py`)
- Use lowercase with underscores (snake_case)
- The prefix should clearly identify the integration or feature

### 3. Category = Folder Name

- The parent folder name is the category (e.g., `channels/`, `security/`, `general/`)
- Each category folder must contain an `__init__.py` (can be empty or contain a docstring)
- The `get_category()` method in the config class should return the same category name as the folder

### 4. Import Path

Config files use relative imports to access `BaseConfig`:

```python
from ...base import BaseConfig, ConfigField, FieldType, register_config
```

This resolves to `service.config.base` from `service.config.sub_config.<category>.<file>`.

### 5. Auto-Discovery

The `sub_config/__init__.py` module automatically:
1. Walks all subdirectories of `sub_config/`
2. Imports any module matching `*_config.py`
3. The `@register_config` decorator registers the class in the global registry

**No manual registration is needed.** Simply create the file with the decorator and it will be discovered.

### 6. Backward Compatibility

For existing code that imports config classes directly, `service/config/__init__.py` re-exports them:

```python
from .sub_config.channels.discord_config import DiscordConfig
```

When adding a new config, add a similar re-export line if external code needs direct access.

## Adding a New Config

1. **Choose or create a category folder** under `sub_config/`
2. **Create `__init__.py`** in the category folder if it doesn't exist
3. **Create `<name>_config.py`** with your `@register_config` dataclass
4. **Set `get_category()`** to match the folder name
5. **(Optional)** Add a re-export in `service/config/__init__.py`

That's it — the config will be automatically discovered, loadable via `ConfigManager`, and rendered in the Settings UI.

## Writing a Config Class

Each config file follows a consistent pattern. Here is a complete annotated example:

```python
"""Short description of the config."""

from dataclasses import dataclass, field
from typing import List

from ...base import BaseConfig, ConfigField, FieldType, register_config


@register_config          # Registers the class in the global registry on import
@dataclass                # Required — enables to_dict() / from_dict() serialization
class ExampleConfig(BaseConfig):
    """Docstring for the config class."""

    # --- Instance fields (actual config values) ---
    enabled: bool = False
    api_key: str = ""
    max_retries: int = 3
    allowed_ids: List[str] = field(default_factory=list)

    # --- Required class methods ---

    @classmethod
    def get_config_name(cls) -> str:
        """Unique identifier. Used as JSON filename (e.g. 'example' -> example.json)"""
        return "example"

    @classmethod
    def get_display_name(cls) -> str:
        """Human-readable name shown in the Settings UI card."""
        return "Example Integration"

    @classmethod
    def get_description(cls) -> str:
        """Brief description shown below the display name."""
        return "Configure the example integration."

    @classmethod
    def get_category(cls) -> str:
        """Must match the parent folder name (e.g. 'channels')."""
        return "channels"

    @classmethod
    def get_icon(cls) -> str:
        """Icon key used by the frontend (optional, default: 'settings')."""
        return "settings"

    @classmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        """Define every field's UI metadata."""
        return [
            ConfigField(
                name="enabled",
                field_type=FieldType.BOOLEAN,
                label="Enable Integration",
                description="Turn this integration on or off",
                default=False,
                group="connection"
            ),
            ConfigField(
                name="api_key",
                field_type=FieldType.STRING,
                label="API Key",
                description="Secret API key for authentication",
                required=True,
                placeholder="Enter your API key",
                group="connection",
                secure=True          # Renders with password masking + eye toggle
            ),
            ConfigField(
                name="max_retries",
                field_type=FieldType.NUMBER,
                label="Max Retries",
                description="Number of retry attempts on failure",
                default=3,
                min_value=0,
                max_value=10,
                group="behavior"
            ),
            ConfigField(
                name="allowed_ids",
                field_type=FieldType.TEXTAREA,
                label="Allowed IDs",
                description="Comma-separated list of allowed IDs",
                placeholder="id1, id2, id3",
                group="permissions"
            ),
        ]
```

## ConfigField Parameter Reference

Every field in `get_fields_metadata()` is a `ConfigField` instance. Below is the full list of parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | `str` | *(required)* | Must match the dataclass field name exactly. Used as the JSON key. |
| `field_type` | `FieldType` | *(required)* | Determines the input widget rendered in the UI. See **FieldType** table below. |
| `label` | `str` | *(required)* | Human-readable label displayed next to the input. |
| `description` | `str` | `""` | Explanation shown as a tooltip (hover `?` icon) in the UI. |
| `required` | `bool` | `False` | If `True`, validation fails when the field is empty. A red `*` is shown next to the label. |
| `default` | `Any` | `None` | Default value. Should match the dataclass field default. |
| `placeholder` | `str` | `""` | Placeholder text shown inside the input when empty. |
| `options` | `List[Dict]` | `[]` | For `SELECT` / `MULTISELECT` only. Each item: `{"value": "...", "label": "..."}`. |
| `min_value` | `float?` | `None` | Minimum allowed value for `NUMBER` fields. |
| `max_value` | `float?` | `None` | Maximum allowed value for `NUMBER` fields. |
| `pattern` | `str?` | `None` | Regex pattern for server-side validation. |
| `group` | `str` | `"general"` | Groups fields visually in the edit modal (e.g. `"connection"`, `"behavior"`). |
| `secure` | `bool` | `False` | If `True`, the field is rendered with password masking and a show/hide eye toggle, regardless of `field_type`. Use for tokens, secrets, passwords, and any sensitive value. |

## FieldType Reference

| FieldType | UI Widget | Notes |
|-----------|-----------|-------|
| `STRING` | Text input | Default for most text fields. |
| `PASSWORD` | Text input | Semantic hint only. Actual masking is controlled by `secure=True`. |
| `NUMBER` | Number input (spinners hidden) | Use `min_value` / `max_value` for range validation. |
| `BOOLEAN` | Toggle switch | Rendered as a horizontal row: label left, toggle right. |
| `SELECT` | Dropdown | Requires `options` parameter. |
| `MULTISELECT` | Multi-select | Requires `options` parameter. |
| `TEXTAREA` | Multi-line text | Good for lists (comma-separated IDs) and long text. |
| `URL` | URL input | Validates `http://` or `https://` prefix. |
| `EMAIL` | Email input | Validates presence of `@`. |

> **Important:** The `PASSWORD` FieldType is a semantic marker. To actually mask a field in the UI, you must set `secure=True` on the `ConfigField`. This allows any field type (STRING, TEXTAREA, etc.) to be masked when it contains sensitive data.
