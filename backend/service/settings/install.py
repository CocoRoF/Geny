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

from service.settings.sections import (
    AffectConfigSection,
    ChannelsConfigSection,
    HooksConfigSection,
    MemoryConfigSection,
    ModelConfigSection,
    NotificationsConfigSection,
    PermissionsConfigSection,
    PresetSection,
    SkillsConfigSection,
    TelemetryConfigSection,
    VTuberSection,
)

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
    # PR-F.1.1..F.1.5 — framework subsystem section schemas. The
    # executor's hooks/skills/model/etc. modules read these sections
    # from settings.json today; registering Pydantic schemas turns
    # raw-dict reads into validated parses + drives the
    # /api/framework-settings UI editor (PR-F.1.6).
    register_section("hooks", HooksConfigSection)
    register_section("skills", SkillsConfigSection)
    register_section("model", ModelConfigSection)
    register_section("telemetry", TelemetryConfigSection)
    register_section("notifications", NotificationsConfigSection)
    # K.2 (cycle 20260426_2) — typed permissions section so
    # FrameworkSettingsPanel can edit it consistently with the others
    # and the D.2 reader map carries the entry.
    register_section("permissions", PermissionsConfigSection)
    # G.1 (cycle 20260426_2) — memory provider section. Read by
    # service.memory_provider.config.build_default_memory_config with
    # env-fallback semantics.
    register_section("memory", MemoryConfigSection)
    # G.3 (cycle 20260426_2) — affect tag emitter knob.
    register_section("affect", AffectConfigSection)
    # L.1 (cycle 20260426_3) — send-message channel registry config.
    register_section("channels", ChannelsConfigSection)

    loaded = loader.load()
    logger.info(
        "settings_installed sections=%d cascade_paths=%d",
        len(loaded), len(loader.paths),
    )
    return loader


__all__ = ["install_geny_settings"]
