"""One-shot YAML → settings.json migrator (PR-B.3.3).

Reads existing per-feature YAML configs (permissions / hooks /
notifications) and writes a unified ``~/.geny/settings.json``.
Creates ``~/.geny/<file>.bak`` for every file it touches so a
mis-migration can be rolled back.

Idempotent: re-running won't add already-present sections; missing
files are silently skipped. Returns a dict summarising what was
migrated for the lifespan log line.

Run from main.py once before ``install_geny_settings``::

    from service.settings.migrator import migrate_yaml_to_settings_json
    migrate_yaml_to_settings_json()
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


SOURCES = (
    # (yaml file, settings.json section name)
    ("permissions.yaml", "permissions"),
    ("hooks.yaml", "hooks"),
    ("notifications.yaml", "notifications"),
)


def migrate_yaml_to_settings_json(
    *,
    home: Optional[Path] = None,
) -> Dict[str, Any]:
    """Migrate the three known yaml configs into settings.json.

    Returns a summary dict::

        {
            "migrated": ["permissions", "hooks"],
            "skipped":  ["notifications"],   # absent on disk
            "kept":     [],                  # already in settings.json
            "settings_path": "...",
        }
    """
    home = home or (Path.home() / ".geny")
    settings_path = home / "settings.json"
    home.mkdir(parents=True, exist_ok=True)

    existing: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError as exc:
            logger.warning(
                "settings_migrator existing_json_invalid path=%s err=%s",
                settings_path, exc,
            )
            existing = {}

    summary: Dict[str, Any] = {
        "migrated": [],
        "skipped": [],
        "kept": [],
        "settings_path": str(settings_path),
    }

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("settings_migrator pyyaml_missing — cannot read yaml sources")
        return summary

    for yaml_name, section in SOURCES:
        src = home / yaml_name
        if not src.exists():
            summary["skipped"].append(section)
            continue
        if section in existing:
            # Already migrated; respect the user's existing choice.
            summary["kept"].append(section)
            continue
        try:
            data = yaml.safe_load(src.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            logger.warning(
                "settings_migrator yaml_invalid path=%s err=%s", src, exc,
            )
            continue
        if data is None:
            data = {}
        if not isinstance(data, dict):
            logger.warning(
                "settings_migrator yaml_root_not_object path=%s type=%s",
                src, type(data).__name__,
            )
            continue
        # Backup the source file so a manual rollback is one ``mv`` away.
        backup = src.with_suffix(src.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(src, backup)
        existing[section] = data
        summary["migrated"].append(section)

    if summary["migrated"]:
        # Write out updated settings.json. Existing file backed up first.
        if settings_path.exists():
            backup = settings_path.with_suffix(".json.bak")
            shutil.copy2(settings_path, backup)
        settings_path.write_text(
            json.dumps(existing, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.info(
            "settings_migrator wrote settings_json migrated=%s",
            summary["migrated"],
        )

    return summary


__all__ = ["migrate_yaml_to_settings_json", "SOURCES"]
