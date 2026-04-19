# 03. `geny-executor` API 델타: 0.8.3 → 0.20.0

> 모든 경로/심볼은 `/home/geny-workspace/geny-executor` 에서 직접 확인 완료 (2026-04-19).

## 1. Import 경로 호환 매트릭스

Geny 가 현재 사용 중인 심볼 기준:

| 심볼 | 0.8.3 | 0.20.0 | 상태 | 비고 |
|------|-------|--------|------|------|
| `geny_executor.memory.GenyPresets` | 존재 | **존재** (`geny_executor/memory/presets.py:56`) | ✔ 호환 | 구현은 `PipelineBuilder` 기반으로 완전 재작성됨 |
| `GenyPresets.worker_easy` | 존재 | **존재** | ✔ | |
| `GenyPresets.worker_full` | (없음 / 다른 이름?) | **존재** | +신규 | 0.8 대비 추가된 프리셋 |
| `GenyPresets.worker_adaptive` | 존재 | **존재** | ✔ | |
| `GenyPresets.vtuber` | 존재 | **존재** | ✔ | |
| `geny_executor.tools.registry.ToolRegistry` | 존재 | 존재 | ✔ | 시그니처 안정 |
| `geny_executor.tools.base.{Tool, ToolContext, ToolResult}` | 존재 | 존재 | ✔ | `ToolContext` 에 `stage_order/stage_name` 추가 (기본값 안전) |
| `geny_executor.tools.built_in.{ReadTool,WriteTool,EditTool,BashTool,GlobTool,GrepTool}` | 존재 | 존재 | ✔ | 내부 변경 있으나 생성자 시그니처 호환 |
| `geny_executor.core.state.PipelineState` | 존재 | 존재 | ✔ | 필드 추가만 있음 (append-only) |

**의미**: Geny 의 현 import 문은 **0.20.0 에서도 그대로 통과한다**. 그러나 *동작 의미* 는 다음 섹션에서 보듯이 크게 달라졌다.

## 2. 모듈 구조 (0.20.0)

`src/geny_executor/`:

```
├── __init__.py
├── core/          # Pipeline / PipelineBuilder / PipelinePresets / State / Stage base
├── events/        # EventBus + PipelineEvent
├── history/       # (신규) 실행 이력 기록
├── memory/        # MemoryProvider / 프로바이더들 / presets (GenyPresets 포함)
├── security/      # (신규)
├── session/       # (신규) SessionManager / SessionContext
├── stages/        # s01_input … s16_yield (16 디렉토리)
└── tools/         # base / registry / built_in / adhoc
```

## 3. 파이프라인 구축 — 이전 vs 현재

### 0.8.3 관례

```python
from geny_executor.memory import GenyPresets
pipeline = GenyPresets.vtuber(api_key=..., memory_manager=session_mem)
```

내부: 프리셋이 고정 스테이지 집합으로 Pipeline 을 직접 빌드.

### 0.20.0 정식 경로

세 가지가 공존한다.

#### (a) PipelineBuilder — 플루언트 API (0.13 도입)

```python
from geny_executor.core.builder import PipelineBuilder

pipeline = (
    PipelineBuilder("worker-easy", api_key=api_key, model=model)
    .with_context(retriever=retriever)
    .with_system(builder=builder)
    .with_guard()
    .with_cache(strategy="system")
    .with_memory(strategy=strategy, persistence=persistence)
    .build()
)
```

#### (b) PipelinePresets — 내장 프리셋 (`core/presets.py:208`)

```python
from geny_executor import PipelinePresets
pipeline = await PipelinePresets.build("chat", api_key=...)
# list(): [("chat", info), ("agent", info), ("evaluator", info), ("minimal", info), ("geny_vtuber", info)]
```

#### (c) Pipeline.from_manifest — YAML 블루프린트 (0.13 도입)

```python
from geny_executor import Pipeline, EnvironmentManifest
manifest = EnvironmentManifest.from_file("env.yaml")
pipeline = Pipeline.from_manifest(manifest, api_key=...)
```

### GenyPresets (`memory/presets.py`) 의 현재 역할

- **여전히 Pipeline 을 반환**하며 내부에서 `PipelineBuilder` 와 `GenyMemoryRetriever/GenyMemoryStrategy/GenyPersistence` 어댑터를 조립.
- 역할은 "Geny 의 `SessionMemoryManager` 를 `MemoryProvider` 스펙에 적응시키는 브리지".
- **즉 Geny 는 `GenyPresets` 를 유지해도 되고, 버릴 수도 있다**. 유지하면 Geny 의 `SessionMemoryManager` 를 계속 쓸 수 있고, 버리면 executor 의 `MemoryProviderFactory` 로 완전 대체.

## 4. 16 스테이지 인벤토리 (확정)

디렉토리로 직접 확인:

```
s01_input   s02_context  s03_system   s04_guard
s05_cache   s06_api      s07_token    s08_think
s09_parse   s10_tool     s11_agent    s12_evaluate
s13_loop    s14_emit     s15_memory   s16_yield
```

> 참고: `geny-executor-web` 에서 `PipelinePresets.chat` 빌드 결과 `get_stage` 목록이
> 11 개로 보였던 것은 **active 스테이지만 노출**되기 때문이다. 프리셋이 사용하지 않는
> 스테이지는 inactive 로 둔다. 16 개가 전체 슬롯이다.

### 필수(required) 스테이지

`EnvironmentManifest.blank_manifest()` 의 coercion 규칙: orders **1, 6, 9, 16** 은 항상 active.
- s01_input (Input), s06_api (API), s09_parse (Parse), s16_yield (Yield).

### 스테이지 베이스

`Stage(ABC, Generic[T_In, T_Out])` — `name`, `order`, `execute()`, `should_bypass()`, `on_enter/on_exit/on_error`, `describe() → StageDescription`.

각 스테이지는 **`StrategySlot`** 을 여러 개 보유 (dual-abstraction). 슬롯마다 `current`, `available`, `set()`, `rotate()`.

### 메모리 와이어링 포인트

- **s02_context** 에 `ContextStage.provider` 세터가 있다 (web v0.9.0 에서 확인됨).
- **s15_memory** 는 executor 가 자체적으로 LTM write-back 시 사용.
- 따라서 `MemoryProvider` 를 파이프라인에 붙일 때는 stage 2 에 attach.

## 5. 메모리 서브시스템 (Phase 1+)

### 프로토콜 (`memory/provider.py`)

```python
class MemoryProvider(Protocol):
    @property
    def descriptor(self) -> MemoryDescriptor: ...
    async def stm(self) -> STMHandle: ...
    async def ltm(self) -> LTMHandle: ...
    async def notes(self) -> NotesHandle: ...
    async def vector(self) -> VectorHandle: ...
    async def curated(self) -> CuratedHandle: ...
    async def global_(self) -> GlobalHandle: ...
    async def index(self) -> IndexHandle: ...
    async def retrieve(self, query: RetrievalQuery) -> RetrievalResult: ...
    async def close(self) -> None: ...
```

### 4축 Enum

```python
class Layer(str, Enum): STM, LTM, NOTES, VECTOR, INDEX, CURATED, GLOBAL
class Capability(str, Enum): READ, WRITE, SEARCH, LINK, PROMOTE, REINDEX, SNAPSHOT, REFLECT, SUMMARIZE
class Scope(str, Enum): EPHEMERAL, SESSION, USER, TENANT, GLOBAL
class Importance(str, Enum): CRITICAL, HIGH, MEDIUM, LOW
```

### 구체 프로바이더 & 팩토리 DSL

| 프로바이더 | 도입 | 백엔드 | DSN |
|-----------|------|--------|-----|
| `EphemeralMemoryProvider` | 0.14 | 인메모리 | — |
| `FileMemoryProvider` | 0.15 | 로컬 FS | `root` |
| `SQLMemoryProvider` | 0.17 (0.20 에서 Postgres dialect 완성) | SQLite / Postgres | `dsn`, optional `dialect` |
| `CompositeMemoryProvider` | 0.18 | 레이어별 라우팅 | — |

`MemoryProviderFactory.build(config_dict)` — `{"provider": "<name>", ...}` 를 받아 프로바이더 인스턴스 반환.

### Embedding

```python
from geny_executor.memory import create_embedding_client, LocalHashEmbeddingClient
client = create_embedding_client({"provider": "openai", "model": "text-embedding-3-small", "api_key": "..."})
```

지원 프로바이더: local hash (384), openai, voyage, google.

### 레거시 어댑터 (Geny 전용, quarantined)

`geny_executor.memory.retriever.GenyMemoryRetriever`,
`geny_executor.memory.strategy.GenyMemoryStrategy`,
`geny_executor.memory.persistence.GenyPersistence` — Geny 의
`SessionMemoryManager` 를 `MemoryProvider` 없이 파이프라인에 꽂기 위한 구세대 경로.
Phase 3 validation 목적이며 **신규 작업에서는 피할 대상**.

## 6. Environment / Manifest

Geny 에는 없고 executor + web 에만 존재. v0.13 에서 도입.

```python
@dataclass
class EnvironmentManifest:
    version: str = "2.0"
    metadata: EnvironmentMetadata
    pipeline: Dict[str, Any]
    model: Dict[str, Any]
    stages: List[StageManifestEntry]
    tools: ToolsSnapshot

    @classmethod
    def from_file(cls, path) -> "EnvironmentManifest": ...
    @classmethod
    def from_dict(cls, data) -> "EnvironmentManifest": ...
    @classmethod
    def blank_manifest(cls, api_key="") -> "EnvironmentManifest": ...
    @classmethod
    def from_snapshot(cls, snapshot, ...) -> "EnvironmentManifest": ...
    def to_dict(self) -> Dict: ...
    def to_yaml(self) -> str: ...
```

```python
@dataclass
class StageManifestEntry:
    order: int
    name: str
    active: bool
    artifact: str
    strategies: Dict[str, str]
    strategy_configs: Dict[str, Dict[str, Any]]
    config: Dict[str, Any]
    tool_binding: Optional[Dict[str, Any]]
    model_override: Optional[Dict[str, Any]]
    chain_order: Dict[str, List[str]]
```

`EnvironmentManager` 는 web 이 직접 쓰지는 않고 executor CLI 경로에 존재. web 은 자체 `EnvironmentService` 로 파일 저장을 한다.

## 7. 툴 인터페이스 델타

- `Tool` ABC: 변경 없음.
- `ToolContext`: 0.8.1 부터 `stage_order: int = 0`, `stage_name: str = ""` 추가 — 기본값 있으므로 기존 코드 영향 없음.
- `ToolRegistry`: 메서드 동일 (`register`, `get`, `list_all`, `to_api_format`).
- 내장 툴: 시그니처 유지. 내부 안전 로직 강화.
- **신규**: `AdhocTool`, `AdhocToolFactory` — JSON 스키마로 런타임 생성.

## 8. 스트리밍 이벤트 스키마

`geny_executor.events.types.PipelineEvent`:

```python
@dataclass
class PipelineEvent:
    type: str
    stage: str = ""
    iteration: int = 0
    timestamp: str  # ISO-8601 UTC
    data: Dict[str, Any]
```

Geny 가 의존하는 이벤트 이름 (모두 **0.20.0 에서도 유효**):

- `pipeline.start`
- `pipeline.complete` (payload: `iterations`, `total_cost_usd`, …)
- `pipeline.error`
- `stage.enter`, `stage.exit`, `stage.error`, `stage.bypass`
- `text.delta` (스트리밍 토큰)
- `tool.execute_start`, `tool.execute_complete`, `tool.execute_error`
- `loop.force_complete` (0.12 신규)

## 9. 세션 계층 (신규)

v0.20 에는 `geny_executor/session/` 패키지 존재 — 이전에 없던 `SessionManager`,
`SessionContext` 등이 있음. 단 **메모리 훅은 없다** (web 은 그래서 자체
`MemorySessionRegistry` 를 둔다).

Geny 의 `AgentSessionManager` 는 executor 의 `SessionManager` 와 **공존 가능**.
둘 다 `session_id` 를 관리하지만 역할이 겹치지 않도록 경계를 설정해야 한다 (plan/02).

## 10. CHANGELOG 요약 (0.9 → 0.20)

| 버전 | 핵심 변화 |
|------|-----------|
| 0.9 | 다중 프로바이더 API 스테이지 (Anthropic/OpenAI/Google) |
| 0.10 | s08_think (extended thinking) 정식 편입 |
| 0.11 | harness phase 7 폴리싱 |
| 0.12 | **듀얼 abstraction (StrategySlot)** 16 스테이지 전면 적용; `PipelineMutator`; 프리셋 플러그인 시스템 |
| 0.13 | **Environment 빌더** — `EnvironmentManifest v2` / `Pipeline.from_manifest` / `PipelineConfig.from_dict` |
| 0.13.1~0.13.5 | blank_manifest, introspection honest flags, required 플래그 |
| 0.14 | **MemoryProvider Phase 1** — 프로토콜 + 4축 모델 + Ephemeral |
| 0.15 | `FileMemoryProvider` |
| 0.16 | `EmbeddingClient` + 벡터 레이어 |
| 0.17 | `SQLMemoryProvider` (SQLite / Postgres) |
| 0.18 | `CompositeMemoryProvider` + `MemoryProviderFactory` |
| 0.19 | Adapter & validation (C1~C6) |
| **0.20** | Postgres dialect 안정화 + pgvector |

## 11. 브레이킹 요약 (Geny 관점)

| 카테고리 | 항목 | 영향 |
|---------|------|------|
| Additive | `ToolContext.stage_order/stage_name` | 무 영향 (기본값 safe) |
| Additive | `PipelineState` 신규 필드 | 무 영향 |
| Additive | 신규 이벤트 (`loop.force_complete` 등) | 구독자 미지정 시 무 영향 |
| Semantic | `GenyPresets` 내부 재작성 | 동일 시그니처라도 **메모리 매니저 연동 경로가 바뀜** → 실제 실행 시 차이 발생. 어댑터 재검증 필요 |
| Semantic | `Pipeline.run_stream()` 이벤트 순서 | 일부 스테이지 추가로 `stage.enter` 총 수 증가 |
| New | `EnvironmentManifest`, `Pipeline.from_manifest`, `PipelinePresets.build`, `MemoryProvider` 생태계 | 사용하려면 Geny 에 신규 통합 코드 필요 |
| New | Ad-hoc Tool | Geny 의 `ToolLoader` 와 중복 — 정책 결정 필요 |

## 12. 의사결정 포인트 (plan 에서 해소)

1. **Geny 의 메모리 경로 유지**(GenyPresets + SessionMemoryManager) vs **완전 교체**(MemoryProvider 로 치환).
2. **GenyPresets 그대로 사용** vs **PipelineBuilder 수동 조립** vs **EnvironmentManifest 기반**.
3. `session/` 모듈의 `SessionManager` 를 받아들일지 (Geny `AgentSessionManager` 와의 경계 설계).
4. 툴 시스템: `ToolLoader → ToolRegistry` 브리지 유지 vs `AdhocTool` 도입.
