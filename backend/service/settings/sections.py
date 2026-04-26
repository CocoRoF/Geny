"""Geny-specific settings section schemas.

Two service-domain sections registered against the executor's
section_registry on lifespan boot:

- ``preset`` — which preset is the default; per-channel overrides.
- ``vtuber`` — VTuber persona / tick / persona feed knobs.

Hosts can ship more by extending this module + ``install_geny_settings``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


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


# ── Framework settings sections (PR-F.1.1..F.1.5) ──────────────────
#
# These mirror the executor subsystems' on-disk shape so SettingsLoader
# returns a parsed model instead of a raw dict. The schemas double as
# input validators for /api/framework-settings PATCH (F.1.6 UI).


class HooksConfigSection(BaseModel):
    """``settings.hooks`` schema (PR-F.1.1).

    Mirrors :class:`geny_executor.hooks.HookConfig`. The ``entries``
    map is left as ``Dict[str, Any]`` so the schema accepts any
    HookEvent name without listing them all here — entry-level CRUD
    lives at :pymod:`controller.hook_controller`.
    """

    enabled: bool = False
    audit_log_path: Optional[str] = None
    entries: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)


class SkillsConfigSection(BaseModel):
    """``settings.skills`` schema (PR-F.1.2)."""

    user_skills_enabled: bool = False
    user_skills_paths: List[str] = Field(default_factory=list)


class ModelConfigSection(BaseModel):
    """``settings.model`` schema (PR-F.1.3) — default model + global
    overrides applied to every session that doesn't pin its own."""

    provider: Optional[str] = None
    name: Optional[str] = None
    max_tokens: Optional[int] = Field(None, ge=1)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    base_url: Optional[str] = None


class TelemetryConfigSection(BaseModel):
    """``settings.telemetry`` schema (PR-F.1.4)."""

    enabled: bool = True
    ring_capacity: int = Field(200, ge=10, le=10_000)
    sample_rate: float = Field(1.0, ge=0.0, le=1.0)


class NotificationsChannel(BaseModel):
    """One row in the notifications array (PR-F.1.5)."""

    name: str
    type: str  # slack | email | webhook | discord | …
    target: str  # webhook url / email / channel id …
    enabled: bool = True
    events: List[str] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)


class NotificationsConfigSection(BaseModel):
    """``settings.notifications`` schema (PR-F.1.5)."""

    channels: List[NotificationsChannel] = Field(default_factory=list)

    @field_validator("channels")
    @classmethod
    def _unique_channel_names(cls, v: List[NotificationsChannel]) -> List[NotificationsChannel]:
        seen: set[str] = set()
        for ch in v:
            if ch.name in seen:
                raise ValueError(f"duplicate channel name: {ch.name!r}")
            seen.add(ch.name)
        return v


class PermissionsConfigSection(BaseModel):
    """``settings.permissions`` schema (K.2 / cycle 20260426_2).

    Mirrors the on-disk shape that ``permission_controller`` writes —
    the ``rules`` list is the same data the cycle's existing
    PermissionsTab CRUD operates on; ``mode`` and ``executor_mode``
    were added in R.1.

    The schema accepts arbitrary mode strings + an arbitrary rule list
    so older deployments with hand-written values keep loading. Strict
    validation lives in the controllers (`_BEHAVIORS` / `_GENY_MODES`
    / `_EXECUTOR_MODES`).
    """

    mode: Optional[str] = Field(
        None,
        description='Geny gate: "advisory" (log only) | "enforce" (block)',
    )
    executor_mode: Optional[str] = Field(
        None,
        description='Executor PermissionMode: default|plan|auto|bypass|acceptEdits|dontAsk',
    )
    rules: List[Dict[str, Any]] = Field(default_factory=list)


__all__ = [
    "PresetSection",
    "VTuberSection",
    "HooksConfigSection",
    "SkillsConfigSection",
    "ModelConfigSection",
    "TelemetryConfigSection",
    "NotificationsConfigSection",
    "NotificationsChannel",
    "PermissionsConfigSection",
]
