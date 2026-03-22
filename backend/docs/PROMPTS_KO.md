# Prompt System

> 역할 기반 시스템 프롬프트를 섹션 단위로 조합하는 모듈형 프롬프트 엔진

## 아키텍처 개요

```
AgentSessionManager._build_prompt_for_session()
        │
        ├── ContextLoader         ── 프로젝트 파일 자동 탐색 (AGENTS.md, CLAUDE.md, …)
        ├── PromptTemplateLoader  ── 역할별 .md 파일 로드 (prompts/*.md)
        ├── SectionLibrary        ── 섹션 팩토리 (identity, capabilities, workspace, …)
        ├── PromptBuilder         ── 빌더 패턴으로 최종 프롬프트 조립
        └── AutonomousPrompts     ── 워크플로우 노드용 포맷 스트링 템플릿
```

---

## PromptBuilder — 빌더 패턴

### PromptMode

| 모드 | 설명 |
|------|------|
| `FULL` | 전체 섹션 포함 (기본값) |
| `MINIMAL` | 핵심 섹션만 (경량 서브 에이전트용) |
| `NONE` | 시스템 프롬프트 없음 (extra context만 사용) |

### PromptSection

```python
@dataclass
class PromptSection:
    name: str                                    # 섹션 식별자
    content: str                                 # 본문 텍스트
    priority: int = 50                           # 정렬 우선순위 (낮을수록 앞)
    condition: Optional[Callable[[], bool]]       # 조건 함수
    modes: Set[PromptMode] = {PromptMode.FULL}   # 포함 모드
    tag: Optional[str] = None                    # XML 래핑 태그
```

- `should_include(mode)` — 모드 + 조건 확인
- `render()` — `tag`이 있으면 `<tag>...</tag>`으로 래핑

### Builder 메서드

모든 메서드가 `self`를 반환하여 **체이닝** 가능:

```python
prompt = (
    PromptBuilder(mode=PromptMode.FULL)
    .add_section(SectionLibrary.identity(...))
    .add_section(SectionLibrary.capabilities(...))
    .override_section("role_protocol", custom_content)
    .add_extra_context("추가 정보...")
    .build()
)
```

| 메서드 | 설명 |
|--------|------|
| `add_section(section)` | 섹션 추가/교체 |
| `remove_section(name)` | 섹션 제거 |
| `override_section(name, content)` | 내용만 교체 (태그·우선순위 유지) |
| `add_extra_context(context)` | 끝에 추가 컨텍스트 삽입 |
| `build()` | 최종 프롬프트 조립 |
| `build_with_safety_wrap()` | `build()` + 안티 오버라이드 지시 추가 |

### build() 알고리즘

1. `NONE` 모드면 → `extra_context`만 반환
2. `should_include(mode)` 필터링
3. `priority` 오름차순 정렬
4. `_overrides` 적용 (내용 교체)
5. 각 섹션 `render()`
6. `_extra_context` 추가
7. `"\n\n"` 구분자로 합치기

---

## SectionLibrary — 섹션 팩토리

모든 메서드는 `@staticmethod`이며 `PromptSection`을 반환.

| 우선순위 | 섹션 이름 | 메서드 | 모드 | 설명 |
|----------|-----------|--------|------|------|
| 10 | `identity` | `identity(agent_name, role, agent_id, session_name)` | FULL, MINIMAL | 에이전트 정체성 한줄 |
| 12 | `user_context` | `user_context()` | FULL, MINIMAL | 사용자 페르소나 (UserConfig) |
| 13 | `geny_platform` | `geny_platform(session_id)` | FULL, MINIMAL | Geny 플랫폼 내장 도구 목록 |
| 15 | `role_protocol` | `role_protocol(role)` | FULL | 역할별 행동 지침 (하드코딩 폴백) |
| 20 | `capabilities` | `capabilities(tools, mcp_servers)` | FULL, MINIMAL | MCP 서버 + 추가 도구 목록 |
| 25 | `tool_style` | `tool_style()` | FULL | 도구 사용 가이드라인 |
| 30 | `safety` | `safety()` | FULL, MINIMAL | 안전 수칙 |
| 40 | `workspace` | `workspace(working_dir, project_name, file_tree)` | FULL, MINIMAL | 작업 디렉토리 정보 |
| 45 | `datetime` | `datetime_info()` | FULL | 현재 KST 시간 |
| 50 | `context_efficiency` | `context_efficiency()` | FULL | 토큰 효율 가이드 |
| 60 | `status_reporting` | `status_reporting()` | FULL | 워커 진행 보고 양식 |
| 90 | `bootstrap_{file}` | `bootstrap_context(file, content, tag)` | FULL, MINIMAL | 프로젝트 컨텍스트 파일 (XML 래핑) |
| 99 | `runtime_line` | `runtime_line(model, session_id, role, version)` | FULL, MINIMAL | 런타임 메타 한줄 |

### 역할별 하드코딩 폴백 (role_protocol)

| 역할 | 내용 |
|------|------|
| `worker` | 빈 문자열 (범용) |
| `developer` | 이해 → 구현 → 검증 3단계 |
| `researcher` | 정보 수집 → 탐구 → 아이디어 생성 |
| `planner` | 아이디어 평가 → 아키텍처 → 문서화 |

---

## PromptTemplateLoader — 역할 템플릿 파일

`prompts/` 디렉토리에서 역할별 Markdown 파일을 로드.

### 역할 → 파일 매핑

```python
_ROLE_FILE_MAP = {
    "worker":     "worker.md",
    "developer":  "developer.md",
    "researcher": "researcher.md",
    "planner":    "planner.md",
}
```

파일이 존재하면 `SectionLibrary.role_protocol()` 하드코딩 폴백을 **오버라이드**.

### 메서드

| 메서드 | 설명 |
|--------|------|
| `load_role_template(role)` | .md 파일 로드 (캐시됨) |
| `list_available_roles()` | 파일이 존재하는 역할 목록 |
| `load_all()` | 모든 역할 → 내용 딕셔너리 |
| `clear_cache()` | 캐시 초기화 |

### 역할 템플릿 (prompts/*.md)

| 파일 | 역할 | 내용 |
|------|------|------|
| `worker.md` | worker | 코드 읽기, 규칙 준수, 에러 핸들링, 테스트 |
| `developer.md` | developer | 이해→구현→검증 3가지 책임, 코드 품질 가이드라인 |
| `researcher.md` | researcher | 정보 수집→실험→아이디어 3가지 책임, 출력 포맷 |
| `planner.md` | planner | 평가→아키텍처→문서화, 산출물 표준 (마스터 플랜 등) |

### 특화 템플릿 (prompts/templates/*.md)

`PromptTemplateLoader`가 자동 로드하지 않으며, UI의 "Prompt Template" 드롭다운으로 선택 시 `extra_system_prompt`로 전달됨.

| 파일 | 제목 | 전문 분야 |
|------|------|-----------|
| `developer-ai-engineer.md` | AI/ML 엔지니어 | PyTorch, TF, HuggingFace, LangChain, MLOps |
| `developer-backend.md` | 백엔드 전문가 | FastAPI, Django, PostgreSQL, Docker |
| `developer-frontend.md` | 프론트엔드 전문가 | React, Next.js, Tailwind, 접근성 |
| `developer-fullstack.md` | 풀스택 전문가 | E2E 타입 안전, API-first |
| `researcher-market-analysis.md` | 시장·비즈니스 분석 | TAM/SAM/SOM, 경쟁 분석 |
| `researcher-tech-trends.md` | 기술 트렌드 | arXiv, GitHub 트렌딩, 기술 성숙도 |

---

## ContextLoader — 프로젝트 컨텍스트 파일 탐색

`working_dir`에서 프로젝트 맥락 파일을 자동 탐색하여 Bootstrap 섹션으로 주입.

### 탐색 파일

**기본 파일 (항상 탐색):**

| 파일명 | XML 태그 | 최대 크기 |
|--------|---------|-----------|
| `AGENTS.md` | `project-context` | 50,000 B |
| `CLAUDE.md` | `ai-instructions` | 50,000 B |
| `.claude` | `ai-instructions` | 50,000 B |
| `.cursorrules` | `ai-instructions` | 30,000 B |
| `.windsurfrules` | `ai-instructions` | 30,000 B |
| `SOUL.md` | `persona` | 20,000 B |

**선택 파일 (`include_readme=True`일 때):**

| 파일명 | XML 태그 | 최대 크기 |
|--------|---------|-----------|
| `README.md` | `project-readme` | 30,000 B |
| `CONTRIBUTING.md` | `project-contributing` | 20,000 B |

### 탐색 동작

1. `working_dir`에서 먼저 탐색
2. 없으면 `working_dir.parent`에서 탐색 (모노레포 대응)
3. 빈 파일, 크기 초과 파일 건너뜀
4. 전체 예산: `max_total_size` (기본 100,000 B)

### 생성자

```python
ContextLoader(
    working_dir: str,
    max_total_size: int = 100_000,
    include_readme: bool = False,
    custom_files: Optional[List[str]] = None,  # 추가 커스텀 파일
)
```

---

## AutonomousPrompts — 워크플로우 노드용 템플릿

워크플로우 그래프의 각 노드에서 사용하는 포맷 스트링 템플릿.

| 메서드 | 플레이스홀더 | 사용 노드 | 설명 |
|--------|-------------|-----------|------|
| `classify_difficulty()` | `{memory_context}`, `{input}` | classify_node | easy/medium/hard 분류 |
| `review()` | `{question}`, `{answer}` | review_node | 품질 검토, VERDICT: approved/rejected |
| `create_todos()` | `{memory_context}`, `{input}` | create_todos_node | 하드 태스크 TODO 분해 |
| `execute_todo()` | `{goal}`, `{title}`, `{description}`, `{previous_results}` | execute_todo_node | 개별 TODO 실행 |
| `final_review()` | `{input}`, `{todo_results}` | final_review_node | 전체 TODO 완료 검토 |
| `final_answer()` | `{input}`, `{todo_results}`, `{review_feedback}` | final_answer_node | 최종 종합 답변 |
| `retry_with_feedback()` | `{previous_feedback}`, `{input_text}` | answer_node | 리뷰 거절 후 재시도 |
| `check_relevance()` | `{agent_name}`, `{role}`, `{message}` | relevance_gate_node | 브로드캐스트 관련성 판단 |

노드별 커스텀 프롬프트: `config.get("prompt_template", AutonomousPrompts.xxx())` 패턴으로 워크플로우 설정에서 오버라이드 가능.

---

## Protocols — 확장 프로토콜 섹션

`build_agent_prompt()`에는 기본 포함되지 않으며, 수동 삽입용.

### ExecutionProtocol

| 메서드 | 우선순위 | 모드 | 내용 |
|--------|---------|------|------|
| `autonomous_execution()` | 35 | FULL | CPEV 사이클: Check→Plan→Execute→Verify |
| `multi_turn_execution()` | 36 | FULL | 턴 예산, 상태 연속성, 진행 추적 |

### CompletionProtocol

| 신호 | 의미 |
|------|------|
| `[CONTINUE: {action}]` | 추가 작업 필요 |
| `[TASK_COMPLETE]` | 모든 작업 완료 |
| `[BLOCKED: {reason}]` | 외부 의존성으로 차단 |
| `[ERROR: {description}]` | 복구 불가 에러 |

### ErrorRecoveryProtocol

4단계 에스컬레이션: 즉시 재시도 → 진단 분석 → 전략 전환 → 우아한 퇴보

---

## 전체 조립 흐름

```
사용자 세션 생성 (role, model, working_dir, system_prompt, ...)
    │
    └── AgentSessionManager._build_prompt_for_session()
          │
          ├── ContextLoader.load_context_files()
          │     └── AGENTS.md, CLAUDE.md 등 자동 탐색
          │
          └── build_agent_prompt(
                agent_name, role, working_dir, model,
                session_id, session_name, tools, mcp_servers,
                mode=FULL, context_files, extra_system_prompt,
                shared_folder_path
              )
                │
                ├── PromptBuilder(FULL) 생성
                ├── §1  identity       (p=10)  — 항상
                ├── §1.5 user_context  (p=12)  — UserConfig 있으면
                ├── §1.7 geny_platform (p=13)  — 항상
                ├── §2  role_protocol  (p=15)  — role ≠ "worker"이면
                │     └── PromptTemplateLoader → prompts/{role}.md 존재 시 오버라이드
                ├── §3  capabilities   (p=20)  — tools/mcp_servers 있으면
                ├── §6  workspace      (p=40)  — working_dir 있으면
                ├── §7  datetime       (p=45)  — FULL 모드이면
                ├── §11 bootstrap_*    (p=90)  — context_files 각각
                │
                ├── builder.build() → 우선순위 정렬, 필터, 렌더
                │
                ├── + "---" + extra_system_prompt (특화 템플릿)
                └── + "---" + shared_folder_info (공유 폴더 활성 시)
```

### 최종 프롬프트 레이아웃

```
You are a Great Agent (role: developer). Your name is "MySession".

[사용자 페르소나] (설정시)

## Geny Platform Tools
- 세션/룸/메시징/읽기 도구 목록...

[역할 프로토콜] (prompts/developer.md 내용)

[MCP 서버 + 추가 도구 목록]

Working directory: /path/to/project

Current time: 2026-03-21 15:30:00 KST

<project-context file="AGENTS.md">
  프로젝트 컨텍스트...
</project-context>

---

(extra_system_prompt: 특화 템플릿 내용)

---

Shared Folder: ./_shared/
A shared directory accessible by ALL sessions...
```

---

## 관련 파일

```
service/prompt/
├── __init__.py              # 공개 API 내보내기
├── builder.py               # PromptBuilder, PromptMode, PromptSection
├── sections.py              # SectionLibrary, AutonomousPrompts, build_agent_prompt()
├── protocols.py             # ExecutionProtocol, CompletionProtocol, ErrorRecoveryProtocol
├── context_loader.py        # ContextLoader (프로젝트 파일 탐색)
└── template_loader.py       # PromptTemplateLoader (역할 .md 로더)

prompts/
├── worker.md                # worker 역할 템플릿
├── developer.md             # developer 역할 템플릿
├── researcher.md            # researcher 역할 템플릿
├── planner.md               # planner 역할 템플릿
└── templates/
    ├── developer-ai-engineer.md
    ├── developer-backend.md
    ├── developer-frontend.md
    ├── developer-fullstack.md
    ├── researcher-market-analysis.md
    └── researcher-tech-trends.md
```
