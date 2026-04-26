"""Geny-specific settings section schemas.

Two service-domain sections registered against the executor's
section_registry on lifespan boot:

- ``preset`` — which preset is the default; per-channel overrides.
- ``vtuber`` — VTuber persona / tick / persona feed knobs.

Hosts can ship more by extending this module + ``install_geny_settings``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PresetSection(BaseModel):
    """``settings.preset`` schema.

    Example::

        {
          "preset": {
            "default": "worker_adaptive",
            "by_channel": {"discord": "vtuber", "slack": "worker_adaptive"}
          }
        }
    """

    default: str = Field("worker_adaptive")
    by_channel: Dict[str, str] = Field(default_factory=dict)
    available: List[str] = Field(
        default_factory=lambda: ["worker_adaptive", "vtuber"],
    )


class VTuberSection(BaseModel):
    """``settings.vtuber`` schema.

    Knobs for the VTuber persona surface: how often the heartbeat
    fires, what the persona name shown to viewers is, etc.
    """

    enabled: bool = True
    persona_name: str = Field("Geny")
    tick_interval_seconds: int = Field(60, ge=5)
    background_topics: List[str] = Field(default_factory=list)
    persona_voice: Optional[str] = None


__all__ = ["PresetSection", "VTuberSection"]
