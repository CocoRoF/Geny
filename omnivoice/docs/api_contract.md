# HTTP API contract

This document is the source of truth for what the
`backend/service/vtuber/tts/engines/omnivoice_engine.py` adapter expects
from this service.

## `GET /`

```jsonc
{
  "service": "geny-omnivoice",
  "version": "0.1.0",
  "model":   "k2-fsa/OmniVoice",
  "device":  "cuda:0",
  "dtype":   "float16"
}
```

## `GET /health`

Returns 200 in all loading phases. Inspect `status`:

| `status`  | Meaning                                                       |
|-----------|---------------------------------------------------------------|
| `loading` | The lifespan task hasn't finished `from_pretrained` yet.      |
| `ok`      | Model is resident and ready.                                  |
| `error`   | (Reserved.) Returned when a fatal error is detected.          |

```jsonc
{
  "status": "ok",
  "model": "k2-fsa/OmniVoice",
  "device": "cuda:0",
  "dtype": "float16",
  "sampling_rate": 24000,
  "auto_asr": false,
  "max_concurrency": 1
}
```

## `GET /voices`

Reflects every subdirectory of `OMNIVOICE_VOICES_DIR`. See
[`voice_profile_format.md`](./voice_profile_format.md).

## `GET /languages`

Returns the sorted list of every language name OmniVoice can address.

## `POST /tts`

### Request

```jsonc
{
  "text": "...",                          // required, non-empty
  "mode": "clone",                        // clone | design | auto
  "ref_audio_path": "/voices/.../ref_neutral.wav",
  "ref_text": "...",                      // optional; null + auto_asr=true → Whisper
  "instruct": "female, british accent",   // required iff mode=design; optional otherwise
  "language": "ko",                       // null = auto-detect
  "speed": 1.0,
  "duration": null,                       // seconds; overrides speed if set
  "num_step": 32,                         // 1..128
  "guidance_scale": 2.0,                  // 0..10
  "denoise": true,
  "preprocess_prompt": true,
  "postprocess_output": true,
  "audio_format": "wav",                  // wav | mp3 | ogg | pcm
  "sample_rate": 24000
}
```

### Response

| Status | Body            | When                                                 |
|-------:|-----------------|------------------------------------------------------|
| 200    | audio bytes     | Success — `Content-Type` reflects `audio_format`.    |
| 400    | `{detail: ...}` | Validation error (e.g. `clone` mode without `ref_audio_path`).|
| 500    | `{detail: ...}` | Synthesis failed inside the model.                   |
| 503    | `{detail: model_not_ready}` | `/health` is still `loading`.            |

Headers always present on 200:

- `X-OmniVoice-Sample-Rate`: integer Hz
- `X-OmniVoice-Mode`: echoed mode (`clone` / `design` / `auto`)

### Audio formats

| `audio_format` | `Content-Type`             | Notes                                |
|----------------|----------------------------|--------------------------------------|
| `wav`          | `audio/wav`                | int16 PCM, mono.                     |
| `mp3`          | `audio/mpeg`               | Requires ffmpeg (provided in image). |
| `ogg`          | `audio/ogg`                | Vorbis via libsndfile.               |
| `pcm`          | `application/octet-stream` | Raw int16, little-endian, mono.      |

### Concurrency

Synthesis is gated by `OMNIVOICE_MAX_CONCURRENCY` (default 1). Excess
callers wait on a semaphore — no 429 is returned.
