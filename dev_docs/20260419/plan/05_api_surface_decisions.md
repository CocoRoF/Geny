# 05. API 표면 결정

Geny 는 이미 40+ 개의 엔드포인트 (agent / chat / vtuber / tts / docs / tool / auth / memory / curated / opsidian / …) 를 보유. 여기에 Environment + Memory (신규) 와 레거시 메모리 정리를 결정한다.

## 유지할 것

| 라우터 | 이유 |
|--------|------|
| `/api/auth/*` | 로그인·권한. 모든 신규 엔드포인트에 통합. |
| `/api/agents/*` (세션 수명/실행) | 실전 사용 중. `env_id`, `memory_config` 옵션 추가. |
| `/api/chat/rooms/*` | 브로드캐스트. |
| `/api/vtuber/*`, `/api/tts/*`, `/api/docs/*`, `/api/tools/*`, `/api/tool-presets/*` | 도메인 전용. |
| `/api/shared-folder/*` | 세션 간 파일 공유. |
| `/api/config/*` | 설정. |
| `/api/agents/{id}/storage/*` | 스토리지 브라우저. |

## 신규 추가 (Phase 3 / 4)

| 라우터 | 설명 | 참조 |
|--------|------|------|
| `/api/environments/*` | 15 endpoints (v2 CRUD + preset + share + diff + import/export) | `plan/04` |
| `/api/catalog/*` | 5 endpoints (stage introspection) | `plan/04` |
| `/api/sessions/{id}/memory/*` | 3 endpoints (descriptor, retrieve, clear) | `plan/03` |

## 정리 대상 (Phase 7)

| 라우터 | 결정 |
|--------|------|
| `/api/agents/{id}/memory/*` (14 endpoints) | 유지하되 **내부를 MemoryProvider 기반으로 재구현**. 스키마는 기존과 동일. 클라이언트 영향 없음. |
| `/api/curated/*` (~15) | 유지. 내부: `CuratedHandle` 호출. 파일 경로는 호환 유지. |
| `/api/opsidian/*` (~14) | 유지. Geny 도메인 로직 (사용자 볼트 인제스트) 가 executor 범위 밖이므로 래퍼 형태로 남김. |

## 인증/권한 정책

- Environment 엔드포인트: 로그인 필요 + `owner_username` 필드로 소유자 확인.
  - Superadmin (Geny 의 기존 개념 확인 필요) 은 전체 열람 가능.
- Memory 엔드포인트: 세션 소유자 또는 superadmin.
- Catalog 엔드포인트: 로그인 필요 (민감 정보는 없지만 외부 노출 방지).

## 응답 스키마 정합

- web 과 필드명/타입을 1 : 1 로 맞춘다. Pydantic v2 사용.
- 응답에 Geny 고유 필드 (예: `owner_username`) 는 web 에 없어도 추가 가능. 단 기본값 / Optional.

## WS 이벤트

- 기존 세션 WS 스트림은 유지.
- Environment 편집/메모리 이벤트는 **별도 WS 도입하지 않음** (polling/HTTP 충분; web 도 동일 결정).

## 수용 기준

- 라우터 충돌 없음.
- 인증 정책이 모든 신규 엔드포인트에 일관 적용.
- 스키마가 web 과 호환되어 필요 시 web 프런트를 Geny 에 그대로 붙일 수 있을 정도.
