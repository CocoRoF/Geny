# 04. Environment 시스템 이식

## 목표

`geny-executor-web` v0.9.0 의 Environment 백엔드/라우터/프런트를 Geny 에 동등하게 구축.

## 백엔드

### 4-A. `backend/service/environment/` (신규)

```
backend/service/environment/
├── __init__.py
├── exceptions.py     # EnvironmentNotFoundError, StageValidationError
├── service.py        # EnvironmentService (web 의 environment_service.py 포팅)
└── storage/
    ├── __init__.py
    └── file_store.py  # ./data/environments/*.json 파일 I/O
```

`EnvironmentService` 메서드는 web 과 동일 (see `analysis/04_environment_feature_map.md §1-A`).

### 4-B. `backend/controller/environment_controller.py` (신규)

web `backend/app/routers/environment.py` 의 15 엔드포인트 포팅.

- 인증: Geny 의 `auth_controller` dependency 로 owner_username 바인딩.
- 응답 스키마: web 과 바이트 호환.

### 4-C. `backend/controller/catalog_controller.py` (신규)

세션 없이 stage introspection 을 노출하는 5 엔드포인트.
- `GET /api/catalog/stages`
- `GET /api/catalog/full`
- `GET /api/catalog/stages/{order}`
- `GET /api/catalog/stages/{order}/artifacts`
- `GET /api/catalog/stages/{order}/artifacts/{name}`

executor `geny_executor.core.introspect` 의 공용 함수 (web 에서 사용하는 것과 동일) 를 호출.

### 4-D. 세션 엔드포인트 확장

기존 `POST /api/agents` 요청에 두 필드를 선택적으로 추가:

```python
class CreateAgentSessionRequest(BaseModel):
    # ... 기존 필드들
    env_id: Optional[str] = None
    memory_config: Optional[Dict[str, Any]] = None
```

- `env_id` 지정시:
  - `environment_service.load_manifest(env_id)` → `Pipeline.from_manifest(manifest, api_key, strict=True)`
  - 이때 `GenyPresets.*` 경로는 bypass.
  - 응답의 `preset` 필드는 `"env:<id>"` 합성값.
- `memory_config` 지정시:
  - `memory_registry.provision(session_id, override=memory_config)` (Phase 4 에서 attach).

### 4-E. 저장 경로

- `./data/environments/*.json` — web 과 동일 포맷.
- Docker 볼륨: `docker-compose.yml` 에 환경별 디렉토리 마운트 추가.

## 프런트엔드

### 4-F. 라우팅

Next.js 14+ App Router 기준 (Geny `frontend/src/app/` 구조 확인 후 조정):

```
frontend/src/
├── app/
│   ├── environments/page.tsx       # EnvironmentView
│   └── builder/
│       └── [envId]/page.tsx        # StageList + StageCard
├── api/
│   └── environment.ts              # REST client (web 에서 포팅)
├── stores/
│   ├── environmentStore.ts
│   └── environmentBuilderStore.ts
├── types/
│   ├── environment.ts
│   └── catalog.ts
└── components/
    ├── environment/                # Card / Preview / Diff / Modal / Import
    └── builder/                    # StageList / StageCard / ConfigTab / …
```

### 4-G. 상태관리

Geny 가 어떤 상태관리 라이브러리를 쓰는지 `frontend/package.json` 으로 확인 후 선택:
- Zustand 이미 있다면 web 스토어를 그대로 포팅.
- Recoil / Redux 라면 등가 리듀서 작성.
- 없다면 Zustand 도입 (경량, web 과 가장 가까움).

### 4-H. 의존성

- `react-hot-toast` (web 과 동일) — 알림.
- `swr` 또는 `@tanstack/react-query` — 데이터 fetching (기존 Geny 에서 사용 중인 것 따라감).

## 배포

### 4-I. Docker 볼륨

```yaml
volumes:
  - ./data/environments:/app/backend/data/environments
  - ./data/memory:/app/backend/data/memory   # (Phase 3 에서 사용)
```

### 4-J. 환경 변수

- `ENVIRONMENT_STORAGE_PATH=./data/environments` (선택).
- `ENVIRONMENT_DEFAULT_PRESET=chat` (선택).

## 테스트

- `backend/tests/test_environments.py` — 세션 스냅샷 저장 (v0.7.x 호환 유지).
- `backend/tests/test_environments_v2.py` — 템플릿 CRUD + mode 분기 + 오류.
- `backend/tests/test_catalog.py` — 5 엔드포인트.
- `backend/tests/test_session_with_env.py` — `env_id` 로 세션 생성 후 정상 실행.
- 프런트: Playwright 또는 Cypress 로 Environment 탭 생성/편집/저장 시나리오.

## 수용 기준

- web 과 동일한 스키마로 20+ 엔드포인트 응답.
- `Pipeline.from_manifest` 경로로 세션이 실행되며 Geny 툴 + (Phase 4 이후) MemoryProvider 가 정상 동작.
- UI 가 Environment 를 CRUD 하고 세션을 "Run this Env" 로 시작.
