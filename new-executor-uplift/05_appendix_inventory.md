# 05. Appendix — claude-code-main 전체 surface inventory

**Source:** `/home/geny-workspace/claude-code-main/src/` 의 직접 탐색 (1902 ts/tsx 파일).
**Date:** 2026-04-25
**용도:** 본 분석의 대상 전체. P0/P1/P2 외 항목 검토 시 lookup 으로.

본 inventory 는 `02_capability_matrix.md` 의 53 항목 + 그 너머의 세부 surface 까지. 카테고리별 정리.

---

## 1. Tool system

**Core:** `src/Tool.ts` — Tool ABC, ToolDef, BuiltTool, buildTool() factory.

**Tool ABC fields:**
- `name`, `description`, `inputSchema` (Zod), `displayInputPreview` (bool)
- `permissions(): PermissionRule[]`
- `useCanUseTool()` hook binding
- async `execute()` (Anthropic tool_use protocol)
- optional `spinnerMode: 'status' | 'spinner' | 'hidden'`
- `ToolCallProgress<>` 콜백
- 일부 tool 은 lifecycle (SkillTool 의 MCP resource bridge 처럼)

**Built-in tools — 39 stable + 9 feature-gated = 48 total:**

```
Stable (39):
  FileReadTool, FileWriteTool, FileEditTool
  BashTool, PowerShellTool
  GlobTool, GrepTool, LSPTool
  WebFetchTool, WebSearchTool
  NotebookEditTool
  ConfigTool, BriefTool
  TodoWriteTool
  AgentTool                   ← sub-agent spawning
  SkillTool
  TaskCreateTool, TaskGetTool, TaskListTool, TaskUpdateTool, TaskStopTool, TaskOutputTool  ← background tasks
  EnterPlanModeTool, ExitPlanModeTool
  EnterWorktreeTool, ExitWorktreeTool
  AskUserQuestionTool
  SendMessageTool
  ListMcpResourcesTool, ReadMcpResourceTool, McpAuthTool, MCPTool
  ToolSearchTool

Feature-gated (9):
  REPLTool                    (USER_TYPE='ant')
  SleepTool                   (PROACTIVE/KAIROS)
  ScheduleCronTool, CronDeleteTool, CronListTool  (AGENT_TRIGGERS)
  RemoteTriggerTool           (AGENT_TRIGGERS_REMOTE)
  MonitorTool                 (MONITOR_TOOL)
  PushNotificationTool        (KAIROS)
  SubscribePRTool             (KAIROS_GITHUB_WEBHOOKS)
  SendUserFileTool            (KAIROS)
```

**Concurrency:** No PartitionExecutor — tools 직렬. (Geny 가 ahead)

**Background task types (7):** local_bash, local_agent, remote_agent, in_process_teammate, local_workflow, monitor_mcp, dream

---

## 2. Permission system

**File hierarchy:** `src/utils/permissions/`
- `permissions.ts` — getAllowRules / getDenyRules / getAskRules / hasPermissionsToUseTool
- `PermissionRule.ts`
- `PermissionMode.ts`
- `PermissionResult.ts`
- `permissionsLoader.ts`
- `denialTracking.ts` — user-denied actions 추적

**Rule format:**
```typescript
PermissionRule = {
  source: 'userSettings' | 'projectSettings' | 'localSettings' | 'flagSettings' | 'policySettings' | 'cliArg' | 'command' | 'session',
  ruleBehavior: 'allow' | 'deny' | 'ask',
  ruleValue: { toolName: string, ruleContent?: string }  // ruleContent 는 regex
}
```

**Permission modes (6):**
- `acceptEdits` — file 편집 자동 승인
- `bypassPermissions` — 모든 권한 무시
- `default` — rule 평가
- `dontAsk` — ask 동작을 deny 로 매핑
- `plan` — execution skip, dry-run
- `auto` — TRANSCRIPT_CLASSIFIER (LLM 기반 권한 판단)

**Managed settings:** `src/services/remoteManagedSettings/` — enterprise MDM 정책 (read-only override).

---

## 3. Hook system

**Files:** `src/utils/hooks/hookEvents.ts`, `src/types/hooks.ts`

**Events:** SessionStart, Setup + 확장 가능한 HOOK_EVENTS list (feature-gated).

**Subprocess contract:**
- STDIN: `PromptRequest` (JSON, message context)
- STDOUT: `PromptResponse` (JSON, allow/deny/modify)
- exit code: 'success' | 'error' | 'cancelled'

**HookSettings 형식:**
```json
{
  "hooks": {
    "PreToolUse": [{ "command": "audit.sh", "timeout_ms": 500 }],
    "PostToolUse": [],
    "SessionStart": []
  }
}
```

**In-process callbacks:** `registerHookEventHandler()` — SDK 사용자 위해. event bus + queue (MAX_PENDING=100).

---

## 4. Skill system

**Files:** `src/skills/loadSkillsDir.ts`, `src/skills/SkillTool.ts`, `src/skills/mcpSkillBuilders.ts`

**SKILL.md frontmatter:**
```yaml
---
name: skill-name
description: ...
category: docs|debug|cli|...
examples:
  - { input: "...", description: "..." }
model: claude-3-5-sonnet  # optional override
effort: low|med|high|vision
permissions:
  allow: [...]
  deny: [...]
tools: [Read, Bash, ...]    # 의존하는 tool 목록
---
body (system prompt injection)
```

**Skill loader paths:**
- `src/skills/bundled/*.ts` — 17개 (batch, claudeApi, debug, keybindings, loop, remember, scheduleRemoteAgents, simplify, stuck, updateConfig, verify, ...)
- `~/.claude/skills/`
- `.claude/skills/`
- MCP-supplied (via `registerMCPSkillBuilders()`)

**SkillTool dispatch:** skill name 으로 lookup, `{example}` argument substitution, prompt injection.

**Execution modes:** inline (default) + forked (Ant-only, sub-agent 으로 spawn).

---

## 5. MCP integration

**Files:** `src/services/mcp/`, `src/tools/MCPTool/`, `src/tools/ListMcpResourcesTool/`, `src/tools/ReadMcpResourceTool/`, `src/tools/McpAuthTool/`

**Transport types (6):**
- `stdio` — local subprocess
- `sse` — remote SSE
- `sse-ide` — IDE extension SSE channel
- `http` — REST
- `ws` — WebSocket
- `sdk` — `InProcessTransport`, `SdkControlTransport`

**Connection FSM:** 추정 — connecting / connected / failed / needs_auth / disabled

**OAuth:** `src/services/mcp/auth.ts` + `oauthPort.ts` — clientId / callbackPort
**XAA:** `McpXaaConfigSchema` (Cross-App Access) — enterprise feature
**Resource scheme:** `mcp://server/path` via `ReadMcpResourceTool`
**Server runtime:** `useManageMCPConnections.ts` — health check + reconnect

---

## 6. Slash commands (~100)

**Discovery:** `src/commands.ts` 의 중앙 registry. 카테고리별:
- **Introspection:** /cost, /clear, /status, /help, /memory, /context, /tasks, /skills, /mcp
- **Control:** /cancel, /compact, /config, /model, /preset, /verify
- **Workflow:** /commit, /pr, /branch, /worktree
- **Debug:** /context, /memory, /history, /trace
- ... (~100 total)

**Argument:** frontmatter 의 `arguments` + `examples` 필드. `parseArgumentNames()` + `substituteArguments()`.

---

## 7. Memory / Context

**Files:** `src/memory/`, `src/context.ts`, `src/services/compact/`

**Memory types:**
- `CLAUDE.md` (project, git-tracked)
- `.claude/.session_memory/<session-id>.md` (session, auto-updated)
- per-message context (Message.memory, Message.fileContext)

**Context budget:** `tokenCountWithEstimation()` + `getSystemContext()` + `getUserContext()` 가 system + user prompt 빌드, git status / CLAUDE.md / file snippets injection.

**Auto-compaction:** `src/services/compact/sessionMemoryCompact.ts` — context fill 임계치 → 자동 trigger. forked agent 가 key facts 추출 → session memory.

---

## 8. Sub-agent / Task system

**AgentTool spawning:** local_agent / remote_agent / in_process_teammate task 생성

**Task lifecycle:** `Task.ts` 의 TaskStateBase
```typescript
{ id, type, status: 'pending'|'running'|'completed'|'failed'|'killed',
  startTime, endTime, outputFile }
```

**Result aggregation:** disk buffer (`getTaskOutputPath()`), `TaskOutputTool` reads.

**Background:** non-blocking spawn, UI polling for status, Spinner 컴포넌트.

---

## 9. Streaming / TTY rendering

**Files:** `src/components/`, `src/ink/`

**Tool result custom JSX:** 각 tool 의 `UI.ts` (FileReadTool/UI.ts, BashTool/UI.ts, ...) — tool 별 전용 renderer.

**Progress hints:** ToolCallProgress<>, ToolProgressData (BashProgress / WebSearchProgress / ...).

**Permission UI:** `src/components/permissions/` — FilePermissionDialog, BashPermissionRequest, ...

---

## 10. Prompt caching / Model

**Caching:** `setSystemPromptInjection()` in context.ts — system / session memory / CLAUDE.md 경계에 cache breakpoint 추정.

**Extended thinking:** `src/utils/thinking.ts` — ThinkingConfig.

**Streaming:** Anthropic SDK ContentBlockDelta — 점진적 tool_use parse.

---

## 11. In-process callbacks

`registerHookEventHandler()` — SDK 사용자가 event 받기. pendingEvents queue 가 handler 등록 전 buffer.

---

## 12. Settings / Config

**Hierarchy:** user (`~/.claude/settings.json`) → project (`.claude/settings.json`) → local (`.claude/settings.local.json`)

**Fields:**
- `defaultMode`, `permissions`, `hooks`, `model`, `additionalWorkingDirectories`, `telemetry`, ...

**Managed:** `src/services/remoteManagedSettings/` — enterprise read-only override.

---

## 13. Notebook support

**NotebookEditTool:**
- edit_mode: 'insert' | 'edit' | 'delete'
- .ipynb JSON parse
- Cell ID auto-gen 또는 user-spec
- output array 보존

---

## 14. Artifacts / file-render

- 별도 artifact system 없음
- file render: FileReadTool / FileEditTool diff
- StructuredDiff component
- IDE deep link: `vscode://file/<path>:<line>:<col>` via `desktopDeepLink.ts`

---

## 15. Cost tracking

**File:** `src/cost-tracker.ts`
- getTotalCostUSD()
- getTotalAPIDuration()
- getTotalInputTokens / OutputTokens / CacheReadInputTokens / CacheCreationInputTokens()
- model pricing in `src/utils/modelCost.ts`

**Budget gates:** `src/services/policyLimits/`

**Reporting:** `/cost` slash command

---

## 16. Scheduling / Cron

**Tools:** ScheduleCronTool / CronDeleteTool / CronListTool — `.claude/scheduled_tasks.json`

**Background runner:** daemon 추정.

**Remote agents:** RemoteTriggerTool — Anthropic Managed Agents API.

---

## 17. Debugging / Introspection

```
/cost        — cost / tokens
/clear       — history clear
/status      — session info
/help        — command list
/context     — git status / CLAUDE.md / files
/memory      — session memory edit
/tasks       — background tasks
/keybindings — keyboard shortcuts
```

---

## 18. Sandbox

**Files:** `src/utils/sandbox/`, `src/components/sandbox/`

- File access boundaries: settings.additionalWorkingDirectories
- Network egress: WebFetch domain allowlist 추정
- Toggle: `/commands/sandbox-toggle/` runtime on/off

---

## 19. 추가 systems

- **Worktree:** EnterWorktreeTool / ExitWorktreeTool — git worktree 격리
- **LSP:** LSPTool — language server bridge
- **Team:** TeamCreateTool / TeamDeleteTool (Anthropic-internal 추정)
- **VerifyPlanExecutionTool:** dry-run before execute (Ant-only)
- **Coordinator mode:** `src/coordinator/coordinatorMode.ts` — multi-agent + scratchpad
- **Auto-compaction:** context fill 자동 SessionMemory extract
- **Plugins:** `src/plugins/bundled/` — extensible plugin system

---

## Summary 통계

| 카테고리 | claude-code 보유 | Geny SHIPPED | 비고 |
|---|---|---|---|
| Stable tools | 39 | 13 | 26 누락 |
| Feature-gated tools | 9 | 0 | OUT_OF_SCOPE 일부 |
| Slash commands | ~100 | 3 | 97 누락 |
| Bundled skills | 17 | 3 | 14 추가 가능 |
| Hook events | 6+extensible | 16 | Geny 가 더 stricter typed |
| MCP transports | 6 | 3 | WS / SDK-managed / SSE-IDE 누락 |
| Permission modes | 6 | 4 | acceptEdits / dontAsk 누락 |
| Permission rule sources | 8 | 5 | flag / policy / session 누락 |
| Background task types | 7 | 0 | 전부 누락 |

---

본 inventory 는 본 분석의 raw material. P0–P3 분류는 `03_priority_buckets.md` 에서, design sketch 는 `04_design_sketches.md` 에서.
