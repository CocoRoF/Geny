"""Geny settings section tests (PR-B.3.5)."""

from __future__ import annotations

import pytest

from service.settings.sections import PresetSection, VTuberSection


# ── PresetSection ────────────────────────────────────────────────────


class TestPresetSection:
    def test_defaults(self):
        s = PresetSection()
        assert s.default == "worker_adaptive"
        assert s.by_channel == {}
        assert "worker_adaptive" in s.available
        assert "vtuber" in s.available

    def test_custom_default(self):
        s = PresetSection(default="vtuber")
        assert s.default == "vtuber"

    def test_by_channel_overrides(self):
        s = PresetSection(by_channel={"discord": "vtuber"})
        assert s.by_channel["discord"] == "vtuber"


# ── VTuberSection ────────────────────────────────────────────────────


class TestVTuberSection:
    def test_defaults(self):
        s = VTuberSection()
        assert s.enabled is True
        assert s.persona_name == "Geny"
        assert s.tick_interval_seconds == 60

    def test_tick_below_floor_rejected(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            VTuberSection(tick_interval_seconds=1)

    def test_disable(self):
        s = VTuberSection(enabled=False)
        assert s.enabled is False


# ── install_geny_settings ────────────────────────────────────────────


pytest.importorskip("geny_executor.settings")


def test_install_returns_loader_with_sections_registered():
    from service.settings.install import install_geny_settings
    from geny_executor.settings.section_registry import (
        list_section_names,
        reset_section_registry,
    )
    from geny_executor.settings.loader import reset_default_loader

    reset_default_loader()
    reset_section_registry()
    loader = install_geny_settings()
    assert loader is not None
    names = list_section_names()
    assert "preset" in names
    assert "vtuber" in names
