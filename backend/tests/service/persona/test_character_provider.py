"""CharacterPersonaProvider — role routing, character load, overrides, context."""

from __future__ import annotations

from pathlib import Path

import pytest

from geny_executor.core.state import PipelineState
from geny_executor.stages.s03_system.artifact.default.builders import PersonaBlock

from backend.service.persona import CharacterPersonaProvider, PersonaProvider


_VTUBER_DEFAULT = "VDEFAULT"
_WORKER_DEFAULT = "WDEFAULT"
_ADAPTIVE = "ADAPTIVE"


@pytest.fixture
def chars_dir(tmp_path: Path) -> Path:
    d = tmp_path / "characters"
    d.mkdir()
    (d / "catgirl.md").write_text("## Character Personality\ncatgirl-body", encoding="utf-8")
    (d / "default.md").write_text("## Character Personality\ndefault-body", encoding="utf-8")
    return d


@pytest.fixture
def provider(chars_dir: Path) -> CharacterPersonaProvider:
    return CharacterPersonaProvider(
        characters_dir=chars_dir,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )


def _persona_text(resolution) -> str:
    assert len(resolution.persona_blocks) == 1
    block = resolution.persona_blocks[0]
    assert isinstance(block, PersonaBlock)
    return block.render(PipelineState())


def test_implements_persona_provider(provider: CharacterPersonaProvider) -> None:
    assert isinstance(provider, PersonaProvider)


def test_vtuber_role_default_persona(provider) -> None:
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert text == _VTUBER_DEFAULT
    # Adaptive must NOT be included for vtuber role.
    assert _ADAPTIVE not in text


def test_worker_role_appends_adaptive(provider) -> None:
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": False})
    text = _persona_text(r)
    assert text == f"{_WORKER_DEFAULT}\n\n{_ADAPTIVE}"


def test_static_override_replaces_default(provider) -> None:
    provider.set_static_override("s", "CUSTOM-BASE")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": False})
    text = _persona_text(r)
    assert text.startswith("CUSTOM-BASE\n\n")
    assert _ADAPTIVE in text
    assert _WORKER_DEFAULT not in text


def test_static_override_cleared_restores_default(provider) -> None:
    provider.set_static_override("s", "CUSTOM")
    provider.set_static_override("s", None)
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r) == _VTUBER_DEFAULT


def test_set_character_loads_named_file(provider) -> None:
    provider.set_character("s", "catgirl")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert "catgirl-body" in text
    assert text.startswith(_VTUBER_DEFAULT)


def test_set_character_fallback_to_default_md(provider) -> None:
    provider.set_character("s", "nonexistent")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert "default-body" in _persona_text(r)


def test_missing_character_and_no_default(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    p = CharacterPersonaProvider(
        characters_dir=empty,
        default_vtuber_prompt=_VTUBER_DEFAULT,
        default_worker_prompt=_WORKER_DEFAULT,
        adaptive_prompt=_ADAPTIVE,
    )
    p.set_character("s", "ghost")
    r = p.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r) == _VTUBER_DEFAULT  # silently skipped


def test_append_context_concatenates(provider) -> None:
    provider.append_context("s", "sub-worker-notice")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    text = _persona_text(r)
    assert text.endswith("sub-worker-notice")


def test_append_context_is_idempotent(provider) -> None:
    provider.append_context("s", "once")
    provider.append_context("s", "once")  # duplicate must be rejected
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert _persona_text(r).count("once") == 1


def test_sessions_are_isolated(provider) -> None:
    provider.set_static_override("A", "ONLY-A")
    provider.set_character("B", "catgirl")

    text_a = _persona_text(provider.resolve(PipelineState(), session_meta={"session_id": "A", "is_vtuber": False}))
    text_b = _persona_text(provider.resolve(PipelineState(), session_meta={"session_id": "B", "is_vtuber": True}))

    assert "ONLY-A" in text_a and "catgirl-body" not in text_a
    assert "catgirl-body" in text_b and "ONLY-A" not in text_b


def test_reset_clears_all_session_state(provider) -> None:
    provider.set_static_override("s", "CUSTOM")
    provider.set_character("s", "catgirl")
    provider.append_context("s", "ctx")
    provider.reset("s")
    text = _persona_text(
        provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    )
    assert text == _VTUBER_DEFAULT


def test_cache_key_encodes_flags(provider) -> None:
    r_default = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    provider.set_static_override("s", "X")
    r_override = provider.resolve(PipelineState(), session_meta={"session_id": "s", "is_vtuber": True})
    assert r_default.cache_key != r_override.cache_key
    assert r_default.cache_key.startswith("V")
    assert r_override.cache_key.startswith("V")


def test_character_file_is_cached_after_first_read(provider, chars_dir: Path) -> None:
    provider.set_character("s1", "catgirl")
    # Remove the file to prove subsequent loads hit the cache.
    (chars_dir / "catgirl.md").unlink()
    provider.set_character("s2", "catgirl")
    r = provider.resolve(PipelineState(), session_meta={"session_id": "s2", "is_vtuber": True})
    assert "catgirl-body" in _persona_text(r)
