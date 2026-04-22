"""Tests for ``service.vtuber.tts.engines.omnivoice_engine``.

Uses ``httpx.MockTransport`` to avoid network calls and an in-memory
profile directory so we don't depend on backend/static/voices.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional
from unittest.mock import patch

import httpx
import pytest

from service.vtuber.tts import base as tts_base
from service.vtuber.tts.base import AudioFormat, TTSRequest
from service.vtuber.tts.engines import omnivoice_engine as ove


# ── Config stub ──────────────────────────────────────────────────────


@dataclass
class _Cfg:
    enabled: bool = True
    api_url: str = "http://omnivoice:9881"
    timeout_seconds: float = 5.0
    mode: str = "clone"
    voice_profile: str = "paimon_ko"
    instruct: str = ""
    language: str = ""
    num_step: int = 32
    guidance_scale: float = 2.0
    speed: float = 1.0
    duration_seconds: float = 0.0
    denoise: bool = True
    audio_format: str = "wav"
    auto_asr: bool = False


def _patch_config(cfg: _Cfg):
    """Replace ConfigManager.load_config with a stub returning ``cfg``."""
    return patch(
        "service.vtuber.tts.engines.omnivoice_engine.get_config_manager",
        lambda: type("CM", (), {"load_config": staticmethod(lambda _c: cfg)})(),
        create=False,
    ) if False else _direct_patch(cfg)


def _direct_patch(cfg: _Cfg):
    # The engine calls `get_config_manager().load_config(OmniVoiceConfig)`
    # at runtime via local imports — patch the manager module itself.
    from service.config import manager as cm

    class _StubMgr:
        def load_config(self, _c):
            return cfg

    return patch.object(cm, "get_config_manager", lambda: _StubMgr())


@pytest.fixture()
def voices_dir(tmp_path, monkeypatch):
    profile_dir = tmp_path / "paimon_ko"
    profile_dir.mkdir()
    (profile_dir / "ref_neutral.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "display_name": "파이몬",
                "language": "ko",
                "emotion_refs": {
                    "neutral": {
                        "file": "ref_neutral.wav",
                        "prompt_text": "안녕",
                        "prompt_lang": "ko",
                    }
                },
            }
        )
    )
    monkeypatch.setattr(ove, "_BACKEND_VOICES_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_persistent_http_clients():
    """The adapter caches httpx clients across calls; clear between tests
    so each test exercises its own MockTransport."""
    ove._clients.clear()
    yield
    ove._clients.clear()


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_check_ok():
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/health"
        return httpx.Response(200, json={"status": "ok", "model": "x", "device": "cpu",
                                         "dtype": "float32", "sampling_rate": 24000,
                                         "auto_asr": False, "max_concurrency": 1})

    transport = httpx.MockTransport(handler)
    with _direct_patch(cfg):
        with patch.object(httpx, "AsyncClient",
                          lambda *a, **kw: httpx.AsyncClient(transport=transport, **kw)):
            engine = ove.OmniVoiceEngine()
            assert await engine.health_check() is True


@pytest.mark.asyncio
async def test_health_check_loading_returns_false():
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "loading", "model": "x", "device": "cpu",
                                         "dtype": "float32", "sampling_rate": 0,
                                         "auto_asr": False, "max_concurrency": 1})

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        assert await engine.health_check() is False


@pytest.mark.asyncio
async def test_health_check_disabled():
    cfg = _Cfg(enabled=False)
    with _direct_patch(cfg):
        engine = ove.OmniVoiceEngine()
        assert await engine.health_check() is False


@pytest.mark.asyncio
async def test_synthesize_clone_mode_resolves_ref_audio(voices_dir):
    cfg = _Cfg(mode="clone")
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/tts"
        captured["payload"] = json.loads(req.content)
        return httpx.Response(200, content=b"WAVDATA",
                              headers={"content-type": "audio/wav"})

    transport = httpx.MockTransport(handler)
    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=transport, **kw)
    ):
        engine = ove.OmniVoiceEngine()
        request = TTSRequest(text="안녕하세요", emotion="neutral", language="ko",
                             audio_format=AudioFormat.WAV, sample_rate=24000)
        chunks = [c async for c in engine.synthesize_stream(request)]

    assert any(c.audio_data == b"WAVDATA" for c in chunks)
    assert chunks[-1].is_final
    payload = captured["payload"]
    assert payload["mode"] == "clone"
    assert payload["ref_audio_path"].endswith("/voices/paimon_ko/ref_neutral.wav")
    assert payload["ref_text"] == "안녕"
    assert payload["language"] == "ko"


@pytest.mark.asyncio
async def test_synthesize_design_mode_requires_instruct(voices_dir):
    cfg = _Cfg(mode="design", instruct="")
    with _direct_patch(cfg):
        engine = ove.OmniVoiceEngine()
        request = TTSRequest(text="hi", emotion="neutral", language="en")
        with pytest.raises(ValueError, match="design requires"):
            async for _ in engine.synthesize_stream(request):
                pass


@pytest.mark.asyncio
async def test_synthesize_design_mode_sends_instruct(voices_dir):
    cfg = _Cfg(mode="design", instruct="female, low pitch, british accent")
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(req.content)
        return httpx.Response(200, content=b"WAV", headers={"content-type": "audio/wav"})

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        request = TTSRequest(text="hi", emotion="neutral", language="en")
        async for _ in engine.synthesize_stream(request):
            pass

    assert captured["payload"]["mode"] == "design"
    assert captured["payload"]["instruct"] == "female, low pitch, british accent"
    assert "ref_audio_path" not in captured["payload"]


@pytest.mark.asyncio
async def test_resolve_emotion_ref_falls_back_to_neutral(voices_dir):
    path, prompt_text, prompt_lang = ove._resolve_emotion_ref("paimon_ko", "anger")
    assert path is not None
    assert path.endswith("/ref_neutral.wav")
    assert prompt_text == "안녕"
    assert prompt_lang == "ko"


@pytest.mark.asyncio
async def test_get_voices_proxies_remote_response(voices_dir):
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/voices"
        return httpx.Response(200, json={"voices": [
            {"id": "paimon_ko", "name": "파이몬", "language": "ko", "ref_audios": []},
            {"id": "ellen_joe", "name": "Ellen", "language": "en", "ref_audios": []},
        ]})

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        voices = await engine.get_voices(language="ko")

    assert len(voices) == 1
    assert voices[0].id == "paimon_ko"
    assert voices[0].engine == "omnivoice"


# ── Phase 1 regression: persistent client + phase-aware health ───────


@pytest.mark.asyncio
async def test_health_check_phase_ok_returns_true():
    """New /health body uses ``phase``; ``ok`` must be honoured."""
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok", "phase": "ok",
            "model": "x", "device": "cpu", "dtype": "float16",
            "sampling_rate": 24000, "auto_asr": False, "max_concurrency": 1,
        })

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        assert await engine.health_check() is True


@pytest.mark.asyncio
async def test_health_check_phase_warming_returns_false():
    """``phase=warming`` is not yet ready, even though HTTP is 200."""
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "loading", "phase": "warming",
            "model": "x", "device": "cuda:0", "dtype": "float16",
            "sampling_rate": 24000, "auto_asr": False, "max_concurrency": 1,
        })

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        assert await engine.health_check() is False


@pytest.mark.asyncio
async def test_health_check_legacy_status_only_still_ready():
    """Old servers without ``phase`` must still report ready via ``status``."""
    cfg = _Cfg()

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "ok",  # no phase field at all
            "model": "x", "device": "cpu", "dtype": "float16",
            "sampling_rate": 24000, "auto_asr": False, "max_concurrency": 1,
        })

    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    ):
        engine = ove.OmniVoiceEngine()
        assert await engine.health_check() is True


@pytest.mark.asyncio
async def test_synthesize_concurrent_calls_do_not_serialise_in_adapter(voices_dir):
    """The module-level adapter lock has been removed (Phase 1b).

    Two concurrent ``synthesize_stream`` calls must both reach the
    upstream handler concurrently. We assert this by counting the peak
    number of in-flight requests observed inside the mock handler.
    """
    import asyncio as _asyncio

    cfg = _Cfg(mode="clone", timeout_seconds=10.0)
    in_flight = 0
    peak = 0
    lock = _asyncio.Lock()
    seen = _asyncio.Event()

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
            if in_flight >= 2:
                seen.set()
        try:
            # Hold the connection long enough for the second caller to land.
            await _asyncio.wait_for(seen.wait(), timeout=2.0)
        except _asyncio.TimeoutError:
            pass
        async with lock:
            in_flight -= 1
        return httpx.Response(200, content=b"WAV", headers={"content-type": "audio/wav"})

    transport = httpx.MockTransport(handler)
    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=transport, **kw)
    ):
        engine = ove.OmniVoiceEngine()
        req1 = TTSRequest(text="첫 번째", emotion="neutral", language="ko")
        req2 = TTSRequest(text="두 번째", emotion="neutral", language="ko")

        async def _drain(r):
            return [c async for c in engine.synthesize_stream(r)]

        results = await _asyncio.gather(_drain(req1), _drain(req2))

    assert all(any(c.audio_data == b"WAV" for c in chunks) for chunks in results)
    assert peak >= 2, (
        f"adapter still serialising calls; peak in-flight={peak} "
        "(expected ≥ 2 after lock removal)"
    )


@pytest.mark.asyncio
async def test_persistent_client_is_reused_across_calls(voices_dir):
    """Phase 1: per-call AsyncClient construction was costing one TCP
    setup per synthesis. Verify that two sequential calls share the
    same cached client instance."""
    cfg = _Cfg(mode="clone", timeout_seconds=10.0)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"WAV", headers={"content-type": "audio/wav"})

    transport = httpx.MockTransport(handler)
    with _direct_patch(cfg), patch.object(
        httpx, "AsyncClient",
        lambda *a, **kw: httpx.AsyncClient(transport=transport, **kw)
    ):
        engine = ove.OmniVoiceEngine()
        req = TTSRequest(text="hi", emotion="neutral", language="ko")

        async for _ in engine.synthesize_stream(req):
            pass
        snapshot = dict(ove._clients)
        assert len(snapshot) == 1
        first_client = next(iter(snapshot.values()))

        async for _ in engine.synthesize_stream(req):
            pass
        assert len(ove._clients) == 1
        assert next(iter(ove._clients.values())) is first_client


@pytest.mark.asyncio
async def test_aclose_clients_clears_pool():
    cfg = _Cfg()
    with _direct_patch(cfg):
        client = await ove._get_client("http://x:1", read_timeout=1.0)
        assert ove._clients
        assert not client.is_closed
        await ove.aclose_clients()
        assert ove._clients == {}
