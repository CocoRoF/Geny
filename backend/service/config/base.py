"""
Base configuration abstract class.

All configs should inherit from BaseConfig to enable:
- Automatic registration in main.py
- JSON serialization/deserialization
- Frontend configuration UI support
- Validation
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Dict, List, Optional, Type, TypeVar, get_type_hints
from enum import Enum
import json


class FieldType(str, Enum):
    """Supported field types for config UI"""
    STRING = "string"
    PASSWORD = "password"  # Masked input
    NUMBER = "number"
    BOOLEAN = "boolean"
    SELECT = "select"  # Dropdown with options
    MULTISELECT = "multiselect"  # Multiple selection
    TEXTAREA = "textarea"  # Multi-line text
    URL = "url"
    EMAIL = "email"


@dataclass
class ConfigField:
    """Metadata for a configuration field"""
    name: str
    field_type: FieldType
    label: str
    description: str = ""
    required: bool = False
    default: Any = None
    placeholder: str = ""
    options: List[Dict[str, str]] = field(default_factory=list)  # For SELECT/MULTISELECT: [{"value": "...", "label": "..."}]
    min_value: Optional[float] = None  # For NUMBER
    max_value: Optional[float] = None  # For NUMBER
    pattern: Optional[str] = None  # Regex pattern for validation
    group: str = "general"  # Group name for UI organization
    secure: bool = False  # If True, field is masked with show/hide toggle in UI


# Registry for all config classes
_config_registry: Dict[str, Type['BaseConfig']] = {}


def register_config(cls: Type['BaseConfig']) -> Type['BaseConfig']:
    """Decorator to register a config class for auto-discovery"""
    _config_registry[cls.get_config_name()] = cls
    return cls


def get_registered_configs() -> Dict[str, Type['BaseConfig']]:
    """Get all registered config classes"""
    return _config_registry.copy()


T = TypeVar('T', bound='BaseConfig')


class BaseConfig(ABC):
    """
    Abstract base class for all configurations.

    To create a new config:
    1. Inherit from BaseConfig
    2. Implement required abstract methods
    3. Define config fields with type hints and defaults
    4. Use @register_config decorator for auto-registration

    Example:
        @register_config
        @dataclass
        class MyConfig(BaseConfig):
            api_key: str = ""
            enabled: bool = True

            @classmethod
            def get_config_name(cls) -> str:
                return "my_config"

            @classmethod
            def get_display_name(cls) -> str:
                return "My Configuration"

            @classmethod
            def get_description(cls) -> str:
                return "Description of my config"

            @classmethod
            def get_fields_metadata(cls) -> List[ConfigField]:
                return [
                    ConfigField(
                        name="api_key",
                        field_type=FieldType.PASSWORD,
                        label="API Key",
                        required=True
                    ),
                    ConfigField(
                        name="enabled",
                        field_type=FieldType.BOOLEAN,
                        label="Enabled",
                        default=True
                    )
                ]
    """

    @classmethod
    @abstractmethod
    def get_config_name(cls) -> str:
        """
        Return the unique identifier for this config.
        This is used as the filename (without .json extension).
        """
        pass

    @classmethod
    @abstractmethod
    def get_display_name(cls) -> str:
        """Return the human-readable name for the config"""
        pass

    @classmethod
    @abstractmethod
    def get_description(cls) -> str:
        """Return a description of what this config is for"""
        pass

    @classmethod
    @abstractmethod
    def get_fields_metadata(cls) -> List[ConfigField]:
        """
        Return metadata for all configurable fields.
        This is used to generate the UI form.
        """
        pass

    @classmethod
    def get_category(cls) -> str:
        """Return the category for grouping in UI (default: 'general')"""
        return "general"

    @classmethod
    def get_icon(cls) -> str:
        """Return an icon identifier for the config (optional)"""
        return "settings"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize config to dictionary"""
        if hasattr(self, '__dataclass_fields__'):
            return asdict(self)
        # Fallback for non-dataclass configs
        result = {}
        for field_meta in self.get_fields_metadata():
            result[field_meta.name] = getattr(self, field_meta.name, field_meta.default)
        return result

    def to_json(self) -> str:
        """Serialize config to JSON string"""
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Create config instance from dictionary"""
        # Filter out unknown fields
        valid_fields = {f.name for f in cls.get_fields_metadata()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Create config instance from JSON string"""
        data = json.loads(json_str)
        return cls.from_dict(data)

    @classmethod
    def get_default_instance(cls: Type[T]) -> T:
        """Create a config instance with all default values"""
        # For dataclass configs, just call the constructor with no args
        # This uses the dataclass field defaults
        if hasattr(cls, '__dataclass_fields__'):
            return cls()

        # Fallback for non-dataclass configs
        defaults = {}
        for field_meta in cls.get_fields_metadata():
            if field_meta.default is not None:
                defaults[field_meta.name] = field_meta.default
        return cls(**defaults)

    def validate(self) -> List[str]:
        """
        Validate the configuration.
        Returns a list of error messages. Empty list means valid.
        """
        errors = []
        for field_meta in self.get_fields_metadata():
            value = getattr(self, field_meta.name, None)

            # Check required fields
            if field_meta.required:
                if value is None or (isinstance(value, str) and value.strip() == ""):
                    errors.append(f"{field_meta.label} is required")
                    continue

            # Skip validation for empty optional fields
            if value is None or (isinstance(value, str) and value.strip() == ""):
                continue

            # Type-specific validation
            if field_meta.field_type == FieldType.NUMBER:
                try:
                    num_value = float(value)
                    if field_meta.min_value is not None and num_value < field_meta.min_value:
                        errors.append(f"{field_meta.label} must be at least {field_meta.min_value}")
                    if field_meta.max_value is not None and num_value > field_meta.max_value:
                        errors.append(f"{field_meta.label} must be at most {field_meta.max_value}")
                except (TypeError, ValueError):
                    errors.append(f"{field_meta.label} must be a number")

            elif field_meta.field_type in (FieldType.SELECT, FieldType.MULTISELECT):
                valid_values = {opt.get('value') for opt in field_meta.options}
                if field_meta.field_type == FieldType.SELECT:
                    if value not in valid_values:
                        errors.append(f"{field_meta.label} has an invalid value")
                else:  # MULTISELECT
                    if isinstance(value, list):
                        invalid = [v for v in value if v not in valid_values]
                        if invalid:
                            errors.append(f"{field_meta.label} contains invalid values: {invalid}")

            elif field_meta.field_type == FieldType.URL:
                if not value.startswith(('http://', 'https://')):
                    errors.append(f"{field_meta.label} must be a valid URL")

            elif field_meta.field_type == FieldType.EMAIL:
                if '@' not in value:
                    errors.append(f"{field_meta.label} must be a valid email")

            # Pattern validation
            if field_meta.pattern:
                import re
                if not re.match(field_meta.pattern, str(value)):
                    errors.append(f"{field_meta.label} format is invalid")

        return errors

    def is_valid(self) -> bool:
        """Check if config is valid"""
        return len(self.validate()) == 0

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """
        Get the full schema for this config.
        Used by frontend to render the configuration UI.
        """
        return {
            "name": cls.get_config_name(),
            "display_name": cls.get_display_name(),
            "description": cls.get_description(),
            "category": cls.get_category(),
            "icon": cls.get_icon(),
            "fields": [
                {
                    "name": f.name,
                    "type": f.field_type.value,
                    "label": f.label,
                    "description": f.description,
                    "required": f.required,
                    "default": f.default,
                    "placeholder": f.placeholder,
                    "options": f.options,
                    "min": f.min_value,
                    "max": f.max_value,
                    "pattern": f.pattern,
                    "group": f.group,
                    "secure": f.secure
                }
                for f in cls.get_fields_metadata()
            ]
        }
