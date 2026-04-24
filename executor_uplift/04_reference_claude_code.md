# 04. Reference — claude-code-main Patterns

**Status:** Draft
**Date:** 2026-04-24
**Source:** `/home/geny-workspace/claude-code-main/src/`

이 문서는 우리 execution engine 고도화에 **참조할 가치가 있는** claude-code 의 아키텍처 패턴을 카탈로그화한 것이다. 전체를 문서화하는 게 아니라 "우리가 훔칠 만한 것" 을 뽑아냄.

인용된 파일 경로는 모두 `claude-code-main/src/` 기준 상대 경로.

---

## 1. 레포 레이아웃 개관

| 디렉토리 | 역할 | 우리에게 의미 |
|---|---|---|
| `tools/` | 45+ built-in tool 구현체 (Bash, Read, Edit, Write, Agent, Skill, MCP, …) | 🔥 **Tool 계약의 금본위** |
| `services/mcp/` | MCP client · transport · OAuth · config · resource | 🔥 **MCP 통합의 금본위** |
| `skills/` | Bundled skill 레지스트리 + 디스크 skill 로더 + MCP skill bridge | 🔥 **Skill 시스템의 금본위** |
| `commands/` | 50+ slash command | 사용자 affordance 참조 |
| `commands.ts` | slash 커맨드 레지스트리 + union 타입 | 참조 |
| `hooks/` | React hooks (UI state) | 관심사 외 (lifecycle hook 은 `utils/hooks/`) |
| `utils/hooks/` | hooks 설정 매니저 + frontmatter 훅 등록 | 🔥 **Hook 프로토콜의 금본위** |
| `coordinator/` | 멀티 에이전트 coordinator-worker | 중요 — 에이전트 연합 |
| `assistant/` | 세션 히스토리 · 에이전트 상태 추적 | 참조 |
| `tasks/` | 백그라운드 task lifecycle (Local / Remote / Dream / InProcessTeammate) | 🔥 **실행 격리 패턴** |
| `context.ts` | 시스템 프롬프트 + 사용자 컨텍스트 어셈블 | 참조 |
| `query.ts` | 메인 쿼리 루프 | 🔥 **실행 엔진 전체** |
| `QueryEngine.ts` | SDK 모드 (headless) | 중요 — 원격 에이전트 |

---

## 2. Tool 계약 — 핵심

### 2.1 `Tool<Input, Output, Progress>` 타입 (`src/Tool.ts:362–695`)

완전한 capability descriptor. 단순 "schema + handler" 가 아니다:

```typescript
export type Tool<Input, Output, Progress> = {
  // Identity
  name: string
  aliases?: string[]

  // Schema + validation
  inputSchema: Input                  // Zod schema
  inputJSONSchema?: ToolInputJSONSchema  // MCP serialization 용
  outputSchema?: z.ZodType<unknown>
  validateInput?(input, context): ValidationResult

  // Execution
  call(args, context, canUseTool, parentMessage, onProgress?): Promise<ToolResult<Output>>

  // Capability metadata
  description(input, options): Promise<string>
  isConcurrencySafe(input): boolean   // ★ orchestration의 핵심
  isReadOnly(input): boolean
  isDestructive?(input): boolean
  isEnabled(): boolean

  // Permission / security
  checkPermissions(input, context): Promise<PermissionResult>
  preparePermissionMatcher?(input): Promise<(pattern) => boolean>

  // UI rendering (React)
  renderToolUseMessage(input, options): React.ReactNode
  renderToolUseProgressMessage?(progress, options): React.ReactNode
  renderToolResultMessage?(content, progress, options): React.ReactNode
  renderToolUseErrorMessage?(result, options): React.ReactNode

  // Lifecycle
  prompt(options): Promise<string>          // LLM 에 주입할 사용 설명
  userFacingName(input): string
  getActivityDescription?(input): string | null
  interruptBehavior?(): 'cancel' | 'block'

  // Search + classification
  searchHint?: string
  toAutoClassifierInput(input): unknown

  // MCP / LSP metadata
  isMcp?: boolean
  isLsp?: boolean
  mcpInfo?: { serverName, toolName }
}
```

**핵심 관찰**
1. 하나의 tool 이 **schema · 실행 · 권한 · 렌더링 · lifecycle** 을 모두 자기 안에 담음
2. 권한 체크는 **tool 자신** 이 수행 (`checkPermissions`) — 외부 engine 이 strip-and-call 하지 않음
3. `isConcurrencySafe` 는 런타임 orchestration 에 **hard input** — 이 flag 로 병렬/직렬이 갈림
4. React 렌더링까지 tool 이 자기 책임으로 가짐 — 이게 없으면 CLI UI 가 각 tool 용도를 몰라서 generic JSON 출력

### 2.2 `buildTool()` 팩토리 + 기본값 병합 (`src/Tool.ts:757–792`)

```typescript
const TOOL_DEFAULTS = {
  isEnabled: () => true,
  isConcurrencySafe: () => false,      // ← fail-closed
  isReadOnly: () => false,
  checkPermissions: async () => ({ behavior: 'allow' }),
  ...
}

export function buildTool<I, O, P>(def: Partial<Tool<I, O, P>>): Tool<I, O, P> {
  return { ...TOOL_DEFAULTS, ...def } as Tool<I, O, P>
}
```

**관찰**: spread 병합의 순서로 "기본은 fail-closed, 명시적 opt-in 만 완화됨". 60+ tool 이 모든 메서드를 직접 구현할 필요 없이 필요한 것만 override.

### 2.3 대표 tool 의 특징

| Tool | `isConcurrencySafe` | 특이점 |
|---|---|---|
| `FileReadTool` | **true** (read-only) | PDF / 이미지 / 노트북 지원, 토큰 예산으로 read limit, 라인 범위 |
| `BashTool` | false (exclusive) | sandbox detection + destructive command warning |
| `FileEditTool` / `FileWriteTool` | false (write serialize) | diff preview + 거절 UI |
| `AgentTool` | false (세션 분리) | subagent spawn — local/remote/worktree 격리 |
| `SkillTool` | false | 메타 tool — prompt command 호출, fork agent 옵션 |
| `MCPTool` | varies | MCP tool 래퍼 — `mcp__server__tool` 네이밍 |

### 2.4 Tool 등록·발견 패턴 (`src/tools.ts:1–100`)

```typescript
// 1. Conditional imports (build-time dead-code elimination)
const REPLTool = process.env.USER_TYPE === 'ant' ? require(...) : null
const SleepTool = feature('PROACTIVE') ? require(...) : null
const cronTools = feature('AGENT_TRIGGERS') ? [CronCreateTool, ...] : []

// 2. Core tools (always present)
const builtinTools = [AgentTool, SkillTool, BashTool, FileEditTool, ...]

// 3. Dynamic MCP tools
const mcpTools = mcpClients.flatMap(client => fetchToolsForClient(client))

// 4. Assembly
export const ALL_TOOLS = [...builtinTools, ...mcpTools, ...conditionalTools]
```

**관찰**: Bun 번들러가 build-time 에 조건을 평가 → 죽은 import 를 binary 에서 제거 → 다른 deployment 용 다른 binary. Geny 는 Python 이라 이 패턴을 직접 쓸 수는 없지만, `feature("PROACTIVE")` 같은 플래그 기반 tool 등록 idea 는 적용 가능.

---

## 3. Tool Orchestration

### 3.1 Partition 기반 병렬 실행 (`src/services/tools/toolOrchestration.ts`)

```typescript
runTools(toolUseMessages, canUseTool, context)
  │
  ├─ partitionToolCalls(...)
  │     └─ concurrency-safe tools → parallel batch (cap: 10)
  │     └─ non-safe tools           → serial batch
  │
  ├─ await parallel batch
  │     └─ apply context modifiers sequentially
  │
  └─ for each non-safe tool:
         await exec   → emit result
```

### 3.2 StreamingToolExecutor (`src/services/tools/StreamingToolExecutor.ts:39–110`)

```
API streaming 으로 tool 블록이 도착
  ↓
executor.add(toolBlock)
  ↓ concurrent-safe 면 즉시 시작, else 대기열
  ↓
Queued → Executing → Progress events → Completed
  ↓
emit in received order (completion order 아님)
```

**관찰**
1. tool 이 **받은 순서대로** emit — 결과 순서가 사용자 경험에 중요
2. progress event 는 버퍼 없이 즉시 yield
3. 한 tool 의 실패는 sibling 에 전파 X (abort signal 따로)

### 3.3 우리에게 주는 교훈

- 현재 geny-executor Stage 10 은 `SequentialExecutor` / `ParallelExecutor` 이분화 — tool 단위가 아닌 **stage 단위** 병렬성
- claude-code 는 **tool 단위** 로 safety 판단 후 batching — 이게 훨씬 세밀함
- 06 design 에서 우리도 tool-level 병렬 + 직렬 파티션 도입 제안

---

## 4. Permission 시스템

### 4.1 Permission rule 구조 (`src/types/permissions.ts`)

```typescript
type PermissionBehavior = 'allow' | 'deny' | 'ask'

type PermissionRule = {
  toolName: string                  // e.g. "Bash"
  ruleContent?: string              // pattern, e.g. "git *"
  behavior: PermissionBehavior
}

type ToolPermissionRulesBySource = {
  [source: string]: {               // 'userSettings' | 'projectSettings' | 'localSettings' | 'cliArg'
    allow?: PermissionRule[]
    deny?: PermissionRule[]
    ask?:  PermissionRule[]
  }
}
```

**계층**: local ⊃ project ⊃ user (local 이 최종 우선).

### 4.2 결정 흐름 (`src/utils/permissions/permissions.ts`)

```
PermissionMode: default | plan | auto | bypassPermissions | ...
  ↓
for each source in [local, project, user, cli-arg]:
    if rule matches tool + input pattern:
        return rule.behavior
  ↓
tool.checkPermissions(input, context)
  ↓
PermissionResult { behavior, updatedInput? }
  ↓
if 'ask' → UI 다이얼로그
if 'allow' / 'deny' → 즉시 진행
```

### 4.3 tool 이 스스로 하는 `preparePermissionMatcher`

```typescript
BashTool.preparePermissionMatcher = async (input) => {
  const command = input.command
  return (pattern: string) => {
    // "Bash(git *)" → 패턴 매치 여부 반환
    ...
  }
}
```

tool 이 자기 input 구조를 알고 있으니 패턴 매칭도 자기가 가장 잘함.

### 4.4 우리에게 주는 교훈

- Geny 의 `ToolPolicyEngine` 은 **서버 수준** 필터만. "Bash 허용하되 `rm` 은 금지" 같은 input pattern 매칭 없음.
- 09 design 에서 rule × source × pattern 매트릭스 도입 제안

---

## 5. MCP 시스템

### 5.1 Transport 추상화 (`src/services/mcp/types.ts:23–135`)

```typescript
type MCPServerConfig =
  | { type: 'stdio',      command, args, env }
  | { type: 'sse',        url, headers }
  | { type: 'http',       url, headers }
  | { type: 'ws',         url, headers }
  | { type: 'sse-ide',    url, ideId }
  | { type: 'sdk',        sdkServerName: 'google-drive' | 'github' | ... }
  | { type: 'claudeai-proxy', ... }
```

### 5.2 연결 상태 FSM

```typescript
type MCPServerConnection =
  | ConnectedMCPServer    { client, capabilities, instructions, serverInfo }
  | FailedMCPServer       { error }
  | NeedsAuthMCPServer    { config }
  | PendingMCPServer      { reconnectAttempt, maxReconnectAttempts }
  | DisabledMCPServer     { config }
```

**관찰**: 실패 / 인증 필요 / 재시도 중 / 비활성화를 구분. Geny 의 MCPLoader 는 "연결 안 되면 조용히 skip" 만 하므로 운영 가시성 부족.

### 5.3 MCP → 내부 tool 변환

```
MCP server 연결
  ↓ list_tools(), list_resources(), list_prompts()
  ↓
for each tool:
    name: `mcp__${serverName}__${toolName}`
    inputSchema: MCP JSON schema → Zod
    call: marshal to MCP request → unmarshal response
  ↓
register as Tool object → added to ALL_TOOLS
```

### 5.4 OAuth / XAA (`src/services/mcp/auth.ts`, `xaa.ts`)

- OAuth 2.0 + callback port 기반
- XAA (Cross-App Access): 외부 IdP 연합 인증
- macOS/Linux keychain 에 credential 저장

**관찰**: Geny 의 MCP 는 `${TOKEN}` 환경 변수 참조에만 의존 — OAuth dance 는 자체 수행 안 함. 외부 서버가 OAuth 를 요구하면 현재 설계는 지원 불가.

---

## 6. Skills 시스템

### 6.1 번들 skill 정의 (`src/skills/bundledSkills.ts:14–41`)

```typescript
export type BundledSkillDefinition = {
  name: string
  description: string
  aliases?: string[]
  whenToUse?: string               // discovery hint
  argumentHint?: string
  allowedTools?: string[]          // subset 제한
  model?: string                   // opus/sonnet/haiku override
  disableModelInvocation?: boolean // 모델 호출 없이 즉시 실행
  userInvocable?: boolean          // UI 노출 여부
  isEnabled?: () => boolean
  hooks?: HooksSettings
  context?: 'inline' | 'fork'      // 격리 모드
  agent?: string                   // 지정된 subagent
  files?: Record<string, string>   // embed reference files
  getPromptForCommand: (args, context) => Promise<ContentBlockParam[]>
}
```

### 6.2 번들 skill 등록

```typescript
registerBundledSkill({
  name: 'update-config',
  description: 'Use this skill to configure the Claude Code harness via settings.json...',
  whenToUse: 'Automated behaviors ("from now on when X"), permissions...',
  getPromptForCommand: async (args, context) => [
    { type: 'text', text: await loadInstructions() }
  ],
})
```

### 6.3 디스크 skill 로드 (`src/skills/loadSkillsDir.ts`)

```
~/.claude/skills/my-skill.md
  ┌──────────────────────────┐
  │ ---                      │
  │ name: my-skill           │  ← frontmatter
  │ description: ...         │
  │ allowedTools: [Read]     │
  │ when_to_use: ...         │
  │ ---                      │
  │ (프롬프트 본문)            │  ← skill body
  └──────────────────────────┘
       ↓ parse
  Command { type: 'prompt', loadedFrom: 'skills', ... }
       ↓
  commands registry 에 자동 등록
```

### 6.4 Skill 호출 흐름

1. `/skill_name` 입력 또는 `SkillTool` 호출
2. 프롬프트 resolve (파일 읽기 또는 generator 호출)
3. 대화에 "skill 실행" 메시지 주입
4. optional: fork agent (isolation)
5. 결과 stream back

**특수 동작**
- `disableModelInvocation: true` — API 호출 없이 즉시 실행 (e.g. `/update-config` 는 파일 편집 지시문을 반환)
- `context: 'fork'` — isolation subagent 로 실행
- `allowedTools` — 해당 skill 실행 중 tool 집합 제한

### 6.5 MCP skill bridge (`src/skills/mcpSkillBuilders.ts`)

MCP 서버가 prompt 을 노출 → frontmatter 파싱 → skill Command 로 등록. 디스크 skill 과 동일한 API.

### 6.6 우리에게 주는 교훈

- Geny 는 role prompt 로 이 역할을 일부 수행하지만 **코드 수정 없는 skill 추가 경로가 없음**
- 08 design 의 직접 소스

---

## 7. Slash command (`src/commands.ts`)

### 7.1 Command union 타입

```typescript
type Command =
  | { type: 'prompt',  name, description, getPromptForCommand, ... }
  | { type: 'builtin', name, handler, ... }
```

- `prompt` — skill 과 동일 구조 (실제로 bundled skill 도 command 로 등록됨)
- `builtin` — 프로그래밍 handler 직접 호출 (`/config`, `/login`, `/session-status` 등)

### 7.2 레지스트리 어셈블

```typescript
const ALL_COMMANDS = [
  ...coreCommands,
  ...feature('X') ? [XCommand] : [],
  ...userDefinedCommands,    // 디스크에서 로드
  ...mcpSkills,              // MCP prompt 에서 변환
]
```

### 7.3 Geny 대응

- 현재 게임 tool (feed/play/gift/talk) 은 **Tool** 로만 노출 — 사용자가 명시적 slash 로 호출하는 경로는 없음
- 10 design 에서 "Command ↔ Tool 이분화" 재설계 제안

---

## 8. Hooks 시스템

### 8.1 이벤트 종류 (`src/types/hooks.ts`)

```
SessionStart, Setup, UserPromptSubmit,
PreToolUse, PostToolUse, PostToolUseFailure,
PermissionRequest, PermissionDenied,
Stop, StopFailure, Notification,
SubagentStart, CwdChanged,
Elicitation, ElicitationResult,
FileChanged, ...
```

### 8.2 등록 방식 (settings.json)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "if":   { "tool_name": ["Bash"] },
        "then": { "command": "my-script.sh" }
      }
    ]
  }
}
```

### 8.3 실행 프로토콜

```
이벤트 발생 (예: PreToolUse, input = { tool_name, tool_input, ... })
  ↓
매처 평가 (tool_name, input pattern, ...)
  ↓
subprocess spawn (stdin = event JSON)
  ↓
subprocess stdout = hook response JSON
{
  "continue": bool,
  "suppressOutput": bool,
  "stopReason": string?,
  "decision": "approve" | "block" | null,
  "hookSpecificOutput": {...}
}
  ↓
engine 이 response 해석 → 실행 계속 / 차단 / input 수정
```

### 8.4 CLAUDE.md frontmatter hook (`src/utils/hooks/registerFrontmatterHooks.ts`)

```markdown
# CLAUDE

hooks:
  PreToolUse:
    - if:
        tool_name: [Bash, FileEdit]
      then:
        command: ./validate.sh

---
프로젝트 문맥 (body)
```

### 8.5 우리에게 주는 교훈

- hooks 는 **subprocess + JSON I/O** — 언어 독립적, 재컴파일 불필요
- Geny 의 `SessionLifecycleBus` 는 프로세스 내 Python callable 만 — subprocess 훅 없음
- 09 design 에서 Geny 에 hooks 추가 제안 (PreToolUse / PostToolUse / PermissionRequest / StageEnter / StageExit)

---

## 9. Agent / Task 조합

### 9.1 AgentTool (`src/tools/AgentTool/AgentTool.tsx`)

```typescript
AgentInput = {
  description: string              // 3–5 word summary
  prompt: string                   // 수행 task
  subagent_type?: string           // 'code-reviewer', 'Plan', 'Explore', ...
  model?: 'opus'|'sonnet'|'haiku'
  run_in_background?: boolean
  isolation?: 'worktree' | 'remote'
  cwd?: string
  name?: string                    // SendMessage 대상 주소
  mode?: PermissionMode            // 자식 agent 의 권한 모드
}
```

### 9.2 실행 모드

1. **Inline** — 같은 터미널/세션에 subprocess 로 spawn, 동기적 결과
2. **Background** — `LocalAgentTask` 로 등록, 메인 세션 계속, 완료 시 알림
3. **Worktree** — git worktree 격리 → sandboxed 변경
4. **Remote** — CCR (Cloud Code Runtime) 원격 실행, 항상 background

### 9.3 Task 시스템 (`src/Task.ts`, `src/tasks/`)

```typescript
type TaskType = 'local_bash' | 'local_agent' | 'remote_agent'
              | 'in_process_teammate' | 'local_workflow'
              | 'monitor_mcp' | 'dream'

type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'killed'
```

```
registerTask(type, description)
  ↓ spawn({ command, cwd })
  ↓ AppState.tasks
     ├─ 진행 업데이트 → UI
     ├─ 최종 상태 도달 시 notification
     └─ 종료 요청 또는 세션 종료 시 kill
```

Task output 은 `.claude/task-output/{taskId}` 로 stream.

### 9.4 Coordinator 모드 (`src/coordinator/coordinatorMode.ts`)

- 메인 agent 가 AgentTool 로 worker spawn
- Worker tool set 제한 (`ASYNC_AGENT_ALLOWED_TOOLS`)
- Worker 는 background 로 실행 (LocalAgentTask)
- Scratchpad 디렉토리로 agent 간 통신 (옵션)
- 메인 완료 시 자동 정리

### 9.5 우리에게 주는 교훈

- Geny 의 Stage 11 (Agent) 는 slot 기반 orchestrator 만 — task lifecycle, 격리 모드, subagent_type 개념 부재
- `AgentSession.delegate()` / VTuber ↔ Sub-Worker pairing 이 이 역할을 일부 수행하지만 **worktree 격리, background task 인터페이스** 없음
- 10 design 에서 Stage 11 고도화 제안

---

## 10. Query 컴파일 파이프라인 (`src/query.ts`)

```
1. Normalize messages (서명 제거, 오래된 메시지 compact)
   ↓
2. Fetch attachments (메모리 파일 / 중첩 CLAUDE.md)
   ↓
3. Token budget 제약 적용
   ├─ Max input tokens
   ├─ Max file read size
   ├─ Trailing context (최근 N 메시지 유지)
   └─ Auto-compact if needed
   ↓
4. System prompt 렌더
   ├─ Base system prompt
   ├─ Tool 설명 (deferred loading 포함)
   ├─ Skill 카탈로그
   ├─ 세션 로컬 command
   └─ Hook reminder
   ↓
5. Request 어셈블 {model, max_tokens, system, tools, messages}
   ↓
6. Stream response (claude.complete)
   ├─ Parse JSON blocks (tool use)
   ├─ Collect parallel tool blocks
   └─ Start tool execution 즉시 (streaming)
   ↓
7. toolOrchestration 호출
   ├─ Concurrent batch (read-only)
   └─ Serial batch (writes)
   ↓
8. Yield tool results
   ├─ ToolResultBlockParam 변환
   ├─ UI 렌더
   └─ messages 에 주입
   ↓
9. 다음 turn (goto 5) 또는 종료
```

### 10.1 우리 16-stage 와의 대응

| query.ts 단계 | 대응 Geny/executor stage |
|---|---|
| 1. Normalize messages | Stage 2 (Context) + 압축 (SummaryCompactor 등) |
| 2. Fetch attachments | (부재 — Geny 측 PromptBuilder 일부가 이 역할) |
| 3. Token budget | Stage 4 (Guard: TokenBudgetGuard) |
| 4. System prompt | Stage 3 (System) + Geny PromptBuilder |
| 5. Request assemble | Stage 5 (Cache) + Stage 6 (API) |
| 6. Stream response | Stage 6 (API — create_message_stream) |
| 7. Tool orchestration | Stage 9 (Parse) → Stage 10 (Tool) |
| 8. Yield tool results | Stage 10 tool 결과 → state.tool_results → 다음 iteration |
| 9. Continue / end | Stage 13 (Loop) |

**관찰**: 16-stage 가 이미 거의 모든 역할을 커버하지만, **tool 계약과 orchestration 의 세밀도** 가 얕음. Stage 10 은 "tool 실행" 하나로 묶여있고 partition / streaming / permission / UI render 는 stage 안에 암묵적.

---

## 11. Top 10 참조 패턴 — "우리에게 의미"

### 1. Tool = 완전한 capability descriptor
- **출처**: `Tool.ts:362–695`
- **우리에게 의미**: Geny `BaseTool` 은 name/description/parameters/run 뿐. concurrency/destructive/permission/render 메타 없음. 06 design 의 핵심.

### 2. Concurrency-safe partition orchestration
- **출처**: `services/tools/toolOrchestration.ts:26–80`
- **우리에게 의미**: Stage 10 을 tool-level partitioning 으로 리파인 → read-only tool (Read/Grep 등) 은 자동 병렬.

### 3. `buildTool()` + fail-closed 기본값
- **출처**: `Tool.ts:757–792`
- **우리에게 의미**: 새 tool 작성 시 boilerplate 제거 + "옵트인" 원칙. 단, Python 에는 dataclass `replace()` 또는 `dataclasses.replace` 패턴으로 이식.

### 4. MCP = 다중 transport 추상화
- **출처**: `services/mcp/types.ts:23–135`, `services/mcp/client.ts`
- **우리에게 의미**: Geny 의 stdio/HTTP/SSE 3 종을 넘어 WS/sdk/proxy 까지 지원. 07 design 소스.

### 5. Feature-flag 기반 죽은 import 제거
- **출처**: `tools.ts:16–53`
- **우리에게 의미**: Python 에서는 lazy import + `if feature('X')` 로 등록 여부 제어. 서로 다른 배포 타깃에 서로 다른 tool set.

### 6. Skills = 프롬프트 + tool allowlist 묶음
- **출처**: `skills/bundledSkills.ts:53–100`, `skills/loadSkillsDir.ts`
- **우리에게 의미**: 08 design 의 직접 소스. "코드 수정 0 으로 capability 추가".

### 7. Hooks = subprocess + JSON I/O
- **출처**: `types/hooks.ts` (150+ LOC), `utils/hooks/`
- **우리에게 의미**: Geny 의 Python callable 훅을 넘어 언어 중립 subprocess 훅. 감사·정책·관측성이 한 자리에서.

### 8. Permission rule = scoped + pattern + hierarchical
- **출처**: `types/permissions.ts`, `utils/permissions/permissions.ts`
- **우리에게 의미**: `ToolPolicyEngine` 을 rule × source × pattern 매트릭스로 재작성. "Bash 허용하되 rm 금지" 가능해짐.

### 9. Tool 결과 persistence 예산
- **출처**: `Tool.ts:465–466`, `utils/toolResultStorage.ts`
- **우리에게 의미**: `maxResultSizeChars` 초과하면 디스크로 저장 + path 만 모델에게. Stage 10 고도화 항목.

### 10. Streaming tool executor + 순서 보존 버퍼
- **출처**: `services/tools/StreamingToolExecutor.ts:39–110`
- **우리에게 의미**: tool 결과가 완료 순이 아닌 수신 순으로 emit. UX + 재현성 측면에서 중요.

---

## 12. 요약 — 우리가 어떤 "언덕" 에 서 있는가

| 축 | Geny 현재 | claude-code 수준 | 격차 |
|---|---|---|---|
| Tool 계약 | name + description + schema + handler | 위 + concurrency + destructive + permission + render + lifecycle | 🔴 크다 |
| Tool orchestration | Stage 단위 serial/parallel | Tool 단위 partition + streaming executor | 🔴 크다 |
| Permission | Role → server prefix 필터 | Rule × source × pattern 매트릭스 | 🟡 중간 |
| MCP transport | stdio/HTTP/SSE | + WS/SDK/proxy + OAuth 기본 지원 | 🟡 중간 |
| MCP 수명 관리 | 정적 JSON 로드, 실패 시 skip | FSM (Connected/Failed/NeedsAuth/Pending/Disabled) | 🟡 중간 |
| Skills | 부재 (role prompt 로 대체) | Bundled + disk + MCP skill 삼위일체 | 🔴 크다 |
| Hooks | LifecycleBus (session 레벨) | 15+ 종 이벤트 × subprocess JSON I/O | 🔴 크다 |
| Agent delegation | Stage 11 orchestrator slot | subagent_type + isolation + background task | 🟡 중간 |
| Query pipeline | 16-stage 구조화 | 절차적, 단 섬세한 budget/stream 처리 | 🟢 Geny 가 더 나음 (구조는) |
| Observability | EventBus | EventBus + React render | 🟡 중간 |

**정리**: 구조적으로는 Geny 의 16-stage 가 더 명시적이고 성숙. 그러나 **Tool/Skill/Hook 인터페이스의 표면적** 은 claude-code 가 훨씬 넓음. 이번 uplift 의 초점은 "우리 뼈대 위에 claude-code 의 표면적을 얹는 것".

다음 문서 ([`05_gap_analysis.md`](05_gap_analysis.md)) 에서 이 격차를 우선순위화.
