# 04 — AdhocToolProvider + manifest.tools.external (PR4, Phase C host)

- **Repo**: `geny-executor`
- **Plan 참조**: `plan/01_unified_tool_surface.md` §"host 측 변경"
- **Branch**: `feat/adhoc-tool-provider`
- **PR**: [CocoRoF/geny-executor#25](https://github.com/CocoRoF/geny-executor/pull/25)
- **의존**: PR1 (`#22`), PR2 (`#23`), PR3 (`#24`)

## 변경 요지

Phase C 의 host-side hook. Geny 의 `BaseTool` 같은 "manifest 직렬 불가" tool
을 수용하기 위한 **명시적 훅** 을 executor 에 도입. `Pipeline.from_manifest`
가 `adhoc_providers: Sequence[AdhocToolProvider]` 를 받고, manifest 의 새
`tools.external: List[str]` 화이트리스트에 있는 이름만 provider 에서 꺼내
registry 에 등록한다.

이 PR 의 핵심 목표는 "executor 가 외부 Tool 을 받아들일 수 있게 한다"
+ "external tool 과 MCP adapter 가 같은 `ToolRegistry` 에 수렴하게 한다"
두 가지. Geny cutover (PR8) 가 이 인터페이스를 그대로 쓴다.

## 추가 / 변경된 파일

1. **신규** `src/geny_executor/tools/providers.py`
   - `@runtime_checkable` `AdhocToolProvider(Protocol)`: `list_names() ->
     List[str]`, `get(name) -> Optional[Tool]`. `isinstance` 로 shape 체크
     가능. 공급자는 "어떤 이름을 제공할 수 있는지" 만 알리고, 어떤 이름을
     활성화할지는 manifest 가 결정.

2. **수정** `src/geny_executor/core/environment.py`
   - `ToolsSnapshot.external: List[str] = field(default_factory=list)`
     추가. `to_dict` 항상 방출, `from_dict` 는 누락 시 `[]` 로 fallback →
     v0.22.0 이전 manifest 는 손상 없이 로드.

3. **수정** `src/geny_executor/core/pipeline.py`
   - 모듈 수준 `_register_external_tools(manifest, registry, providers)`
     helper: `manifest.tools.external` 순회 → provider 를 왼→오로 질의 →
     첫 non-`None` tool 을 등록. 매칭 없는 이름은 warning + skip. provider
     없이 external 이 선언되면 전체를 warning + skip.
   - `Pipeline.from_manifest(..., adhoc_providers: Sequence[...] = (),
     tool_registry: Optional[ToolRegistry] = None)` 로 확장. registry 를
     만들거나 caller 가 준 것을 받아 external 등록 후 `pipeline._tool_registry`
     에 부착. 기존 sync 콜러 (약 10개) 는 kwarg 미지정이라 아무 변화 없음.
   - `Pipeline.from_manifest_async(..., adhoc_providers: Sequence[...] = ())`
     : inner `from_manifest(tool_registry=registry, adhoc_providers=...)`
     호출로 external 등록 → MCP 어댑터 등록 → 같은 registry 에 수렴. **
     external + MCP 통합 surface** 확보.
   - `logging.getLogger(__name__)` 도입 (provider 없음 / 이름 없음 경고용).

4. **수정** `src/geny_executor/tools/__init__.py`
   - `AdhocToolProvider` 를 패키지 루트로 re-export + `__all__` 에 추가.

5. **신규** `tests/unit/test_adhoc_providers.py` (19 tests, 전부 PASS)
   - **Protocol**: `isinstance(provider, AdhocToolProvider)`, 메서드 누락
     시 `isinstance` 실패, unknown name 에 `None` 반환.
   - **`ToolsSnapshot.external` round-trip**: `to_dict` 방출 / `from_dict`
     읽기 / legacy (field 없음) 기본값 `[]` / manifest 전체 round-trip.
   - **`from_manifest` wiring**: external name 등록, provider 가 가진
     extra tool 은 무시 (manifest authoritative), 공급자 없는 external
     name → warning skip, provider 없이 external 선언 → warning, 첫
     provider 매칭 우선, 두 번째 provider fallback, empty external
     noop, caller registry 에 주입, pre-registered tool 보존.
   - **`from_manifest_async`**: external-only 등록 / external + MCP 공존
     / MCP 실패 시에도 `MCPConnectionError` 가 먼저 튀어나옴.

## 검증

- `pytest tests/unit tests/contract tests/integration` → **1003 passed,
  5 skipped** (PR3 대비 +19).

## 호환성

- **Backward compatible**. `adhoc_providers` / `tool_registry` 는 모두
  default 가 있어 기존 sync 콜러는 영향 없음.
- `ToolsSnapshot.external` 는 `from_dict` 에서 누락 시 `[]` 로 fallback
  하므로 저장된 v2 manifest 파일들도 변환 없이 로드됨.

## 후속 TODO (다음 PR)

- **PR5**: `geny-executor` v0.22.0 bump + CHANGELOG + tag (PR1–PR4 를
  하나의 breaking release 로 묶음).
- **PR6 (Geny safe-refactor)**: `GenyToolProvider(AdhocToolProvider)`
  클래스와 `build_default_manifest(preset)` 순수 함수를 **dead code 로**
  도입 (호출 지점 없음 → 기존 동작 무영향).
- **PR7 (Geny logging)**: Phase D — `_format_tool_detail` 통일 +
  `"(parse error)"` swallower 제거.
- **PR8 (Geny cutover)**: `pyproject.toml` pin `geny-executor>=0.22.0,
  <0.23.0`, `AgentSession._build_pipeline` 의 legacy 블록 전면 제거,
  단일 `Pipeline.from_manifest_async(manifest, adhoc_providers=[geny_provider])`
  경로로 교체. `BaseTool` 계열을 `ToolFailure` 기반 에러 모델로 마이그.
