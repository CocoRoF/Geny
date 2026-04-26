"""Geny-specific settings sections + loader install (PR-B.3.5)."""

from service.settings.install import install_geny_settings
from service.settings.sections import PresetSection, VTuberSection

__all__ = ["PresetSection", "VTuberSection", "install_geny_settings"]
