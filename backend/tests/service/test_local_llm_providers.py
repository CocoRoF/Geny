"""Local LLM provider integration (A-6) — Geny side of executor 2.9.0.

Covers the credential bundle builder emitting the branded local
providers, the boot-time active-provider resolution preferring a
local-only setup, and the LLM Backends controller's reachability +
model-discovery helpers.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional
from unittest.mock import patch

import controller.llm_backends_controller as ctrl
from service.config.sub_config.general.cli_backends_config import (
    CLIBackendClaudeCodeConfig,
)
from service.config.sub_config.general.llm_credentials_config import (
    LLMCredentialsConfig,
)
from service.executor.credentials import CredentialBundleBuilder


class _StubCM:
    """Config manager stub returning a fixed LLMCredentialsConfig +
    (disabled) Claude Code config."""

    def __init__(self, **llm_kwargs: Any) -> None:
        self._llm = LLMCredentialsConfig(**llm_kwargs)
        self._cli = CLIBackendClaudeCodeConfig(enabled=False)

    def load_config(self, cls):
        if cls is LLMCredentialsConfig:
            return self._llm
        if cls is CLIBackendClaudeCodeConfig:
            return self._cli
        raise ValueError(cls)


def _scrub_env():
    keys = (
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "LLM_BASE_URL",
        "OLLAMA_BASE_URL", "OLLAMA_NUM_CTX", "LMSTUDIO_BASE_URL", "CUSTOM_LLM_BASE_URL",
    )
    return patch.dict(os.environ, {k: "" for k in keys}, clear=False)


# ── CredentialBundleBuilder ────────────────────────────────────────────


def test_ollama_included_with_num_ctx_extra():
    with _scrub_env():
        cm = _StubCM(ollama_base_url="http://localhost:11434/v1", ollama_num_ctx=32768)
        bundle = CredentialBundleBuilder(config_manager=cm).build()
    creds = bundle.get("ollama")
    assert creds.base_url == "http://localhost:11434/v1"
    assert dict(creds.extras) == {"ollama_num_ctx": 32768}
    assert bundle.has("ollama")


def test_ollama_num_ctx_zero_omits_extra():
    with _scrub_env():
        cm = _StubCM(ollama_base_url="http://localhost:11434/v1", ollama_num_ctx=0)
        bundle = CredentialBundleBuilder(config_manager=cm).build()
    assert dict(bundle.get("ollama").extras) == {}


def test_lmstudio_and_custom_included_when_url_set():
    with _scrub_env():
        cm = _StubCM(
            lmstudio_base_url="http://127.0.0.1:1234/v1",
            custom_base_url="http://box:8080/v1",
        )
        bundle = CredentialBundleBuilder(config_manager=cm).build()
    assert bundle.get("lmstudio").base_url == "http://127.0.0.1:1234/v1"
    assert bundle.get("custom").base_url == "http://box:8080/v1"


def test_local_providers_absent_when_unconfigured():
    with _scrub_env():
        cm = _StubCM()  # no local urls
        bundle = CredentialBundleBuilder(config_manager=cm).build()
    for p in ("ollama", "lmstudio", "custom"):
        assert not bundle.has(p), p
        assert p not in bundle.by_provider, p


def test_ollama_base_url_env_fallback():
    cm = _StubCM()  # config empty
    with patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://envhost:11434/v1", "OLLAMA_NUM_CTX": "8192"}):
        bundle = CredentialBundleBuilder(config_manager=cm).build()
    creds = bundle.get("ollama")
    assert creds.base_url == "http://envhost:11434/v1"
    assert dict(creds.extras) == {"ollama_num_ctx": 8192}


def test_local_only_setup_resolves_to_ollama():
    """A local-only install (Ollama configured, no cloud keys) must resolve
    to ``ollama`` instead of the keyless anthropic last-resort."""
    cm = _StubCM(ollama_base_url="http://localhost:11434/v1")
    with _scrub_env():
        order = (
            "geny_claude_code", "anthropic", "openai", "google", "vllm",
            "ollama", "lmstudio", "custom",
        )
        provider = CredentialBundleBuilder(config_manager=cm).build().preferred_provider(order=order)
    assert provider == "ollama"


def test_cloud_key_still_wins_over_local():
    cm = _StubCM(anthropic_api_key="sk-ant-x", ollama_base_url="http://localhost:11434/v1")
    order = (
        "geny_claude_code", "anthropic", "openai", "google", "vllm",
        "ollama", "lmstudio", "custom",
    )
    provider = CredentialBundleBuilder(config_manager=cm).build().preferred_provider(order=order)
    assert provider == "anthropic"


# ── controller helpers ─────────────────────────────────────────────────


def test_ollama_native_root_strips_v1():
    assert ctrl._ollama_native_root("http://localhost:11434/v1") == "http://localhost:11434"
    assert ctrl._ollama_native_root("http://h:11434/v1/") == "http://h:11434"


def test_resolve_local_base_url_precedence():
    class C:
        base_url = "http://saved/v1"

    assert ctrl._resolve_local_base_url("ollama", C(), "http://typed/v1") == "http://typed/v1"
    assert ctrl._resolve_local_base_url("ollama", C(), None) == "http://saved/v1"

    class Empty:
        base_url = ""

    assert ctrl._resolve_local_base_url("ollama", Empty(), None) == "http://localhost:11434/v1"
    assert ctrl._resolve_local_base_url("custom", Empty(), None) == ""


def _patch_http(monkeypatch, payload: Optional[Dict[str, Any]]):
    async def fake_get(url, timeout=5.0):
        fake_get.url = url
        return payload

    monkeypatch.setattr(ctrl, "_http_get_json", fake_get)
    return fake_get


def test_discover_ollama_models(monkeypatch):
    spy = _patch_http(monkeypatch, {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]})
    models = asyncio.run(ctrl._discover_local_models("ollama", "http://localhost:11434/v1"))
    assert models == ["llama3.1:8b", "qwen2.5:7b"]  # sorted
    assert spy.url == "http://localhost:11434/api/tags"


def test_discover_openai_compatible_models(monkeypatch):
    spy = _patch_http(monkeypatch, {"data": [{"id": "model-b"}, {"id": "model-a"}]})
    models = asyncio.run(ctrl._discover_local_models("lmstudio", "http://127.0.0.1:1234/v1"))
    assert models == ["model-a", "model-b"]
    assert spy.url == "http://127.0.0.1:1234/v1/models"


def test_discover_unreachable_returns_none(monkeypatch):
    _patch_http(monkeypatch, None)
    assert asyncio.run(ctrl._discover_local_models("ollama", "http://x/v1")) is None


def test_check_local_reachable_and_configured(monkeypatch):
    async def fake_discover(provider, base_url):
        return ["m1", "m2"]

    monkeypatch.setattr(ctrl, "_discover_local_models", fake_discover)

    class _Bundle:
        def get(self, p):
            return type("C", (), {"base_url": "http://localhost:11434/v1"})()

    h = asyncio.run(ctrl._check_local("ollama", _Bundle()))
    assert h.available is True
    assert h.detail_code == "local.reachable"
    assert h.detail_params["count"] == "2"


def test_check_local_unreachable(monkeypatch):
    async def fake_discover(provider, base_url):
        return None

    monkeypatch.setattr(ctrl, "_discover_local_models", fake_discover)

    class _Bundle:
        def get(self, p):
            return type("C", (), {"base_url": "http://localhost:11434/v1"})()

    h = asyncio.run(ctrl._check_local("ollama", _Bundle()))
    assert h.available is False
    assert h.detail_code == "local.unreachable"


def test_check_local_custom_unconfigured():
    class _Bundle:
        def get(self, p):
            return type("C", (), {"base_url": ""})()

    h = asyncio.run(ctrl._check_local("custom", _Bundle()))
    assert h.available is False
    assert h.detail_code == "local.base_url_missing"
