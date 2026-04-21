"""PersonaProvider Protocol + PersonaResolution dataclass contracts."""

from __future__ import annotations

from typing import Any

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import PersonaBlock

from backend.service.persona import PersonaProvider, PersonaResolution


class _FakeProvider:
    """Minimal PersonaProvider — structural typing target."""

    def __init__(self, blocks):
        self._blocks = blocks

    def resolve(self, state: Any, *, session_meta: dict) -> PersonaResolution:
        return PersonaResolution(persona_blocks=list(self._blocks))


def test_fake_provider_is_recognized_as_personaprovider() -> None:
    fake = _FakeProvider([PersonaBlock("hello")])
    # Protocol uses structural typing — isinstance must succeed with runtime_checkable.
    assert isinstance(fake, PersonaProvider)


def test_resolution_default_fields() -> None:
    r = PersonaResolution()
    assert r.persona_blocks == []
    assert r.system_tail is None
    assert r.cache_key == ""


def test_resolution_is_frozen() -> None:
    r = PersonaResolution(cache_key="x")
    try:
        r.cache_key = "y"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("PersonaResolution must be frozen")


def test_provider_passes_session_meta_through() -> None:
    captured = {}

    class _Capturing:
        def resolve(self, state, *, session_meta):
            captured["sm"] = session_meta
            return PersonaResolution()

    state = PipelineState()
    _Capturing().resolve(state, session_meta={"session_id": "abc", "is_vtuber": True})
    assert captured["sm"] == {"session_id": "abc", "is_vtuber": True}
