"""
Configuration Manager for Claude Control.

Handles:
- Loading/saving configs from JSON files
- Auto-discovery of config classes
- Config validation
- Thread-safe config access
"""

import json
import os
from logging import getLogger
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Type, TypeVar

from service.config.base import BaseConfig, get_registered_configs

logger = getLogger(__name__)

T = TypeVar('T', bound=BaseConfig)

# Global config manager instance
_config_manager: Optional['ConfigManager'] = None


class ConfigManager:
    """
    Manages configuration loading, saving, and access.

    Configs are stored as JSON files in the config directory.
    Automatically discovers and registers config classes.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize the config manager.

        Args:
            config_dir: Directory to store config files.
                       Defaults to 'service/config/variables' in project root.
        """
        if config_dir is None:
            # Default to service/config/variables
            config_dir = Path(__file__).parent / "variables"

        self.config_dir = Path(config_dir)
        self._ensure_config_dir()

        # Cache for loaded configs
        self._configs: Dict[str, BaseConfig] = {}
        self._lock = RLock()  # Use RLock to allow nested lock acquisition

        logger.info(f"ConfigManager initialized with config dir: {self.config_dir}")

    def _ensure_config_dir(self):
        """Ensure config directory exists"""
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def _get_config_path(self, config_name: str) -> Path:
        """Get the file path for a config"""
        return self.config_dir / f"{config_name}.json"

    def get_registered_config_classes(self) -> Dict[str, Type[BaseConfig]]:
        """Get all registered config classes"""
        return get_registered_configs()

    def load_config(self, config_class: Type[T], create_if_missing: bool = True) -> T:
        """
        Load a configuration from file.

        Args:
            config_class: The config class to load
            create_if_missing: If True, create default config if file doesn't exist

        Returns:
            The loaded or default config instance
        """
        config_name = config_class.get_config_name()
        config_path = self._get_config_path(config_name)

        with self._lock:
            # Check cache first
            if config_name in self._configs:
                return self._configs[config_name]

            if config_path.exists():
                try:
                    with open(config_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    config = config_class.from_dict(data)
                    logger.info(f"Loaded config: {config_name}")
                except Exception as e:
                    logger.error(f"Failed to load config {config_name}: {e}")
                    if create_if_missing:
                        config = config_class.get_default_instance()
                        self.save_config(config)
                    else:
                        raise
            elif create_if_missing:
                config = config_class.get_default_instance()
                self.save_config(config)
                logger.info(f"Created default config: {config_name}")
            else:
                raise FileNotFoundError(f"Config file not found: {config_path}")

            self._configs[config_name] = config
            return config

    def save_config(self, config: BaseConfig) -> bool:
        """
        Save a configuration to file.

        Args:
            config: The config instance to save

        Returns:
            True if saved successfully
        """
        config_name = config.get_config_name()
        config_path = self._get_config_path(config_name)

        try:
            with self._lock:
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)

                # Update cache
                self._configs[config_name] = config

            logger.info(f"Saved config: {config_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config {config_name}: {e}")
            return False

    def update_config(self, config_name: str, updates: Dict[str, Any]) -> Optional[BaseConfig]:
        """
        Update a configuration with partial data.

        Args:
            config_name: The config name to update
            updates: Dictionary of fields to update

        Returns:
            The updated config instance, or None if failed
        """
        config_classes = self.get_registered_config_classes()

        if config_name not in config_classes:
            logger.error(f"Unknown config: {config_name}")
            return None

        config_class = config_classes[config_name]

        # Load existing config
        config = self.load_config(config_class)

        # Apply updates
        current_data = config.to_dict()
        current_data.update(updates)

        # Create new instance with updated data
        updated_config = config_class.from_dict(current_data)

        # Validate
        errors = updated_config.validate()
        if errors:
            logger.warning(f"Config validation errors for {config_name}: {errors}")
            # Still save but log warnings

        # Save
        if self.save_config(updated_config):
            return updated_config
        return None

    def get_config(self, config_name: str) -> Optional[BaseConfig]:
        """
        Get a config by name.

        Args:
            config_name: The config name

        Returns:
            The config instance or None if not found
        """
        config_classes = self.get_registered_config_classes()

        if config_name not in config_classes:
            return None

        return self.load_config(config_classes[config_name])

    def get_config_value(self, config_name: str, field_name: str, default: Any = None) -> Any:
        """
        Get a specific field value from a config.

        Args:
            config_name: The config name
            field_name: The field name to get
            default: Default value if not found

        Returns:
            The field value or default
        """
        config = self.get_config(config_name)
        if config is None:
            return default
        return getattr(config, field_name, default)

    def get_all_configs(self) -> List[Dict[str, Any]]:
        """
        Get all configs with their values and schemas.

        Returns:
            List of config data with schema and values
        """
        result = []

        for config_name, config_class in self.get_registered_config_classes().items():
            try:
                config = self.load_config(config_class)
                result.append({
                    "schema": config_class.get_schema(),
                    "values": config.to_dict(),
                    "valid": config.is_valid(),
                    "errors": config.validate()
                })
            except Exception as e:
                logger.error(f"Failed to get config {config_name}: {e}")
                result.append({
                    "schema": config_class.get_schema(),
                    "values": {},
                    "valid": False,
                    "errors": [str(e)]
                })

        return result

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """
        Get schemas for all registered configs.

        Returns:
            List of config schemas
        """
        return [
            config_class.get_schema()
            for config_class in self.get_registered_config_classes().values()
        ]

    def delete_config(self, config_name: str) -> bool:
        """
        Delete a config file.

        Args:
            config_name: The config name to delete

        Returns:
            True if deleted successfully
        """
        config_path = self._get_config_path(config_name)

        try:
            with self._lock:
                if config_path.exists():
                    config_path.unlink()

                # Remove from cache
                if config_name in self._configs:
                    del self._configs[config_name]

            logger.info(f"Deleted config: {config_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete config {config_name}: {e}")
            return False

    def reload_config(self, config_name: str) -> Optional[BaseConfig]:
        """
        Reload a config from file, bypassing cache.

        Args:
            config_name: The config name to reload

        Returns:
            The reloaded config instance
        """
        config_classes = self.get_registered_config_classes()

        if config_name not in config_classes:
            return None

        with self._lock:
            # Remove from cache
            if config_name in self._configs:
                del self._configs[config_name]

        return self.load_config(config_classes[config_name])

    def reload_all_configs(self):
        """Reload all configs from files"""
        with self._lock:
            self._configs.clear()

        for config_class in self.get_registered_config_classes().values():
            try:
                self.load_config(config_class)
            except Exception as e:
                logger.error(f"Failed to reload config {config_class.get_config_name()}: {e}")

    def export_all_configs(self) -> Dict[str, Any]:
        """
        Export all configs to a single dictionary.
        Useful for backup.

        Returns:
            Dictionary with all config data
        """
        return {
            config_name: self.load_config(config_class).to_dict()
            for config_name, config_class in self.get_registered_config_classes().items()
        }

    def import_configs(self, data: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """
        Import configs from a dictionary.

        Args:
            data: Dictionary mapping config names to config data

        Returns:
            Dictionary mapping config names to success status
        """
        results = {}

        config_classes = self.get_registered_config_classes()

        for config_name, config_data in data.items():
            if config_name not in config_classes:
                logger.warning(f"Unknown config during import: {config_name}")
                results[config_name] = False
                continue

            try:
                config = config_classes[config_name].from_dict(config_data)
                results[config_name] = self.save_config(config)
            except Exception as e:
                logger.error(f"Failed to import config {config_name}: {e}")
                results[config_name] = False

        return results


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


def init_config_manager(config_dir: Optional[Path] = None) -> ConfigManager:
    """Initialize the global config manager with custom config directory"""
    global _config_manager
    _config_manager = ConfigManager(config_dir)
    return _config_manager
