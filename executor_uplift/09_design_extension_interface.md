# 09. Design — Extension Interface

**Status:** Draft
**Date:** 2026-04-24
**Priority:** P1 — 전체 설계의 정합성을 결정하는 "지도"

---

## 1. 왜 통합 Extension Interface 가 필요한가

현재 geny-executor + Geny 에는 서로 다른 확장 메커니즘이 7 종 이상 공존:

1. `ConfigField` / `ConfigSchema` — 파라미터
2. `StrategySlot` — 내부 로직 교체
3. `SlotChain` — 순서 있는 합성
4. `PipelineMutator` — 런타임 변경 + 감사
5. `EventBus` — pub/sub
6. `attach_runtime(...)` kwargs — 런타임 주입
7. `EnvironmentManifest` — 직렬화된 빌드 명세

여기에 이번 uplift 로 추가되는:

8. **Tool 계약 메타** (06)
9. **Permission rule matrix** (아래 2 절)
10. **Subprocess hooks** (아래 3 절)
11. **Skill 레지스트리** (08)
12. **MCP runtime manager** (07)
13. **state.shared 스키마** (아래 4 절)

개별 설계만 하면 **"이 기능 추가하려면 어떤 메커니즘을 써야 하는가?"** 에 답하기 어려워짐. 이 문서는 **의사결정 트리** + **각 메커니즘의 역할 경계** 를 정한다.

---

## 2. Permission Rule Matrix (P0)

### 2.1 모델

```python
# geny_executor/permission/types.py

from enum import Enum
from dataclasses import dataclass
from typing import Optional

class PermissionBehavior(str, Enum):
    ALLOW = "allow"
    DENY  = "deny"
    ASK   = "ask"

class PermissionSource(str, Enum):
    CLI_ARG        = "cli_arg"          # 실행시 --allow Bash
    LOCAL          = "local"            # <project>/.geny/permissions.json
    PROJECT        = "project"          # <project>/.geny/permissions.yaml
    USER           = "user"             # ~/.geny/permissions.yaml
    PRESET_DEFAULT = "preset_default"   # preset 내장

@dataclass(frozen=True)
class PermissionRule:
    tool_name: str                      # "Bash", "Edit", "*"
    pattern:   Optional[str] = None     # "git *" 같은 input 패턴
    behavior:  PermissionBehavior = PermissionBehavior.ALLOW
    source:    PermissionSource = PermissionSource.CLI_ARG
    reason:    Optional[str] = None     # 감사 로그용

class PermissionMode(str, Enum):
    DEFAULT = "default"
    PLAN    = "plan"        # read-only 만 허용, edit 시 ask
    AUTO    = "auto"        # destructive 도 allow (위험)
    BYPASS  = "bypass"      # 전부 allow (개발자 전용)
```

### 2.2 체크 흐름

```python
async def evaluate_permission(
    tool: Tool,
    input: dict,
    rules: list[PermissionRule],
    mode: PermissionMode,
) -> PermissionDecision:
    # mode=BYPASS 는 즉시 allow
    if mode == PermissionMode.BYPASS:
        return PermissionDecision(behavior="allow")

    matcher = await tool.prepare_permission_matcher(input)
    # 우선순위: CLI > LOCAL > PROJECT > USER > PRESET_DEFAULT
    ordered = _sort_by_source_priority(rules)

    for rule in ordered:
        if rule.tool_name not in (tool.name, "*"):
            continue
        if rule.pattern and not matcher(rule.pattern):
            continue
        return PermissionDecision(
            behavior=rule.behavior.value,
            reason=f"matched {rule.source.value}: {rule.tool_name}({rule.pattern or '*'})",
        )

    # 매칭 없음 → tool 자체 결정
    return await tool.check_permissions(input, ctx)
```

### 2.3 저장 형식

```yaml
# ~/.geny/permissions.yaml
allow:
  - { tool: Bash,   pattern: "git *" }
  - { tool: Bash,   pattern: "ls *" }
  - { tool: Read,   pattern: "*" }
  - { tool: "*",    pattern: "*",    reason: "local dev" }   # 개발자용
deny:
  - { tool: Bash,   pattern: "rm -rf *" }
  - { tool: Bash,   pattern: "mkfs *" }
ask:
  - { tool: Edit,   pattern: "*" }       # 파일 수정은 매번 물어봄 (plan mode)
```

### 2.4 우리의 `ToolPolicyEngine` 과의 관계

- 현재 `ToolPolicyEngine` 은 **서버 prefix 수준 필터** → Stage 3 에서 tool 목록 자체에서 제외
- 새 Permission matrix 는 **call time 수준 gate** → Stage 10 직전에서 차단
- 두 레이어는 **보완적**:
  - `ToolPolicyEngine` — "이 세션에 이 tool 이 보이게 할 것인가"
  - `Permission matrix` — "이 특정 input 으로 이 tool 을 호출하는 것이 허용되나"

---

## 3. Subprocess Hooks (P1)

### 3.1 이벤트 카테고리

```python
# geny_executor/hooks/events.py

class HookEvent(str, Enum):
    SESSION_START       = "session_start"
    SESSION_END         = "session_end"
    USER_PROMPT_SUBMIT  = "user_prompt_submit"
    PIPELINE_START      = "pipeline_start"
    STAGE_ENTER         = "stage_enter"
    STAGE_EXIT          = "stage_exit"
    PRE_TOOL_USE        = "pre_tool_use"       # Stage 10 직전
    POST_TOOL_USE       = "post_tool_use"      # Stage 10 직후 (성공)
    POST_TOOL_FAILURE   = "post_tool_failure"  # Stage 10 직후 (실패)
    PERMISSION_REQUEST  = "permission_request" # ask behavior 시
    PERMISSION_DENIED   = "permission_denied"
    LOOP_ITERATION_END  = "loop_iteration_end"
    CWD_CHANGED         = "cwd_changed"
    MCP_SERVER_STATE    = "mcp_server_state"
    NOTIFICATION        = "notification"       # 임의 알림 채널
```

### 3.2 등록 형식

사용자는 `~/.geny/settings.yaml` 또는 `<project>/.geny/settings.yaml` 에:

```yaml
hooks:
  pre_tool_use:
    - if:
        tool_name: [Bash, Edit, Write]
      then:
        command: ./scripts/pre_check.sh
        timeout_ms: 5000
  post_tool_use:
    - if:
        tool_name: "*"
      then:
        command: ./scripts/audit_log.sh
        timeout_ms: 2000
  permission_request:
    - then:
        command: ./scripts/notify_slack.sh
```

### 3.3 Subprocess 프로토콜

```
이벤트 발생
  ↓
hook_runner(event, payload) 호출
  ↓
for each matched hook:
    ┌ stdin (JSON):
    │   {
    │     "event": "pre_tool_use",
    │     "session_id": "...",
    │     "tool_name": "Bash",
    │     "tool_input": { "command": "git status" },
    │     "permission_mode": "default",
    │     "timestamp": "2026-04-24T15:30:00Z"
    │   }
    ↓
    subprocess spawn (with timeout)
    ↓
    ┌ stdout (JSON):
    │   {
    │     "continue": true,
    │     "suppress_output": false,
    │     "decision": null,          // 'block' | 'approve' | null (pass-through)
    │     "modified_input": { ... }, // optional — tool_input 수정
    │     "hook_specific_output": { ... }
    │   }
    ↓
engine 이 응답 해석 → 실행 계속 / 차단 / input 변형
```

### 3.4 구현 스케치

```python
# geny_executor/hooks/runner.py

class HookRunner:
    def __init__(self, config: HooksConfig, *, enabled: bool):
        self._config = config
        self._enabled = enabled        # GENY_ALLOW_HOOKS=1 일 때만 True
        self._audit_log = []

    async def fire(self, event: HookEvent, payload: dict) -> HookOutcome:
        if not self._enabled:
            return HookOutcome.passthrough()

        matched = self._config.find_matching(event, payload)
        outcome = HookOutcome.passthrough()

        for spec in matched:
            result = await self._run_one(spec, event, payload)
            self._audit_log.append({"event": event, "spec": spec.command, "result": result})
            outcome = outcome.combine(result)
            if outcome.blocked:
                break
        return outcome

    async def _run_one(self, spec, event, payload) -> HookOutcome:
        stdin = json.dumps({
            "event": event.value, "timestamp": _now_iso(), **payload,
        }).encode("utf-8")
        try:
            proc = await asyncio.create_subprocess_exec(
                *_parse_command(spec.command),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=spec.cwd,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(input=stdin),
                timeout=spec.timeout_ms / 1000,
            )
            resp = json.loads(out.decode("utf-8"))
            return HookOutcome.from_response(resp)
        except asyncio.TimeoutError:
            return HookOutcome(blocked=False, note="timeout")
        except Exception as e:
            return HookOutcome(blocked=False, note=f"error: {e}")
```

### 3.5 보안 가드

- 기본 disabled (`GENY_ALLOW_HOOKS=1` opt-in)
- 파일 경로만 허용 (URL 실행 금지)
- PATH 로 검색 금지 — 절대 경로 강제
- timeout 강제 (기본 5 초)
- stdout 크기 제한 (1 MiB)
- hook output 의 `modified_input` 은 **whitelisted keys** 만 적용

---

## 4. `state.shared` 스키마화

현재 `state.shared` 는 `Dict[str, Any]` — 누구나 임의 key 에 쓸 수 있음. 09 design 에서는 **namespace + TypedDict** 로 구조화.

### 4.1 Namespace 제안

```python
# geny_executor/core/shared_keys.py

class SharedKeys:
    """state.shared 에서 공식 사용되는 키의 중앙 카탈로그."""
    # Geny 전용
    CREATURE_STATE   = "geny.creature_state"
    MUTATION_BUFFER  = "geny.mutation_buffer"
    CREATURE_ROLE    = "geny.creature_role"

    # executor core
    TOOL_CALL_ID     = "executor.current_tool_call_id"
    SKILL_CTX        = "executor.current_skill_ctx"
    PERMISSION_CACHE = "executor.permission_cache"

    # memory
    MEMORY_CONTEXT   = "memory.context_chunks"
    MEMORY_DIRTY     = "memory.needs_reflection"

    # 사용자 정의 (plugin 이름 prefix 필수)
    @staticmethod
    def plugin(namespace: str, key: str) -> str:
        return f"plugin.{namespace}.{key}"
```

### 4.2 타입 힌트 via TypedDict

```python
# geny_executor/core/shared_schema.py

from typing import TypedDict, Optional

class CreatureState(TypedDict):
    mood: str
    bond: dict
    vitals: dict

class MutationBufferEntry(TypedDict):
    stat: str
    delta: float
    reason: str

class SharedDict(TypedDict, total=False):
    # Geny
    creature_state: CreatureState
    mutation_buffer: list[MutationBufferEntry]
    creature_role: str
    # executor
    current_tool_call_id: str
    current_skill_ctx: dict
    permission_cache: dict[str, str]
    memory_context_chunks: list[str]
    memory_needs_reflection: bool
```

`PipelineState.shared` 타입을 `Dict[str, Any]` 대신 `SharedDict` (total=False) 로 명시 — IDE 가 힌트 제공, 잘못된 키 타이핑 경고.

### 4.3 마이그레이션 비용

- 기존 코드는 모두 `state.shared.get("key")` 사용 → TypedDict 으로 변경해도 런타임 동작 동일
- 문서 + IDE 힌트 + lint 만 개선됨

---

## 5. 의사결정 트리

**"새 기능 X 를 추가하려는데 어떤 메커니즘을 써야 하나?"**

```
X 가…
│
├── 파라미터 튜닝 (숫자/문자열/enum) 인가?
│     → ConfigField / ConfigSchema
│
├── Stage 내부 로직 한 부분 바꾸는 건가?
│     ├── 단일 교체?        → StrategySlot.swap
│     └── 순서 있는 합성?   → SlotChain.add/remove/reorder
│
├── Stage 전체를 새로 쓰는 건가?
│     → register_stage(new_stage) 로 교체
│
├── 런타임에 주입되는 의존성인가? (LLM client, tool 목록, MCP 등)
│     → Pipeline.attach_runtime(...) kwargs 확장
│
├── 실행 중 변경이 감사 로그에 남아야 하나?
│     → PipelineMutator
│
├── 비동기 observer (로깅, UI 표시, 통계) 인가?
│     → EventBus.on(...)
│
├── 실행 흐름을 block 하거나 input 을 변형해야 하나?
│     → Subprocess Hook (설치 형)
│     또는 Stage.on_enter/on_exit (코드 레벨)
│
├── 프롬프트 + tool 묶음 인가? (재사용 가능한 "캡슐")
│     → Skill (SKILL.md 또는 register_bundled_skill)
│
├── 외부 프로세스가 tool / resource 를 노출하나?
│     → MCP 서버 등록 (MCPManager.register_server)
│
├── 언제 어떤 Tool 이 허용되는가?
│     ├── 서버/역할 수준      → ToolPolicyEngine (Geny)
│     └── Tool × input 수준  → PermissionRule matrix
│
├── 파이프라인 전체를 serializable 하게 만들고 싶은가?
│     → EnvironmentManifest 로 저장/로드
│
├── "이 preset 쓰면 다 맞춰서 돌아감" 같은 프리셋인가?
│     → register_preset 으로 PresetRegistry 에 등록
│
└── 여러 stage 가 공유해야 할 상태인가?
      → state.shared (SharedKeys 로 네임스페이스) + contextvar 로 scope 관리
```

---

## 6. 메커니즘별 책임 경계

### 6.1 "Level 0: 설정만 바꾸면 되는 것"

- ConfigField / ConfigSchema — UI 자동 생성, validate, 직렬화
- 예: `max_turns`, `cache strategy name`, `timeout`

### 6.2 "Level 1: 동작 로직을 바꿔야 하는 것"

- StrategySlot / SlotChain — 내부 로직 교체, stage 정체성 보존
- 예: 다른 compactor, 다른 retriever, 다른 emitter 추가

### 6.3 "Level 2: 여러 stage 에 걸친 capability"

- Skill — prompt + tool + model + 격리 묶음
- 예: "웹검색 후 요약" 같은 복합 워크플로

### 6.4 "Level 3: 실행 외부 관찰/조작"

- EventBus — 비동기 관찰 (메트릭, 대시보드)
- Subprocess Hook — 동기/차단 가능 관찰 (정책, 감사)

### 6.5 "Level 4: 런타임 구조 변경"

- PipelineMutator — 감사 로그 포함 atomic 변경
- attach_runtime — 1회성 런타임 주입

### 6.6 "Level 5: 파이프라인 자체를 재구성"

- PipelineBuilder / register_stage / EnvironmentManifest
- 예: 새 preset, 새 stage 삽입

이 6 레벨을 올라갈수록 **영향 범위 확대 + 변경 비용 상승 + revert 난이도 증가**. 항상 가장 낮은 레벨에서 해결할 수 있는지 먼저 검토.

---

## 7. Extension "Contract" — 새 확장 메커니즘 도입 시 체크리스트

새로운 확장 포인트 (예: Stage 10 의 새 slot) 를 추가할 때 반드시 준수:

1. **ConfigSchema 제공** — 파라미터 튜닝 UI 자동 생성
2. **introspection 대응** — `describe()` / `list_strategies()` 에 반영
3. **Event 방출** — 변경/사용 시 EventBus 이벤트 (예: `slot.swapped`)
4. **Mutation 지원** — `PipelineMutator` 로 atomic 변경 가능
5. **Manifest 직렬화** — `EnvironmentManifest` 에 포함될지 결정 + 포함 시 스키마 확장
6. **Test coverage** — unit + integration + round-trip 직렬화

이 6 개가 보장되면 새 확장은 자연스럽게 기존 운영 도구 (UI, 감사, 직렬화) 의 혜택을 받음.

---

## 8. 공개 API 추가 요약

```python
# Permission
from geny_executor.permission import (
    PermissionBehavior, PermissionSource, PermissionMode,
    PermissionRule, evaluate_permission,
    load_permission_rules,   # YAML 로더
)

# Hooks
from geny_executor.hooks import (
    HookEvent, HookRunner, HookOutcome, HooksConfig,
    load_hooks_config,
)

# SharedKeys
from geny_executor.core.shared_keys import SharedKeys, SharedDict
```

---

## 9. 다음 문서

- [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) — 이 확장 인터페이스를 **각 Stage 별로** 어떻게 활용할지
- [`11_migration_roadmap.md`](11_migration_roadmap.md) — 도입 순서 (Permission matrix 가 왜 P0 인가)
