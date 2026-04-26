"""Wire the executor's SettingsLoader with Geny's cascade + sections.

Lifespan calls ``install_geny_settings`` once at boot. Cascade
order (lowest → highest priority):

    ~/.geny/settings.json
    .geny/settings.json
    .geny/settings.local.json   (gitignored)

Two service sections are registered: ``preset`` + ``vtuber``.
Hosts can register more by importing register_section directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from service.settings.sections import PresetSection, VTuberSection

logger = logging.getLogger(__name__)


def install_geny_settings() -> Optional[Any]:
    """Configure the executor's default loader for Geny's cascade
    and register Geny-specific section schemas.

    Returns the loader instance, or ``None`` if executor 1.2.0+
    isn't importable."""
    try:
        from geny_executor.settings import (
            get_default_loader,
            register_section,
        )
    except ImportError:
        logger.warning("settings_loader_unavailable executor_version<1.2.0")
        return None

    loader = get_default_loader()

    # Geny cascade — paths added bottom-up (later = higher priority).
    for path in (
        Path.home() / ".geny" / "settings.json",
        Path(".geny") / "settings.json",
        Path(".geny") / "settings.local.json",
    ):
        loader.add_path(path)

    register_section("preset", PresetSection)
    register_section("vtuber", VTuberSection)

    loaded = loader.load()
    logger.info(
        "settings_installed sections=%d cascade_paths=%d",
        len(loaded), len(loader.paths),
    )
    return loader


__all__ = ["install_geny_settings"]
