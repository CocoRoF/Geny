"""Regression tests for the memory-LLM adapter.

Phase H — memory always uses the Anthropic client because the
``memory_model`` default is a Claude model and there is no global
"current provider" setting (provider selection is per-Environment at
the manifest level). The remaining contract surface:

* ``build_memory_llm`` returns ``None`` when no API key is configured,
  so ``CurationEngine`` degrades cleanly without raising.
* Empty ``APIConfig.memory_model`` falls back to ``anthropic_model``.
* ``MemoryLLM.complete`` wraps a ``BaseClient.create_message`` call
  with the ``ModelConfig`` built from the above; the return value
  is the joined text content.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from service.memory.memory_llm import MemoryLLM, build_memory_llm


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


def _reset_config_manager(monkeypatch, tmp_path) -> None:
    """Redirect the config-manager singleton at a fresh tmp dir.

    ``get_config_manager`` is a process-global singleton with a cache
    and an on-disk JSON fallback. Without this reset, env-var changes
    made inside one test leak into the next.
    """
    for var in (
        "MEMORY_MODEL",
        "ANTHROPIC_MODEL",
        "LLM_PROVIDER",
        "LLM_BASE_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    from service.config import manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "_config_manager", None)
    original_ctor = mgr_mod.ConfigManager.__init__

    def _tmp_ctor(self, config_dir=None, app_db=None):
        original_ctor(self, config_dir=tmp_path, app_db=app_db)

    monkeypatch.setattr(mgr_mod.ConfigManager, "__init__", _tmp_ctor)


# ─────────────────────────────────────────────────────────────────
# build_memory_llm
# ─────────────────────────────────────────────────────────────────


def test_build_memory_llm_returns_none_without_api_key(monkeypatch, tmp_path):
    _reset_config_manager(monkeypatch, tmp_path)
    # No ANTHROPIC_API_KEY → adapter cannot be built.
    assert build_memory_llm() is None


def test_build_memory_llm_uses_memory_model_when_set(monkeypatch, tmp_path):
    _reset_config_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MEMORY_MODEL", "claude-haiku-4-5-20251001")

    llm = build_memory_llm()
    assert llm is not None
    assert llm.model_config.model == "claude-haiku-4-5-20251001"
    assert llm.model_config.max_tokens == 2048
    assert llm.model_config.temperature == 0.0
    assert llm.model_config.thinking_enabled is False


def test_build_memory_llm_falls_back_to_main_model_when_memory_empty(
    monkeypatch, tmp_path
):
    _reset_config_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MEMORY_MODEL", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    llm = build_memory_llm()
    assert llm is not None
    assert llm.model_config.model == "claude-sonnet-4-6"


def test_build_memory_llm_always_uses_anthropic(monkeypatch, tmp_path):
    """Phase H — memory client is hardcoded to Anthropic regardless of
    env hints. Provider selection is per-Environment via the manifest,
    not a global setting that the memory path consults."""
    _reset_config_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    llm = build_memory_llm()
    assert llm is not None
    assert llm.client.provider == "anthropic"


# ─────────────────────────────────────────────────────────────────
# MemoryLLM.complete
# ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_memory_llm_complete_returns_response_text():
    from geny_executor.core.config import ModelConfig
    from geny_executor.llm_client.types import APIResponse, ContentBlock

    fake_response = APIResponse(
        content=[ContentBlock(type="text", text="hello world")],
        stop_reason="end_turn",
    )
    fake_client = AsyncMock()
    fake_client.create_message = AsyncMock(return_value=fake_response)

    llm = MemoryLLM(
        client=fake_client,
        model_config=ModelConfig(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            temperature=0.0,
            thinking_enabled=False,
        ),
    )

    out = await llm.complete("test prompt", purpose="memory.curation.analyze")

    assert out == "hello world"
    fake_client.create_message.assert_awaited_once()
    call_kwargs = fake_client.create_message.await_args.kwargs
    assert call_kwargs["model_config"].model == "claude-haiku-4-5-20251001"
    assert call_kwargs["messages"] == [{"role": "user", "content": "test prompt"}]
    assert call_kwargs["purpose"] == "memory.curation.analyze"


# ─────────────────────────────────────────────────────────────────
# provider ↔ model pairing
# ─────────────────────────────────────────────────────────────────


def test_a_provider_is_never_handed_a_model_it_cannot_serve():
    """The 2026-09-19 regression: the provider came from a credential
    heuristic and the model from APIConfig, so when the legacy
    claude_code_cli entry left the bundle the pair became
    (openai, claude-haiku-*) and every curation call 404'd."""
    from service.memory.memory_llm import _serves

    assert _serves("openai", "claude-haiku-4-5-20251001") is False
    assert _serves("anthropic", "gpt-4.1") is False
    assert _serves("geny_codex", "claude-sonnet-5") is False

    assert _serves("anthropic", "claude-sonnet-5") is True
    assert _serves("geny_claude_code", "sonnet") is True
    assert _serves("openai", "gpt-5.6-terra") is True
    assert _serves("geny_codex", "gpt-5.6-terra") is True


def test_an_unknown_provider_is_trusted_with_any_model():
    """vllm / ollama / a host-registered backend serves whatever it is
    told — only families we KNOW are wrong get refused."""
    from service.memory.memory_llm import _serves

    assert _serves("vllm", "some-local-model") is True
    assert _serves("geny_router", "anything") is True
    assert _serves("", "anything") is True


def test_a_mismatched_pair_yields_no_adapter(monkeypatch, tmp_path):
    """Better no LLM curation (callers degrade to rules) than a model id
    the provider will 404 on."""
    _reset_config_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("MEMORY_MODEL", "claude-haiku-4-5-20251001")

    assert build_memory_llm() is None


# ─────────────────────────────────────────────────────────────────
# the cheap tier, and why it is not a pinned id
# ─────────────────────────────────────────────────────────────────


def test_every_declared_cheap_tier_is_a_model_that_kind_offers():
    """The rot this replaces: an id pinned in a settings row goes stale the
    day the provider retires it, and every curation call then spends a round
    trip 404ing. Keeping it in the kind's own catalogue means it moves when
    the catalogue moves — this test is what keeps that true."""
    from service.llm_accounts.kinds import KINDS

    for kind, info in KINDS.items():
        if not info.aux_model:
            continue
        offered = {m.id for m in info.models}
        assert info.aux_model in offered, (
            f"{kind} names {info.aux_model!r} as its cheap tier but does not offer it"
        )


def test_a_kind_with_no_cheap_tier_keeps_the_account_model():
    """Returning '' means 'no opinion' — the caller keeps the account's own
    model rather than guessing an id the provider may not serve."""
    from service.llm_accounts.kinds import aux_model_for

    assert aux_model_for("vllm") == ""
    assert aux_model_for("no-such-kind") == ""


def test_claude_code_curates_on_haiku_not_on_the_conversation_model(monkeypatch, tmp_path):
    """Curation is background work: it should not spend Opus tokens just
    because that is what the user happens to be talking to."""
    from service.llm_accounts.kinds import aux_model_for

    assert aux_model_for("claude_code") == "haiku"
