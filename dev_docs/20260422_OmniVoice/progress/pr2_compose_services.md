# PR-OV-2: docker-compose 통합

## 변경
세 개의 compose 파일에 **순수 추가**로 `omnivoice` 서비스 + 모델 캐시 볼륨을 주입.
GPT-SoVITS 블록은 손대지 않음.

| 파일 | 컨테이너 | 네트워크 | 노출 | 모델 볼륨 |
|---|---|---|---|---|
| `docker-compose.yml` | `geny-omnivoice` | `geny-net` | `9881` (ports) | `geny-omnivoice-models` |
| `docker-compose.dev.yml` | `geny-omnivoice-dev` | `geny-net-dev` | `9881` (ports) + bind-mount + `--reload` | `geny-omnivoice-models-dev` |
| `docker-compose.prod.yml` | `geny-omnivoice-prod` | `geny-net-prod` | `expose: 9881` (nginx-fronted) | `geny-omnivoice-models-prod` |

공통:
- `profiles: ["tts-local"]` — GPT-SoVITS와 동일하게 옵트인.
- `geny-voices[-prod|-dev]` 볼륨을 `/voices:ro`로 공유 (보이스 프로필 호환).
- NVIDIA GPU device reservation.
- HEALTHCHECK `start_period: 300s` (모델 다운로드 시간 고려).

## 검증
- `docker compose config` 통과 여부는 GPU 호스트에서 확인 예정.
