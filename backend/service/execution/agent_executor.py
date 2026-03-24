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

Both ``agent_controller`` (command tab) and ``chat_controller``
(messenger broadcast) delegate here.
"""

import asyncio
import time
from dataclasses import dataclass, asdict
from logging import getLogger
from typing import Any, Dict, Optional

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
# Centralised active-execution registry
# ============================================================================

_active_executions: Dict[str, dict] = {}
"""session_id → holder dict for every in-flight execution."""


def is_executing(session_id: str) -> bool:
    """Return True if *session_id* is currently running a command."""
    holder = _active_executions.get(session_id)
    return holder is not None and not holder.get("done", True)


def get_execution_holder(session_id: str) -> Optional[dict]:
    """Return the live holder dict, or None."""
    return _active_executions.get(session_id)


def cleanup_execution(session_id: str) -> None:
    """Remove the holder entry.  Safe to call even if missing."""
    _active_executions.pop(session_id, None)


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

    try:
        # 1. Log command
        if session_logger:
            session_logger.log_command(
                prompt=prompt,
                timeout=timeout,
                system_prompt=system_prompt,
                max_turns=max_turns,
            )

        # 2. Invoke
        effective_timeout = timeout or getattr(agent, "timeout", 21600.0)
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

        # 3. Log response
        if session_logger:
            session_logger.log_response(
                success=True,
                output=result_text,
                duration_ms=duration_ms,
                cost_usd=result_cost,
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
    **invoke_kwargs,
) -> ExecutionResult:
    """
    Execute a command synchronously (blocking until completion).

    Used by:
      - ``POST /api/agents/{id}/execute``   (command tab, synchronous)
      - Messenger ``_run_broadcast``         (each agent in the room)

    Extra ``invoke_kwargs`` are forwarded to ``agent.invoke()`` — e.g.
    ``is_chat_message=True`` for broadcast context.

    Raises:
      AgentNotFoundError    – session does not exist
      AgentNotAliveError    – process dead, revival failed
      AlreadyExecutingError – another command is already running
    """
    # 1. Resolve & revive
    agent = await _resolve_agent(session_id)

    # 2. Double-execution guard
    if is_executing(session_id):
        raise AlreadyExecutingError(
            f"Execution already in progress for session {session_id}"
        )

    # 3. Register
    session_logger = _get_session_logger(session_id, create_if_missing=True)
    holder: dict = {
        "done": False,
        "result": None,
        "error": None,
        "start_time": time.time(),
        "cache_cursor": session_logger.get_cache_length() if session_logger else 0,
    }
    _active_executions[session_id] = holder

    # 4. Execute (blocking)
    try:
        return await _execute_core(
            agent, session_id, prompt, holder,
            timeout=timeout,
            system_prompt=system_prompt,
            max_turns=max_turns,
            **invoke_kwargs,
        )
    finally:
        # Cleanup — holder is no longer needed for SSE streaming
        cleanup_execution(session_id)


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
    # 1. Resolve & revive
    agent = await _resolve_agent(session_id)

    # 2. Double-execution guard
    if is_executing(session_id):
        raise AlreadyExecutingError(
            f"Execution already in progress for session {session_id}"
        )

    # 3. Register
    session_logger = _get_session_logger(session_id, create_if_missing=True)
    holder: dict = {
        "done": False,
        "result": None,
        "error": None,
        "start_time": time.time(),
        "cache_cursor": session_logger.get_cache_length() if session_logger else 0,
    }
    _active_executions[session_id] = holder

    # 4. Fire-and-forget background task
    async def _run():
        try:
            await _execute_core(
                agent, session_id, prompt, holder,
                timeout=timeout,
                system_prompt=system_prompt,
                max_turns=max_turns,
            )
        finally:
            # Schedule deferred cleanup: keep the holder alive for a grace
            # period so a reconnecting frontend can pick up the final result,
            # then remove it to prevent memory leaks.
            async def _deferred_cleanup():
                await asyncio.sleep(300)  # 5 minutes
                cleanup_execution(session_id)

            asyncio.create_task(_deferred_cleanup())

    asyncio.create_task(_run())
    return holder
