# 01 — Unified Tool Surface (Phase C)

"두 개의 등록 경로" 문제를 해결한다 (analysis/04). 목표는 **`Pipeline.from_manifest`
단 하나만으로 파이프라인의 tool 구성이 결정되도록** 만드는 것.

## 방향성

Geny 의 `BaseTool` 기반 도메인 tool 은 **manifest 직렬 형식으로 표현 불가능
하다** (executor_type: `http|script|template|composite` 중 어느 것에도 맞지
않음). 따라서 해결은 manifest 에 JSON 스키마를 늘리는 방향이 아니라,
`Pipeline.from_manifest` 가 **"런타임-제공 tool"** 을 외부에서 받아들일 수 있는
**명시적 훅** 을 갖는 방향이다.

## 제안 — `AdhocToolProvider` protocol

### host (`geny-executor`) 측 변경

파일: `geny-executor/src/geny_executor/tools/providers.py` (신규)

```python
class AdhocToolProvider(Protocol):
    """Supplies tools that cannot be expressed as AdhocToolDefinition."""

    def list_names(self) -> List[str]: ...
    def get(self, name: str) -> Optional[Tool]: ...
```

`Pipeline.from_manifest(manifest, api_key, *, strict=True)` 시그니처에
**kwarg 만 추가**:

```python
@classmethod
def from_manifest(
    cls,
    manifest: EnvironmentManifest,
    *,
    api_key: str,
    strict: bool = True,
    adhoc_providers: Sequence[AdhocToolProvider] = (),
) -> Pipeline: ...
```

manifest 의 `ToolsSnapshot` 에는 새 필드 추가:

```python
@dataclass
class ToolsSnapshot:
    built_in: List[str] = field(default_factory=list)
    adhoc: List[Dict[str, Any]] = field(default_factory=list)
    mcp_servers: List[Dict[str, Any]] = field(default_factory=list)
    external: List[str] = field(default_factory=list)     # ← 추가
    scope: Dict[str, Any] = field(default_factory=dict)
```

`external: List[str]` 은 "이 환경은 host 가 제공하는 provider 중 다음 이름들을
사용한다" 는 **화이트리스트**. Pipeline.from_manifest 는 manifest 를 로드할 때
`adhoc_providers` 를 순회하여 `external` 안에 이름이 들어있는 tool 만 레지스트리에
넣는다.

이렇게 설계하는 이유:
- manifest 가 여전히 권위 있는 source (어떤 external tool 이 활성인지를 선언함).
- Geny 가 제공하는 tool 집합이 바뀌어도 manifest 는 동일하게 해석 가능.
- 다중 provider (Geny 백엔드의 built-in + 사용자 정의 plugin 등) 를 동시에 받을
  수 있음.

### consumer (`Geny`) 측 변경

`Geny/backend/service/langgraph/tool_bridge.py` 의 `build_geny_tool_registry`
를 리팩터링하여 `AdhocToolProvider` 를 구현한 `GenyToolProvider` 클래스를
만든다. 기존 `ToolRegistry` 반환은 `provider.list_names()` / `provider.get(...)`
인터페이스로 교체.

`environment/service.py:484-495` 의 `instantiate_pipeline` 는:

```python
def instantiate_pipeline(self, env_id, *, api_key, strict=True) -> Pipeline:
    manifest = self.load_manifest(env_id)
    if manifest is None: raise EnvironmentNotFoundError(env_id)
    geny_provider = self._tool_provider_factory()  # new dependency
    return Pipeline.from_manifest(
        manifest, api_key=api_key, strict=strict,
        adhoc_providers=[geny_provider],
    )
```

## Legacy 경로 제거 (단일 경로로 통합)

`AgentSession._build_pipeline` 의 `ToolRegistry()` 수동 register 블록과
`GenyPresets.*(tools=tools)` 분기는 **같은 PR 에서 삭제** 된다. 대체 경로는
하나뿐이며, env_id 가 있든 없든 모든 세션은 아래 형태로 파이프라인을
구성한다.

```python
manifest = (
    self._environment_service.load_manifest(env_id)
    if env_id
    else build_default_manifest(preset=preset_name)   # ← env_id 없는 세션용
)
geny_provider = self._tool_provider_factory()
self._pipeline = Pipeline.from_manifest(
    manifest, api_key=api_key,
    adhoc_providers=[geny_provider],
)
```

`build_default_manifest(preset)` 는 vtuber / worker_adaptive 등 preset 이름에서
stage 구성과 `tools.built_in` / `tools.external` 기본값을 즉석 생성하는 순수
함수로 도입. 이 함수와 `GenyToolProvider` 는 Phase A 종료 시점에 **dead code
로 먼저 머지** 해두고 (아무 곳에서도 호출되지 않는 safe refactor), Phase C 의
switch-over PR 이 legacy 블록을 삭제하며 이들을 호출하도록 전환한다. 이로써
Phase C PR 은 추가가 아니라 **교체** 만 포함해 리뷰 범위를 좁게 유지.

## Frontend 일관성 (F-10 해소)

`SessionEnvironmentTab` 의 tool 목록은 `tools.external` 까지 함께 표시한다.
UI 라벨은 기존 `Built-in / Ad-hoc / MCP` 외에 `External (provider-backed)` 을
추가. Geny 가 제공하는 각 tool 은 preset 정의에 매핑되므로, `PresetDefinition`
의 이름/설명을 그대로 활용.

## 단일 전환 계획

Phase C 는 단일 PR 에서 legacy 경로 제거 + 새 경로 활성화를 동시에 수행.
feature flag 는 두지 않는다.

1. **host PR** (선행, Phase A/B 와 함께 머지):
   `AdhocToolProvider` protocol, `from_manifest(adhoc_providers=)`,
   `ToolsSnapshot.external` 필드를 도입. 이 시점에서도 executor 자체는
   기존 동작을 깨지 않지만, **Phase A/B 의 Breaking change 들과 함께**
   `geny-executor` v0.22.0 으로 bump.
2. **Geny safe-refactor PR** (dead code 도입):
   `GenyToolProvider` 클래스, `build_default_manifest(preset)` 순수 함수,
   마이그레이션 스크립트를 추가. 호출 지점 없음 → 기존 동작 무영향.
3. **Geny switch-over PR** (본 Phase C 의 본체):
   - `pyproject.toml` 의 `geny-executor>=0.22.0,<0.23.0` 으로 pin.
   - `AgentSession._build_pipeline` 의 legacy 블록 전면 삭제.
   - `env_id` 존재 여부에 따른 분기를 제거하고 위의 단일 경로로 교체.
   - 마이그레이션 스크립트를 repo 에 포함, deploy 직후 1 회 실행하도록
     `progress/` PR 기록에 절차 명시.

## 되돌리기

- switch-over PR 자체를 revert 하면 safe-refactor PR 의 dead code 와 host PR
  로 남되 legacy 경로가 복원된다. flag 를 통한 "숨긴 복원" 은 없다.
- executor v0.22.0 이 이미 배포된 상태에서 Geny revert 만으로는 import
  호환성이 깨지므로, revert 시점에 `pyproject.toml` 의 pin 도 함께 이전
  버전으로 되돌려야 한다. 이 절차는 `plan/05` 의 "되돌리기 체크포인트" 에
  기록.

## 성공 기준

- `env_id` 기반 세션과 non-env_id 세션 모두 동일한 tool 집합을 갖는다.
- `SessionEnvironmentTab` 에 표시되는 tool 목록이 실제 활성 레지스트리와
  완전히 일치한다.
- `news_search` 호출이 manifest 경로에서 성공.
