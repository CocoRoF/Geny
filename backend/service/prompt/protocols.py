"""
Execution / Completion / Error Recovery Protocols (opt-in sections)

NOTE: The sections in this module are NOT included in the default prompt build.
- The `geny-executor` Pipeline controls the execution loop, retries, and completion detection.
- The Claude API (via geny-executor's APIStage) provides default safety guidelines.
- All sessions already have autonomous execution capability via the Pipeline's stages.

Use these only when you want to manually add them to a PromptBuilder:
    builder.add_section(ExecutionProtocol.autonomous_execution())
"""

from __future__ import annotations

from service.prompt.builder import PromptMode, PromptSection


class ExecutionProtocol:
    """Execution protocol — behavioral rules during autonomous execution."""

    @staticmethod
    def autonomous_execution() -> PromptSection:
        """Autonomous execution protocol section.

        Integrates the autonomous graph's execution loop with
        the Geny Agent's [CONTINUE] signal.
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
        """Multi-turn execution guidelines."""
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
    """Completion detection protocol.

    Integrates OpenClaw's structured completion signals with the
    Geny Agent's [TASK_COMPLETE] pattern.
    """

    @staticmethod
    def completion_signals() -> PromptSection:
        """Completion signal convention section."""
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
    """Error self-recovery protocol.

    Translates OpenClaw's multi-stage recovery strategies (auth rotation,
    context compaction, etc.) into agent-level prompt guidelines.
    """

    @staticmethod
    def self_recovery() -> PromptSection:
        """Error self-recovery protocol."""
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
