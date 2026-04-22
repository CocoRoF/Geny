# Cycle Close — 20260422 OmniVoice 통합

## 도달한 상태
- ✅ `Geny/omnivoice/` 마이크로서비스 (벤더링 + FastAPI + Dockerfile + 테스트).
- ✅ 5개 docker-compose 변형 중 `yml`, `dev.yml`, `prod.yml` 3개 갱신
  (`dev-core.yml`, `prod-core.yml`은 코어 전용으로 `tts-local` 비대상).
- ✅ 백엔드 어댑터 (Config + Engine + 등록 + provider 옵션 + 단위 테스트).
- ✅ 운영자 가이드 + PR 단위 retros.

## 불변 조건 유지
- **Pure Additive** — GPT-SoVITS 코드/이미지/설정 무손상.
- **Voice profile 포맷 미변경** — 기존 `static/voices/` 그대로 양 엔진에서 사용.
- **Fallback 체인 미변경** — TTSService → edge_tts.
- **Backend deps 미변경** — `requirements.txt`에 torch/omnivoice 추가 없음
  (HTTP 호출만으로 통신).

## 미검증 사항 (Follow-up)
- GPU 호스트에서 `docker compose --profile tts-local up omnivoice` 실제 빌드/기동.
- `k2-fsa/OmniVoice` 모델의 한국어 voice clone 품질 (paimon_ko 회귀 테스트).
- 다국어 TTS 회귀 (en/ja/zh/ko 4개 보이스 프로필).
- 백엔드 단위 테스트 (`pytest`)는 GPU 없는 dev 컨테이너에서 통과 가능
  (httpx MockTransport 사용).

## 다음 사이클 후보
- **OV-Cycle-2**: GPT-SoVITS 제거 (서비스/엔진/Config/리소스 파일 일괄).
- **OV-Cycle-3**: streaming chunked 응답 (현재는 한 번에 audio bytes 반환).
- **OV-Cycle-4**: 보이스 프로필 등록 UI에 "OmniVoice voice design" 폼 추가
  (instruct 자연어 → preview 생성).
