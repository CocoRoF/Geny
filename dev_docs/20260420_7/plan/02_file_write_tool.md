# Plan/02 — geny-executor 내장 도구 자동 등록

**범위.** 두 단계 PR.
- PR-A: geny-executor (`Pipeline.from_manifest_async`가 `tools.built_in`을 소비)
- PR-B: Geny (`default_manifest`가 `tools.built_in`을 역할별로 채움)

**선행.** Plan/01와 독립. 같은 사이클에서 순차 병합 권장.

## 핵심 원칙

> **프레임워크는 인터페이스만 제공하는 게 아니라, 그 인터페이스로
> 만든 기본 도구도 함께 출하해야 한다.**

geny-executor는 이미 `Write`, `Read`, `Edit`, `Bash`, `Glob`, `Grep`
도구 구현을 갖고 있다 (`geny_executor/tools/built_in/`). 문제는
manifest 기반 파이프라인 빌드 경로가 이 도구들을 자동 등록하지
않는다는 점. PR-A는 이 결함을 직접 고친다. PR-B는 Geny가 새 기능을
사용하도록 manifest를 업데이트한다.

---

## PR-A. geny-executor: manifest.tools.built_in 활성화

**브랜치(executor).** `feat/pipeline-autoregister-built-ins`

### A.1 내장 도구 레지스트리 상수

`geny_executor/tools/built_in/__init__.py`에 이름→클래스 매핑을 추가:

```python
from geny_executor.tools.built_in.read_tool import ReadTool
from geny_executor.tools.built_in.write_tool import WriteTool
from geny_executor.tools.built_in.edit_tool import EditTool
from geny_executor.tools.built_in.bash_tool import BashTool
from geny_executor.tools.built_in.glob_tool import GlobTool
from geny_executor.tools.built_in.grep_tool import GrepTool

BUILT_IN_TOOL_CLASSES: dict[str, type] = {
    "Read": ReadTool,
    "Write": WriteTool,
    "Edit": EditTool,
    "Bash": BashTool,
    "Glob": GlobTool,
    "Grep": GrepTool,
}

__all__ = [
    "ReadTool", "WriteTool", "EditTool",
    "BashTool", "GlobTool", "GrepTool",
    "BUILT_IN_TOOL_CLASSES",
]
```

이후 내장 도구가 추가되면 이 매핑만 갱신하면 된다 — 사용 지점이
하나로 모인다.

### A.2 파이프라인에서 등록 헬퍼 추가

`geny_executor/core/pipeline.py`의 `_register_external_tools` 위 또는
아래에 새 함수:

```python
def _register_built_in_tools(
    manifest: "EnvironmentManifest",
    registry: "ToolRegistry",
) -> None:
    """Register framework-shipped tools named in ``manifest.tools.built_in``.

    Values accepted:
      * ``["*"]`` — register every tool in ``BUILT_IN_TOOL_CLASSES``.
      * ``["Read", "Write", ...]`` — register only the listed names.
      * Empty list or missing field — skip (no built-ins attached).

    Unknown names emit a warning and are skipped; an unknown name is a
    manifest error worth surfacing but not worth crashing the build.
    Already-registered names (e.g. a host provider beat us to it)
    are skipped silently — the first registration wins.
    """
    from geny_executor.tools.built_in import BUILT_IN_TOOL_CLASSES

    names = list(getattr(manifest.tools, "built_in", []) or [])
    if not names:
        return

    if names == ["*"]:
        names = list(BUILT_IN_TOOL_CLASSES.keys())

    for name in names:
        cls = BUILT_IN_TOOL_CLASSES.get(name)
        if cls is None:
            logger.warning(
                "manifest.tools.built_in contains unknown name '%s' — "
                "expected one of %s",
                name, sorted(BUILT_IN_TOOL_CLASSES.keys()),
            )
            continue
        if registry.get(name) is not None:
            continue  # host provider already registered something here
        registry.register(cls())
```

### A.3 `from_manifest_async` 호출 지점

`pipeline.py:317` 근처 — 현재 `_register_external_tools` 직전에
`_register_built_in_tools`를 호출. 순서는 의도적: 내장 도구 먼저
등록 → external 이름이 동일 이름을 선언하면 external이 덮어쓸 수도
있도록(기본 동작: 같은 이름은 "이미 등록됨"으로 skip; 사용자가
재정의하려면 `adhoc_providers`에서 명시 교체).

현재 파일 기준:
```python
_register_built_in_tools(manifest, registry)           # ← 추가
_register_external_tools(manifest, registry, adhoc_providers)
```

### A.4 구성 예: 테스트 / 직접 소비자용 공용 팩토리 업데이트

`geny_executor/tools/__init__.py`의 `get_built_in_registry()`는
`BUILT_IN_TOOL_CLASSES`를 참조하도록 정리 (중복 import 제거).
외부 API 시그니처 불변.

### A.5 테스트 — `tests/tools/test_built_in_autoregister.py` (신규)

| 케이스 | 기대 |
|---|---|
| `built_in=["Write"]` | 레지스트리에 `Write`만 |
| `built_in=["*"]` | 6종 전체 등록 |
| `built_in=[]` / 필드 누락 | 내장 도구 없음 (기존 동작 보존) |
| `built_in=["Unknown"]` | 경고 로그, 등록 0건, 크래시 없음 |
| `built_in=["Write"]` + external provider가 `Write` 제공 | 내장이 먼저 등록되고 external은 skip(경고) |
| `WriteTool.execute` 샌드박싱 | `working_dir` 밖 경로는 PermissionError |

기존 `test_pipeline_from_manifest` 회귀 suite에도 `built_in=["*"]`
assertion 추가.

---

## PR-B. Geny: default_manifest에 built_in 채우기

**브랜치(geny).** `feat/manifest-wire-executor-built-ins`
**의존.** PR-A 병합 + executor 버전 bump.

### B.1 `backend/service/langgraph/default_manifest.py`

```python
# 역할별 내장 도구 기본 세트
_WORKER_BUILT_INS = ["*"]                  # 모든 filesystem/bash 도구
_VTUBER_BUILT_INS: list[str] = []          # 대화 페르소나는 파일 조작 없음

def build_default_manifest(
    *,
    preset: str,
    model: str | None = None,
    external_tool_names: list[str] | None = None,
    built_in_tool_names: list[str] | None = None,   # ← 새 인자
) -> EnvironmentManifest:
    ...
    tools = ToolsSnapshot(
        built_in=list(built_in_tool_names or []),   # ← 더 이상 빈 배열 고정 아님
        external=list(external_tool_names or []),
    )
    ...
```

주석도 교체 — "dead metadata" 설명을 지우고, "executor의 내장
도구는 PR-A 이후 manifest.tools.built_in으로 활성화된다"로 갱신.

### B.2 `backend/service/environment/templates.py`

두 팩토리에서 역할에 맞는 built_in 전달:

```python
def create_worker_env(external_tool_names=None):
    manifest = build_default_manifest(
        preset="worker_adaptive",
        external_tool_names=list(external_tool_names or []),
        built_in_tool_names=["*"],   # ← Worker/Sub-Worker는 전체
    )
    ...

def create_vtuber_env(all_tool_names=None):
    ...
    manifest = build_default_manifest(
        preset="vtuber",
        external_tool_names=external,
        built_in_tool_names=[],      # ← VTuber는 파일 조작 비허용
    )
    ...
```

`install_environment_templates`가 boot 시 seed env를 재작성하므로
배포 즉시 반영.

### B.3 `ToolContext.working_dir` 확인

`backend/service/langgraph/agent_session.py`(또는 executor 호출부)에서
파이프라인 실행 시 전달되는 `ToolContext.working_dir`가 세션의
`storage_path`로 세팅되는지 검증. 이미 세팅되어 있으면 변경 없음;
아니면 한 줄 추가. 이 값이 `_path_guard.resolve_and_validate`의 샌드
박스 루트가 된다.

### B.4 Sub-Worker 프롬프트 가이드 (선택)

`backend/prompts/templates/sub-worker-default.md`에 한 줄:

> 파일을 생성/수정할 때는 `Write`(생성·전체 교체) / `Edit`(부분
> 수정) 도구를 사용한다. 경로는 세션 작업 디렉터리 기준.

memory_write로 도피하는 패턴을 끊기 위한 힌트.

### B.5 Geny 쪽 테스트

- `tests/service/environment/test_templates.py` — Worker seed의
  `tools.built_in == ["*"]`, VTuber seed의 `tools.built_in == []`
- `tests/service/environment/test_tool_registry_roster.py` — Worker
  pipeline 생성 후 registry에 `Write`/`Read`/`Edit`/`Bash`/`Glob`/
  `Grep` 모두 존재하는지; VTuber pipeline에는 부재
- `tests/integration/test_sub_worker_file_write.py`(신규) — Sub-Worker
  에게 `Write` 호출 주입 시 `storage_path/test.txt`가 실제로 생성되는지

---

## 라이브 스모크 (두 PR 병합 후)

1. executor 새 버전 bump, Geny 백엔드 재시작
2. VTuber 세션 하나 생성 → Sub-Worker 자동 링크
3. "Sub-Worker에게 test.txt 파일을 만들라고 해줘"
4. 기대:
   - VTuber가 Plan/01의 `geny_message_counterpart`로 위임
   - Sub-Worker가 `Write(file_path="test.txt", content="...")` 호출
   - `backend/storage/<sub_id>/test.txt`가 실재
   - `/api/sessions/<sub_id>/files` 응답에 test.txt 포함
   - 응답이 inbox 경유로 VTuber→사용자 전달
5. **반례 검증**: VTuber에게 직접 "test.txt 만들어" 요청 시,
   VTuber는 `Write` 도구를 못 봐야 함 (role별 분리 확인)

## 롤백

- PR-B 롤백: `built_in_tool_names=[]`로 되돌림 → 이전 상태 (도구
  미등록)
- PR-A 롤백: 새 헬퍼 제거 → manifest.tools.built_in은 다시 죽은
  메타데이터로 회귀; 기존 external 경로는 그대로 동작
- 데이터 호환성: manifest JSON 스키마 불변 (기존 `built_in: []`
  필드가 활성화될 뿐, 필드 자체는 v2부터 존재)

## 보안/경계

- `_path_guard.resolve_and_validate`가 `working_dir` 밖 경로를 이미
  차단 — 추가 방어 불필요
- `ToolContext.allowed_paths` 활용 시 더 촘촘한 제한 가능; 현재는
  `working_dir` 루트만 강제
- `BashTool`도 함께 노출됨 — 역할별 built_in을 `["*"]`로 한 건 운영
  트레이드오프. Bash를 제외하려면 `["Read", "Write", "Edit", "Glob",
  "Grep"]`로 명시
- 크기 상한·쿼터는 이번 범위 밖 (운영 정책으로 별도 관리)

## 확장 경로 — 향후 투자

이번 PR 이후 "executor가 더 많은 기본 도구를 출하한다"가 깨끗한
추가 경로가 된다:

- `Delete` / `Move` / `Copy` (FS 조작 완전화)
- `HttpGet` / `HttpPost` (MCP 없이 가벼운 HTTP)
- `Json` / `Yaml` (구조 데이터 조작)

각각 `built_in/*_tool.py` + `BUILT_IN_TOOL_CLASSES` 등록이면 끝 —
manifest 소비자 측은 `["*"]`만 쓰고 있었다면 자동 수혜.
