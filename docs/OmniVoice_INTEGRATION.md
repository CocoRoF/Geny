# OmniVoice 통합 가이드 (Geny TTS)

> **상태**: 추가 통합 완료 — GPT-SoVITS와 공존. 검증 후 GPT-SoVITS 제거 예정.

OmniVoice는 Geny 모노레포에 자체 호스팅되는 TTS 마이크로서비스입니다.
600+ 언어를 지원하며 voice cloning / voice design / auto 모드를 제공합니다.

- 코드: [`omnivoice/`](../omnivoice/)
- API 서버: `geny-omnivoice` 컨테이너, 포트 `9881`
- 백엔드 어댑터: [`backend/service/vtuber/tts/engines/omnivoice_engine.py`](../backend/service/vtuber/tts/engines/omnivoice_engine.py)
- 설정: [`backend/service/config/sub_config/tts/omnivoice_config.py`](../backend/service/config/sub_config/tts/omnivoice_config.py)

---

## 1. 빠른 시작

### 1-1. 서비스 기동
```bash
# Dev (코어 + omnivoice)
docker compose --profile tts-local -f docker-compose.dev.yml up -d omnivoice

# Prod
docker compose --profile tts-local -f docker-compose.prod.yml up -d omnivoice
```

최초 기동 시 HuggingFace에서 `k2-fsa/OmniVoice` 모델을 다운로드합니다 (~수 GB).
다운로드는 `geny-omnivoice-models[-prod|-dev]` 영구 볼륨에 캐시됩니다.

### 1-2. 헬스 체크
```bash
curl http://localhost:9881/health
# {"status": "ok", ...}  ← 사용 가능
# {"status": "loading"} ← 모델 로딩 중
```

### 1-3. Geny 백엔드에서 활성화
1. Geny UI의 **Settings → TTS → General** 에서 `provider`를 `omnivoice`로 변경.
2. **Settings → TTS → OmniVoice** 에서 `enabled = true`.
3. `api_url`은 도커 네트워크 기준 `http://omnivoice:9881` 유지.

GPT-SoVITS는 그대로 남아 있으며, `provider`만 바꾸면 즉시 전환됩니다.

---

## 2. 환경 변수

| 변수 | 기본값 | 설명 |
|---|---|---|
| `OMNIVOICE_MODEL` | `k2-fsa/OmniVoice` | HuggingFace 모델 이름 |
| `OMNIVOICE_DEVICE` | `cuda:0` | `cpu` / `cuda:N` |
| `OMNIVOICE_DTYPE` | `float16` | `float16` / `bfloat16` / `float32` |
| `OMNIVOICE_MAX_CONCURRENCY` | `1` | 동시 추론 슬롯 (GPU VRAM에 맞게) |
| `OMNIVOICE_AUTO_ASR` | `false` | `true`이면 Whisper 로드 → ref_text 자동 전사 |
| `OMNIVOICE_LOG_LEVEL` | `info` | uvicorn 로그 레벨 |

---

## 3. Voice Profile 호환성

OmniVoice는 GPT-SoVITS와 **동일한** 디렉터리 레이아웃을 사용합니다:

```
backend/static/voices/<profile_id>/
  profile.json
  ref_neutral.wav
  ref_happy.wav
  ...
```

`profile.json`의 `emotion_refs[<emo>].prompt_text`가 그대로 OmniVoice의
`ref_text`로 전달됩니다. 등록된 보이스 프로필은 두 엔진 모두에서 동작합니다.

`prompt_text`가 비어 있고 `auto_asr=true`이면 서버가 Whisper로 자동 전사합니다.

---

## 4. 모드 선택

| 모드 | 사용 사례 |
|---|---|
| `clone` | 등록된 보이스 프로필 재현. **권장 기본값.** |
| `design` | "female, low pitch, british accent" 등 자연어 지시문 |
| `auto` | 임의의 보이스 — 빠른 데모용 |

`design` 모드는 Config의 `instruct` 필드를 채워야 동작합니다.

---

## 5. 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `/health` 가 `loading` 상태로 멈춤 | 모델 다운로드 진행 중 — `docker logs geny-omnivoice` 확인 |
| `503 model_not_ready` | 모델 미로드 — 서비스 재시작 또는 GPU 메모리 확인 |
| `400 OmniVoice mode=design requires Config.instruct` | `instruct`를 비어 있지 않게 설정 |
| TTS가 무음 / 깨짐 | `denoise=false`로 토글, `num_step↑` (32 → 64) |
| GPU OOM | `OMNIVOICE_DTYPE=float16`, `OMNIVOICE_MAX_CONCURRENCY=1` |

---

## 6. GPT-SoVITS 제거 로드맵

OmniVoice 검증이 끝나면 다음 단계로 GPT-SoVITS를 제거합니다:

1. 모든 활성 보이스 프로필을 OmniVoice에서 회귀 테스트.
2. 사용자에게 마이그레이션 공지 → 기본 provider를 `omnivoice`로 전환.
3. 다음 사이클에서 `gpt-sovits` 서비스 / 엔진 / 설정 제거 (별도 PR).

본 사이클에서는 **순수 추가**만 수행했습니다 (`Pure Additive`).
