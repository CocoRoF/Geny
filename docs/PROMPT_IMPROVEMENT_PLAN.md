# Geny 프롬프트 시스템 개선 계획

> 작성일: 2025-07-14
> 목표: VTuber / CLI / 일반 에이전트의 시스템 프롬프트를 깔끔하고 목적에 맞게 재설계

---

## 1. 현재 구조 분석

### 1.1 프롬프트 조립 흐름

```
AgentSessionManager._build_system_prompt()
  └─ build_agent_prompt()
       └─ PromptBuilder (priority 순 정렬, mode 필터)
            ├─ §1  identity()           [P10] "You are a Great Agent (role: X)."
            ├─ §1.5 user_context()      [P12] UserConfig 기반 사용자 정보
            ├─ §1.7 geny_platform()     [P13] ★ 11개 Geny 플랫폼 툴 목록
            ├─ §2  role_protocol()      [P15] 역할별 행동 지침 (prompts/{role}.md 로드)
            ├─ §3  capabilities()       [P20] ★ "Additional tools: ..." / "MCP servers: ..."
            ├─ §4  workspace()          [P40] 작업 디렉토리 경로
            ├─ §5  datetime_info()      [P45] 현재 시각 (KST)
            ├─ §6  bootstrap_context()  [P90] AGENTS.md, CLAUDE.md, SOUL.md 등
            └─ §12 runtime_line()       [P99] 메타데이터 한 줄
       └─ + extra_system_prompt (persona template)
       └─ + shared_folder_path
  └─ + memory_context
  └─ + VTuber linked CLI 정보 (vtuber only)
  └─ VTuber character injection (_inject_character_prompt)
```

### 1.2 현재 문제점

| # | 문제 | 영향 |
|---|------|------|
| **P1** | `geny_platform()` 이 11개 플랫폼 툴 이름을 전부 나열 | Claude CLI는 MCP를 통해 이미 툴 스키마를 알고 있음 → 중복, 토큰 낭비 |
| **P2** | `capabilities()` 가 "Additional tools: tool1, tool2, ..." 식으로 나열 | 마찬가지로 MCP가 제공하므로 중복 |
| **P3** | VTuber 프롬프트에 `vtuber.md` + `vtuber-default.md` + `vtuber_characters/default.md` 3중 중복 | 성격/말투/위임 규칙이 3곳에 분산, 일관성 문제 |
| **P4** | `identity()` 가 "You are a Great Agent" 로 하드코딩 | VTuber에게 어울리지 않음 |
| **P5** | `tool_style`, `safety`, `context_efficiency`, `status_reporting` 등 미사용 섹션 존재 | 코드에 남아 있지만 `build_agent_prompt()`에서 호출하지 않음 → 데드코드 |
| **P6** | VTuber의 "Thinking Behavior" / "Memory" 섹션이 `vtuber.md`에만 있음 | persona template이 override 못함 |
| **P7** | CLI worker의 프롬프트가 VTuber와 별도로 동작하지만, VTuber 연동 컨텍스트가 부족 | CLI가 "누구에게 보고해야 하는지" 정도만 알고, VTuber의 사용자가 어떤 맥락을 가졌는지 모름 |
| **P8** | `role_protocol()` fallback과 `prompts/{role}.md` 이 겹침 | md 파일이 있으면 override 하지만, fallback 문자열도 유지되어 혼란 |

---

## 2. 핵심 설계 원칙

### 원칙 1: MCP가 제공하는 것은 프롬프트에서 제거

Claude CLI는 `--mcp-config` 를 통해 모든 툴의 이름, 설명, 파라미터 스키마를 자동으로 인지합니다. 따라서:

- ~~프롬프트에 툴 이름 나열~~ → **삭제**
- ~~"Additional tools: ..."~~ → **삭제**
- ~~"MCP servers: ..."~~ → **삭제**

대신 **행동 지침**만 남김:
- "Geny 플랫폼 툴을 통해 다른 세션과 소통할 수 있다" (이름 나열 없이)
- "복잡한 작업은 CLI에게 위임하라" (VTuber에서)

### 원칙 2: 역할(Role)별 프롬프트는 단일 소스

현재 3곳에 VTuber 프롬프트가 분산:
1. `role_protocol()` fallback → 1줄 하드코딩
2. `prompts/vtuber.md` → 상세 역할 지침
3. `prompts/templates/vtuber-default.md` → 페르소나 (extra_system_prompt)
4. `prompts/vtuber_characters/default.md` → 캐릭터 성격 (character injection)

**개선**: 계층 명확화
```
Layer 1: identity()          ← "너는 누구다" 한 줄
Layer 2: prompts/vtuber.md   ← 역할 행동 규칙 (위임 기준, 감정 표현, 사고 트리거)
Layer 3: persona template    ← 말투/분위기 (cheerful, professional 등)
Layer 4: character file      ← Live2D 모델별 캐릭터 특성
```

각 레이어는 하위 레이어를 덮어쓰지 않고 **추가**만 한다.

### 원칙 3: 토큰 예산 의식

시스템 프롬프트가 길수록 실제 대화 컨텍스트가 줄어듭니다.
- VTuber: 대화형이므로 시스템 프롬프트를 **짧게** (< 1,500 토큰 목표)
- CLI Worker: 작업자이므로 상세 가능하지만 **불필요한 반복 제거**
- Developer/Planner: bootstrap context가 크므로 본문은 간결하게

---

## 3. 구체적 변경 계획

### Phase 1: 중복 툴 정보 정리 (sections.py)

#### 3.1.1 `geny_platform()` 리팩토링

**Before:**
```python
"- **Session management**: `geny_session_list`, `geny_session_info`, `geny_session_create` — ..."
"- **Room management**: `geny_room_list`, `geny_room_create`, ..."
"- **Messaging**: `geny_send_room_message`, `geny_send_direct_message` — ..."
"- **Reading**: `geny_read_room_messages`, `geny_read_inbox` — ..."
```

**After:**
```python
"## Geny Platform",
"",
"You are running inside the Geny multi-agent platform.",
"You have built-in tools (provided via MCP) for:",
"- Managing sessions (list, create, inspect agent sessions)",
"- Messaging (send/read messages to rooms or directly to other agents)",
"- Room collaboration (create rooms, add members)",
"",
f"Your session ID: `{session_id}`",
```

변경: 개별 함수 이름 나열 삭제, 카테고리만 설명, session_id는 유지

#### 3.1.2 `capabilities()` 단순화

**Before:**
```python
"Additional tools: web_search, news_search, web_fetch, ..."
"MCP servers: filesystem, geny-proxy, ..."
```

**After:**
```python
# capabilities() 함수 자체를 제거하거나, MCP 서버 이름만 간략 참조
# 또는 tools/mcp_servers 인자를 build_agent_prompt에서 삭제
```

**결정 필요**: capabilities() 를 완전 삭제할지, "외부 MCP 서버 N개 연결됨" 정도만 남길지?

→ **제안**: 완전 삭제. MCP가 모든 스키마를 Claude에게 직접 전달하므로 프롬프트에서 다시 알려줄 필요 없음.

#### 3.1.3 `identity()` 역할별 차별화

**Before**: 모든 역할에 "You are a Great Agent (role: worker)."

**After**:
```python
ROLE_IDENTITY = {
    "worker":     "You are a Geny CLI agent.",
    "developer":  "You are a Geny Developer agent.",
    "researcher": "You are a Geny Researcher agent.",
    "planner":    "You are a Geny Plan Architect agent.",
    "vtuber":     "You are a Geny VTuber agent — a conversational persona that interacts with users.",
}
```

---

### Phase 2: VTuber 프롬프트 재설계

#### 3.2.1 `prompts/vtuber.md` 개선

현재 `vtuber.md` 문제:
- "Direct Response" / "Delegate to CLI Agent" 구분이 너무 상세하고 rigid
- Memory 사용법까지 지시 → Claude CLI가 이미 tool schema로 알고 있음
- Thinking Behavior 설명이 구현과 불일치할 수 있음

**개선된 vtuber.md:**
```markdown
You are the conversational face of the Geny system.

## Behavior
- Respond naturally and expressively in Korean (unless the user speaks another language)
- Express emotions using tags: [joy], [sadness], [anger], [fear], [surprise], [disgust], [smirk], [neutral]
- Keep responses concise for casual exchanges; elaborate when the topic warrants it
- Remember important details and reference past conversations naturally

## Task Delegation
- Handle casual conversation, simple questions, emotional support, and memory recall yourself
- Delegate coding, file operations, complex research, and multi-step technical tasks
  to your paired CLI agent via `geny_send_direct_message`
- When delegating: acknowledge naturally → send task → inform user → summarize result when received

## Triggers
- [THINKING_TRIGGER]: Reflect on recent events, check pending tasks, optionally initiate conversation
- [CLI_RESULT]: Summarize the CLI agent's work result conversationally with appropriate emotion
```

핵심 변경:
- ~~툴 이름 나열~~ 삭제 (memory_write 등)
- ~~"Simple factual questions", "Quick calculations"~~ 상세 예시 간소화
- `geny_send_direct_message` 만 명시 (이것은 행동 지침이지 툴 설명이 아님)
- 전체 분량 대폭 축소

#### 3.2.2 Persona Templates 정비 (`prompts/templates/vtuber-*.md`)

현재 문제: `vtuber-default.md` 가 `vtuber.md` 와 80% 중복.

**개선**: persona template은 **말투와 분위기만** 담당

```markdown
# vtuber-default.md
- 친근하고 따뜻한 톤
- 존댓말/반말은 사용자 선호에 맞춤
- 적절한 리액션과 이모티콘 사용
```

```markdown
# vtuber-cheerful.md
- 밝고 에너지 넘치는 톤
- 반말 위주, 감탄사 적극 활용 ("와!", "대박!")
- [joy] 기본 상태, 위임 시 "잠깐만! 내가 해볼게~"
```

```markdown
# vtuber-professional.md
- 차분하고 전문적인 톤
- 존댓말 기반, 결론부터 말하기
- [neutral] 기본 상태, 기술 용어 자연스럽게 사용
```

→ `vtuber.md` 의 행동 규칙과 겹치는 내용 제거, 순수 페르소나만 유지

#### 3.2.3 Character Files 정비 (`prompts/vtuber_characters/`)

현재 `default.md` 도 persona와 비슷.

**개선**: character file은 **Live2D 모델 특화** 정보만
```markdown
## Character: Default
- 기본 아바타
- 특별한 캐릭터 설정 없음 — persona template의 설정을 따름
```

모델별 character file (향후):
```markdown
## Character: Hiyori
- 하이요리(ひより): 밝은 성격의 고등학생 캐릭터
- 1인칭: 나/저
- 학교생활 관련 비유를 자연스럽게 사용
```

---

### Phase 3: CLI Worker 프롬프트 개선

#### 3.3.1 `prompts/templates/cli-default.md` 개선

현재: 일반적인 코딩 지침 + 보고 형식

**개선:**
```markdown
# CLI Worker

You are the internal task executor paired with a VTuber persona.

## Core
- Execute delegated tasks thoroughly and autonomously
- Report results back via `geny_send_direct_message` to the VTuber session
- Include: what was done, key outcomes, files changed, any issues

## Execution
- Read existing code before modifying
- Make incremental, focused changes
- Verify your work when possible
```

변경:
- ~~style/convention 등 일반론~~ 삭제 (Claude CLI 기본 행동)
- VTuber와의 연동에 집중
- 보고 형식 간소화

#### 3.3.2 Linked Session Context 개선

현재 `_build_system_prompt()` 에서:
```python
"Your paired CLI worker session ID: `{linked_session_id}`"
```

**개선**: CLI 쪽에도 VTuber session ID와 사용자 맥락 전달
```python
# VTuber → CLI 방향
f"## Paired CLI Agent\n"
f"Session ID: `{linked_session_id}`\n"
f"Send tasks via `geny_send_direct_message`. Results will come back to your inbox."

# CLI → VTuber 방향 (현재는 없음 - 추가 필요)
f"## Paired VTuber Agent\n"
f"Session ID: `{vtuber_session_id}`\n"
f"Report results via `geny_send_direct_message` to this session."
```

---

### Phase 4: 일반 에이전트 프롬프트 정리

#### 3.4.1 데드 코드 제거

`sections.py` 에서 `build_agent_prompt()` 이 호출하지 않는 섹션들:
- `tool_style()` — Claude CLI가 처리
- `safety()` — Claude CLI가 처리
- `context_efficiency()` — Claude CLI가 처리
- `status_reporting()` — 사용처 없음

**결정 필요**:
- 삭제? → 깔끔하지만 향후 쓸 수 있음
- `# DEPRECATED` 주석? → 안전하지만 코드 잡음
- 별도 파일로 이동? → 과도한 엔지니어링

→ **제안**: `# NOT IN USE` 주석 추가 + 당장 삭제하지 않음. 저비용 결정.

#### 3.4.2 `role_protocol()` fallback 정리

현재: `protocols = {"worker": "", "developer": "...", ...}` 하드코딩 + `prompts/{role}.md` 로 override.

**개선**: 하드코딩 fallback을 최소화
```python
protocols = {
    "worker": "",
    "developer": "",  # prompts/developer.md 사용
    "researcher": "",  # prompts/researcher.md 사용
    "planner": "",     # prompts/planner.md 사용
    "vtuber": "",      # prompts/vtuber.md 사용
}
```
md 파일이 없을 때의 fallback은 사실상 사용되지 않으므로 빈 문자열로 통일.

---

### Phase 5: `prompts/geny-default.md` 및 Worker 처리

#### 3.5.1 Worker 프롬프트

현재: `worker.md` 는 7줄짜리 간단 지침. Worker는 가장 범용적인 역할.

**개선**: 유지. Worker는 최소한의 지침만 가지는 것이 설계 의도.

#### 3.5.2 Developer / Researcher / Planner

현재 `prompts/{role}.md` 파일들은 잘 작성되어 있음.

**개선**: 각 파일에서 툴 관련 언급만 정리
- developer.md: "Use the shared folder to access plans..." → 유지 (행동 지침이므로)
- researcher.md: 유지
- planner.md: 유지

---

## 4. 변경 우선순위 및 난이도

| 순서 | 작업 | 난이도 | 영향 |
|------|------|--------|------|
| 1 | `geny_platform()` 에서 툴 이름 나열 제거 | ⭐ | 높음 — 모든 세션에 적용 |
| 2 | `capabilities()` 호출 제거 또는 단순화 | ⭐ | 높음 — 토큰 절약 |
| 3 | `identity()` 역할별 차별화 | ⭐ | 중간 |
| 4 | `prompts/vtuber.md` 재작성 | ⭐⭐ | 높음 — VTuber 핵심 |
| 5 | VTuber persona templates 정비 | ⭐⭐ | 중간 — 중복 제거 |
| 6 | CLI worker 프롬프트 개선 | ⭐ | 중간 |
| 7 | CLI ↔ VTuber 양방향 세션 연동 | ⭐⭐ | 중간 |
| 8 | 데드코드 정리 (`tool_style` 등) | ⭐ | 낮음 |
| 9 | `role_protocol()` fallback 정리 | ⭐ | 낮음 |

---

## 5. 예상 결과 (Before/After)

### VTuber 시스템 프롬프트 (Before ≈ 2,800 토큰)

```
You are a Great Agent (role: vtuber). Your name is "Geny".

## Geny Platform Tools
You have built-in tools to interact with the Geny platform:
- **Session management**: `geny_session_list`, `geny_session_info`, `geny_session_create` — ...
- **Room management**: `geny_room_list`, `geny_room_create`, `geny_room_info`, `geny_room_add_members` — ...
- **Messaging**: `geny_send_room_message`, `geny_send_direct_message` — ...
- **Reading**: `geny_read_room_messages`, `geny_read_inbox` — ...
Your session ID: `abc123`

You are a conversational VTuber persona. Respond naturally...

Additional tools: web_search, news_search, web_fetch, memory_read, memory_write, ...

Working directory: /app/workspace
Current time: 2025-07-14 15:30:00 KST

---
(vtuber-default.md — 20줄)

---
Shared Folder: ./_shared/
...

(memory context)

## Linked CLI Agent
Your paired CLI worker session ID: `def456`
...

(character injection — default.md)
```

### VTuber 시스템 프롬프트 (After ≈ 1,200 토큰)

```
You are a Geny VTuber agent — a conversational persona that interacts with users.
Your name is "Geny". Session ID: `abc123`

## Geny Platform
You are running inside the Geny multi-agent platform.
You have tools (provided via MCP) for managing sessions, messaging, and room collaboration.

You are the conversational face of the Geny system.

## Behavior
- Respond naturally and expressively in Korean
- Express emotions: [joy], [sadness], [anger], [fear], [surprise], [disgust], [smirk], [neutral]
- Keep responses concise; elaborate when warranted
- Remember important details naturally

## Task Delegation
- Handle casual conversation, simple questions, emotional support yourself
- Delegate coding, file ops, complex research to CLI via `geny_send_direct_message`
- Acknowledge → send → inform user → summarize result

## Triggers
- [THINKING_TRIGGER]: Reflect, check tasks, optionally initiate
- [CLI_RESULT]: Summarize work result with appropriate emotion

Working directory: /app/workspace
Current time: 2025-07-14 15:30:00 KST

---
(persona — 5줄)

---
Shared Folder: ./_shared/

(memory context)

## Paired CLI Agent
Session ID: `def456` — delegate via `geny_send_direct_message`

(character — 5줄)
```

**토큰 절약**: 약 57% 감소 (2,800 → 1,200)

---

## 6. 논의 사항

### Q1: `geny_platform()` 을 완전히 삭제할까, 간략 버전으로 유지할까?

- **옵션 A**: 완전 삭제, session_id만 identity에 통합
- **옵션 B**: 간략 버전 유지 (카테고리만 언급, 함수 이름 제거)  ← 제안
- **근거**: "플랫폼 툴이 있다" 는 행동 결정에 영향을 주므로 존재 자체는 알려야 함

### Q2: `capabilities()` 를 완전히 제거할까?

- **옵션 A**: 완전 제거 (MCP가 전부 처리) ← 제안
- **옵션 B**: "N개 외부 도구 사용 가능" 한 줄만 유지
- **근거**: Claude는 MCP를 통해 이미 모든 tool schema를 받으므로 프롬프트에서 반복할 필요 없음

### Q3: VTuber character 시스템을 persona template에 통합할까?

- **옵션 A**: 별도 유지 (character = Live2D 모델별, persona = 말투/분위기)
- **옵션 B**: persona template에 통합
- **현재 제안**: 옵션 A 유지 — 모델 변경 시 character만 교체하는 런타임 활용

### Q4: 미사용 섹션 (`tool_style`, `safety` 등) 처리

- **옵션 A**: 삭제
- **옵션 B**: `# NOT IN USE` 주석 ← 제안
- **옵션 C**: 별도 `_archive.py` 로 이동

### Q5: CLI Worker 에게 VTuber session_id를 전달할까?

- 현재 CLI는 VTuber를 모름 (DM을 받아서 수행하지만, 보고 대상을 프롬프트로는 모름)
- **제안**: 전달 추가 — CLI가 자율적으로 VTuber에게 보고할 수 있게

---

## 7. 구현 순서

```
Phase 1: sections.py 정리
  ├─ geny_platform() 간소화
  ├─ capabilities() 제거 또는 단순화
  ├─ identity() 역할별 차별화
  └─ 데드코드 주석 처리

Phase 2: VTuber 프롬프트 재설계
  ├─ prompts/vtuber.md 재작성
  ├─ prompts/templates/vtuber-*.md 간소화
  └─ prompts/vtuber_characters/default.md 정비

Phase 3: CLI 프롬프트 개선
  ├─ prompts/templates/cli-*.md 업데이트
  └─ _build_system_prompt()에 CLI→VTuber 세션 연동 추가

Phase 4: 일반 정리
  ├─ role_protocol() fallback 정리
  └─ build_agent_prompt() 주석 업데이트
```

---

## 부록: 파일별 변경 대상

| 파일 | 변경 내용 |
|------|-----------|
| `backend/service/prompt/sections.py` | `geny_platform()`, `capabilities()`, `identity()` 수정, 미사용 섹션 주석 |
| `backend/service/prompt/sections.py` (build_agent_prompt) | capabilities 호출 제거/수정, 주석 업데이트 |
| `backend/service/langgraph/agent_session_manager.py` | CLI→VTuber 세션 연동 추가 |
| `backend/prompts/vtuber.md` | 전면 재작성 |
| `backend/prompts/templates/vtuber-default.md` | 중복 제거, 페르소나만 유지 |
| `backend/prompts/templates/vtuber-cheerful.md` | 중복 제거, 페르소나만 유지 |
| `backend/prompts/templates/vtuber-professional.md` | 중복 제거, 페르소나만 유지 |
| `backend/prompts/templates/cli-default.md` | VTuber 연동 중심으로 개선 |
| `backend/prompts/templates/cli-detailed.md` | VTuber 연동 중심으로 개선 |
| `backend/prompts/vtuber_characters/default.md` | 최소화 (모델 특화 정보만) |
