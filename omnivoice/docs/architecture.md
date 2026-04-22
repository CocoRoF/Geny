# Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│ geny-omnivoice container                                             │
│                                                                      │
│  uvicorn (server.main:app)                                           │
│   └── FastAPI(lifespan=...)                                          │
│        ├── lifespan()  ─────► server/engine.py :: load(settings)     │
│        │                       OmniVoice.from_pretrained(...)        │
│        │                       (≈ multi-GB checkpoint, GPU resident) │
│        │                                                             │
│        └── Routes (server/api.py)                                    │
│              GET  /             → service info                       │
│              GET  /health       → loading | ok                       │
│              GET  /voices       → server/voices.py :: list_profiles  │
│              GET  /languages    → omnivoice_core.utils.lang_map      │
│              POST /tts          → engine.synthesize(...)             │
│                                    │                                 │
│                                    ▼                                 │
│                           asyncio.Semaphore(MAX_CONCURRENCY)         │
│                                    │                                 │
│                                    ▼ run_in_executor                 │
│                           OmniVoice.generate(...)                    │
│                                    │                                 │
│                                    ▼                                 │
│                           server/streaming.py :: encode(...)         │
│                                                                      │
│  Volumes:                                                            │
│    /voices       (ro)  ◄── backend/static/voices  (Geny shared vol)  │
│    /models       (rw)  ◄── geny-omnivoice-models  (HF cache)         │
└──────────────────────────────────────────────────────────────────────┘
                                ▲
                                │ HTTP (httpx)
┌───────────────────────────────┴──────────────────────────────────────┐
│ geny-backend container                                               │
│   service/vtuber/tts/engines/omnivoice_engine.py                     │
│   ←── service/vtuber/tts/tts_service.py (TTSService singleton)       │
│   ←── service/config/sub_config/tts/omnivoice_config.py              │
└──────────────────────────────────────────────────────────────────────┘
```

## Why two Python packages (`omnivoice_core` + `server`)?

- `omnivoice_core/` is a **vendored snapshot** of upstream `omnivoice/`.
  Treat it as an immutable copy — never patch it ad-hoc; instead
  refresh it through the procedure in
  [`upstream_sync.md`](./upstream_sync.md). Its imports were
  rewritten from `omnivoice.utils.*` to `omnivoice_core.utils.*` to
  avoid colliding with a system-installed `omnivoice` package.
- `server/` is **100% Geny-owned**. It contains the FastAPI app,
  process-wide model holder, concurrency semaphore, voice-profile
  scanner, and audio encoders. This is where we add our own metrics,
  auth, batch endpoints, etc.

## Concurrency model

A single `asyncio.Semaphore(max_concurrency)` lives on the
`EngineState`. Each `POST /tts` acquires it before calling
`OmniVoice.generate(...)` inside `loop.run_in_executor(None, ...)`.

For single-GPU hosts (the common Geny setup) we keep
`max_concurrency=1`. The Geny backend adapter additionally holds a
module-level `asyncio.Lock` as a defense-in-depth guard, mirroring the
existing GPT-SoVITS adapter pattern.

## Failure modes

| Failure                                | What happens                                                              |
|----------------------------------------|---------------------------------------------------------------------------|
| Container can't reach HuggingFace      | `from_pretrained` raises during `lifespan`; `/health` stays `loading`; backend's `OmniVoiceEngine.health_check()` returns False; `TTSService` falls back to `edge_tts`. |
| GPU OOM mid-synthesis                  | `POST /tts` returns 500; backend falls back to `edge_tts` per the existing `TTSService.speak` retry logic. |
| Reference audio path doesn't exist     | `OmniVoice.create_voice_clone_prompt` raises; we surface 400. |
| `mode=design` but `instruct` missing   | 400.                                                                       |
| `mode=clone` but `ref_audio_path` missing | 400.                                                                    |
