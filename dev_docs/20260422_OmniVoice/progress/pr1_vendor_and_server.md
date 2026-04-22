# PR-OV-1: omnivoice/ 벤더링 + FastAPI 서버

## 변경
- `Geny/omnivoice/omnivoice_core/` — upstream `k2-fsa/OmniVoice`의
  `models/` + `utils/`를 sed로 import 경로 재작성하여 벤더링.
  - 보존: `model_type = "omnivoice"`, `AutoConfig.register("omnivoice", …)`,
    docstring (HuggingFace 체크포인트 메타데이터와 결합되어 있음 — 변경 시 로딩 실패).
- `Geny/omnivoice/server/` — FastAPI 래퍼.
  - `settings.py`: `OMNIVOICE_*` 환경변수 + `pydantic_settings`.
  - `engine.py`: `asyncio.Semaphore` + `loop.run_in_executor`로 GPU 호출 격리.
  - `api.py`: `/`, `/health`, `/voices`, `/languages`, `POST /tts`.
  - `voices.py`: `backend/static/voices/<id>/profile.json` 그대로 파싱
    (GPT-SoVITS와 동일 포맷).
  - `streaming.py`: WAV/MP3/OGG/PCM 인코딩.
- `pyproject.toml`, `Dockerfile` (CUDA 12.8 + Python 3.12 + torch 2.8).
- `tests/conftest.py` — `omnivoice_core` 스텁으로 GPU 없이 단위 테스트 가능.

## 결정
- ASR은 OmniVoice 내장(`load_asr=True` → `model._asr_pipe`) 사용.
  외부 `transformers.pipeline` 직접 호출 X.
- 동시성: 서버 + 백엔드 어댑터 양쪽에 락 (defense-in-depth).

## 검증
- 단위 테스트(스텁 기반): `tests/test_api_smoke.py`, `tests/test_engine_loading.py` 작성.
- 실제 모델 로드는 GPU 호스트의 Docker 빌드 단계에서 검증 예정.
