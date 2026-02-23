"""
Sub-config auto-discovery module.

This package automatically discovers and imports all config modules
organized under category folders (e.g., channels/, general/, security/).

Folder structure:
    sub_config/
        <category_name>/          # Folder name becomes the category
            <name>_config.py      # Individual config file

Each *_config.py file should define a single @register_config dataclass
that inherits from BaseConfig. The @register_config decorator ensures
the config class is automatically registered in the global registry.
"""

import importlib
import pkgutil
from logging import getLogger
from pathlib import Path

def _discover_configs():
    """
    Automatically discover and import all config modules
    in category subdirectories.

    Walks through each subdirectory of sub_config/ and imports
    any Python module whose name ends with '_config'.
    """
    package_dir = Path(__file__).parent

    for category_dir in sorted(package_dir.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith(('_', '.')):
            continue

        # Import each *_config.py module in the category folder
        category_package = f"{__name__}.{category_dir.name}"

        # Ensure the category package is importable
        try:
            importlib.import_module(category_package)
        except ImportError:
            continue

        for module_info in pkgutil.iter_modules([str(category_dir)]):
            if module_info.name.endswith('_config'):
                try:
                    importlib.import_module(f"{category_package}.{module_info.name}")
                except ImportError as e:
                    getLogger(__name__).warning(
                        f"Failed to import config module {category_package}.{module_info.name}: {e}"
                    )


# Auto-discover on import
_discover_configs()
