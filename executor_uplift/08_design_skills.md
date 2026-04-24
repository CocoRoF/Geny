# 08. Design — Skills System

**Status:** Draft
**Date:** 2026-04-24
**Priority:** P0 (core capability — 사용자 확장 friction 을 질적으로 바꾼다)

---

## 1. 왜 Skill 이 필요한가

현재 Geny 에서 "새 capability 를 추가" 하려면:
- **단순 tool** — Python 모듈 + ToolLoader 수정 (1–2 파일)
- **특화 role** — SessionRole enum + 프롬프트 파일 + 정책 매핑 + 어쩌면 persona (4–6 파일)
- **복합 워크플로 (예: "diff 검토 후 PR 초안 작성")** — 코드 수정 없이는 **추가 불가**

claude-code 의 Skill 은 이 gap 을 메운다:
- 하나의 `.md` 파일 또는 `registerBundledSkill(...)` 한 줄로
- **프롬프트 본문 + 허용 tool 리스트 + 모델 override + 실행 컨텍스트 (inline/fork)** 를 번들로 정의
- 사용자가 `/skill_name` 으로 명시적으로 또는 LLM 이 동적 trigger 로 호출

이 시스템을 Geny 에 이식한다.

---

## 2. Skill 정의 스키마

### 2.1 프론트매터 + 본문 구조

```markdown
---
name: search-web-and-summarize
description: 여러 웹 검색 결과를 수집해 주제별 요약을 작성한다
aliases: [websearch-summary]
when_to_use: 사용자가 특정 주제의 "최신 정보" 나 "여러 출처 비교" 를 요청할 때
argument_hint: "<검색어 또는 주제>"
allowed_tools: [search_web, fetch_url, read, write]
model: claude-sonnet-4-5
disable_model_invocation: false       # true 면 API 호출 없이 즉시 실행
user_invocable: true                   # /search-web-and-summarize 로 명시 호출 가능
context: inline                        # inline | fork
agent: null                            # fork 시 특정 subagent type
hooks: {}
files:
  # 선택: skill 본문 외 참조할 파일 embed
  checklist.md: |
    - 출처 다양성
    - 중복 제거
    - 날짜 최신성
---

당신은 웹 검색 전문가입니다. 사용자 요청 주제 **{{argument}}** 에 대해:

1. `search_web` 으로 5 개 이상의 출처를 확보
2. 각 URL 을 `fetch_url` 로 읽어 핵심만 추출
3. `checklist.md` 기준으로 품질 검증
4. 최종 요약을 500 단어 이내로 작성
5. 참고 출처를 번호 매겨 리스트

출력은 마크다운으로.
```

### 2.2 데이터 모델

```python
# geny_executor/skills/types.py

from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

@dataclass
class SkillMetadata:
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    when_to_use: Optional[str] = None       # discovery hint (LLM 이 읽음)
    argument_hint: Optional[str] = None
    allowed_tools: Optional[list[str]] = None   # None = 전체 허용
    model: Optional[str] = None                 # override (없으면 session default)
    disable_model_invocation: bool = False
    user_invocable: bool = True
    context: str = "inline"                     # 'inline' | 'fork'
    agent: Optional[str] = None                 # subagent_type
    hooks: dict = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    loaded_from: str = "unknown"                # 'bundled' | 'disk' | 'mcp'
    source_path: Optional[str] = None           # 디스크 skill 의 원본 경로

@dataclass
class Skill:
    meta: SkillMetadata
    # Prompt 빌더 — 호출 시 contextual 데이터 받아 prompt 블록 리스트 반환
    get_prompt: Callable[[str, "SkillContext"], Awaitable[list[dict]]]
    # disable_model_invocation=True 인 경우 직접 실행 핸들러
    direct_handler: Optional[Callable[[str, "SkillContext"], Awaitable[str]]] = None
```

---

## 3. Skill 등록 & 발견 경로

### 3.1 번들 skill (`registerBundledSkill`)

```python
# geny_executor/skills/registry.py

class SkillRegistry:
    def __init__(self):
        self._by_name: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._by_name[skill.meta.name] = skill
        for alias in skill.meta.aliases:
            self._by_name[alias] = skill

    def unregister(self, name: str) -> None:
        self._by_name.pop(name, None)
        # aliases 도 정리

    def get(self, name: str) -> Optional[Skill]:
        return self._by_name.get(name)

    def list(self) -> list[Skill]:
        # dedupe by .meta.name
        return list({s.meta.name: s for s in self._by_name.values()}.values())

    def user_invocable(self) -> list[Skill]:
        return [s for s in self.list() if s.meta.user_invocable]


# 전역 접근 (또는 DI)
_default_registry = SkillRegistry()

def register_bundled_skill(skill: Skill) -> None:
    _default_registry.register(skill)

def get_default_skill_registry() -> SkillRegistry:
    return _default_registry
```

번들 skill 예시:

```python
# geny_executor/skills/bundled/summarize_session.py

async def _build_prompt(args: str, ctx):
    return [{"type": "text", "text": f"세션 요약. 범위: {args or 'entire'}."}]

register_bundled_skill(Skill(
    meta=SkillMetadata(
        name="summarize-session",
        description="현재 세션 대화 전체를 3단락 요약",
        when_to_use="사용자가 '지금까지 무슨 일이 있었지?' 같은 recap 을 요청할 때",
        user_invocable=True,
        context="inline",
        loaded_from="bundled",
    ),
    get_prompt=_build_prompt,
))
```

### 3.2 디스크 skill 로더

```python
# geny_executor/skills/loader.py

import re
import yaml
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

def load_skills_dir(root: Path, registry: SkillRegistry) -> int:
    count = 0
    for p in sorted(root.rglob("*.md")):
        try:
            skill = _parse_skill_file(p)
        except Exception as e:
            logger.warning(f"skill parse failed: {p} — {e}")
            continue
        registry.register(skill)
        count += 1
    return count

def _parse_skill_file(path: Path) -> Skill:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError("missing frontmatter")
    fm_raw, body = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_raw) or {}
    meta = SkillMetadata(
        name=fm["name"],
        description=fm["description"],
        aliases=tuple(fm.get("aliases", [])),
        when_to_use=fm.get("when_to_use"),
        argument_hint=fm.get("argument_hint"),
        allowed_tools=fm.get("allowed_tools"),
        model=fm.get("model"),
        disable_model_invocation=fm.get("disable_model_invocation", False),
        user_invocable=fm.get("user_invocable", True),
        context=fm.get("context", "inline"),
        agent=fm.get("agent"),
        hooks=fm.get("hooks", {}),
        files=fm.get("files", {}),
        loaded_from="disk",
        source_path=str(path),
    )

    async def _build(args: str, ctx):
        expanded = _expand_template(body, args=args, ctx=ctx, files=meta.files)
        return [{"type": "text", "text": expanded}]

    return Skill(meta=meta, get_prompt=_build)

def _expand_template(body: str, *, args: str, ctx, files: dict) -> str:
    # 아주 단순한 {{argument}} / {{session_id}} / {{files.X}} 치환
    out = body.replace("{{argument}}", args or "")
    out = out.replace("{{session_id}}", ctx.session_id)
    for fname, content in files.items():
        out = out.replace(f"{{{{files.{fname}}}}}", content)
    return out
```

### 3.3 디렉토리 규약

| 위치 | 용도 |
|---|---|
| `~/.geny/skills/*.md` | 사용자 전역 skill |
| `<project>/.geny/skills/*.md` | 프로젝트 로컬 skill |
| `<geny-executor pkg>/skills/bundled/*.py` | 번들 (등록시 `register_bundled_skill`) |

우선순위: 프로젝트 > 사용자 > 번들 (이름 충돌 시).

### 3.4 MCP prompt bridge

07 design 참조. `mcp_prompts_to_skills(manager)` 로 MCP 서버의 prompt 를 Skill 객체로 변환 → registry 에 등록. `loaded_from='mcp'`.

---

## 4. Skill 실행

### 4.1 실행 컨텍스트

```python
@dataclass
class SkillContext:
    session_id: str
    working_dir: Optional[str]
    tool_registry: "ToolRegistry"
    mcp_manager: Optional["MCPManager"]
    event_emit: Callable[[str, dict], None]
    parent_message_id: Optional[str]
    permission_mode: str = "default"
```

### 4.2 SkillTool — Tool ABC 로 래핑

```python
# geny_executor/skills/tool.py

class SkillTool(Tool):
    """메타 tool: LLM 이 `SkillTool(skill_name, args)` 로 스킬을 호출."""
    name = "Skill"
    description = (
        "Invoke a registered skill. A skill bundles a prompt, allowed tools, "
        "and optional model override. Use when available skills match the task."
    )

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill": {"type": "string", "description": "Name of the skill to invoke"},
                "args":  {"type": "string", "description": "Optional argument string"},
            },
            "required": ["skill"],
        }

    def capabilities(self, input: dict) -> ToolCapabilities:
        # skill 자체는 상위 메타 — underlying 실행이 safe/unsafe 결정
        # 보수적으로 unsafe 로 취급 (내부에서 다른 tool 호출 가능하므로)
        return ToolCapabilities(concurrency_safe=False, read_only=False)

    async def execute(self, input, ctx, *, on_progress=None) -> ToolResult:
        skill = self._registry.get(input["skill"])
        if not skill:
            return ToolResult(data=None, is_error=True, display_text=f"unknown skill: {input['skill']}")

        # 즉시 실행형 (disable_model_invocation)
        if skill.meta.disable_model_invocation and skill.direct_handler:
            text = await skill.direct_handler(input.get("args", ""), ctx)
            return ToolResult(data=text, display_text=text)

        # prompt 기반 — pipeline 내에서 sub-run 으로 실행
        blocks = await skill.get_prompt(input.get("args", ""), ctx)

        # 실행 컨텍스트: inline vs fork
        if skill.meta.context == "fork":
            # 자식 Pipeline 을 spawn 해 격리 실행 (Stage 11 참조)
            result_text = await _run_forked_skill(skill, blocks, ctx)
            return ToolResult(data=result_text, display_text=result_text)

        # inline: prompt 를 new_messages 로 반환 → 메인 루프가 다음 API 호출
        return ToolResult(
            data={"skill": skill.meta.name, "blocks": blocks},
            new_messages=[{"role": "user", "content": blocks}],
            display_text=f"Skill '{skill.meta.name}' prompt injected.",
        )
```

### 4.3 명시적 호출 — Slash command 연결

Geny 의 chat/command 에 `/` 파싱을 추가:

```python
# 사용자 입력이 "/search-web-and-summarize AI 안전성" 으로 시작하면
# → SkillTool(skill="search-web-and-summarize", args="AI 안전성") 로 즉시 실행
```

```python
def try_parse_slash_command(input_text: str, registry: SkillRegistry) -> Optional[dict]:
    if not input_text.startswith("/"):
        return None
    head, _, tail = input_text[1:].partition(" ")
    skill = registry.get(head)
    if skill and skill.meta.user_invocable:
        return {"skill": head, "args": tail.strip()}
    return None
```

### 4.4 LLM 자동 trigger

LLM 에게 skill 카탈로그를 system prompt 에 공급 + `SkillTool` 을 도구 목록에 포함 → LLM 이 상황에 맞게 스스로 호출.

Stage 3 (System) 이 skill 카탈로그를 생성:

```python
def build_skills_catalog(registry: SkillRegistry) -> str:
    lines = ["# Available skills\n"]
    for skill in registry.list():
        if not skill.meta.user_invocable and skill.meta.disable_model_invocation:
            continue
        lines.append(f"## {skill.meta.name}\n")
        lines.append(f"{skill.meta.description}\n")
        if skill.meta.when_to_use:
            lines.append(f"**When to use:** {skill.meta.when_to_use}\n")
        if skill.meta.argument_hint:
            lines.append(f"**Argument:** {skill.meta.argument_hint}\n")
        lines.append("")
    return "\n".join(lines)
```

시스템 프롬프트 뒤에 붙임. 토큰 예산이 부족할 때는 compactor 가 truncate.

---

## 5. Stage 통합

### 5.1 Stage 3 (System)

`ComposablePromptBuilder` 가 skill 카탈로그 섹션을 자동 추가:

```python
class SkillCatalogSection(PromptSection):
    def __init__(self, registry: SkillRegistry):
        super().__init__(
            name="skills_catalog",
            priority=80,
            modes={PromptMode.FULL},
        )
        self._registry = registry

    @property
    def content(self) -> str:
        return build_skills_catalog(self._registry)
```

### 5.2 Stage 10 (Tool)

`SkillTool` 을 기본 등록 도구로 포함 (항상 사용 가능). Skill 내에서 다시 다른 tool 을 호출하면 Stage 10 이 재귀로 다시 실행.

### 5.3 Stage 11 (Agent) — fork 격리

`skill.meta.context == "fork"` 인 경우, Stage 11 의 `DelegateOrchestrator` 를 사용해 서브 파이프라인 spawn:

```python
async def _run_forked_skill(skill: Skill, blocks, ctx: SkillContext) -> str:
    # 자식 파이프라인 설정: allowed_tools 제한, model override
    sub_config = _derive_child_config(skill, ctx)
    sub_pipeline = Pipeline(sub_config)
    sub_pipeline.attach_runtime(
        llm_client=ctx.llm_client,
        tools=_filter_tools(ctx.tool_registry, skill.meta.allowed_tools),
        tool_context=ToolContext(session_id=f"{ctx.session_id}:skill:{skill.meta.name}", ...),
        ...
    )
    result = await sub_pipeline.run(blocks, max_iterations=10)
    return result.final_text
```

### 5.4 Stage 4 (Guard) — skill 권한

`allowed_tools` 를 런타임 tool binding 으로 변환 → 해당 skill 실행 중에는 명시된 tool 만 사용 가능.

---

## 6. Geny 측 통합

### 6.1 `AgentSession` 에 skill registry 주입

```python
# service/executor/agent_session.py

class AgentSession:
    def __init__(self, ...):
        ...
        self._skill_registry = SkillRegistry()

    async def _build_pipeline(self):
        # 1. 번들 skill 은 이미 import 시 등록됨
        # 2. 사용자/프로젝트 skill 로드
        from geny_executor.skills.loader import load_skills_dir
        load_skills_dir(Path.home() / ".geny" / "skills", self._skill_registry)
        if self._working_dir:
            load_skills_dir(Path(self._working_dir) / ".geny" / "skills", self._skill_registry)

        # 3. MCP prompt → skill bridge
        if mcp_manager:
            mcp_skills = await mcp_prompts_to_skills(mcp_manager)
            for s in mcp_skills:
                self._skill_registry.register(s)

        # 4. attach
        attach_kwargs["skill_registry"] = self._skill_registry
        ...
```

### 6.2 Role 별 번들 skill

기존 `_DEFAULT_WORKER_PROMPT` 같은 role prompt 를 번들 skill 로 전환:
- `worker-default` skill — worker 역할의 기본 행동 지침
- `vtuber-cheerful` skill — VTuber cheerful 아키타입
- ...

이는 현재 `CharacterPersonaProvider` + 프롬프트 파일 조합을 skill 일원화로 대체하는 시나리오. 호환성 유지 위해 **병행 운용**: 기존 role prompt 는 legacy fallback 으로 두고, 새 skill 이 발견되면 우선 적용.

### 6.3 Slash command 파싱

`service/execution/agent_executor.py` 진입점에서 `try_parse_slash_command` 적용. 일반 텍스트로 LLM 에 보내기 전 skill 즉시 실행 경로 시도.

---

## 7. Skill authoring 가이드 (사용자 문서)

Skill 작성자가 보는 문서 (별도 파일로 발행 예정):

- `name` 은 `kebab-case`, 영문 + 숫자 + 하이픈
- `description` 은 1 문장
- `when_to_use` 는 LLM 이 읽고 trigger 결정 → **구체적 상황** 서술 (추상 금지)
- `allowed_tools` 는 whitelist — 없으면 전체 허용 (주의)
- 본문 템플릿은 `{{argument}}`, `{{session_id}}`, `{{files.filename}}` 치환
- `disable_model_invocation: true` 는 프롬프트 API 호출 없이 `direct_handler` 만 — 간단한 스크립트용
- `context: fork` 는 다른 tool 집합 / 다른 모델로 격리 실행할 때

예시 3 가지 (번들로 포함 권장):

1. **`search-web-and-summarize`** — 위 예시
2. **`draft-pr`** — 현재 git diff 읽고 PR 초안 작성
3. **`review-changes`** — uncommitted diff 를 self-review

---

## 8. 테스트 전략

| 테스트 | 목적 |
|---|---|
| 프론트매터 파싱 | 누락/오타 메타 graceful 에러 |
| `register_bundled_skill` | 이름 중복 시 동작 |
| `load_skills_dir` priority | 프로젝트 > 사용자 > 번들 |
| MCP bridge | MCP prompt → Skill 변환 메타 보존 |
| SkillTool 호출 → inline | new_messages 주입 정상 |
| SkillTool 호출 → fork | 서브 pipeline 격리 동작 |
| `disable_model_invocation` | direct_handler 경로 |
| `allowed_tools` 제한 | 다른 tool 호출 시 거부 |
| slash command 파싱 | `/name args` 매칭 |

---

## 9. 공개 API

```python
from geny_executor.skills import (
    Skill, SkillMetadata, SkillContext, SkillRegistry,
    register_bundled_skill, get_default_skill_registry,
    load_skills_dir, mcp_prompts_to_skills,
    SkillTool,
)
```

## 10. 다음 문서

- [`09_design_extension_interface.md`](09_design_extension_interface.md) — Skill 은 확장 메커니즘의 **상위 추상**. 하위 layer (config/strategy/slot/mutation/hook/event) 와의 관계
- [`10_design_stage_enhancements.md`](10_design_stage_enhancements.md) — Stage 3/10/11 의 skill 연동 세부
