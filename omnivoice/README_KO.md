# geny-omnivoice (한국어)

Geny 모노레포에 추가된 자체 TTS 마이크로서비스입니다.
[k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) 의 추론 코드를
[`omnivoice_core/`](./omnivoice_core/) 에 *vendoring* 하고, 그 위에
[`server/`](./server/) 가 FastAPI 래퍼를 얹습니다.

이전까지는 `xxxxrt666/gpt-sovits` 도커 이미지에 의존해
[`backend/service/vtuber/tts/engines/gpt_sovits_engine.py`](../backend/service/vtuber/tts/engines/gpt_sovits_engine.py)
가 HTTP 로 호출했지만, 이미지 내부 소스를 손댈 수 없다는 제약이 컸습니다.
geny-omnivoice 는 이 문제를 정면 해결합니다.

> 본 서비스의 설계 배경과 단계별 계획은
> [`Geny/dev_docs/20260422_OmniVoice/index.md`](../dev_docs/20260422_OmniVoice/index.md)
> 에서 확인하세요.

## 핵심 차이점

- **소스 소유.** `omnivoice_core/` 가 우리 레포에 들어 있으므로 자유롭게
  패치/디버깅 가능합니다.
- **600+ 언어, voice cloning + voice design** 을 같은 `POST /tts` 로 호출.
- **FastAPI** — `/tts`, `/voices`, `/health`, `/languages` 표준 엔드포인트.

## 레이아웃

`README.md` 의 "Layout" 절을 참고해 주세요. 디렉터리 구조 / 환경변수 /
HTTP API 명세는 영문판과 동일합니다.

## docker-compose 로 실행

```bash
# Geny/ 루트에서
docker compose --profile tts-local up --build              # 풀스택
docker compose -f docker-compose.dev.yml --profile tts-local up --build  # 개발 모드 (server/ hot-reload)
```

backend 컨테이너에서는 `http://omnivoice:9881` 로 접근합니다.

## Voice profile

[`Geny/backend/static/voices/`](../backend/static/voices) 의 기존 GPT-SoVITS
형식과 100% 호환됩니다. 컨테이너에 `/voices` 로 read-only 바인드 마운트됩니다.

## 업스트림 동기화

`omnivoice_core/` 는 [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice)
의 *고정 시점 스냅샷* 입니다. 갱신 절차는
[`docs/upstream_sync.md`](./docs/upstream_sync.md) 참조.

## 라이선스

`omnivoice_core/` 는 업스트림 라이선스인 **Apache-2.0** 을 그대로 따릅니다.
`server/` 도 Apache-2.0.
