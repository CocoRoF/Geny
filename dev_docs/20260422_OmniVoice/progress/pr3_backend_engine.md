# PR-OV-3: 백엔드 어댑터 (Config + Engine)

## 변경
- `backend/service/config/sub_config/tts/omnivoice_config.py` (신규):
  `@register_config OmniVoiceConfig` — provider 키 `tts_omnivoice`.
  필드: `enabled, api_url, mode (clone/design/auto), voice_profile,
  instruct, language, num_step, guidance_scale, speed, duration_seconds,
  denoise, audio_format, auto_asr, timeout_seconds`.
  보이스 프로필 옵션은 GPT-SoVITS와 동일하게 `static/voices/` 스캔.
- `backend/service/vtuber/tts/engines/omnivoice_engine.py` (신규):
  - `OmniVoiceEngine(TTSEngine)`, `engine_name = "omnivoice"`.
  - 모듈 레벨 `_synthesis_lock = asyncio.Lock()` (서버 측 세마포어와 별개로 유지).
  - `synthesize_stream` → `httpx.AsyncClient` POST `/tts`.
  - `health_check` → 서버가 `loading` 이면 `False` (TTSService fallback 보장).
  - `get_voices` → 서버 `/voices` 프록시.
  - `_resolve_emotion_ref` → backend 경로(`/app/static/voices/...`)에서
    프로필을 찾고, 컨테이너 ref 경로(`/voices/<profile>/<file>`)로 변환.
- `backend/service/vtuber/tts/tts_service.py`: 싱글턴에 `OmniVoiceEngine()` 등록.
- `backend/service/config/sub_config/tts/tts_general_config.py`:
  provider SELECT에 `omnivoice` 옵션 추가.
- `backend/tests/service/vtuber/test_omnivoice_engine.py` (신규):
  `httpx.MockTransport`로 7개 케이스 — health, design 검증 실패,
  clone payload, voice 프록시, emotion fallback 등.

## 결정
- 백엔드는 HTTP 전용 — `requirements.txt`에 torch/omnivoice deps 추가하지 않음.
- `request.voice_profile`(세션 오버라이드) > `config.voice_profile`.
- `config.speed * request.speed`로 합성 (TTSService가 이미 emotion-applied speed를 넘김).

## 호환성
- GPT-SoVITS와 완전 공존 — TTSService 라우팅은 `provider` 키만 보고 분기.
- 동일 voice profile이 두 엔진에서 동작 (`profile.json` 포맷 변경 없음).
