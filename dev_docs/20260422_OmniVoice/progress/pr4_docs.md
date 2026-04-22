# PR-OV-4: 운영자/개발자 문서

## 변경
- `Geny/docs/OmniVoice_INTEGRATION.md` (신규):
  운영자 가이드 — 기동, 헬스 체크, provider 전환, 환경변수, 보이스 프로필
  호환성, 트러블슈팅, GPT-SoVITS 제거 로드맵.
- `Geny/omnivoice/README.md`, `README_KO.md`: 서비스 자체 사용 가이드.
- `Geny/omnivoice/docs/`:
  - `architecture.md` — 컴포넌트/요청 흐름.
  - `api_contract.md` — `/tts` 요청/응답 스키마.
  - `voice_profile_format.md` — 디렉터리 + `profile.json` 명세.
  - `upstream_sync.md` — k2-fsa/OmniVoice 업스트림 재벤더링 절차 (sed 명령 포함).

## 결정
- 운영 문서는 `Geny/docs/` 아래 단일 파일로 — 사용자 진입점 단순화.
- 업스트림 동기화는 manual + checklist 방식 (자동 vendoring 스크립트는 추후).
