# PR-X5-1 · `feat/geny-plugin-protocol` — 진행 기록

**Date.** 2026-04-22
**Status.** Implemented, 9 신규 테스트 pass. Registry / loader / 재포장은 PR-X5-2 / PR-X5-3 이월.

X5 사이클 개시. analysis 04 §9 "17번째 stage 금지" 원칙에 따라, 기존 7개
확장 표면 (attach_runtime, s03 PromptBlock, s14 Emitter, TickEngine,
Tool, SessionLifecycleBus, ManifestSelector) 에 얹는 *번들 컨트랙트*
만 이 PR 에서 도입한다. Registry 는 PR-X5-2, 기존 X3/X4 기능의
GenyPlugin 재포장은 PR-X5-3.

## 범위

### 1. `backend/service/plugin/protocol.py` — `GenyPlugin` Protocol

`@runtime_checkable Protocol` 으로 선언. Registry (PR-X5-2) 가
`isinstance(x, GenyPlugin)` 으로 import cycle 없이 판정할 수 있게
하는 것이 1차 목적. Protocol 은 6개의 `contribute_*` 훅을 선언한다:

- **Per-session** (SessionContext 인자를 받음):
  - `contribute_prompt_blocks(session_ctx) -> Sequence[PromptBlock]`
  - `contribute_emitters(session_ctx) -> Sequence[Emitter]`
  - `contribute_attach_runtime(session_ctx) -> Mapping[str, Any]`
- **Registry-global** (인자 없음):
  - `contribute_tickers() -> Sequence[TickSpec]`
  - `contribute_tools() -> Sequence[Any]`
  - `contribute_session_listeners() -> Mapping[str, SessionListener]`

Plus 두 개의 필수 클래스 속성:

- `name: str` — 레지스트리 키이자 진단 id. PR-X5-2 에서 중복
  등록을 raise.
- `version: str` — 자유 양식. MVP 는 SemVer 강제 없음.

### 2. `SessionContext = Mapping[str, Any]`

Rich dataclass 대신 얇은 Mapping 별칭. Registry 가 `PipelineState`
`shared` 를 스냅샷해 넘기는 용도. 합의된 키:

- `session_id: str` · `character_id: str` · `owner_user_id: str`
- `is_vtuber: bool` — role hint
- `shared: Mapping[str, Any]` — read-only 스냅샷

플러그인은 **read-only** 로 다뤄야 한다. 쓰기는 MutationBuffer /
state.shared 쓰기 (stage 실행 중) 경로로.

### 3. `SessionListener = Callable[..., Awaitable[None]]`

Bus 이벤트별 payload 모양이 다르므로 varargs. 시그니처 검증은
`SessionLifecycleBus` (X2 PR-1) publish 쪽이 담당.

### 4. `PluginBase` — canonical no-op defaults

모든 훅에 빈 리턴 기본 구현을 제공하는 convenience parent.

- `contribute_prompt_blocks` · `contribute_emitters` ·
  `contribute_tickers` · `contribute_tools` → `()` (빈 시퀀스)
- `contribute_attach_runtime` · `contribute_session_listeners` →
  `{}` (빈 매핑)
- `name` / `version` 은 기본값을 주지 않음 — 서브클래스가 반드시
  세팅. 이름 없는 플러그인은 조용히 collision 날 수 있어, 레지스트리
  contract 상 "이름 누락은 버그" 로 취급.

**_per-call fresh mapping_**: 기본 attach_runtime 은 호출마다 새
`{}` 를 돌려주도록 `_empty_mapping()` 헬퍼 경유 — 여러 플러그인이
기본값을 공유하더라도 mutation 이 번지지 않는다.

### 5. `PluginLike = Union[GenyPlugin, PluginBase]`

테스트 / 문서에서 "Protocol 이든 ABC 이든 상관없이 플러그인
객체" 를 타이핑하기 위한 편의 alias.

### 6. `backend/service/plugin/__init__.py`

패키지 루트에서 5개 심볼 재노출: `GenyPlugin`, `PluginBase`,
`PluginLike`, `SessionContext`, `SessionListener`.

## 테스트 — `backend/tests/service/plugin/test_protocol.py`

9 tests, 전부 pass:

1. `test_plugin_base_implements_protocol` — `_BareMinimumPlugin`
   (`name` + `version` 만) 이 `isinstance(_, GenyPlugin)` 통과.
2. `test_plugin_base_defaults_are_empty_but_callable` — 6 훅 전부
   호출 가능 + 빈 시퀀스/매핑 리턴.
3. `test_plugin_base_default_attach_runtime_is_per_call_empty` —
   기본 attach_runtime 이 호출마다 독립된 빈 dict 리턴.
4. `test_structural_plugin_is_recognized_as_geny_plugin` —
   `PluginBase` 미상속, duck-typed `_StructuralPlugin` 도
   runtime_checkable 덕분에 인식.
5. `test_structural_plugin_contributions_round_trip` — 구조형
   플러그인의 6 훅 리턴값이 계약대로 (PromptBlock / Emitter /
   TickSpec / session listener) 라운드트립.
6. `test_missing_name_and_version_is_not_a_plugin` — 속성 누락은
   isinstance 실패.
7. `test_incomplete_hook_surface_is_not_a_plugin` — 일부
   `contribute_*` 메서드 누락 → isinstance 실패.
8. `test_override_keeps_inherited_defaults_for_other_hooks` —
   PluginBase 서브클래스가 일부 훅만 override 했을 때 나머지는
   기본값 유지.
9. `test_plugin_without_name_fails_protocol_check` —
   `PluginBase` 는 `name: str` 을 annotation 만 선언하므로
   서브클래스가 세팅 안 하면 `AttributeError` + isinstance 실패.

실행:

```
PYTHONPATH=/home/geny-workspace/Geny \
/home/geny-workspace/geny-executor/.venv/bin/pytest \
    backend/tests/service/plugin/ -q
```

→ `9 passed in 0.10s`.

## 설계 선택

### ABC 가 아니라 Protocol

Registry 는 import cycle 회피를 위해 플러그인 타입을 직접 import
하지 않을 수 있어야 한다. 또한 plugin authors 가 PluginBase 를
반드시 상속하지 않고도 기존 클래스에 `name` + `contribute_*` 만
붙여 등록할 수 있어야 MVP 이월 비용이 낮다. `runtime_checkable`
Protocol 이 두 요구를 동시에 만족.

### 훅 시그니처의 갈라짐 — `SessionContext` vs. 인자 없음

Tickers / tools / session_listeners 는 registry 수명 동안 한 번만
세팅되므로 per-session context 가 불필요. PromptBlocks / Emitters /
attach_runtime 은 session 별로 달라질 수 있어 (예: is_vtuber,
character_id 기반 게이팅) session_ctx 인자가 필요. 훅 시그니처 둘로
쪼개는 것이 registry 호출 경로에서도 자연스럽다.

### `contribute_*` 는 side-effect 없이 값만

stateful 초기화 (소켓, 파일, 캐시) 는 Plugin `__init__` — Registry
조립 시점 — 에 끝낸다. per-session 호출은 값만 리턴. 이 규약이
있으면 Registry 가 diagnostics 목적으로 훅을 여러 번 불러도
놀람이 없다. Protocol docstring 에 "Design pillars" 섹션으로 박아
둠.

## 의도적 이월

- **PluginRegistry / loader** — PR-X5-2. 이름 중복 거부, entry-point
  discovery, attach_runtime 키 충돌 검증 등은 전부 거기서.
- **X3/X4 기능의 GenyPlugin 재포장** — PR-X5-3. 현 tamagotchi /
  live2d 번들이 X1–X4 로 직접 wire 되어 있는데, 이를 Plugin 형태로
  리팩터. 테스트 리그레션은 없어야 한다 (plan/05 §5.2).
- **Executor bump (attach_runtime session_runtime kwarg)** — PR-X5-4,
  PR-X5-5. plan/05 §5.3 정책상 "ToolContext.metadata 로 해결 안
  되는 슬롯이 생길 때만". 현 MVP 는 shared dict 로 충분.

## 테스트 회귀 확인

Plugin 전용 9 개 pass. 주변 영역 회귀는 main 에도 존재하는 것만
남아 있음 (numpy/fastapi 미설치 등 — 본 PR 과 무관).

## 다음 PR

PR-X5-2 `feat/plugin-registry-and-loader` — `PluginRegistry` 클래스,
`register(plugin)` 중복 이름 raise, 훅 fan-out (prompt_blocks →
CharacterPersonaProvider, emitters → EmitterChain, tickers →
TickEngine, ...), attach_runtime 키 충돌 raise. 명시적 등록만 (entry-
point discovery 는 X6).
