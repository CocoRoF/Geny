# 04. `geny-executor-web` ENVIRONMENT 기능 지도

> web v0.9.0 (2026-04-19 릴리스). Geny 는 이 표면을 *완전히* 재현해야 한다.
> 모든 파일 경로는 `/home/geny-workspace/geny-executor-web/` 기준.

## 1. 백엔드 서비스

### 1-A. `EnvironmentService` (`backend/app/services/environment_service.py`)

디스크에 v2 매니페스트를 저장·로드·변환하는 단일 퍼시스턴스 서비스.

공개 메서드 (시그니처):

```python
def __init__(storage_path: str = "./data/environments"):
def load_manifest(env_id: str) -> Optional[EnvironmentManifest]:
def save(session, mutator, name, description, tags) -> str:
def load(env_id: str) -> Optional[Dict]:
def list_all() -> List[Dict]:
def update(env_id: str, changes: Dict) -> Optional[Dict]:
def delete(env_id: str) -> bool:
def export_json(env_id: str) -> Optional[str]:
def import_json(data: Dict) -> str:
def create_blank(name, description, tags, base_preset) -> str:
def create_from_preset(preset_name, name, description, tags) -> str:
def update_manifest(env_id, manifest: EnvironmentManifest) -> Dict:
def update_stage(env_id, order, *, artifact=None, strategies=None,
                 strategy_configs=None, config=None, tool_binding=None,
                 model_override=None, chain_order=None, active=None) -> Dict:
def duplicate(env_id, new_name) -> Optional[str]:
def instantiate_pipeline(env_id, api_key, strict=True) -> Pipeline:
def diff(env_id_a, env_id_b) -> List[Dict]:
```

상수:

- `_PRESET_FACTORIES = {"minimal", "chat", "agent", "evaluator", "geny_vtuber"}` → `PipelinePresets` 팩토리 메서드 바인딩.
- `_REQUIRED_ORDERS = frozenset({1, 6, 9, 16})` — 항상 active 로 강제.

executor 와의 결합:
- `EnvironmentManifest.from_dict / from_snapshot / blank_manifest`
- `Pipeline.from_manifest(manifest, api_key, strict)`
- `PipelineMutator(pipeline).snapshot()` (legacy 저장 경로)

### 1-B. `MemorySessionRegistry` (`backend/app/services/memory_service.py`)

세션 단위 `MemoryProvider` 생명주기 매니저 (v0.9.0 신규).

```python
def __init__(factory=None, default_config=None):
def provision(session_id, override=None) -> Optional[MemoryProvider]:
def get(session_id) -> Optional[MemoryProvider]:
def require(session_id) -> MemoryProvider:
def get_config(session_id) -> Optional[Dict]:
def release(session_id) -> bool:                  # async-close-aware
def attach_to_pipeline(pipeline, provider):       # stage 2 에 provider 세팅
def describe(session_id) -> Dict:                 # 세션 ID / provider / version / scope / layers / capabilities / backends / metadata / config
def default_config() -> Optional[Dict]:
```

- `attach_to_pipeline` 은 `pipeline.get_stage(2)` 가 `provider` 속성을 가지면 세팅. (Context 스테이지 전용 — 0.20 executor 의 공식 훅)
- `release` 는 `provider.close()` 가 코루틴일 때 현재 이벤트 루프에 `create_task` 로 스케줄하거나, 루프가 없으면 `asyncio.run` 으로 즉시 완주.

### 1-C. 예외 (`backend/app/services/exceptions.py`)

```python
class EnvironmentNotFoundError(LookupError): ...
class StageValidationError(ValueError): ...
class MemoryConfigError(ValueError): ...
class MemorySessionNotFoundError(LookupError): ...
```

### 1-D. `SessionService` (참고)

`create(pipeline, preset, *, memory_config=None)` 시 `memory_registry.provision(session_id, override=memory_config)` 후 `attach_to_pipeline` 호출.
`delete(session_id)` 시 `memory_registry.release(session_id)` 호출.

### 1-E. `CatalogRouter` (`backend/app/routers/catalog.py`)

- `GET /api/catalog/stages` — 16 행 요약
- `GET /api/catalog/full` — 전체 introspection
- `GET /api/catalog/stages/{order}` — 기본 artifact
- `GET /api/catalog/stages/{order}/artifacts` — artifact 목록
- `GET /api/catalog/stages/{order}/artifacts/{name}` — 단일 introspection

## 2. REST 엔드포인트 목록

### `/api/environments`

| Verb | Path | 요청 | 응답 |
|------|------|------|------|
| GET | `` | — | `EnvironmentListResponse` |
| POST | `` | `CreateEnvironmentRequest` (mode=`blank`\|`from_session`\|`from_preset`, 자동추론 지원) | `CreateEnvironmentResponse` |
| POST | `/from-session` | `SaveEnvironmentRequest` | `CreateEnvironmentResponse` |
| GET | `/{env_id}` | — | `EnvironmentDetailResponse` |
| PUT | `/{env_id}` | `UpdateEnvironmentRequest` | `{"updated": bool}` |
| DELETE | `/{env_id}` | — | `{"deleted": bool}` |
| PUT | `/{env_id}/manifest` | `UpdateManifestRequest` | `EnvironmentDetailResponse` |
| PATCH | `/{env_id}/stages/{order}` | `UpdateStageTemplateRequest` | `EnvironmentDetailResponse` |
| POST | `/{env_id}/duplicate` | `DuplicateEnvironmentRequest` | `CreateEnvironmentResponse` |
| POST | `/{env_id}/preset` | — | `{"marked": bool}` |
| DELETE | `/{env_id}/preset` | — | `{"unmarked": bool}` |
| GET | `/{env_id}/export` | — | `{"data": str}` |
| POST | `/import` | `ImportEnvironmentRequest` | `CreateEnvironmentResponse` |
| GET | `/{env_id}/share` | — | `ShareLinkResponse` |
| POST | `/diff` | `DiffEnvironmentsRequest` | `EnvironmentDiffResponse` |

### `/api/sessions/{session_id}/memory`

| Verb | Path | 요청 | 응답 |
|------|------|------|------|
| GET | `/memory` | — | `MemoryDescriptorResponse` |
| POST | `/memory/retrieve` | `MemoryRetrievalRequest` | `MemoryRetrievalResponse` (407 when `SEARCH` 미지원) |
| DELETE | `/memory` | — | `{"cleared": bool}` |

### `/api/sessions`

기존 엔드포인트가 `env_id` 와 `memory_config` 를 받도록 확장됨.

## 3. 스키마 (요청/응답 shape)

### Environment

```python
# 요청
SaveEnvironmentRequest  {session_id, name, description, tags}
CreateEnvironmentRequest  {mode?, name, description?, tags?, session_id?, preset_name?}
UpdateEnvironmentRequest  {name?, description?, tags?}
UpdateManifestRequest  {manifest: Dict}
UpdateStageTemplateRequest  {artifact?, strategies?, strategy_configs?, config?, tool_binding?, model_override?, chain_order?, active?}
DuplicateEnvironmentRequest  {new_name}
DiffEnvironmentsRequest  {env_id_a, env_id_b}
ImportEnvironmentRequest  {data: Dict}

# 응답
EnvironmentSummaryResponse  {id, name, description, tags, created_at, updated_at, stage_count, active_stage_count, model, base_preset}
EnvironmentDetailResponse  {id, name, description, tags, created_at, updated_at, manifest?, snapshot?}
EnvironmentListResponse  {environments: [Summary]}
CreateEnvironmentResponse  {id}
DiffEntry  {path, change_type, old_value, new_value}
EnvironmentDiffResponse  {identical, entries, summary}
ShareLinkResponse  {url}
```

### Memory

```python
MemoryBackendInfo  {layer, backend}
MemoryDescriptorResponse  {session_id, provider, version, scope, layers, capabilities, backends, metadata, config?}
MemoryRetrievalRequest  {query, top_k?, layers?, tags?}
MemoryChunkPayload  {key, content, source, relevance_score, metadata}
MemoryRetrievalResponse  {chunks}
```

## 4. 프런트엔드 표면

### 4-A. API 클라이언트 (`frontend/src/api/environment.ts`)

Environment: `fetchEnvironments / saveEnvironment / fetchEnvironmentV2 / updateEnvironment / deleteEnvironment / createEnvironment / replaceManifest / duplicateEnvironment / markAsPreset / unmarkPreset / getShareLink / exportEnvironment / importEnvironment / diffEnvironments`.

History (참고): `fetchSessionHistory / fetchAllHistory / fetchRunDetail / fetchRunEvents`.

### 4-B. Zustand 스토어

- `environmentStore`: 목록/상세/업데이트/삭제/임포트/익스포트/diff/프리셋토글/공유링크.
- `environmentBuilderStore`: 로컬 드래프트 편집 전용. `draft: EnvironmentManifest | null` + `dirty: boolean`; `loadTemplate / saveDraft / updateStageDraft / discardDraft / createFromPreset / duplicateTemplate / closeTemplate`.

### 4-C. 타입 (`frontend/src/types/environment.ts`)

`EnvironmentMetadata / StageToolBinding / StageModelOverride / StageManifestEntry / ToolsSnapshot / EnvironmentManifest / CreateEnvironmentPayload / UpdateStageTemplatePayload / EnvironmentDetailV2`.

### 4-D. 컴포넌트

- **Environment 탭**: `EnvironmentView`, `EnvironmentCard`, `EnvironmentPreview`, `EnvironmentDiffView`, `EnvironmentSaveModal`, `EnvironmentShareModal`, `EnvironmentImport`.
- **Builder 탭**: `StageList`, `StageCard` (4 탭 — `ConfigTab` / `ToolsTab` / `ModelTab` / `ChainTab`), `ConfigSchemaForm`.

## 5. Deploy / config 배관

`docker-compose.yml`:

```yaml
backend:
  environment:
    - MEMORY_PROVIDER=${MEMORY_PROVIDER:-ephemeral}
    - MEMORY_DSN=${MEMORY_DSN:-}
    - MEMORY_DIALECT=${MEMORY_DIALECT:-}
    - MEMORY_ROOT=${MEMORY_ROOT:-}
    - MEMORY_TIMEZONE=${MEMORY_TIMEZONE:-}
    - MEMORY_SCOPE=${MEMORY_SCOPE:-session}

# 옵션 postgres 서비스 (주석 상태)
```

`backend/app/config.py`:

```python
class Settings:
    memory_provider: str
    memory_dsn: str
    memory_dialect: str
    memory_root: str
    memory_timezone: str
    memory_scope: str

    def default_memory_config() -> dict:
        # file → root 필수, sql → dsn 필수; 옵션값은 생략
```

`backend/app/main.py` 의 lifespan:

```python
memory_registry = _build_memory_registry()   # ValueError swallow → 비활성 안전
app.state.memory_service = memory_registry
app.state.session_service = SessionService(memory_registry=memory_registry)
app.include_router(memory.router)
```

## 6. 테스트 보증

| 파일 | 보장하는 행위 |
|------|-------------|
| `backend/tests/test_environments.py` | 세션 스냅샷 저장 (v0.7.x 호환) |
| `backend/tests/test_environments_v2.py` | `POST /api/environments` mode 분기 (blank/from_session/from_preset) + `PUT /manifest` + `PATCH /stages/{order}` + `duplicate` + 오류 코드 |
| `backend/tests/test_memory_session.py` | memory 디스크립터 / missing / clear / 세션 삭제 연동 / 잘못된 config 400 |
| `backend/tests/test_catalog.py` | 카탈로그 라우터 5 엔드포인트 |
| `backend/tests/conftest.py` | `FakeMemoryRegistry`, `FakeSessionService` 로 executor 없이 라우터를 E2E 테스트 |

## 7. CHANGELOG 슬라이스 (v0.7 → v0.9)

- **0.8.0** — 빈 Environment + preset 기반 Environment 빌더; `/api/catalog` 라우터; `PUT /manifest`; `PATCH /stages/{order}`; `POST /duplicate`; `POST /api/sessions` 가 `env_id` 수용.
- **0.8.1** — blank 생성 경로 수정, `fetchPresets` 중복 제거, pin `>=0.13.1`.
- **0.8.2** — 카탈로그 타입 정합 (`strategy_chains`, `tool_binding_supported`, `model_override_supported` 등).
- **0.8.3** — 스테이지별 capability flag 에 따른 탭 가시성 제어.
- **0.8.4** — 빌더를 "로컬 드래프트 + 명시적 Save" 모델로 전환 (`draft / dirty / saveDraft`).
- **0.8.5** — 파이프라인 뷰에서 저장 Env 로 세션 시작 가능; 필수 스테이지 비활성 금지.
- **0.8.6** — Environment 미리보기가 v2 매니페스트를 직접 표시.
- **0.8.7** — blank env 가 필수 스테이지를 active 로 내려받음 (`StageIntrospection.required`).
- **0.8.9** — 3 개 회귀 픽스 (required 필드 누락 / bypass 스타일 / env-backed 세션 describe).
- **0.9.0** — **per-session memory** — `MemorySessionRegistry`, `MEMORY_*` env, `memory_config` 옵션, `/api/sessions/{id}/memory` 3 엔드포인트.

## 8. Geny 가 재현해야 하는 것 — 통합 목록

1. **`EnvironmentService`** (저장/로드/리스트/업데이트/매니페스트 교체/스테이지 PATCH/복제/임포트/익스포트/diff/인스턴스화).
2. **Environment REST 15 엔드포인트** (위 §2-A).
3. **Catalog REST 5 엔드포인트** (세션 없이 스테이지 introspection 제공).
4. **`MemorySessionRegistry`** + **memory REST 3 엔드포인트** + **`MEMORY_*` env** + **세션 생성시 `memory_config` 옵션**.
5. **CreateSessionRequest.env_id** → 저장된 매니페스트로 세션 기동 + 응답 preset 라벨 `"env:<id>"`.
6. **필수 스테이지 (1, 6, 9, 16) active 강제** + **`provider: mock` → `anthropic` 자동 교정**.
7. **프런트 Environment 탭** (리스트/상세/미리보기/diff/저장모달/공유모달/임포트).
8. **프런트 Builder 탭** (StageList + StageCard 4 탭 + ConfigSchemaForm).
9. **Zustand `environmentStore` + `environmentBuilderStore`** 동등품 (Geny 는 Next.js + 상태관리 라이브러리 확인 필요).
10. **문서/테스트** — Geny 측 `test_environments_v2.py` 상응 + `test_memory_session.py` 상응.

## 9. 주의할 Geny-특이 요소

- Geny 의 UI 는 Next.js (`frontend/`) — 프런트 Zustand 코드는 동등한 상태 관리 수단 (Zustand 또는 React Context) 로 포팅해야 함.
- Geny 에는 **인증/권한** (auth_controller, `gkfua00@gmail.com` 소유 정책) 이 있어 environment/memory 엔드포인트에도 `owner_username` 등 인가 필드 추가가 필요할 가능성 — `plan/05_api_surface_decisions.md` 에서 결정.
- Geny 는 이미 `CurationEngine`, `ThinkingTriggerService` 등 배경 서비스 와 메모리 로직이 얽혀 있음 — Environment 기동 시점과의 순서 관리 필요.
