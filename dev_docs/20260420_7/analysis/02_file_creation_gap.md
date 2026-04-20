# Analysis/02 — 파일 생성 도구 부재

## 증상

Sub-Worker `5e2edaab`가 "test.txt 파일을 만들어주세요" 요청을
받고 다음을 수행했다:

1. `memory_write(title="...", content="...",
   category="projects")` 호출 → `projects/vtuber-agent-self-
   introduction-task.md` 생성 (세션의 구조화 메모리 저장소)
2. 응답 텍스트 "I'll help you create the test.txt file... Let m"
   에서 절단 — 실제 `test.txt`는 생성되지 않음

## 구조 — 도구는 이미 존재하나 배선되지 않는다

geny-executor는 파일시스템 관련 기본 도구를 **이미 출하**하고 있다:

```
geny_executor/tools/built_in/
├── _path_guard.py      ← resolve_and_validate 샌드박스 검사
├── bash_tool.py        ← BashTool
├── edit_tool.py        ← EditTool  (부분 수정)
├── glob_tool.py        ← GlobTool  (파일 패턴 검색)
├── grep_tool.py        ← GrepTool  (내용 검색)
├── read_tool.py        ← ReadTool
└── write_tool.py       ← WriteTool (생성/덮어쓰기)
```

이들은 `Tool` ABC를 구현하고 `ToolContext.working_dir` +
`ToolContext.allowed_paths`로 샌드박싱된다. `WriteTool.execute`는
실제 디스크에 파일을 쓴다 — 기능은 완성되어 있다.

문제는 **등록 경로가 활성화되어 있지 않다**는 것이다.

### `_register_external_tools`만 활성 상태

`geny_executor/core/pipeline.py:85-122` —

```python
def _register_external_tools(
    manifest, registry, providers,
) -> None:
    external_names = list(getattr(manifest.tools, "external", []) or [])
    ...
```

`Pipeline.from_manifest_async`는 `manifest.tools.external`만 순회하며
host-측 `AdhocToolProvider`가 공급하는 이름들만 등록한다.

### `manifest.tools.built_in`은 현재 "죽은 메타데이터"

`ToolsSnapshot` 구조체는 `built_in: List[str]`를 선언하나,
파이프라인 빌드 경로에서 어떤 코드도 이 필드를 소비하지 않는다.
Geny의 `default_manifest.py:360-368`에도 명시되어 있다:

```python
# `.built_in` is left empty: the executor's `from_manifest` path
# only consumes `.external` ... Populating `.built_in` with
# names no provider supplies would be dead metadata.
tools = ToolsSnapshot(built_in=[], external=list(external_tool_names or []))
```

### `get_built_in_registry()` 팩토리 — 수동 호출 전용

`geny_executor/tools/__init__.py:53-80`에 모든 내장 도구를 등록하는
팩토리가 있으나, **manifest 경로에 연결되어 있지 않다.** 수동으로
파이프라인을 조립하는 (테스트·예제 수준의) 호출자만 사용한다.

## 결과 — 소비자가 도구를 재구현해야 한다

- Geny는 자체 `tools/built_in/`, `tools/custom/` 체계를 별도로 구축
- 파일 쓰기 능력은 executor에 있으나 Geny의 Sub-Worker는 접근 불가
- LangChain / MCP / 기타 소비자도 같은 벽에 부딪힘 — 프레임워크가
  "인터페이스만" 제공하고 기본 도구는 각자 알아서 만들라는 셈

사용자의 지적과 일치:
> "geny-executor가 기본적으로 파일시스템 컨트롤과 관련된 툴을
> 갖고 있어야만 해. 즉 geny-executor의 시스템이 인터페이스를
> 제공할 뿐만 아니라, 해당 인터페이스를 이용한 기본적인 유용한
> 도구들을 지니고 있어야 하는 거야."

출하된 `WriteTool` 등이 **manifest 경로에서 자동으로 등록**되어야
한다. 그러면:

- Sub-Worker는 `Write(file_path, content)`로 `test.txt` 생성 가능
- Geny는 파일 쓰기 도구를 별도로 구현할 필요가 없어짐
- LangChain 등 다른 소비자도 executor만 설치하면 기본 도구 획득
- `ToolContext.working_dir` = Sub-Worker의 `storage_path`로 세팅되면
  샌드박싱도 자동

## 기대 형상

1. `manifest.tools.built_in: ["Read", "Write", "Edit", "Bash",
   "Glob", "Grep"]` 또는 `["*"]`(전체)로 선언 가능
2. `Pipeline.from_manifest_async`가 이 리스트를 해석해 executor의
   내장 도구를 자동 등록
3. Geny의 `default_manifest.build_default_manifest`가 역할별로
   적절한 built_in 리스트를 채움 (Worker/Sub-Worker: `["*"]`,
   VTuber: `["Read"]` 또는 `[]`)
4. `ToolContext.working_dir`은 세션 `storage_path`로 세팅되어
   샌드박스가 자동 성립

## 비결함 확인

- `_path_guard.resolve_and_validate`는 이미 경로 탈출을 차단한다 —
  추가 보안 로직 불필요.
- `WriteTool.execute`는 parent dir 자동 생성, UTF-8 인코딩 처리
  완료 상태 — 코드 변경 대상 아님.
- `ToolContext` 스키마 (`working_dir`, `allowed_paths`)도 충분 —
  구조체 변경 불필요.
- MCP filesystem 서버는 여전히 불필요 — executor 내장으로 해결.
