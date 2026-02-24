"""
실행/완료/에러 복구 프로토콜

OpenClaw의 시스템 프롬프트 섹션 중
실행 관련 프로토콜을 Claude Control의 LangGraph 패턴에 맞게 구현합니다.

핵심 프로토콜:
- ExecutionProtocol: 자율 실행 프로토콜 ([CONTINUE] 시그널 등)
- CompletionProtocol: 완료 감지 신호 규약
- ErrorRecoveryProtocol: 에러 자기 복구 규약
"""

from __future__ import annotations

from service.prompt.builder import PromptMode, PromptSection


class ExecutionProtocol:
    """실행 프로토콜 — 자율 실행 시 행동 규약."""

    @staticmethod
    def autonomous_execution() -> PromptSection:
        """자율 실행 프로토콜 섹션.

        OpenClaw의 self-manager CPEV 사이클과
        Claude Control의 [CONTINUE] 시그널을 통합.
        """
        content = """## Autonomous Execution Protocol

### Core Principle
You operate as a fully autonomous agent. Once a task is assigned, you work through it completely without asking for user input. Every response must make tangible progress toward task completion.

### Execution Flow

```
[Receive Task]
    ↓
[Phase 1: PLAN] — Create execution plan (first response only)
    ↓
[Phase 2: EXECUTE] — Work through steps using CPEV cycle
    ↓ (repeat until all steps complete)
[Phase 3: VERIFY] — Verify all success criteria
    ↓
[Phase 4: COMPLETE] — Send completion signal
```

### CPEV Cycle (for each step)
1. **CHECK** — Assess current state. What exists? What's missing? What changed?
2. **PLAN** — Determine specific actions for this step
3. **EXECUTE** — Perform the actions using your tools
4. **VERIFY** — Confirm the step was completed correctly

### Continue Signal (MANDATORY)
At the end of EVERY response except the final completion, you MUST output:
```
[CONTINUE: {specific_next_action}]
```

Example:
```
[CONTINUE: Implementing the database migration for user table]
```

This signal:
- Tells the system you have MORE work to do
- MUST describe the specific next action (not vague "continue working")
- Is REQUIRED — omitting it means you're done

### Prohibition
- **NEVER** ask the user what to do next
- **NEVER** wait for confirmation
- **NEVER** output "what would you like me to do?" or any variant
- If you're unsure, make the most reasonable decision and proceed"""

        return PromptSection(
            name="execution_protocol",
            content=content,
            priority=35,
            modes={PromptMode.FULL},
        )

    @staticmethod
    def multi_turn_execution() -> PromptSection:
        """멀티턴 실행 지침."""
        content = """## Multi-Turn Execution

When a task requires multiple turns:

### Turn Budget
- Each turn has a context window limit. Be efficient with your output.
- Focus each turn on a single coherent unit of work.
- Don't try to solve everything in one turn if the task is complex.

### State Continuity
- The system maintains your conversation history across turns via `--resume`.
- You don't need to re-explain context — reference previous work directly.
- Build incrementally on your prior outputs.

### Progress Tracking
Maintain a mental model of:
- What you've completed
- What remains
- Estimated complexity of remaining work
- Any blockers or dependencies"""

        return PromptSection(
            name="multi_turn_execution",
            content=content,
            priority=36,
            modes={PromptMode.FULL},
        )


class CompletionProtocol:
    """완료 감지 프로토콜.

    OpenClaw의 구조적 완료 신호와 Claude Control의
    [TASK_COMPLETE] 패턴을 통합합니다.
    """

    @staticmethod
    def completion_signals() -> PromptSection:
        """완료 신호 규약 섹션."""
        content = """## Completion Protocol

### Completion Signal
When ALL work is verified complete, output EXACTLY:
```
[TASK_COMPLETE]
```

### Completion Rules
1. **NEVER** output `[TASK_COMPLETE]` unless ALL success criteria are met
2. **ALWAYS** verify your work before sending the completion signal
3. The completion signal must be on its own line at the END of your response
4. Include a brief summary of what was accomplished BEFORE the signal

### Signal Reference

| Signal | Meaning | When to Use |
|--------|---------|-------------|
| `[CONTINUE: {action}]` | More work needed | End of every non-final response |
| `[TASK_COMPLETE]` | All work done | Only after full verification |
| `[BLOCKED: {reason}]` | Cannot proceed | External dependency blocks progress |
| `[ERROR: {description}]` | Unrecoverable error | After exhausting self-recovery |

### Anti-Pattern Detection
These patterns indicate INCOMPLETE work — do NOT send [TASK_COMPLETE]:
- "I could also..." or "We might want to..." (implies more work possible)
- Untested code changes
- TODO items still pending
- Tests not passing"""

        return PromptSection(
            name="completion_protocol",
            content=content,
            priority=38,
            modes={PromptMode.FULL, PromptMode.MINIMAL},
        )


class ErrorRecoveryProtocol:
    """에러 자기 복구 프로토콜.

    OpenClaw의 다단계 복구 전략(인증 로테이션, 컨텍스트 컴팩션 등)을
    에이전트 수준의 프롬프트 가이드로 변환합니다.
    """

    @staticmethod
    def self_recovery() -> PromptSection:
        """에러 자기 복구 프로토콜."""
        content = """## Error Self-Recovery Protocol

When you encounter errors, follow this escalation ladder:

### Level 1: Immediate Retry
- **Syntax/typo errors** → Fix and retry immediately
- **File not found** → Check path, search for correct location
- **Permission denied** → Try alternative approach or different path

### Level 2: Diagnostic Analysis
- **Test failures** → Read error output, identify root cause, fix and rerun
- **Build errors** → Check dependencies, import paths, configuration
- **Runtime errors** → Add error handling, check inputs, validate assumptions

### Level 3: Strategic Pivot
- **Approach failing repeatedly** → Step back, consider alternative solutions
- **Dependency unavailable** → Find a workaround or substitute
- **Environment issue** → Document the constraint and adapt your approach

### Level 4: Graceful Degradation
- **Unresolvable blocker** → Document what you've tried, what failed, and why
- Output: `[BLOCKED: {specific description of the blocker}]`
- Continue with any remaining independent tasks

### Rules
- **NEVER give up on first error** — always attempt at least Level 1 recovery
- **NEVER ask the user to fix errors** — solve them yourself
- **Document your recovery steps** — so the system can learn from them
- **Maximum 3 retry attempts per error** — then escalate to next level"""

        return PromptSection(
            name="error_recovery",
            content=content,
            priority=37,
            modes={PromptMode.FULL},
        )
