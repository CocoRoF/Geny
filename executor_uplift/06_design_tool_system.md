# 06. Design — Tool System Uplift

**Status:** Draft
**Date:** 2026-04-24
**Priority:** P0 — foundation for Stage 10 orchestration, Permission matrix, Result budget

---

## 1. 목표

Tool 을 **단순 "이름·스키마·handler"** 에서 **완전한 capability descriptor** 로 격상시킨다. 이 descriptor 는:

1. Stage 10 orchestration 이 **안전한 병렬** 과 **직렬 serialization** 을 결정하는 근거가 된다
2. Permission rule matrix 가 **input 패턴** 까지 매칭할 수 있게 해준다
3. Result 가 비대해졌을 때 **자동 persist → path 반환** 으로 context 를 보호한다
4. Tool lifecycle (진입·진행·종료·에러·취소) 의 hook 진입점을 제공한다

구조적으로는:
- 새 `Tool` ABC 를 `geny-executor` 에 정의
- 기존 Geny `BaseTool` 은 **adapter** 로 호환 유지
- 신규 tool 은 새 ABC 로 작성 권장

---

## 2. 새 Tool ABC — 설계

```python
# geny_executor/tools/base.py (격상안)

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Generic, TypeVar, Optional

T_Input  = TypeVar("T_Input")   # 주로 dict 또는 Pydantic
T_Output = TypeVar("T_Output")
T_Progress = TypeVar("T_Progress")


# ────────────────────────────────────────────────────────
# 1. 런타임 특성 메타
# ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ToolCapabilities:
    """Runtime traits — Stage 10 orchestration + Guard + Permission 가 참조."""

    concurrency_safe: bool = False     # True 이면 sibling 과 병렬 가능
    read_only:        bool = False     # True 이면 side-effect 없음
    destructive:      bool = False     # True 이면 파일/데이터 소실 가능
    idempotent:       bool = False     # 같은 입력이면 같은 결과 (retry 가능)
    network_egress:   bool = False     # 외부 네트워크 I/O 하는가
    interrupt:        str  = "block"   # 'cancel' | 'block' — 인터럽트 시 행동
    max_result_chars: int  = 100_000   # 결과 문자열이 이를 넘으면 persist


# ────────────────────────────────────────────────────────
# 2. Permission 결과
# ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class PermissionDecision:
    behavior: str                      # 'allow' | 'deny' | 'ask'
    updated_input: Optional[dict] = None
    reason: Optional[str] = None


# ────────────────────────────────────────────────────────
# 3. Tool 실행 컨텍스트
# ────────────────────────────────────────────────────────
@dataclass
class ToolContext:
    session_id:   str
    working_dir:  Optional[str] = None
    storage_path: Optional[str] = None
    state_view:   Optional[Any] = None      # PipelineState 읽기 view (writes X)
    event_emit:   Optional[Callable[[str, dict], None]] = None
    permission_mode: str = "default"        # 'default'|'plan'|'auto'|'bypass'
    parent_tool_use_id: Optional[str] = None
    extras: dict = field(default_factory=dict)


# ────────────────────────────────────────────────────────
# 4. 실행 결과
# ────────────────────────────────────────────────────────
@dataclass
class ToolResult(Generic[T_Output]):
    data: T_Output                     # 주 결과
    new_messages: list = field(default_factory=list)   # 대화 주입
    state_mutations: dict = field(default_factory=dict) # state.shared 변경
    artifacts: dict = field(default_factory=dict)       # 저장된 파일 경로 등
    display_text: Optional[str] = None                  # LLM 에 보낼 요약
    persist_full: Optional[str] = None                  # 전체 결과 파일 경로 (자동 설정)
    is_error: bool = False
    mcp_meta: Optional[dict] = None


# ────────────────────────────────────────────────────────
# 5. 기본 Tool ABC
# ────────────────────────────────────────────────────────
class Tool(ABC, Generic[T_Input, T_Output, T_Progress]):
    """
    Complete capability descriptor. Subclasses override what differs from defaults.
    """
    name: str
    description: str
    aliases: tuple[str, ...] = ()

    # ── Schema (필수) ─────────────────────────────────
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON Schema 로 입력 스키마 반환."""

    def output_schema(self) -> Optional[dict]:
        """선택적 출력 스키마."""
        return None

    def validate_input(self, raw: dict) -> dict:
        """기본: schema-based validation 후 그대로 통과. override 가능."""
        # default implementation: jsonschema.validate
        return raw

    # ── Capability 메타 ────────────────────────────────
    def capabilities(self, input: dict) -> ToolCapabilities:
        """input 에 따라 달라질 수 있음 (e.g. Bash 는 명령어에 따라 destructive)."""
        return ToolCapabilities()  # all defaults: fail-closed

    # ── Permission ─────────────────────────────────────
    async def check_permissions(
        self, input: dict, ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def prepare_permission_matcher(
        self, input: dict
    ) -> Callable[[str], bool]:
        """rule pattern 과 이 input 이 매칭되는지 판별하는 closure 반환."""
        # default: 'tool_name' 만 매칭
        return lambda pattern: pattern == self.name

    # ── 실행 ─────────────────────────────────────────
    @abstractmethod
    async def execute(
        self,
        input: T_Input,
        ctx: ToolContext,
        *,
        on_progress: Optional[Callable[[T_Progress], None]] = None,
    ) -> ToolResult[T_Output]:
        ...

    # ── Lifecycle hooks ────────────────────────────────
    async def on_enter(self, input: dict, ctx: ToolContext) -> None: ...
    async def on_exit(self, result: ToolResult, ctx: ToolContext) -> None: ...
    async def on_error(self, error: Exception, ctx: ToolContext) -> None: ...

    # ── UI/Display ────────────────────────────────────
    def user_facing_name(self, input: dict) -> str:
        return self.name

    def activity_description(self, input: dict) -> Optional[str]:
        """프로그레스 indicator 에 표시할 현재 활동 설명."""
        return None

    def render_result_preview(self, result: ToolResult) -> Optional[str]:
        """LLM 이 아닌 사람이 볼 요약 (log UI 용)."""
        return result.display_text

    # ── MCP 메타 ──────────────────────────────────────
    is_mcp: bool = False
    mcp_info: Optional[dict] = None

    # ── 활성화 게이트 ─────────────────────────────────
    def is_enabled(self) -> bool:
        return True

    # ── API 포맷 ──────────────────────────────────────
    def to_api_format(self) -> dict:
        """Anthropic tool definition 포맷 (OpenAI/Google 은 client 가 변환)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
        }
```

### 관찰

- `capabilities()` 는 **input-dependent** — `BashTool` 이 `rm -rf` 를 받으면 `destructive=True`, `ls` 를 받으면 `read_only=True`.
- `prepare_permission_matcher()` 는 tool 이 자기 input 구조를 가장 잘 앎 → 매처도 tool 이 생성.
- `ToolResult` 에 `state_mutations` 가 있어 Stage 10 이 `state.shared` 에 반영할 수 있음 (contextvar 기반 mutation buffer 와 연동).
- `display_text` / `persist_full` 이분화 — LLM 에는 summary, 디스크에는 full.

---

## 3. `build_tool()` 팩토리 — Python 버전

Dataclass 의 `replace()` 와 유사한 spread 패턴을 Python 에 맞게 재현:

```python
def build_tool(
    *, name: str, description: str, input_schema: dict,
    execute: Callable[..., Awaitable[ToolResult]],
    **overrides,
) -> Tool:
    """
    간편한 factory — 간단한 tool 은 subclass 없이 이걸로 충분.
    """
    class _Built(Tool):
        pass
    _Built.name = name
    _Built.description = description

    _Built.input_schema = lambda self: input_schema
    async def _exec(self, inp, ctx, *, on_progress=None):
        return await execute(inp, ctx, on_progress=on_progress)
    _Built.execute = _exec

    for attr, val in overrides.items():
        if callable(val):
            setattr(_Built, attr, val)
        else:
            # 상수 값
            def _make(v): return lambda self, *a, **kw: v
            setattr(_Built, attr, _make(val))

    return _Built()
```

예:
```python
read_tool = build_tool(
    name="read",
    description="Read a file.",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    execute=_read_impl,
    capabilities=ToolCapabilities(concurrency_safe=True, read_only=True, max_result_chars=500_000),
)
```

---

## 4. 기존 BaseTool → 새 Tool 어댑터

`BaseTool` 을 그대로 두고 adapter 가 새 ABC 로 감쌈.

```python
# geny_executor/tools/legacy_adapter.py

class LegacyToolAdapter(Tool):
    """기존 Geny BaseTool 을 새 Tool ABC 에 맞춤."""

    def __init__(self, legacy: "BaseTool"):
        self._legacy = legacy
        self.name = legacy.name
        self.description = legacy.description
        self._schema = legacy.parameters or {}
        self._accepts_session_id = _probe_session_id_support(legacy)

    def input_schema(self) -> dict:
        return self._schema

    def capabilities(self, input: dict) -> ToolCapabilities:
        # 보수적 기본값: 모든 legacy tool 은 fail-closed
        return ToolCapabilities(
            concurrency_safe=getattr(self._legacy, "_concurrency_safe", False),
            read_only=getattr(self._legacy, "_read_only", False),
            destructive=getattr(self._legacy, "_destructive", False),
        )

    async def execute(self, input, ctx, *, on_progress=None) -> ToolResult:
        kwargs = dict(input)
        if self._accepts_session_id and ctx.session_id:
            kwargs.setdefault("session_id", ctx.session_id)

        try:
            result_raw = await self._legacy.arun(**kwargs) \
                         if hasattr(self._legacy, "arun") \
                         else self._legacy.run(**kwargs)
        except Exception as e:
            return ToolResult(data=None, is_error=True, display_text=str(e))

        text = result_raw if isinstance(result_raw, str) else str(result_raw)
        return ToolResult(data=result_raw, display_text=text)
```

**마이그레이션 정책**: 새로 만드는 built-in tool 은 새 ABC 로, 기존 것은 adapter 로 감싸서 시간 두고 점진 전환.

---

## 5. Stage 10 — Partition-based orchestration

```python
# geny_executor/stages/s10_tool/artifact/default/orchestrator.py

async def orchestrate_tools(
    pending_calls: list[ToolCall],
    registry: "ToolRegistry",
    ctx: ToolContext,
    *,
    max_concurrent: int = 10,
    event_bus: "EventBus",
) -> list[ToolResult]:
    # 1. partition by concurrency_safe
    safe, unsafe = [], []
    for call in pending_calls:
        tool = registry.get(call.tool_name)
        caps = tool.capabilities(call.input)
        (safe if caps.concurrency_safe else unsafe).append(call)

    results: list[ToolResult] = []

    # 2. safe batch — parallel (bounded)
    sem = asyncio.Semaphore(max_concurrent)
    async def _run_one(call):
        async with sem:
            return await _run_with_lifecycle(call, registry, ctx, event_bus)
    safe_results = await asyncio.gather(*[_run_one(c) for c in safe])
    results.extend(safe_results)

    # 3. unsafe batch — serial
    for call in unsafe:
        r = await _run_with_lifecycle(call, registry, ctx, event_bus)
        results.append(r)

    return results


async def _run_with_lifecycle(call, registry, ctx, bus):
    tool = registry.get(call.tool_name)
    event_emit("tool.call_start", {"id": call.id, "tool": tool.name})
    try:
        await tool.on_enter(call.input, ctx)
        # validation
        validated = tool.validate_input(call.input)
        # permission
        decision = await tool.check_permissions(validated, ctx)
        if decision.behavior == "deny":
            return ToolResult(data=None, is_error=True, display_text=f"denied: {decision.reason}")
        if decision.behavior == "ask":
            # Stage 4 Guard 가 PermissionRequest hook 을 띄우고 resume
            ...
        validated = decision.updated_input or validated

        # execute
        result = await tool.execute(validated, ctx)

        # auto-persist on overflow
        caps = tool.capabilities(validated)
        if result.display_text and len(result.display_text) > caps.max_result_chars:
            path = _persist_large_result(result, ctx)
            result.persist_full = path
            result.display_text = f"(result persisted to {path}, showing first N chars)\n{result.display_text[:caps.max_result_chars]}"

        await tool.on_exit(result, ctx)
        event_emit("tool.call_complete", {"id": call.id, "tool": tool.name})
        return result
    except Exception as e:
        await tool.on_error(e, ctx)
        event_emit("tool.call_error", {"id": call.id, "tool": tool.name, "error": str(e)})
        return ToolResult(data=None, is_error=True, display_text=f"error: {e}")
```

### 관찰

- `max_concurrent` 는 `ConfigSchema` 로 노출 → preset 별 튜닝 가능
- `ask` behavior 는 Stage 4 Guard (PermissionGuard 확장) 와 협업 — 09 design 참조
- `_persist_large_result` 는 `ctx.storage_path` 하위 `tool-results/{call_id}.json` 등에 저장

---

## 6. Streaming tool executor

LLM 이 tool_use 블록을 **스트리밍으로** 내보낼 때 (Anthropic streaming API), 이미 도착한 tool 은 즉시 실행 시작하는 구조:

```python
class StreamingToolExecutor:
    def __init__(self, registry, ctx, event_bus, max_concurrent=10):
        self._queue: list[ToolCall] = []
        self._done: dict[str, ToolResult] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._sem = asyncio.Semaphore(max_concurrent)
        self._order: list[str] = []   # 수신 순

    async def add(self, call: ToolCall):
        self._order.append(call.id)
        tool = self._registry.get(call.tool_name)
        caps = tool.capabilities(call.input)
        if caps.concurrency_safe and self._no_unsafe_pending():
            # 즉시 시작
            self._tasks[call.id] = asyncio.create_task(self._run(call))
        else:
            # 이전 unsafe 가 끝날 때까지 대기
            self._queue.append(call)

    async def drain(self) -> list[ToolResult]:
        # 대기열 + 실행중 전부 완료
        while self._queue or self._tasks:
            if self._tasks:
                done_id = await self._wait_any()
                self._done[done_id] = ...
            if self._queue and self._no_unsafe_pending():
                next_call = self._queue.pop(0)
                self._tasks[next_call.id] = asyncio.create_task(self._run(next_call))
        # 수신 순으로 반환
        return [self._done[i] for i in self._order]
```

**관찰**: 결과는 **수신 순** 으로 돌려줌. LLM 이 여러 tool_use 를 한 응답 안에 섞어서 보냈을 때, 재현성과 UX 가 일관됨.

---

## 7. Result persistence

```python
def _persist_large_result(result: ToolResult, ctx: ToolContext) -> str:
    storage = Path(ctx.storage_path) / "tool-results"
    storage.mkdir(parents=True, exist_ok=True)
    call_id = ctx.extras.get("current_tool_call_id") or uuid.uuid4().hex[:12]
    path = storage / f"{call_id}.json"
    path.write_text(json.dumps({
        "data":        _to_jsonable(result.data),
        "display_text": result.display_text,
        "artifacts":   result.artifacts,
        "timestamp":   datetime.utcnow().isoformat(),
    }, ensure_ascii=False, indent=2))
    return str(path)
```

LLM 은 `{call_id}.json` 경로만 받고, 후속 turn 에서 `read` tool 로 필요한 부분만 가져오면 됨. context 가 단번에 터지는 것을 막는다.

---

## 8. Permission matcher 예시 — `BashTool`

```python
class BashTool(Tool):
    name = "Bash"
    description = "Run a bash command."

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 120_000},
            },
            "required": ["command"],
        }

    def capabilities(self, input: dict) -> ToolCapabilities:
        cmd = (input.get("command") or "").strip()
        destructive = any(bad in cmd for bad in ("rm -rf", "mkfs", "dd if="))
        read_only = cmd.startswith(("ls ", "cat ", "grep ", "find ", "echo "))
        return ToolCapabilities(
            concurrency_safe=False,   # Bash 는 exclusive
            read_only=read_only,
            destructive=destructive,
            interrupt="cancel",
            max_result_chars=30_000,
        )

    async def prepare_permission_matcher(self, input: dict):
        cmd = input.get("command", "")
        def match(pattern: str) -> bool:
            # "Bash(git *)" 스타일
            if pattern == self.name:
                return True
            if pattern.startswith(f"{self.name}("):
                inner = pattern[len(self.name)+1:-1]
                return fnmatch.fnmatch(cmd, inner)
            return False
        return match

    async def check_permissions(self, input, ctx):
        # permission_mode 에 따라 기본 동작
        if ctx.permission_mode == "bypass":
            return PermissionDecision(behavior="allow")
        caps = self.capabilities(input)
        if caps.destructive and ctx.permission_mode != "auto":
            return PermissionDecision(behavior="ask", reason="destructive command")
        return PermissionDecision(behavior="allow")

    async def execute(self, input, ctx, *, on_progress=None):
        # 실제 subprocess 실행
        ...
```

이 구조에서는:
- `Bash(git *)` 같은 allow rule 이 있으면 `git push` 명령은 통과, `rm -rf /` 는 destructive 판정 → ask
- concurrency_safe=False 이므로 다른 Bash 와 직렬

---

## 9. Geny 어댑터 — `_GenyToolAdapter` 재구성

현재 `backend/service/executor/tool_bridge.py` 의 `_GenyToolAdapter` 는 새 Tool ABC 가 도입되면 다음과 같이 단순해진다:

```python
class _GenyToolAdapter(Tool):
    """Geny BaseTool → geny-executor Tool. 기존 로직을 새 ABC 에 맞춤."""
    def __init__(self, geny_tool):
        self._t = geny_tool
        self.name = geny_tool.name
        self.description = geny_tool.description
        self._schema = geny_tool.parameters or {"type": "object", "properties": {}}
        self._accepts_session_id = _probe_session_id_support(geny_tool)

    def input_schema(self): return self._schema

    def capabilities(self, input):
        # Geny BaseTool 에 선언된 optional 속성 읽기
        caps_dict = getattr(self._t, "_capabilities", {}) or {}
        return ToolCapabilities(**caps_dict)

    async def execute(self, input, ctx, *, on_progress=None):
        kwargs = dict(input)
        if self._accepts_session_id:
            kwargs.setdefault("session_id", ctx.session_id)
        raw = await self._t.arun(**kwargs) if hasattr(self._t, "arun") else self._t.run(**kwargs)
        return ToolResult(data=raw, display_text=str(raw))
```

Geny `BaseTool` 에 새 optional 속성을 얹는 정도의 변경으로 기존 tool 전부가 새 Tool ABC 의 혜택을 받을 수 있게 됨:

```python
# backend/tools/built_in/geny_tools.py 예시

@tool
def search_knowledge(query: str, session_id: str = None) -> str:
    """..."""
    return result

# optional: capability 선언
search_knowledge._capabilities = dict(
    concurrency_safe=True,
    read_only=True,
    network_egress=True,
    max_result_chars=50_000,
)
```

---

## 10. 테스트 전략

새 Tool ABC 에 대해 다음 테스트 필수:

1. **capability contract** — 각 built-in tool 의 `capabilities()` 가 input 별 올바른 flag 반환
2. **permission matcher** — 패턴 × input 조합 매칭 정확성
3. **orchestrator partition** — safe vs unsafe 가 올바르게 나뉘는지, 병렬 cap 준수
4. **streaming executor** — 수신 순 결과 보존, unsafe blocker 처리
5. **result persistence** — overflow 시 디스크 저장, LLM 에 경로 전달
6. **legacy adapter** — 기존 BaseTool 이 새 ABC 하에서 동작, capability 는 fail-closed 기본값

---

## 11. 마이그레이션 인터페이스 (요약)

| 단계 | 변경 위치 | 영향 |
|---|---|---|
| 1 | `geny_executor/tools/base.py` 에 새 ABC 추가 | 신규 API, 기존 영향 없음 |
| 2 | `LegacyToolAdapter` 추가 | 기존 `BaseTool` 자동 래핑 |
| 3 | Stage 10 artifact 재작성 (partition orchestrator) | 내부 로직 변경, 외부 API 동일 |
| 4 | built-in tool 점진 마이그레이션 | per-PR (Read/Write/Edit/Bash 등) |
| 5 | Geny `_GenyToolAdapter` 단순화 | backend 쪽 `_capabilities` 속성 도입 |
| 6 | Permission rule 매트릭스 도입 | 09 design 과 동시 |

상세 순서는 `11_migration_roadmap.md` 참조.

---

## 12. 공개 API 시그니처 요약

```python
# geny_executor 공개 export 추가
from geny_executor.tools import (
    Tool,                  # new ABC
    ToolCapabilities,
    ToolContext,
    ToolResult,
    PermissionDecision,
    build_tool,
    LegacyToolAdapter,     # 호환 bridge
)
from geny_executor.stages.s10_tool import orchestrate_tools, StreamingToolExecutor
```

---

## 13. Built-in Tool Catalog — "executor 가 기본 제공해야 할 15–20 종"

### 13.1 현재 vs 목표

| 상태 | 현재 (0.31.x) | 목표 (1.0) |
|---|---|---|
| executor 내장 | 6 종 | 15–20 종 |
| 호스트 (Geny) 가 공급 | 16+ 종 (web_search, browser, web_fetch, …) | 5–7 종 (플랫폼 특화만) |

이 이동의 이유는 01 원칙 P7 (geny-executor first) + P8 (rich built-in catalog). **같은 도구 로직이 여러 호스트에 중복 구현되는 것을 막는 가장 확실한 방법은 executor 에 내장하는 것**.

### 13.2 신설 built-in tool 카탈로그 (제안)

각 tool 은 claude-code 의 동명 tool 을 1차 참조로 해 Python 으로 재구현. Tool ABC 에 맞춘 capability 선언은 **중요** (Stage 10 orchestration 이 이 메타에 의존).

#### 13.2.1 파일시스템·쉘 (이미 있음, 개선만)

| 이름 | capability 요약 | 개선 방향 |
|---|---|---|
| `Read` | concurrency_safe=True, read_only=True, max_result_chars=500_000 | 이미지·PDF·notebook 지원 추가. 토큰 budget 기반 라인 범위. |
| `Write` | concurrency_safe=False, destructive=False | diff preview + reject UI hook |
| `Edit` | concurrency_safe=False, destructive=False | 다중 edit 직렬화 |
| `Bash` | concurrency_safe=False, input-dependent destructive | timeout + sandbox hint + ANSI color 보존 |
| `Glob` | concurrency_safe=True, read_only=True | 현재 유지 |
| `Grep` | concurrency_safe=True, read_only=True | 결과 persist (큰 grep 대비) |

#### 13.2.2 Web 계열 (신설)

| 이름 | 설명 | capability |
|---|---|---|
| `WebFetch` | URL 을 읽고 본문 HTML/Markdown 추출 | concurrency_safe=True, read_only=True, network_egress=True |
| `WebSearch` | 검색 엔진 질의 (DDG 등 backend 추상) | concurrency_safe=True, read_only=True, network_egress=True |

지금 Geny 의 `tools/custom/web_fetch_tools.py`, `web_search_tools.py` 는 executor 로 이식. Geny 는 dependency (ddgs, playwright) 만 extras 에 포함.

#### 13.2.3 Agent / Skill / Task 메타 (신설, 핵심)

| 이름 | 설명 | capability |
|---|---|---|
| `Agent` | subagent spawn (isolation: inline/worktree/remote, subagent_type 지정) | concurrency_safe=False (자식의 격리 때문), network_egress=True |
| `Skill` | 등록된 skill 호출 — 08 design 참조 | 자식 skill 에 의존 |
| `TaskCreate` / `TaskGet` / `TaskList` / `TaskUpdate` / `TaskOutput` / `TaskStop` | background task 관리 | 대부분 read_only=True, `TaskCreate`/`Stop` 만 destructive |

이들은 "LLM 이 자기 실행을 제어" 하는 메타 tool. Geny 의 Sub-Worker pairing / thinking trigger 는 이 위에서 플랫폼 특화 레이어로 남는다.

#### 13.2.4 노트 / 일정 / 감시 (신설)

| 이름 | 설명 | capability |
|---|---|---|
| `TodoWrite` | 현재 세션의 todo 리스트 관리 (state.shared 에 저장) | concurrency_safe=False, read_only=False, destructive=False |
| `NotebookEdit` | Jupyter `.ipynb` 편집 | concurrency_safe=False |
| `Schedule` / `CronCreate` / `CronList` / `CronDelete` | 예약 task | scheduling backend 필요 |
| `Monitor` | 장기 실행 프로세스 이벤트 스트리밍 (Bash 의 `run_in_background` 와 짝) | concurrency_safe=True, read_only=True |

`TodoWrite` 와 `Monitor` 는 executor 가 "자기 워크플로를 자기가 보는" 능력을 제공 — claude-code 가 이를 유용히 활용.

#### 13.2.5 유틸리티 메타 (신설)

| 이름 | 설명 |
|---|---|
| `ToolSearch` | 지연 로드된 tool 의 schema 를 필요 시 가져오는 메커니즘 (deferred tools) — 대용량 tool 카탈로그 운영 시 컨텍스트 절약 |
| `EnterPlanMode` / `ExitPlanMode` | permission mode 를 런타임에 전환 |
| `EnterWorktree` / `ExitWorktree` | git worktree 격리 진입·해제 (Agent 와 연동) |

### 13.3 호스트 (Geny) 가 유지해야 할 tool — "플랫폼 특화만"

| 이름 | 이유 |
|---|---|
| `feed` / `play` / `gift` / `talk` (게임 도구) | 타마고치 게임 규칙 — 다른 프로젝트에 의미 없음 |
| `search_knowledge` / `read_memory` / `write_memory` | Geny 메모리 시스템 고유 |
| `get_session_info` / `send_direct_message_internal` 등 | Geny 세션·메신저 고유 |
| Character / persona 조작 | VTuber 전용 |

즉 Geny 가 유지해야 할 tool 은 **플랫폼 수준에서 말이 되는 것** 들만.

### 13.4 카탈로그 배치 구조

```
geny-executor/src/geny_executor/tools/
├── base.py                         # Tool ABC + ToolCapabilities + build_tool
├── registry.py                     # ToolRegistry
├── legacy_adapter.py               # LegacyToolAdapter
├── built_in/
│   ├── __init__.py                 # auto-register
│   ├── filesystem/
│   │   ├── read.py
│   │   ├── write.py
│   │   ├── edit.py
│   │   ├── glob.py
│   │   └── grep.py
│   ├── shell/
│   │   └── bash.py
│   ├── web/
│   │   ├── fetch.py
│   │   └── search.py
│   ├── agent/
│   │   ├── agent_tool.py
│   │   └── skill_tool.py
│   ├── task/
│   │   ├── create.py
│   │   ├── read.py
│   │   ├── update.py
│   │   └── monitor.py
│   ├── notebook/
│   │   └── edit.py
│   ├── workflow/
│   │   ├── todo_write.py
│   │   ├── schedule.py
│   │   └── cron.py
│   └── meta/
│       ├── tool_search.py
│       ├── permission_mode.py
│       └── worktree.py
└── mcp/
    ├── manager.py
    └── adapter.py
```

`built_in/__init__.py` 가 자동 등록:

```python
# geny_executor/tools/built_in/__init__.py

from . import filesystem, shell, web, agent, task, notebook, workflow, meta

def get_builtin_tools() -> list[Tool]:
    from .filesystem import read, write, edit, glob, grep
    from .shell import bash
    from .web import fetch, search
    from .agent import agent_tool, skill_tool
    from .task import create, read as task_read, update, monitor
    from .notebook import edit as nb_edit
    from .workflow import todo_write, schedule, cron
    from .meta import tool_search, permission_mode, worktree

    return [
        read.READ_TOOL, write.WRITE_TOOL, edit.EDIT_TOOL, glob.GLOB_TOOL, grep.GREP_TOOL,
        bash.BASH_TOOL,
        fetch.WEB_FETCH_TOOL, search.WEB_SEARCH_TOOL,
        agent_tool.AGENT_TOOL, skill_tool.SKILL_TOOL,
        create.TASK_CREATE_TOOL, task_read.TASK_GET_TOOL, task_read.TASK_LIST_TOOL,
        update.TASK_UPDATE_TOOL, update.TASK_STOP_TOOL, monitor.MONITOR_TOOL,
        nb_edit.NOTEBOOK_EDIT_TOOL,
        todo_write.TODO_WRITE_TOOL,
        schedule.SCHEDULE_TOOL,
        cron.CRON_CREATE_TOOL, cron.CRON_LIST_TOOL, cron.CRON_DELETE_TOOL,
        tool_search.TOOL_SEARCH_TOOL,
        permission_mode.ENTER_PLAN_MODE_TOOL, permission_mode.EXIT_PLAN_MODE_TOOL,
        worktree.ENTER_WORKTREE_TOOL, worktree.EXIT_WORKTREE_TOOL,
    ]
```

### 13.5 Feature flag + conditional 등록

claude-code 의 "feature flag 로 tool 포함 제어" 패턴을 Python lazy import 로:

```python
# geny_executor/tools/built_in/__init__.py

def get_builtin_tools(*, features: Optional[set[str]] = None) -> list[Tool]:
    features = features or set()
    tools = _core_tools()   # 항상 포함

    if "web" in features or _default_enabled("GENY_EXECUTOR_WEB"):
        tools += _web_tools()
    if "task" in features or _default_enabled("GENY_EXECUTOR_TASK"):
        tools += _task_tools()
    ...

    return tools
```

이렇게 해서 "web 도구 없이 가벼운 executor" 같은 deployment 도 가능.

---

## 14. Extension Provider — 호스트가 tool 을 주입하는 표준 패턴

호스트 (Geny 등) 가 플랫폼 특화 tool 을 executor 에 넣을 때의 공식 channel. 이미 `AdhocToolProvider` 가 존재하지만 uplift 에서 계약을 명확화한다.

### 14.1 Provider 프로토콜

```python
# geny_executor/tools/provider.py

from typing import Protocol, runtime_checkable, Iterable

@runtime_checkable
class ToolProvider(Protocol):
    """호스트 (Geny 등) 가 built-in 위에 추가 tool 을 공급하는 표준 인터페이스."""

    def namespace(self) -> str:
        """provider 이름 — tool 충돌 시 prefix 로 사용. 예: 'geny'."""

    def list_tools(self) -> Iterable[Tool]:
        """이 provider 가 제공하는 Tool ABC 인스턴스."""

    def health_check(self) -> dict:
        """provider 의 상태 (초기화 여부, 외부 의존 서비스 상태 등)."""
```

Geny 측 구현 예시:

```python
# Geny/backend/service/executor/tool_provider.py

class GenyPlatformToolProvider:
    """Geny 플랫폼 특화 tool provider."""

    def __init__(self, tool_loader, session_manager, game_state_store):
        self._loader = tool_loader
        self._mgr = session_manager
        self._state = game_state_store

    def namespace(self) -> str:
        return "geny"

    def list_tools(self) -> list[Tool]:
        tools = []
        # 게임 도구
        tools.append(FeedTool(self._state))
        tools.append(PlayTool(self._state))
        tools.append(GiftTool(self._state))
        tools.append(TalkTool(self._state))
        # 세션 관리
        tools.append(SessionInfoTool(self._mgr))
        tools.append(InternalMessageTool(self._mgr))
        # 메모리
        tools.append(KnowledgeSearchTool(self._loader))
        tools.append(MemoryReadTool(self._loader))
        tools.append(MemoryWriteTool(self._loader))
        # (legacy 어댑터가 필요한 기존 BaseTool 들)
        for name in self._loader.builtin_tools:
            if name not in _REPLACED_BY_NEW:
                tools.append(LegacyToolAdapter(self._loader.get_tool(name)))
        return tools

    def health_check(self) -> dict:
        return {
            "state_store_alive": self._state.is_alive(),
            "session_count": len(self._mgr.list_agents()),
        }
```

### 14.2 Pipeline 빌드 시 주입

```python
# Geny/backend/service/executor/agent_session_manager.py

from geny_executor import Pipeline
from geny_executor.tools.built_in import get_builtin_tools
from .tool_provider import GenyPlatformToolProvider

async def create_agent_session(...):
    builtin = get_builtin_tools()              # 15-20 종 executor 기본 제공
    platform = GenyPlatformToolProvider(...)   # 플랫폼 특화 10 종 내외
    pipeline = Pipeline.from_manifest_async(
        manifest,
        tool_providers=[platform],             # ← 호스트 주입 채널
        builtin_tools=builtin,                 # ← executor 기본 세트
        adhoc_providers=[],                    # (deprecated) legacy 슬롯
    )
    pipeline.attach_runtime(...)
```

`tool_providers` 는 list — 여러 provider 를 동시에 받을 수 있어 "플랫폼 + 조직 + 사용자" 같은 계층 공급 가능.

### 14.3 Namespace 충돌 해결

- built-in tool 의 name 은 prefix 없이 (`Read`, `Bash`)
- provider tool 은 자동으로 `{namespace}.{name}` 으로 registry 에 저장 (`geny.feed`)
- 사용자 프롬프트 / MCP 에는 짧은 이름 노출, 충돌 시 full-qualified 이름
- Skill 이 `allowed_tools: [Read, geny.feed]` 처럼 mixed 선언 가능

### 14.4 Provider → EventBus

Provider 가 health_check 실패하면 `tool_provider.degraded` 이벤트 발사 → 해당 provider 의 tool 이 일시 `isEnabled()=False`. 복구 시 자동 재활성.

---

## 15. 이 섹션이 의미하는 것

- Geny 의 `backend/tools/built_in/` 대부분은 **executor 로 이동** 대상 (Read/Write/Bash/Glob/Grep 이 이미 executor 에 있다면, web_search/web_fetch/browser 등도 이동).
- Geny 에 남는 것은 `geny_tools.py` / `game_tools.py` / `knowledge_tools.py` / `memory_tools.py` — 전부 플랫폼 특화.
- 그 결과 Geny 가 유지보수해야 하는 tool 코드가 **절반 이하**로 줄어들고, executor 사용자 (앞으로 등장할 타 프로젝트) 는 Geny 수준의 도구 함량을 기본으로 얻는다.

다음 문서 ([`07_design_mcp_integration.md`](07_design_mcp_integration.md)) 에서 MCP 측 고도화가 이 Tool ABC 를 어떻게 채우는지 이어감.
