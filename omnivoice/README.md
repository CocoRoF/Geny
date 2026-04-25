# geny-omnivoice

A Geny-monorepo TTS microservice that wraps a vendored snapshot of
[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) behind a small
FastAPI HTTP layer.

This service replaces our previous reliance on the third-party
`xxxxrt666/gpt-sovits` Docker image by giving us:

- **Source-level ownership.** The inference engine lives in
  [`omnivoice_core/`](./omnivoice_core/) — a vendored snapshot that we can
  patch and ship without depending on an upstream image.
- **A clean HTTP contract.** [`server/`](./server/) exposes
  `POST /tts`, `GET /voices`, `GET /health`, `GET /languages`.
- **600+ language coverage**, voice cloning **and** voice design via
  the same `POST /tts` call.

> See the cycle plan at
> [`Geny/dev_docs/20260422_OmniVoice/index.md`](../dev_docs/20260422_OmniVoice/index.md)
> for the design rationale.

## Layout

```
omnivoice/
├── Dockerfile               CUDA 12.8 + PyTorch 2.8 image
├── pyproject.toml           geny-omnivoice package (omnivoice_core + server)
├── omnivoice_core/          Vendored inference subset of upstream omnivoice/
│   ├── models/omnivoice.py
│   └── utils/{audio,duration,lang_map,text,voice_design,common}.py
├── server/                  Geny-owned FastAPI wrapper
│   ├── main.py              FastAPI app + lifespan model loading
│   ├── api.py               HTTP routes
│   ├── engine.py            Process-wide model holder + concurrency gate
│   ├── voices.py            Voice profile discovery (compatible with backend/static/voices)
│   ├── streaming.py         wav / mp3 / ogg / pcm encoding helpers
│   ├── schemas.py           Pydantic request/response models
│   └── settings.py          OMNIVOICE_* env vars
├── tests/
└── docs/
```

## HTTP API

| Method | Path           | Notes                                                    |
|-------:|----------------|----------------------------------------------------------|
| GET    | `/`            | Service info (version, model id, device).                |
| GET    | `/health`      | Returns `loading` until the model finishes initialising. |
| GET    | `/voices`      | Lists profiles found under `OMNIVOICE_VOICES_DIR`.       |
| GET    | `/languages`   | All 600+ supported language names.                        |
| POST   | `/tts`         | Single-shot synthesis. Returns audio in `audio_format`.  |

`POST /tts` body (see [`server/schemas.py`](./server/schemas.py)):

```jsonc
{
  "text": "안녕하세요, 반갑습니다.",
  "mode": "clone",                 // clone | design | auto
  "ref_audio_path": "/voices/paimon_ko/ref_neutral.wav",
  "ref_text": "으음~ 나쁘지 않은데?",  // optional; omit + auto_asr=true → Whisper
  "instruct": null,                  // required iff mode=design
  "language": "ko",                  // optional; null = auto-detect
  "speed": 1.0,
  "duration": null,
  "num_step": 32,
  "guidance_scale": 2.0,
  "audio_format": "wav",
  "sample_rate": 24000
}
```

## Environment variables

All knobs use the `OMNIVOICE_` prefix.

| Var                         | Default                  | Description                                        |
|-----------------------------|--------------------------|----------------------------------------------------|
| `OMNIVOICE_MODEL`           | `k2-fsa/OmniVoice`       | HF repo id or absolute checkpoint path.            |
| `OMNIVOICE_DEVICE`          | `cuda:0`                 | `cuda:N`, `cpu`, or `mps`.                         |
| `OMNIVOICE_DTYPE`           | `float16`                | `float16` / `bfloat16` / `float32`.                |
| `OMNIVOICE_HOST`            | `0.0.0.0`                | uvicorn bind host.                                 |
| `OMNIVOICE_PORT`            | `9881`                   | uvicorn bind port.                                 |
| `OMNIVOICE_VOICES_DIR`      | `/voices`                | Container path to the voice profile directory.    |
| `OMNIVOICE_HF_CACHE`        | `/models/hf-cache`       | HuggingFace cache; mirrored to `HF_HOME`.          |
| `OMNIVOICE_AUTO_ASR`        | `false`                  | Load Whisper for ref-text auto-transcription.      |
| `OMNIVOICE_ASR_MODEL`       | `openai/whisper-large-v3-turbo` | Whisper model id (only when `auto_asr=true`).|
| `OMNIVOICE_MAX_CONCURRENCY` | `4`                      | In-flight synthesis slots. Default tuned for RTX 5070 (12 GB, fp16). Drop to 1–2 on smaller / shared GPUs. |
| `OMNIVOICE_DEFAULT_NUM_STEP` | `16`                    | Diffusion outer-loop steps. 32 = upstream default, 16 = balanced, 8–12 = speed-first. |
| `OMNIVOICE_GPU_MEMORY_FRACTION` | `0.85`               | Per-process VRAM cap. 0 disables the cap. |
| `OMNIVOICE_LOG_LEVEL`       | `info`                   | uvicorn log level.                                 |

## Running locally (without Docker)

```bash
cd Geny/omnivoice
pip install torch==2.8.0 torchaudio==2.8.0 \
    --extra-index-url https://download.pytorch.org/whl/cu128
pip install -e ".[dev]"
geny-omnivoice-server
```

## Running via docker-compose (full Geny stack)

```bash
# from the Geny/ root
docker compose --profile tts-local up --build
# or for development with live-reload of server/
docker compose -f docker-compose.dev.yml --profile tts-local up --build
```

The compose service is named `omnivoice` and is reachable from the
backend container at `http://omnivoice:9881`.

## Voice profile format

Compatible with the existing GPT-SoVITS layout under
[`Geny/backend/static/voices/`](../backend/static/voices), which is
bind-mounted into this container at `/voices`.

```
voices/
└── paimon_ko/
    ├── profile.json        { "display_name": "...", "language": "ko", "emotion_refs": { ... } }
    ├── ref_neutral.wav
    └── ref_joy.wav
```

See [`docs/voice_profile_format.md`](./docs/voice_profile_format.md).

## Upstream sync

`omnivoice_core/` is a *snapshot copy* of upstream `omnivoice/` (inference
subset). To refresh, see [`docs/upstream_sync.md`](./docs/upstream_sync.md).

## License

`omnivoice_core/` retains its upstream **Apache-2.0** license. The Geny
wrapper code under `server/` is also Apache-2.0.
