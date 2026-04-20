# Geny 프롬프트 시스템

Geny Agent 세션을 위한 모듈형 시스템 프롬프트 아키텍처.

---

## 설계 원칙

### 원칙 1: MCP가 툴 정보를 제공한다 — 프롬프트에서는 제공하지 않는다

Claude CLI는 MCP 프로토콜을 통해 모든 툴의 이름, 설명, 파라미터 스키마를 자동으로 전달받습니다.
**시스템 프롬프트에 툴 이름을 나열하는 것은 중복이며 토큰을 낭비합니다.**

- 프롬프트에 툴 이름이나 설명을 추가하지 마세요
- MCP 서버 이름을 프롬프트에 나열하지 마세요
- **행동 지침**을 줄 때만 툴을 언급하세요 (예: "`geny_send_direct_message`로 위임하라")

### 원칙 2: 레이어별 단일 책임

각 프롬프트 레이어는 고유한 역할을 가집니다. 레이어 간 내용을 절대 중복하지 마세요.

```
Layer 1: identity()              ← 에이전트가 누구인지 (1줄, 역할별)
Layer 2: geny_platform()         ← 플랫폼 인지 (카테고리만, 툴 이름 없음)
Layer 3: prompts/{role}.md       ← 역할 행동 규칙 (무엇을 하고, 어떻게 행동하는지)
Layer 4: templates/{persona}.md  ← 페르소나/톤 (말투, 감정 기본값)
Layer 5: characters/{model}.md   ← Live2D 모델별 캐릭터 특성 (VTuber 전용)
```

각 레이어는 이전 레이어에 **추가**만 합니다 — 반복하지 않습니다.

### 원칙 3: 토큰 예산 인식

시스템 프롬프트 길이는 사용 가능한 대화 컨텍스트를 직접적으로 줄입니다.

| 역할 | 목표 | 근거 |
|------|------|------|
| VTuber | < 1,500 토큰 | 대화형 — 최대 대화 컨텍스트 필요 |
| 서브 워커 | < 800 토큰 | 작업 실행자 — 최소한의 프레이밍 |
| Developer | < 1,200 토큰 | bootstrap context 파일이 클 수 있음 |
| Researcher / Planner | < 1,200 토큰 | 동일 |

### 원칙 4: 인프라가 처리하는 것은 프롬프트에서 처리하지 않는다

| 관심사 | 처리 주체 | 프롬프트에서 처리하지 않음 |
|--------|-----------|--------------------------|
| 툴 스키마 및 설명 | MCP 프로토콜 | ~~capabilities 섹션~~ |
| 안전 가이드라인 | Claude CLI 내장 | ~~safety 섹션~~ |
| 툴 사용 패턴 | Claude CLI 내장 | ~~tool_style 섹션~~ |
| 실행 루프 및 재시도 | LangGraph | ~~execution_protocol~~ |
| 컨텍스트 윈도우 관리 | Claude CLI 내장 | ~~context_efficiency 섹션~~ |

---

## 아키텍처

### 프롬프트 조립 흐름

```
AgentSessionManager._build_system_prompt()
  └─ build_agent_prompt()
       └─ PromptBuilder (priority 정렬, mode 필터)
            ├── §1   identity()           [P10] 역할별 아이덴티티 한 줄
            ├── §1.5 user_context()       [P12] 사용자 정보 (UserConfig)
            ├── §1.7 geny_platform()      [P13] 플랫폼 인지 (툴 이름 없음)
            ├── §2   role_protocol()      [P15] 역할 행동 (prompts/{role}.md 로드)
            ├── §3   workspace()          [P40] 작업 디렉토리 경로
            ├── §4   datetime_info()      [P45] 현재 시각 (KST)
            └── §5   bootstrap_context()  [P90] AGENTS.md, CLAUDE.md, SOUL.md 등
       + extra_system_prompt (드롭다운으로 선택한 페르소나 템플릿)
       + shared_folder_path (활성화된 경우)
  + memory_context (SessionMemoryManager)
  + VTuber ↔ CLI 세션 링킹
  + 캐릭터 주입 (VTuber 전용, vtuber_characters/)
```

### 파일 구조

```
backend/prompts/
├── README.md               ← 영문 문서
├── README_KO.md            ← 한국어 문서 (이 파일)
├── worker.md               ← Worker 역할 행동
├── developer.md            ← Developer 역할 행동
├── researcher.md           ← Researcher 역할 행동
├── planner.md              ← Planner 역할 행동
├── vtuber.md               ← VTuber 역할 행동
├── templates/              ← 페르소나/전문화 템플릿
│   ├── geny-default.md         (범용)
│   ├── vtuber-default.md       (VTuber: 따뜻한/친근한 톤)
│   ├── vtuber-cheerful.md      (VTuber: 밝고 에너지 넘치는 톤)
│   ├── vtuber-professional.md  (VTuber: 차분한/전문적인 톤)
│   ├── sub-worker-default.md   (서브 워커: 기본 작업자)
│   ├── sub-worker-detailed.md  (서브 워커: 상세 보고)
│   ├── developer-*.md          (Developer 전문화)
│   └── researcher-*.md         (Researcher 전문화)
└── vtuber_characters/      ← Live2D 모델별 캐릭터 파일
    ├── README.md
    └── default.md
```

### 핵심 코드 파일

| 파일 | 역할 |
|------|------|
| `service/prompt/sections.py` | `SectionLibrary` (섹션 팩토리) + `build_agent_prompt()` |
| `service/prompt/builder.py` | `PromptBuilder` 엔진 + `PromptSection` / `PromptMode` |
| `service/prompt/template_loader.py` | `prompts/{role}.md` 파일 로딩 |
| `service/prompt/context_loader.py` | bootstrap 파일 로딩 (AGENTS.md, CLAUDE.md 등) |
| `service/langgraph/agent_session_manager.py` | 프롬프트 빌드 오케스트레이션 + 세션 링킹 |
| `controller/vtuber_controller.py` | Live2D 모델용 캐릭터 프롬프트 주입 |

---

## 역할 템플릿 (`prompts/{role}.md`)

각 역할은 **행동 규칙만** 정의하는 전용 마크다운 파일을 가집니다.

| 파일 | 역할 | 내용 |
|------|------|------|
| `worker.md` | worker | 최소한 — 범용 작업 실행 |
| `developer.md` | developer | 코드 품질, 컨벤션, 검증 |
| `researcher.md` | researcher | 연구 방법론, 소스 다양성, 아이디어 종합 |
| `planner.md` | planner | 비판적 평가, 상세 스펙, 구현 가이드 |
| `vtuber.md` | vtuber | 대화 행동, 감정 태그, 작업 위임, 트리거 |

**규칙:**
- **무엇을 하고** **어떻게 행동하는지**에 집중, 어떤 도구가 있는지는 적지 않음
- 특정 도구는 **행동 지침**을 줄 때만 언급 (예: `geny_send_direct_message`)
- 500단어 이내로 유지

---

## 페르소나 템플릿 (`prompts/templates/`)

UI의 "프롬프트 템플릿" 드롭다운으로 선택하는 선택적 전문화.
기본 프롬프트 뒤에 `---` 구분자와 함께 추가됩니다.

**VTuber 페르소나:**
- **톤** (말투, 격식)과 **감정 기본값**만 정의
- `vtuber.md`의 행동 규칙을 반복하지 마세요

**CLI 페르소나:**
- **보고 스타일**과 **작업 접근 방식**만 정의
- 일반적인 코딩 가이드라인을 반복하지 마세요

**기타 역할:**
- 도메인 전문화 (예: `developer-backend.md`로 백엔드 집중)

---

## VTuber 캐릭터 파일 (`prompts/vtuber_characters/`)

Live2D 모델별 캐릭터 특성. 모델이 할당될 때 런타임에 주입됩니다.

- 파일명은 `model_registry.json`의 모델명과 일치해야 합니다
- 모델 전용 파일이 없으면 `default.md`가 사용됩니다
- `## Character Personality` 마커로 중복 주입을 방지합니다
- **캐릭터 특화** 특성만 포함 (성격, 말버릇)
- 페르소나 또는 역할 행동 내용을 반복하지 마세요

---

## VTuber ↔ Sub-Worker 세션 링킹

VTuber 세션이 생성되면 서브 워커 세션이 자동 생성됩니다
(`dev_docs/20260420_3/plan/03_vtuber_worker_binding.md` 참고).

**VTuber가 받는 정보:**
```
## Sub-Worker Agent
You have a Worker agent bound to you: session_id=`{worker_session_id}`.
For complex tasks (coding, research, multi-step execution),
delegate to the Worker via the `geny_send_direct_message` tool
with target_session_id=`{worker_session_id}`. The Worker's reply
will arrive in your inbox; read it with `geny_read_inbox` and
summarize for the user.
```

**서브 워커가 받는 정보:**
```
## Paired VTuber Agent
Session ID: `{vtuber_session_id}`
You are the Worker bound to this VTuber persona.
Report results via `geny_send_direct_message` to this session when done.
```

---

## 미사용 섹션 (보관)

다음 `SectionLibrary` 메서드들은 존재하지만 `build_agent_prompt()`에서 **호출되지 않습니다**:

| 섹션 | 이유 |
|------|------|
| `tool_style()` | Claude CLI가 도구 사용을 기본 처리 |
| `safety()` | Claude CLI가 안전 가이드라인 내장 |
| `context_efficiency()` | 응답 스타일은 Claude CLI가 처리 |
| `status_reporting()` | 필요 시 .md 파일에서 역할별로 정의 가능 |

향후 사용을 위해 유지됩니다 (예: 프로젝트별 엄격한 정책).

---

## 새 역할 추가하기

1. `prompts/{role}.md` 에 행동 규칙 작성
2. `service/prompt/template_loader.py`의 `_ROLE_FILE_MAP`에 항목 추가
3. `service/prompt/sections.py`의 `SectionLibrary._ROLE_IDENTITY`에 아이덴티티 한 줄 추가
4. 선택적으로 `prompts/templates/{role}-*.md`에 페르소나 템플릿 생성

## 새 VTuber 캐릭터 추가하기

1. `prompts/vtuber_characters/{model_name}.md` 생성
2. `## Character Personality` 헤더로 시작
3. 모델 전용 특성만 정의 (성격, 말버릇)
4. 모델명은 `model_registry.json`의 `name` 필드와 일치해야 함
