"""
Unified Agent Execution Service
================================

Core Philosophy:
    **All agent execution goes through this single module.**
    A chat-room broadcast is nothing more than N concurrent command
    executions.  There is ONE execution path — never two.

This module owns:
    - Active execution tracking  (_active_executions)
    - Session logging            (log_command / log_response)
    - Cost persistence           (increment_cost)
    - Auto-revival               (agent.revive)
    - Double-execution prevention
    - Timeout handling
    - Avatar state updates       (emotion extraction from output)

Both ``agent_controller`` (command tab) and ``chat_controller``
(messenger broadcast) delegate here.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, asdict
from logging import getLogger
from typing import Any, Dict, Optional, Set

logger = getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================

class AgentNotFoundError(Exception):
    """Raised when the requested session does not exist."""


class AgentNotAliveError(Exception):
    """Raised when the session process is dead and revival failed."""


class AlreadyExecutingError(Exception):
    """Raised when a command is already running on this session."""


# ============================================================================
# Result model
# ============================================================================

@dataclass
class ExecutionResult:
    """Immutable result of a single command execution."""
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ============================================================================
# App-state reference (set once during startup from main.py lifespan)
# ============================================================================

_app_state = None
"""Module-level reference to FastAPI app.state (for avatar/VTuber services)."""


def set_app_state(app_state) -> None:
    """
    Called once during startup to give the executor access to app.state.
    This avoids passing app_state through every call chain.
    """
    global _app_state
    _app_state = app_state


# ============================================================================
# Avatar state emission (called after every execution)
# ============================================================================

async def _emit_avatar_state(session_id: str, result: 'ExecutionResult') -> None:
    """
    Emit avatar state update based on execution result.
    Called after _execute_core completes — ensures ALL execution paths
    (sync, async, chat broadcast) update the Live2D avatar.

    Best-effort: never raises.
    """
    if _app_state is None:
        return
    if not hasattr(_app_state, 'avatar_state_manager') or not hasattr(_app_state, 'live2d_model_manager'):
        return

    try:
        state_manager = _app_state.avatar_state_manager
        model_manager = _app_state.live2d_model_manager

        model = model_manager.get_agent_model(session_id)
        if not model:
            return

        from service.vtuber.emotion_extractor import EmotionExtractor
        extractor = EmotionExtractor(model.emotionMap)

        if result.success and result.output:
            # Extract emotion from agent output text
            emotion, index = extractor.resolve_emotion(result.output, "completed")
            await state_manager.update_state(
                session_id=session_id,
                emotion=emotion,
                expression_index=index,
                trigger="agent_output",
            )
        elif not result.success:
            # Error/timeout → set appropriate emotion
            agent_state = "timeout" if "Timeout" in (result.error or "") else "error"
            emotion, index = extractor.resolve_emotion(None, agent_state)
            await state_manager.update_state(
                session_id=session_id,
                emotion=emotion,
                expression_index=index,
                trigger="state_change",
            )
    except Exception:
        logger.debug("Avatar state emission failed for %s", session_id, exc_info=True)


# ============================================================================
# Sub-Worker → VTuber auto-report (called after every execution)
# ============================================================================

async def _notify_linked_vtuber(session_id: str, result: 'ExecutionResult') -> None:
    """
    If this session is a Sub-Worker linked to a VTuber, fire-and-forget
    a [SUB_WORKER_RESULT] message to the VTuber so it can summarise for the user.

    Best-effort: never raises.
    """
    try:
        from service.langgraph import get_agent_session_manager

        manager = get_agent_session_manager()
        agent = manager.get_agent(session_id)
        if not agent:
            return

        # Only Sub-Workers with a linked VTuber should notify
        if getattr(agent, '_session_type', None) != 'sub':
            return
        linked_id = getattr(agent, 'linked_session_id', None)
        if not linked_id:
            return

        vtuber_agent = manager.get_agent(linked_id)
        if not vtuber_agent:
            return

        # Build a concise summary for the VTuber
        if result.success and result.output:
            summary = result.output[:2000]
            content = f"[SUB_WORKER_RESULT] Task completed successfully.\n\n{summary}"
        elif result.error:
            content = f"[SUB_WORKER_RESULT] Task failed: {result.error[:500]}"
        else:
            content = "[SUB_WORKER_RESULT] Task finished with no output."

        # Emit delegation.sent on the Sub-Worker's log so the flow is
        # visible from the sender side. The receiver side will emit
        # delegation.received when the VTuber's _execute_core picks up
        # the tagged prompt (via either the direct path or the inbox).
        try:
            sender_logger = _get_session_logger(session_id, create_if_missing=False)
            if sender_logger is not None:
                _sender_role = getattr(agent, "role", None)
                _target_role = getattr(vtuber_agent, "role", None)
                sender_logger.log_delegation_event(
                    "delegation.sent",
                    {
                        "tag": "[SUB_WORKER_RESULT]",
                        "from_session_id": session_id,
                        "to_session_id": linked_id,
                        "from_role": (
                            _sender_role.value if _sender_role is not None
                            and hasattr(_sender_role, "value") else _sender_role
                        ),
                        "to_role": (
                            _target_role.value if _target_role is not None
                            and hasattr(_target_role, "value") else _target_role
                        ),
                    },
                )
        except Exception:
            logger.debug("delegation.sent emit failed for %s", session_id, exc_info=True)

        # Fire-and-forget: trigger VTuber to process the result
        async def _trigger_vtuber() -> None:
            try:
                vtuber_result = await execute_command(linked_id, content)
            except AlreadyExecutingError:
                # VTuber is busy — store in inbox for later pickup
                try:
                    from service.chat.inbox import get_inbox_manager
                    inbox = get_inbox_manager()
                    inbox.deliver(
                        target_session_id=linked_id,
                        content=content,
                        sender_session_id=session_id,
                        sender_name="Sub-Worker",
                    )
                    logger.info(
                        "VTuber %s busy — SUB_WORKER_RESULT stored in inbox", linked_id
                    )
                except Exception as inbox_err:
                    # Inbox also failed — store in DLQ for recovery
                    logger.warning(
                        "VTuber notification inbox fallback failed for %s: %s",
                        linked_id, inbox_err,
                    )
                    try:
                        from service.chat.inbox import get_inbox_manager
                        get_inbox_manager().send_to_dlq(
                            target_session_id=linked_id,
                            content=content,
                            sender_session_id=session_id,
                            sender_name="Sub-Worker",
                            reason="vtuber_notify_inbox_failed",
                            original_error=str(inbox_err),
                        )
                    except Exception:
                        logger.error(
                            "VTuber notification DLQ fallback also failed for %s",
                            linked_id, exc_info=True,
                        )
            except (AgentNotFoundError, AgentNotAliveError) as exc:
                logger.debug(
                    "VTuber notification to %s skipped: %s", linked_id, exc
                )
                return

            # VTuber produced a conversational reply to the
            # [SUB_WORKER_RESULT] trigger. Without this broadcast the
            # reply is generated but never surfaces in the user's chat
            # panel — the THINKING_TRIGGER path is the only other code
            # that writes to the room, and it doesn't run here. Mirror
            # `_save_drain_to_chat_room` / `thinking_trigger.
            # _save_to_chat_room` so SSE subscribers see the response.
            _save_subworker_reply_to_chat_room(linked_id, vtuber_result)

        asyncio.create_task(_trigger_vtuber())
        logger.info(
            "Sub-Worker→VTuber auto-report queued: %s → %s", session_id, linked_id
        )

    except Exception:
        logger.debug(
            "VTuber notification failed for %s", session_id, exc_info=True
        )


async def _notify_vtuber_sub_worker_progress(session_id: str, status: str) -> None:
    """
    If this is a Sub-Worker session linked to a VTuber, update the VTuber avatar
    to show that the Sub-Worker is active (e.g., "surprise" expression).

    Best-effort: never raises.
    """
    try:
        if _app_state is None:
            return
        if not hasattr(_app_state, 'avatar_state_manager') or not hasattr(_app_state, 'live2d_model_manager'):
            return

        from service.langgraph import get_agent_session_manager
        manager = get_agent_session_manager()
        agent = manager.get_agent(session_id)
        if not agent:
            return
        if getattr(agent, '_session_type', None) != 'sub':
            return
        linked_id = getattr(agent, 'linked_session_id', None)
        if not linked_id:
            return

        model_manager = _app_state.live2d_model_manager
        model = model_manager.get_agent_model(linked_id)
        if not model:
            return

        state_manager = _app_state.avatar_state_manager

        if status == "executing":
            await state_manager.update_state(
                session_id=linked_id,
                emotion="surprise",
                expression_index=model.emotionMap.get("surprise", 0),
                trigger="sub_worker_progress",
            )
    except Exception:
        pass  # Best-effort


# ============================================================================
# Centralised active-execution registry
# ============================================================================

_active_executions: Dict[str, dict] = {}
"""session_id → holder dict for every in-flight execution."""

_draining_sessions: Set[str] = set()
"""Sessions currently draining their inbox (prevents infinite recursion)."""


def is_executing(session_id: str) -> bool:
    """Return True if *session_id* is currently running a command."""
    holder = _active_executions.get(session_id)
    return holder is not None and not holder.get("done", True)


def is_trigger_executing(session_id: str) -> bool:
    """Return True if *session_id* is running a trigger (preemptible)."""
    holder = _active_executions.get(session_id)
    return (
        holder is not None
        and not holder.get("done", True)
        and holder.get("is_trigger", False)
    )


def get_execution_holder(session_id: str) -> Optional[dict]:
    """Return the live holder dict, or None."""
    return _active_executions.get(session_id)


def cleanup_execution(session_id: str, exec_id: Optional[str] = None) -> None:
    """Remove the holder entry if *exec_id* matches (or is None).

    When *exec_id* is given, only remove the holder if its ``exec_id``
    matches — this prevents a finishing execution from accidentally
    removing a *newer* holder registered by a different command.
    """
    if exec_id is not None:
        holder = _active_executions.get(session_id)
        if holder and holder.get("exec_id") != exec_id:
            return  # Not our holder — leave it alone
    _active_executions.pop(session_id, None)


async def abort_trigger_execution(session_id: str) -> bool:
    """
    Cancel a running trigger execution so a higher-priority command
    (user message) can take over.

    Returns True if a trigger was successfully aborted, False otherwise.
    Only aborts executions tagged with ``is_trigger=True``.
    """
    holder = _active_executions.get(session_id)
    if not holder or holder.get("done", True):
        return False
    if not holder.get("is_trigger", False):
        return False

    abort_exec_id = holder.get("exec_id")
    task = holder.get("task")
    if not task or task.done():
        # No cancellable task — just clean up
        cleanup_execution(session_id, exec_id=abort_exec_id)
        return True

    logger.info(
        "Aborting trigger execution for %s (elapsed=%.1fs)",
        session_id,
        time.time() - holder.get("start_time", time.time()),
    )

    task.cancel()
    try:
        await task  # wait for CancelledError handling in _execute_core
    except (asyncio.CancelledError, Exception):
        pass

    # Ensure cleanup (only our holder)
    cleanup_execution(session_id, exec_id=abort_exec_id)
    return True


async def stop_execution(session_id: str) -> bool:
    """
    Cancel any running execution for a session (trigger or user-initiated).

    Returns True if an execution was stopped. Used by broadcast cancel.
    """
    holder = _active_executions.get(session_id)
    if not holder or holder.get("done", True):
        return False

    stop_exec_id = holder.get("exec_id")
    task = holder.get("task")
    if not task or task.done():
        cleanup_execution(session_id, exec_id=stop_exec_id)
        return True

    logger.info(
        "Stopping execution for %s (elapsed=%.1fs)",
        session_id,
        time.time() - holder.get("start_time", time.time()),
    )

    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass

    cleanup_execution(session_id, exec_id=stop_exec_id)
    return True


# ============================================================================
# Internal helpers (lazy imports to avoid circular deps)
# ============================================================================

def _get_agent_manager():
    from service.langgraph import get_agent_session_manager
    return get_agent_session_manager()


def _get_session_logger(session_id: str, *, create_if_missing: bool = True):
    from service.logging.session_logger import get_session_logger
    return get_session_logger(session_id, create_if_missing=create_if_missing)


def _get_session_store():
    from service.claude_manager.session_store import get_session_store
    return get_session_store()


# ============================================================================
# Resolve & revive agent
# ============================================================================

async def _resolve_agent(session_id: str):
    """
    Look up the agent, auto-revive if its process died.

    Returns the live AgentSession.
    Raises AgentNotFoundError / AgentNotAliveError on failure.
    """
    agent_manager = _get_agent_manager()
    agent = agent_manager.get_agent(session_id)
    if not agent:
        raise AgentNotFoundError(f"AgentSession not found: {session_id}")

    if not agent.is_alive():
        logger.info("[%s] Process not alive — attempting auto-revival", session_id)
        try:
            revived = await agent.revive()
            if revived:
                logger.info("[%s] ✅ Auto-revival successful", session_id)
                if agent.process:
                    agent_manager._local_processes[session_id] = agent.process
            else:
                raise AgentNotAliveError(
                    f"AgentSession is not running and revival failed (status: {agent.status})"
                )
        except AgentNotAliveError:
            raise
        except Exception as e:
            raise AgentNotAliveError(f"AgentSession revival error: {e}")

    return agent


# ============================================================================
# Core execution logic (shared by sync & async paths)
# ============================================================================

async def _execute_core(
    agent,
    session_id: str,
    prompt: str,
    holder: dict,
    *,
    timeout: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_turns: Optional[int] = None,
    **invoke_kwargs,
) -> ExecutionResult:
    """
    Run the full execution lifecycle once.

    1. Log command    →  session_logger.log_command
    2. Invoke agent   →  agent.invoke (with timeout)
    3. Log response   →  session_logger.log_response
    4. Persist cost   →  session_store.increment_cost

    Caller is responsible for registering/cleaning *holder* in
    ``_active_executions``.

    Extra ``invoke_kwargs`` are forwarded to ``agent.invoke()`` — e.g.
    ``is_chat_message=True`` for broadcast context.
    """
    session_logger = _get_session_logger(session_id, create_if_missing=True)
    start_time = holder["start_time"]

    # env_id / role metadata threaded into every per-turn log entry.
    # Resolved once up front so every log_command / log_response call
    # below can pass identical values, keeping the log coherent across
    # the command/response/error branches.
    log_env_id = getattr(agent, "env_id", None)
    _role = getattr(agent, "role", None)
    log_role = _role.value if _role is not None and hasattr(_role, "value") else _role

    try:
        # 1. Log command
        logger.info(
            "[Executor:%s] _execute_core: prompt=%s, timeout=%s, max_turns=%s",
            session_id[:8], prompt[:80], timeout, max_turns,
        )
        if session_logger:
            session_logger.log_command(
                prompt=prompt,
                timeout=timeout,
                system_prompt=system_prompt,
                max_turns=max_turns,
                env_id=log_env_id,
                role=log_role,
            )
            # Receiver-side delegation marker: if the incoming prompt is
            # a tagged delegation message, record a matching
            # delegation.received event so LogsTab can pair it with the
            # sender's delegation.sent entry.
            try:
                from service.vtuber.delegation import parse_delegation_headers

                headers = parse_delegation_headers(prompt)
                if headers is not None:
                    session_logger.log_delegation_event(
                        "delegation.received",
                        {
                            "tag": headers.get("tag"),
                            "from_session_id": headers.get("from_session_id"),
                            "to_session_id": session_id,
                            "task_id": headers.get("task_id"),
                            "to_role": log_role,
                        },
                    )
            except Exception:
                logger.debug(
                    "delegation.received emit failed for %s", session_id, exc_info=True,
                )

        # 2. Invoke
        effective_timeout = timeout or getattr(agent, "timeout", 21600.0)
        logger.info(
            "[Executor:%s] invoking agent (effective_timeout=%s, agent_type=%s)",
            session_id[:8], effective_timeout, type(agent).__name__,
        )
        invoke_result = await asyncio.wait_for(
            agent.invoke(input_text=prompt, **invoke_kwargs),
            timeout=effective_timeout,
        )

        result_text = (
            invoke_result.get("output", "")
            if isinstance(invoke_result, dict)
            else str(invoke_result)
        )
        result_cost = (
            invoke_result.get("total_cost", 0.0)
            if isinstance(invoke_result, dict)
            else None
        )
        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "[Executor:%s] invoke returned: output_len=%d, cost=%s, duration=%dms",
            session_id[:8], len(result_text), result_cost, duration_ms,
        )

        # 3. Log response
        if session_logger:
            session_logger.log_response(
                success=True,
                output=result_text,
                duration_ms=duration_ms,
                cost_usd=result_cost,
                env_id=log_env_id,
                role=log_role,
            )

        # 4. Persist cost
        if result_cost and result_cost > 0:
            try:
                _get_session_store().increment_cost(session_id, result_cost)
            except Exception:
                logger.debug("Cost persistence failed for %s", session_id, exc_info=True)

        result = ExecutionResult(
            success=True,
            session_id=session_id,
            output=result_text,
            duration_ms=duration_ms,
            cost_usd=result_cost,
        )
        holder["result"] = result.to_dict()
        return result

    except asyncio.TimeoutError:
        duration_ms = int((time.time() - start_time) * 1000)
        error_msg = f"Timeout after {duration_ms / 1000:.1f}s"
        logger.warning("Execution timeout for %s (%dms)", session_id, duration_ms)
        if session_logger:
            session_logger.log_response(
                success=False, error=error_msg, duration_ms=duration_ms,
                env_id=log_env_id, role=log_role,
            )
        result = ExecutionResult(
            success=False,
            session_id=session_id,
            error=error_msg,
            duration_ms=duration_ms,
        )
        holder["error"] = error_msg
        holder["result"] = result.to_dict()
        return result

    except asyncio.CancelledError:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.warning("Execution cancelled for %s", session_id)
        result = ExecutionResult(
            success=False,
            session_id=session_id,
            error="Execution cancelled",
            duration_ms=duration_ms,
        )
        holder["error"] = "Execution cancelled"
        holder["result"] = result.to_dict()
        return result

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error("❌ Execution failed for %s: %s", session_id, e, exc_info=True)
        if session_logger:
            session_logger.log_response(
                success=False, error=str(e), duration_ms=duration_ms,
                env_id=log_env_id, role=log_role,
            )
        result = ExecutionResult(
            success=False,
            session_id=session_id,
            error=str(e),
            duration_ms=duration_ms,
        )
        holder["error"] = str(e)
        holder["result"] = result.to_dict()
        return result

    finally:
        holder["done"] = True


# ============================================================================
# Public API — synchronous (await) execution
# ============================================================================

async def execute_command(
    session_id: str,
    prompt: str,
    *,
    timeout: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_turns: Optional[int] = None,
    is_trigger: bool = False,
    **invoke_kwargs,
) -> ExecutionResult:
    """
    Execute a command synchronously (blocking until completion).

    Used by:
      - ``POST /api/agents/{id}/execute``   (command tab, synchronous)
      - Messenger ``_run_broadcast``         (each agent in the room)
      - Thinking trigger service             (is_trigger=True)

    When *is_trigger* is True the execution is tagged as preemptible:
    a subsequent user-initiated ``execute_command`` will automatically
    cancel this trigger before proceeding.

    Extra ``invoke_kwargs`` are forwarded to ``agent.invoke()`` — e.g.
    ``is_chat_message=True`` for broadcast context.

    Raises:
      AgentNotFoundError    – session does not exist
      AgentNotAliveError    – process dead, revival failed
      AlreadyExecutingError – another command is already running
    """
    logger.info(
        "[Executor:%s] execute_command called: prompt=%s, is_trigger=%s, kwargs=%s",
        session_id[:8], prompt[:80], is_trigger, list(invoke_kwargs.keys()),
    )

    # 1. Resolve & revive
    agent = await _resolve_agent(session_id)
    logger.debug("[Executor:%s] agent resolved, alive=%s", session_id[:8], agent.is_alive())

    # 1b. Record activity for VTuber thinking trigger
    #     Skip for trigger executions (would break adaptive backoff)
    if not is_trigger and getattr(agent, '_session_type', None) == 'vtuber':
        try:
            from service.vtuber.thinking_trigger import get_thinking_trigger_service
            get_thinking_trigger_service().record_activity(session_id)
        except Exception:
            pass  # best-effort

    # 2. Double-execution guard — with trigger preemption
    if is_executing(session_id):
        if not is_trigger and is_trigger_executing(session_id):
            # User message takes priority over trigger — abort the trigger
            logger.info(
                "[Executor:%s] preempting trigger for user message",
                session_id[:8],
            )
            aborted = await abort_trigger_execution(session_id)
            if not aborted:
                logger.warning("[Executor:%s] trigger preemption failed", session_id[:8])
                raise AlreadyExecutingError(
                    f"Execution already in progress for session {session_id}"
                )
            # Small yield to let cleanup propagate
            await asyncio.sleep(0)
        else:
            logger.warning(
                "[Executor:%s] already executing (is_trigger=%s, current_is_trigger=%s)",
                session_id[:8], is_trigger, is_trigger_executing(session_id),
            )
            raise AlreadyExecutingError(
                f"Execution already in progress for session {session_id}"
            )

    # 3. Register
    session_logger = _get_session_logger(session_id, create_if_missing=True)
    exec_id = uuid.uuid4().hex
    cache_cursor = session_logger.get_cache_length() if session_logger else 0
    holder: dict = {
        "done": False,
        "result": None,
        "error": None,
        "start_time": time.time(),
        "cache_cursor": cache_cursor,
        "is_trigger": is_trigger,
        "task": None,
        "exec_id": exec_id,
    }
    _active_executions[session_id] = holder
    logger.info(
        "[Executor:%s] holder registered: exec_id=%s, cache_cursor=%d",
        session_id[:8], exec_id[:8], cache_cursor,
    )

    # 4. Execute (blocking)
    try:
        # Notify linked VTuber that Sub-Worker is working (best-effort)
        await _notify_vtuber_sub_worker_progress(session_id, "executing")

        exec_task = asyncio.create_task(
            _execute_core(
                agent, session_id, prompt, holder,
                timeout=timeout,
                system_prompt=system_prompt,
                max_turns=max_turns,
                **invoke_kwargs,
            )
        )
        holder["task"] = exec_task

        result = await exec_task

        # 5. Emit avatar state (best-effort, never raises)
        await _emit_avatar_state(session_id, result)
        # 6. Notify linked VTuber if this is a Sub-Worker (best-effort)
        await _notify_linked_vtuber(session_id, result)

        return result
    except asyncio.CancelledError:
        # This execution was preempted by a higher-priority command
        duration_ms = int((time.time() - holder["start_time"]) * 1000)
        logger.info(
            "Execution preempted for %s (is_trigger=%s, %dms)",
            session_id, is_trigger, duration_ms,
        )
        return ExecutionResult(
            success=False,
            session_id=session_id,
            error="Preempted by user message",
            duration_ms=duration_ms,
        )
    finally:
        # Cleanup — only remove our own holder (exec_id guard prevents
        # accidentally removing a newer execution's holder).
        cleanup_execution(session_id, exec_id=exec_id)

        # 7. Post-execution inbox drain (fire-and-forget, best-effort)
        #    Only for non-trigger, non-drain executions to avoid recursion.
        if not is_trigger and session_id not in _draining_sessions:
            asyncio.create_task(_drain_inbox(session_id))


# ============================================================================
# Post-execution inbox drain
# ============================================================================

async def _drain_inbox(session_id: str) -> None:
    """
    After an execution completes, consume unread inbox messages one at a
    time and feed them back through ``execute_command``. Messages are
    marked read at pull time (consumed-on-pull), so a deterministic
    processing failure cannot loop — the message is lost but the drain
    does not spin.

    Ordering: each pull + synthesised turn runs serially under the
    ``_draining_sessions`` guard. The existing ``AlreadyExecutingError``
    is the backstop against concurrent execution (the winning caller's
    own finally block will re-invoke this drain).
    """
    if session_id in _draining_sessions:
        return

    try:
        from service.chat.inbox import get_inbox_manager
    except Exception:
        logger.debug("Inbox import failed for %s drain", session_id, exc_info=True)
        return

    inbox = get_inbox_manager()
    _draining_sessions.add(session_id)
    try:
        while True:
            try:
                pulled = inbox.pull_unread(session_id, limit=1)
            except Exception:
                logger.debug(
                    "Inbox pull failed for %s", session_id, exc_info=True,
                )
                return
            if not pulled:
                return
            msg = pulled[0]

            sender = msg.get("sender_name") or "Unknown"
            prompt = f"[INBOX from {sender}]\n{msg['content']}"
            logger.info(
                "Draining inbox msg %s for %s (sender=%s)",
                msg.get("id"), session_id, sender,
            )

            try:
                result = await execute_command(session_id, prompt)
            except AlreadyExecutingError:
                # A concurrent execution took the slot. Its finally
                # block will re-trigger drain; bail to avoid racing.
                logger.debug(
                    "Drain for %s yielded to concurrent execution",
                    session_id,
                )
                return
            except Exception:
                logger.debug(
                    "Drained execute_command failed for %s",
                    session_id, exc_info=True,
                )
                # Message already consumed — skip to next one.
                continue

            if result.success and result.output and result.output.strip():
                _save_drain_to_chat_room(session_id, result)
    finally:
        _draining_sessions.discard(session_id)


def _save_subworker_reply_to_chat_room(
    vtuber_session_id: str,
    result: 'ExecutionResult',
) -> None:
    """Post the VTuber's reply to the user's chat room.

    Mirrors :func:`_save_drain_to_chat_room` /
    :meth:`ThinkingTriggerService._save_to_chat_room` for the
    Sub-Worker → VTuber auto-report pathway. Without this the VTuber's
    response to ``[SUB_WORKER_RESULT]`` is generated (and even costed)
    but never reaches the panel the user is watching — cycle 20260420_8
    Bug 2a.

    Best-effort: never raises. Noop when the VTuber has no
    ``_chat_room_id`` (solo session, pre-binding state, etc.) or when
    the VTuber produced no meaningful output (empty string, failure).
    """
    try:
        if not result.success or not result.output or not result.output.strip():
            return

        agent = _get_agent_manager().get_agent(vtuber_session_id)
        if agent is None:
            return

        chat_room_id = getattr(agent, '_chat_room_id', None)
        if not chat_room_id:
            logger.debug(
                "VTuber %s has no _chat_room_id; skipping sub-worker reply broadcast",
                vtuber_session_id,
            )
            return

        from service.chat.conversation_store import get_chat_store
        store = get_chat_store()

        session_name = getattr(agent, '_session_name', None) or vtuber_session_id
        role_val = getattr(agent, '_role', None)
        role = role_val.value if hasattr(role_val, 'value') else str(role_val or 'vtuber')

        msg = store.add_message(chat_room_id, {
            "type": "agent",
            "content": result.output.strip(),
            "session_id": vtuber_session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "source": "sub_worker_reply",
        })

        logger.info(
            "[SubWorkerReply] Posted VTuber response to chat room %s "
            "(msg_id=%s, len=%d)",
            chat_room_id, msg.get("id", "?"), len(result.output),
        )

        try:
            from controller.chat_controller import _notify_room
            _notify_room(chat_room_id)
        except Exception:
            logger.warning(
                "[SubWorkerReply] _notify_room failed for %s",
                chat_room_id, exc_info=True,
            )
    except Exception:
        logger.warning(
            "[SubWorkerReply] Failed to post VTuber reply to chat room",
            exc_info=True,
        )


def _save_drain_to_chat_room(session_id: str, result: 'ExecutionResult') -> None:
    """
    Save an inbox-drain execution result to the session's chat room.
    Similar to ThinkingTriggerService._save_to_chat_room but usable
    from agent_executor without circular dependency.
    """
    try:
        agent_manager = _get_agent_manager()
        agent = agent_manager.get_agent(session_id)
        if not agent:
            return

        chat_room_id = getattr(agent, '_chat_room_id', None)
        if not chat_room_id:
            return

        from service.chat.conversation_store import get_chat_store
        store = get_chat_store()

        session_name = getattr(agent, '_session_name', None) or session_id
        role_val = getattr(agent, '_role', None)
        role = role_val.value if hasattr(role_val, 'value') else str(role_val or 'worker')

        store.add_message(chat_room_id, {
            "type": "agent",
            "content": result.output.strip(),
            "session_id": session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
        })

        # Notify SSE listeners
        try:
            from controller.chat_controller import _notify_room
            _notify_room(chat_room_id)
        except Exception:
            pass

        logger.info(
            "Inbox drain result saved to chat room %s (len=%d)",
            chat_room_id, len(result.output),
        )
    except Exception:
        logger.debug("Failed to save drain result to chat room", exc_info=True)


# ============================================================================
# Public API — background execution (non-blocking, returns holder)
# ============================================================================

async def start_command_background(
    session_id: str,
    prompt: str,
    *,
    timeout: Optional[float] = None,
    system_prompt: Optional[str] = None,
    max_turns: Optional[int] = None,
) -> dict:
    """
    Start command execution in the background.  Returns the *holder*
    dict immediately.

    Used by:
      - ``POST /api/agents/{id}/execute/start``  (two-step SSE)
      - ``POST /api/agents/{id}/execute/stream``  (single SSE)

    The SSE streaming loop in the controller polls
    ``holder["done"]`` and ``session_logger.get_cache_entries_since()``
    to stream real-time log events.

    The caller is responsible for calling ``cleanup_execution()``
    when the SSE stream ends.

    Raises:
      AgentNotFoundError    – session does not exist
      AgentNotAliveError    – process dead, revival failed
      AlreadyExecutingError – another command is already running
    """
    logger.info(
        "[Executor:%s] start_command_background called: prompt=%s, timeout=%s",
        session_id[:8], prompt[:80], timeout,
    )

    # 1. Resolve & revive
    agent = await _resolve_agent(session_id)
    logger.debug("[Executor:%s] (bg) agent resolved, alive=%s", session_id[:8], agent.is_alive())

    # 1b. Record activity for VTuber thinking trigger
    if getattr(agent, '_session_type', None) == 'vtuber':
        try:
            from service.vtuber.thinking_trigger import get_thinking_trigger_service
            get_thinking_trigger_service().record_activity(session_id)
        except Exception:
            pass

    # 2. Double-execution guard — with trigger preemption
    if is_executing(session_id):
        if is_trigger_executing(session_id):
            logger.info("[Executor:%s] (bg) preempting trigger", session_id[:8])
            aborted = await abort_trigger_execution(session_id)
            if not aborted:
                logger.warning("[Executor:%s] (bg) trigger preemption failed", session_id[:8])
                raise AlreadyExecutingError(
                    f"Execution already in progress for session {session_id}"
                )
            await asyncio.sleep(0)
        else:
            logger.warning("[Executor:%s] (bg) already executing", session_id[:8])
            raise AlreadyExecutingError(
                f"Execution already in progress for session {session_id}"
            )

    # 3. Register
    session_logger = _get_session_logger(session_id, create_if_missing=True)
    exec_id = uuid.uuid4().hex
    cache_cursor = session_logger.get_cache_length() if session_logger else 0
    holder: dict = {
        "done": False,
        "result": None,
        "error": None,
        "start_time": time.time(),
        "cache_cursor": cache_cursor,
        "is_trigger": False,
        "task": None,
        "exec_id": exec_id,
    }
    _active_executions[session_id] = holder
    logger.info(
        "[Executor:%s] (bg) holder registered: exec_id=%s, cache_cursor=%d",
        session_id[:8], exec_id[:8], cache_cursor,
    )

    # 4. Fire-and-forget background task
    async def _run():
        try:
            result = await _execute_core(
                agent, session_id, prompt, holder,
                timeout=timeout,
                system_prompt=system_prompt,
                max_turns=max_turns,
            )
            # Emit avatar state (best-effort)
            await _emit_avatar_state(session_id, result)
            # Notify linked VTuber if this is a Sub-Worker (best-effort)
            await _notify_linked_vtuber(session_id, result)
        finally:
            # Schedule deferred cleanup: keep the holder alive for a grace
            # period so a reconnecting frontend can pick up the final result,
            # then remove it to prevent memory leaks.
            async def _deferred_cleanup():
                from service.config.sub_config.general.chat_config import ChatConfig
                _chat_cfg = ChatConfig.get_default_instance()
                await asyncio.sleep(_chat_cfg.holder_grace_period_s)
                cleanup_execution(session_id, exec_id=exec_id)

            asyncio.create_task(_deferred_cleanup())

            # Post-execution inbox drain
            if session_id not in _draining_sessions:
                asyncio.create_task(_drain_inbox(session_id))

    asyncio.create_task(_run())
    return holder
