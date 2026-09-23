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

import os
import asyncio
from service.utils.background import spawn_background
import re
import time
import uuid
from dataclasses import dataclass, asdict, field
from logging import getLogger
from typing import Any, Dict, List, Optional, Set

from service.logging.session_logger import LogLevel

logger = getLogger(__name__)

# Appended to a turn's prompt when the session's long-term-memory warm-up is
# still running past the bounded wait (see execute_command step 1a): partial
# retrieval must read as "still loading", never as "no record exists".
MEMORY_WARMUP_NOTICE = (
    "\n\n[system] 장기기억 워밍업이 아직 진행 중입니다. 기억 조회 결과가 비거나 얕더라도 "
    "'기록이 없다'고 단정하지 마세요 — memory_search로 재확인하거나, 잠시 뒤 다시 조회하면 "
    "전체 기억이 보입니다."
)


# ============================================================================
# Exceptions
# ============================================================================

class AgentNotFoundError(Exception):
    """Raised when the requested session does not exist."""


class AgentNotAliveError(Exception):
    """Raised when the session process is dead and revival failed."""


class AlreadyExecutingError(Exception):
    """Raised when a command is already running on this session."""


class SessionClosingError(AlreadyExecutingError):
    """Raised when a new turn is refused because the session is being torn
    down (DELETE drain). Subclasses ``AlreadyExecutingError`` so existing
    "busy, try later" handlers reject it the same way — the session will be
    gone shortly, so a new turn must not start."""


# ============================================================================
# Result model
# ============================================================================

@dataclass
class ExecutionResult:
    """Immutable result of a single command execution.

    ``tool_calls`` carries the per-turn tool execution log captured by
    :meth:`AgentSession._invoke_pipeline` from ``tool.call_start`` /
    ``tool.call_complete`` events. Each entry is
    ``{"name": str, "input": dict, "is_error": bool, "duration_ms": int}``.

    The list lets ``_notify_linked_vtuber`` build a meaningful
    ``[SUB_WORKER_RESULT]`` payload even when the LLM emitted no final
    text — typical for "tool-only" turns where the worker only called
    ``Write`` / ``Bash`` and skipped the chat reply. See
    ``dev_docs/20260430_1/analysis/01_subworker_dm_dual_dispatch.md``
    (R1, P0-2) for the rationale.
    """
    success: bool
    session_id: str
    output: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0
    cost_usd: Optional[float] = None
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    # Files the agent delivered to the user this turn via the SendUserFile
    # tool (workspace-canvas P1). ChatAttachment-shaped dicts (kind/name/
    # mime_type/size/url) — message writers copy this onto the chat
    # message's ``attachments`` field so the existing AttachmentList
    # renderer shows them inline.
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    # Structured executor error identifier (since executor 2.1.0).
    # ``"exec.cli.auth_failed"`` etc. — populated only when the
    # surfaced exception was a ``GenyExecutorError`` subclass. ``None``
    # otherwise. Surfaces verbatim in the SSE payload so the frontend
    # can render via i18n key (``executor.<code>``) instead of the raw
    # English ``error`` message.
    error_code: Optional[str] = None
    # Fully-qualified exception class name for cases where no
    # structured code is available — useful for Sentry / log grouping.
    exception_type: Optional[str] = None
    # ``output`` with its emotion cues still inline — ``[joy:0.6] 좋아!`` —
    # for the two consumers that act on them: the avatar's expression and
    # the voice's emotional reference. ``None`` when the turn had no cues,
    # in which case ``output`` is all there is to say.
    spoken: Optional[str] = None

    @property
    def spoken_text(self) -> Optional[str]:
        """What the avatar and TTS should read: the cued text, else the output."""
        return self.spoken or self.output

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


def get_app_state():
    """Return the FastAPI app.state set at startup, or ``None``.

    Lets lower-level builders (e.g. ``AgentSession._build_pipeline``) read
    boot-wired runtime handles — ``task_registry`` / ``task_runner`` /
    ``cron_store`` / ``cron_runner`` / ``subagent_orchestrator`` — to inject
    into the pipeline's ``ToolContext.extras`` so the executor's built-in
    Task/Cron/Agent tools function (audit 2026-06-18, GAP A/B)."""
    return _app_state


# ============================================================================
# Avatar state emission (called after every execution)
# ============================================================================

async def _load_mood_for_session(session_id: str):
    """Best-effort lookup of ``CreatureState.mood`` for this session.

    Returns ``None`` when:
      * the ``AgentSessionManager`` has no ``state_provider`` wired
        (classic, non-game mode),
      * the session isn't registered (background / unit-test call),
      * the agent has no ``character_id``, or
      * the provider raises for any reason.

    Never raises — the caller treats ``None`` as "no mood signal, fall
    back to text/agent_state extraction".
    """
    try:
        manager = _get_agent_manager()
        provider = getattr(manager, "state_provider", None)
        if provider is None:
            return None

        agent = manager.get_agent(session_id)
        character_id = getattr(agent, "character_id", None) if agent else None
        if not character_id:
            return None

        creature = await provider.load(character_id)
        return getattr(creature, "mood", None)
    except Exception:
        logger.debug("mood lookup failed for %s", session_id, exc_info=True)
        return None


async def _emit_avatar_state(session_id: str, result: 'ExecutionResult') -> None:
    """
    Emit avatar state update based on execution result.
    Called after _execute_core completes — ensures ALL execution paths
    (sync, async, chat broadcast) update the Live2D avatar.

    When a ``CreatureState`` is hydrated for this session, its
    ``MoodVector`` is passed into ``EmotionExtractor.resolve_emotion``
    so the facial signal reflects the accumulated mood rather than a
    keyword guess from the most recent reply (PR-X3-9).

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

        mood = await _load_mood_for_session(session_id)

        if result.success and result.spoken_text:
            # The cued text, not the display text: the display text has had
            # every ``[emotion]`` removed, and extracting from it is what left
            # the avatar on the mood fallback for every reply.
            emotion, index = extractor.resolve_emotion(
                result.spoken_text, "completed", mood=mood
            )
            await state_manager.update_state(
                session_id=session_id,
                emotion=emotion,
                expression_index=index,
                trigger="agent_output",
            )
        elif not result.success:
            # Error/timeout → set appropriate emotion
            agent_state = "timeout" if "Timeout" in (result.error or "") else "error"
            emotion, index = extractor.resolve_emotion(
                None, agent_state, mood=mood
            )
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

# Tool names whose `input` reliably carries a user-meaningful filesystem
# artifact (so we can list it under `artifacts:` in the synthesised
# `[SUB_WORKER_RESULT]` payload). Anything not in this map only
# contributes to the `Tools used: …` line.
_ARTIFACT_TOOL_KEYS: Dict[str, tuple] = {
    "Write": ("file_path", "path"),
    "Edit": ("file_path", "path"),
    "NotebookEdit": ("notebook_path", "file_path"),
    "MultiEdit": ("file_path", "path"),
}


# Cycle 20260430_1 P1-3 — pipeline-internal loop signals that are
# meaningful to the executor's stop / continue logic (see
# ``service/prompt/protocols.py``) but useless to the VTuber. A worker
# that ends a tool-only turn with nothing but `[TASK_COMPLETE]` should
# be treated as if it left no narration at all, so the synthesis path
# in ``_notify_linked_vtuber`` can do its job. The pattern is
# anchored to first/last so it only strips signals when they are the
# *only* content (we never alter intentional narration that happens
# to mention the marker word).
_LOOP_SIGNAL_PATTERN = re.compile(
    r"^\s*"
    r"(?:\[TASK_COMPLETE\]|\[BLOCKED(?::[^\]]*)?\]|\[CONTINUE(?::[^\]]*)?\])"
    r"\s*$",
)


def _strip_only_loop_signals(text: Optional[str]) -> Optional[str]:
    """Return ``text`` unchanged unless its entire content reduces to
    pipeline loop signals — in which case return ``None`` so callers
    can treat the turn as "no narration".
    """
    if not text:
        return text
    if _LOOP_SIGNAL_PATTERN.match(text.strip()):
        return None
    return text


# Cycle 20260430_2 A4 — categorisation buckets for SubWorkerRun payload.
# Same source data as the yaml-payload synthesis (P0-2), but materialised
# once into a structured dict so both the SUB_WORKER_RESULT compose path
# *and* the VTuber-side STM recorder (this PR) can read it without
# re-parsing tool_calls.

_FILES_READ_TOOLS = frozenset({"Read", "Glob", "Grep"})
_BASH_TOOLS = frozenset({"Bash"})
# Browser* = the an-web built-ins that replaced the custom web_fetch /
# browser_* tools (geny-executor 2.43 migration).
_WEB_TOOLS = frozenset(
    {"WebFetch", "WebSearch", "web_search", "news_search", "BrowserNavigate"}
)
_BASH_PREVIEW_CHARS = 200
_WEB_PREVIEW_CHARS = 200
_ERROR_PREVIEW_CHARS = 200


def _categorize_tool_calls(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bucket the per-turn tool log into user-meaningful categories.

    Returns a JSON-serialisable dict — the same one used as the
    ``payload`` field of the ``tool_run_summary`` InteractionEvent
    recorded on the VTuber's STM (cycle 20260430_2 A4) and as the
    structured source for ``_compose_subworker_payload_from_tools``
    (cycle 20260430_1 P0-2).

    The categorisation is intentionally narrow — only the buckets the
    VTuber persona can actually paraphrase to a non-technical user.
    Anything else lives in ``raw_tool_calls`` for debugging and
    detailed inspection.
    """
    files_written = _extract_artifacts(tool_calls)
    files_read: List[str] = []
    bash_commands: List[Dict[str, Any]] = []
    web_fetches: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    seen_files_read: set = set()

    for entry in tool_calls:
        name = entry.get("name") or "unknown"
        params = entry.get("input") or {}
        is_err = bool(entry.get("is_error"))
        duration = int(entry.get("duration_ms") or 0)

        if is_err:
            errors.append({
                "name": name,
                "duration_ms": duration,
                "input_preview": _stringify_input(params)[:_ERROR_PREVIEW_CHARS],
            })

        if name in _FILES_READ_TOOLS:
            path = (
                params.get("file_path")
                or params.get("path")
                or params.get("pattern")
                or ""
            )
            if isinstance(path, str) and path.strip():
                key = path.strip()
                if key not in seen_files_read:
                    seen_files_read.add(key)
                    files_read.append(key)
        elif name in _BASH_TOOLS:
            cmd = params.get("command", "")
            bash_commands.append({
                "command": (cmd[:_BASH_PREVIEW_CHARS] if isinstance(cmd, str) else ""),
                "ok": not is_err,
                "duration_ms": duration,
            })
        elif name in _WEB_TOOLS:
            target = (
                params.get("url")
                or params.get("query")
                or ""
            )
            web_fetches.append({
                "tool": name,
                "target": (target[:_WEB_PREVIEW_CHARS] if isinstance(target, str) else ""),
                "ok": not is_err,
                "duration_ms": duration,
            })

    total = len(tool_calls)
    n_errors = len(errors)
    if total == 0:
        status = "ok"  # vacuous; caller checks total before using
    elif n_errors == 0:
        status = "ok"
    elif n_errors == total:
        status = "failed"
    else:
        status = "partial"

    # Distinct tool names in encounter order — handy for one-line
    # summaries downstream.
    seen_names: set = set()
    tools_used: List[str] = []
    for entry in tool_calls:
        name = entry.get("name") or "unknown"
        if name in seen_names:
            continue
        seen_names.add(name)
        tools_used.append(name)

    return {
        "status": status,
        "tools_used": tools_used,
        "files_written": files_written,
        "files_read": files_read,
        "bash_commands": bash_commands,
        "web_fetches": web_fetches,
        "errors": errors,
        "total_calls": total,
        "ok_calls": total - n_errors,
        "failed_calls": n_errors,
    }


def _stringify_input(params: Dict[str, Any]) -> str:
    """Best-effort short stringification for input previews."""
    try:
        import json as _json
        return _json.dumps(params, ensure_ascii=False)[:400]
    except Exception:
        return str(params)[:400]


def _extract_artifacts(tool_calls: List[Dict[str, Any]]) -> List[str]:
    """Pull file-path artifacts out of completed tool calls.

    Only consults the whitelist in :data:`_ARTIFACT_TOOL_KEYS` —
    every other tool reports through ``Tools used:`` instead of
    inventing user-facing paths. Skips errored calls so a failed Write
    doesn't end up looking like a successful artifact.
    """
    artifacts: List[str] = []
    for entry in tool_calls:
        if entry.get("is_error"):
            continue
        keys = _ARTIFACT_TOOL_KEYS.get(entry.get("name", ""))
        if not keys:
            continue
        params = entry.get("input") or {}
        for key in keys:
            value = params.get(key)
            if isinstance(value, str) and value.strip():
                artifacts.append(value.strip())
                break
    # Deduplicate while preserving order — the worker may have edited
    # the same file twice.
    seen: set = set()
    deduped: List[str] = []
    for a in artifacts:
        if a in seen:
            continue
        seen.add(a)
        deduped.append(a)
    return deduped


def _compose_subworker_payload_from_tools(
    result: 'ExecutionResult',
) -> Optional[str]:
    """Build a worker.md-shaped ``[SUB_WORKER_RESULT]`` payload from
    :attr:`ExecutionResult.tool_calls` when the LLM left no final text.

    Returns ``None`` when there is nothing to summarise (no tool calls
    at all) — the caller should treat that as "no notification" rather
    than emitting a meaningless "Task finished with no output." line.
    See ``dev_docs/20260430_1/analysis/01_subworker_dm_dual_dispatch.md``
    (P0-2 / P0-3).
    """
    tool_calls = list(getattr(result, "tool_calls", None) or [])
    if not tool_calls:
        return None

    total = len(tool_calls)
    errors = sum(1 for t in tool_calls if t.get("is_error"))
    ok = total - errors

    if errors == 0:
        status = "ok"
    elif errors == total:
        status = "failed"
    else:
        status = "partial"

    # Distinct tool names in encounter order
    seen_names: set = set()
    name_order: List[str] = []
    for entry in tool_calls:
        name = entry.get("name") or "unknown"
        if name in seen_names:
            continue
        seen_names.add(name)
        name_order.append(name)
    tools_line = ", ".join(name_order) if name_order else "—"

    if status == "ok":
        if total == 1:
            summary = f"Completed using {tools_line} ({ok} tool call)."
        else:
            summary = f"Completed using {tools_line} ({ok} tool calls)."
    elif status == "failed":
        summary = (
            f"Could not complete the task — every tool call failed "
            f"({errors}/{total})."
        )
    else:
        summary = (
            f"Partial — {ok} tool call(s) succeeded, {errors} failed "
            f"using {tools_line}."
        )

    artifacts = _extract_artifacts(tool_calls)

    details_lines: List[str] = [
        f"Tools used: {tools_line}",
        f"Total calls: {total} ({ok} ok, {errors} failed)",
    ]

    payload_lines = [
        "[SUB_WORKER_RESULT]",
        f"status: {status}",
        f"summary: {summary}",
        "details: |",
    ]
    for line in details_lines:
        payload_lines.append(f"  {line}")
    if artifacts:
        payload_lines.append("artifacts:")
        for art in artifacts:
            payload_lines.append(f"  - {art}")
    else:
        payload_lines.append("artifacts: []")

    return "\n".join(payload_lines)


def _find_linked_task_request_event_id(
    vtuber_memory_manager,
    sub_session_id: str,
) -> Optional[str]:
    """Cycle 20260430_2 A4 — best-effort linkage from a fresh
    ``tool_run_summary`` back to its originating ``task_request`` on
    the VTuber side. Scans the VTuber's recent STM tail (last 20
    entries) for the most recent task_request whose counterpart_id
    matches the Sub-Worker's session_id.

    Returns ``None`` when no link is found — that's fine; the
    InteractionEvent without ``linked_event_id`` is still a valid
    record, just without the parent pointer.
    """
    try:
        stm = getattr(vtuber_memory_manager, "short_term", None)
        if stm is None:
            return None
        entries = stm.get_recent(20) or []
    except Exception:
        return None

    for entry in reversed(entries):
        meta = getattr(entry, "metadata", None) or {}
        if (
            meta.get("kind") == "task_request"
            and meta.get("counterpart_id") == sub_session_id
        ):
            event_id = meta.get("event_id")
            if event_id:
                return str(event_id)
    return None


def _build_subworker_run_event_metadata(
    *,
    sub_session_id: str,
    result: 'ExecutionResult',
    vtuber_memory: Any,
) -> Optional[Dict[str, Any]]:
    """Cycle 20260501_1 D — assemble the canonical InteractionEvent
    metadata for the upcoming TASK_RESULT entry on the VTuber's STM.

    This used to be the body of ``_record_subworker_run_on_vtuber``,
    which wrote *directly* into VTuber STM as a side-channel — the
    audit (`dev_docs/20260501_1/analysis/01_memory_circuit_audit.md`
    §6) flagged that as a cross-session direct write. Cycle 20260501_1
    consolidates the write site to s18 via ``GenyDedupeStrategy``
    (Stage C), so this helper now just *prepares the metadata*. The
    actual record_message call happens when the VTuber's invoke
    triggered by ``_notify_linked_vtuber`` reaches s18.

    Returns ``None`` when the run is genuinely empty (no tool calls,
    no meaningful text, no error) — caller treats that as "no
    metadata to thread through" and falls through to the parser.
    """
    try:
        tool_calls = list(getattr(result, "tool_calls", None) or [])
        meaningful_text = _strip_only_loop_signals(result.output) if result.success else None
        has_meaningful_text = bool(meaningful_text and meaningful_text.strip())
        has_error = bool(result.error)

        if not tool_calls and not has_meaningful_text and not has_error:
            return None

        categorised = _categorize_tool_calls(tool_calls) if tool_calls else {
            "status": "failed" if has_error else ("ok" if has_meaningful_text else "ok"),
            "tools_used": [],
            "files_written": [],
            "files_read": [],
            "bash_commands": [],
            "web_fetches": [],
            "errors": [],
            "total_calls": 0,
            "ok_calls": 0,
            "failed_calls": 0,
        }
        if has_error and tool_calls:
            categorised = dict(categorised)
            categorised["status"] = "failed"

        payload = {
            **categorised,
            "duration_ms": int(result.duration_ms or 0),
            "cost_usd": result.cost_usd,
            "raw_tool_calls": tool_calls,
        }
        if has_error:
            payload["error"] = (result.error or "")[: _ERROR_PREVIEW_CHARS * 2]

        from service.memory.interaction_event import (
            CounterpartRole,
            Direction,
            Kind,
            make_event_metadata,
        )
        linked: Optional[str] = None
        if vtuber_memory is not None:
            linked = _find_linked_task_request_event_id(vtuber_memory, sub_session_id)
        return make_event_metadata(
            kind=Kind.TOOL_RUN_SUMMARY,
            direction=Direction.IN,
            counterpart_id=sub_session_id,
            counterpart_role=CounterpartRole.PAIRED_SUBWORKER,
            linked_event_id=linked,
            payload=payload,
        )
    except Exception:
        logger.debug(
            "Failed to build subworker_run InteractionEvent metadata for %s",
            sub_session_id, exc_info=True,
        )
        return None


#: Active command executions, keyed by session id (the in-flight holder dict).
_active_executions: Dict[str, dict] = {}

#: Per-session lock serializing the execute_command admission critical section
#: (double-exec guard → trigger preempt → holder register → task create). Without
#: it, two concurrent execute_command calls could both pass the is_executing()
#: check across an await (revive/rehydrate) and clobber each other's holder,
#: running two turns on one shared pipeline (integrity audit 2026-06-25). Only the
#: brief admission section is held — NOT the turn itself — so in-turn tool calls
#: (the MCP bridge) never contend with it (avoids the prior hot-path deadlock).
_exec_locks: Dict[str, asyncio.Lock] = {}

#: Sessions currently draining their inbox — re-entry guard for ``_drain_inbox``.
_draining_sessions: Set[str] = set()

#: Sessions being torn down (DELETE / teardown drain). While a session id is
#: in this set the admission critical section refuses NEW turns
#: (``SessionClosingError``), so a delete can quiesce the session — wait for
#: the in-flight turn to finish, or gracefully cancel it — and then tear the
#: pipeline down without a new turn slipping in behind the drain.
_closing_sessions: Set[str] = set()


def mark_session_closing(session_id: str) -> None:
    """Gate new turns for *session_id* (teardown in progress)."""
    _closing_sessions.add(session_id)


def clear_session_closing(session_id: str) -> None:
    """Re-open *session_id* for turns (teardown aborted, or a fresh restore)."""
    _closing_sessions.discard(session_id)


async def close_session_execution(
    session_id: str, *, drain_timeout: float = 30.0, cancel_timeout: float = 10.0
) -> bool:
    """Quiesce a session for teardown, robustly.

    1. Gate new turns (``_closing_sessions``) so nothing new starts.
    2. Synchronise with any in-flight *admission* by taking the admission
       lock once — after that, a racing admission has either registered its
       holder (drained below) or seen the gate and bailed.
    3. Wait up to ``drain_timeout`` for the in-flight turn to finish on its
       own (shielded, so our wait never cancels it mid-step).
    4. If it is still running, gracefully ``cancel()`` the turn task and wait
       for it — the turn's own ``finally`` runs (``cleanup_execution`` + its
       per-turn resource release), so we NEVER tear the pipeline down under a
       live turn.

    Returns True once the session is idle (safe to ``cleanup()``); False only
    if a turn is somehow still registered after a cancel (abnormal). The gate
    stays set — the caller clears it (``clear_session_closing``) if it decides
    NOT to tear down.
    """
    _closing_sessions.add(session_id)
    async with _get_exec_lock(session_id):
        holder = _active_executions.get(session_id)
    if holder is None or holder.get("done", True):
        return True
    task = holder.get("task")
    if task is None or task.done():
        return not is_executing(session_id)

    # 3. Wait for natural completion.
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=drain_timeout)
        return True
    except asyncio.TimeoutError:
        pass
    except Exception:  # noqa: BLE001 — the turn raised: it is DONE, that's fine
        return True

    # 4. Still running past the window — cancel gracefully, let its finally run.
    logger.warning(
        "[Executor:%s] teardown drain exceeded %ss; cancelling in-flight turn",
        session_id[:8], drain_timeout,
    )
    task.cancel()
    try:
        await asyncio.wait_for(task, timeout=cancel_timeout)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    except Exception:  # noqa: BLE001
        pass
    return not is_executing(session_id)


def _get_exec_lock(session_id: str) -> asyncio.Lock:
    """Get-or-create the admission lock for *session_id* (atomic in asyncio:
    no await between get and store, so concurrent callers see the same lock)."""
    lock = _exec_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _exec_locks[session_id] = lock
    return lock


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


def forget_session(session_id: str) -> None:
    """Drop every per-session entry this module keeps, on permanent delete.

    These registries are keyed by session id and nothing removed a deleted
    session's row, so entries outlived the sessions they described — small in
    bytes, but a registry that only ever grows is a leak regardless of rate.

    The admission lock is dropped ONLY when it is currently unlocked. Removing
    a held lock would be worse than leaking it: the next caller would create a
    fresh lock, and two turns would enter a critical section designed for one.
    A held lock at delete time means the drain above did not finish, so we
    keep it and accept the entry.
    """
    _active_executions.pop(session_id, None)
    _draining_sessions.discard(session_id)
    _closing_sessions.discard(session_id)
    lock = _exec_locks.get(session_id)
    if lock is not None and not lock.locked():
        _exec_locks.pop(session_id, None)


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
    from service.executor import get_agent_session_manager
    return get_agent_session_manager()


#: A turn that has recorded NOTHING for this long is wedged, not slow.
#: Every real turn writes to the session log continuously — stage entries,
#: tool calls, streamed deltas — so silence is the signal. Generous enough
#: that a single long tool call (a big build, a slow HTTP fetch) does not
#: trip it; short enough that a user is not left watching a spinner.
_STALL_TIMEOUT_S = float(os.getenv("GENY_TURN_STALL_TIMEOUT_S", "300"))
_STALL_POLL_S = 5.0

#: Only these count as THIS TURN making progress. The first version watched
#: the session's total write count, which background work — memory
#: compaction, trigger bookkeeping — keeps nudging forever: a turn whose CLI
#: had died sat "progressing" for ten minutes while nothing about it moved.
_TURN_PROGRESS_LEVELS = frozenset({
    LogLevel.STAGE, LogLevel.GRAPH, LogLevel.TOOL_USE,
    LogLevel.RESPONSE, LogLevel.ERROR,
})

#: Ceiling for an INTERACTIVE turn when the caller named no timeout. The
#: session default is 1800s, which is a runaway-guard for a batch job, not a
#: budget for a reply someone is waiting on — measured healthy turns here run
#: 9-17 s. Autonomous triggers already pass their own 180 s.
_INTERACTIVE_TIMEOUT_S = float(os.getenv("GENY_TURN_MAX_SECONDS", "600"))


async def _invoke_bounded(
    agent,
    *,
    prompt: str,
    invoke_kwargs: Dict[str, Any],
    total_timeout: float,
    session_logger,
    session_id: str,
):
    """Run one turn under TWO limits: a hard ceiling and a no-progress stall.

    The ceiling alone is not a safety net at a conversation's timescale. The
    session default is 1800s, so a wedged turn sat there for 29 minutes with
    the user watching a spinner before anything gave up — which is exactly
    what a stuck subprocess, a wedged lock or a lost child process looks
    like from here.

    The stall guard makes the two cases distinguishable. A turn doing real
    work writes to the session log the whole time (stage transitions, tool
    calls, streamed deltas), and ``get_cache_length()`` is a monotonic count
    of those writes. No writes for ``_STALL_TIMEOUT_S`` means no progress,
    whatever the ceiling still allows.

    Raises ``asyncio.TimeoutError`` for either limit, so the caller's
    existing timeout handling covers both.
    """
    cursor = {"at": 0}
    seen = {"n": 0}

    def _progress() -> int:
        """How many entries THIS turn has produced.

        Filtered by level on purpose: the session log is shared, and counting
        every write meant background memory work kept a dead turn looking
        alive.
        """
        if session_logger is None:
            return -1
        try:
            entries, cursor["at"] = session_logger.get_cache_entries_since(
                cursor["at"])
        except Exception:  # noqa: BLE001 — a probe must never fail the turn
            return -1
        for entry in entries:
            level = getattr(entry, "level", None)
            if level in _TURN_PROGRESS_LEVELS:
                seen["n"] += 1
        return seen["n"]

    try:
        cursor["at"] = int(session_logger.get_cache_length()) if session_logger else 0
    except Exception:  # noqa: BLE001
        cursor["at"] = 0
    task = asyncio.ensure_future(agent.invoke(input_text=prompt, **invoke_kwargs))
    started = time.monotonic()
    last_progress = _progress()
    last_moved = started

    try:
        while True:
            remaining_total = total_timeout - (time.monotonic() - started)
            if remaining_total <= 0:
                logger.warning(
                    "[Executor:%s] turn hit the %.0fs ceiling", session_id[:8],
                    total_timeout,
                )
                raise asyncio.TimeoutError
            try:
                return await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=min(_STALL_POLL_S, remaining_total),
                )
            except asyncio.TimeoutError:
                pass  # still running — that is what we are here to check

            now = time.monotonic()
            current = _progress()
            if current != last_progress:
                last_progress, last_moved = current, now
                continue
            if current < 0:
                # No usable progress signal (no logger). The ceiling is all
                # we have; do not invent a stall.
                continue
            if now - last_moved >= _STALL_TIMEOUT_S:
                logger.warning(
                    "[Executor:%s] no progress for %.0fs (log cursor stuck at "
                    "%d, %.0fs into a %.0fs budget) — abandoning the turn",
                    session_id[:8], now - last_moved, current,
                    now - started, total_timeout,
                )
                raise asyncio.TimeoutError
    finally:
        if not task.done():
            task.cancel()
            # Give it a moment to unwind (its `finally` releases the
            # execution holder); never let cleanup outlive the turn.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception:  # noqa: BLE001 — the turn's own error, already handled
                pass


def _get_session_logger(session_id: str, *, create_if_missing: bool = True):
    from service.logging.session_logger import get_session_logger
    return get_session_logger(session_id, create_if_missing=create_if_missing)


def _get_session_store():
    from service.sessions.store import get_session_store
    return get_session_store()


# ============================================================================
# Resolve & revive agent
# ============================================================================

async def _resolve_agent(session_id: str):
    """
    Look up the agent, lazily re-hydrating a dormant (post-restart) session
    and auto-reviving a live-but-dead process.

    Returns the live AgentSession.
    Raises AgentNotFoundError / AgentNotAliveError on failure.
    """
    agent_manager = _get_agent_manager()
    # ensure_session_live re-hydrates a dormant session from the store (lazy
    # restore after redeploy/restart/crash) before we touch it; falls back to
    # the in-memory lookup when already live or unknown.
    agent = await agent_manager.ensure_session_live(session_id)
    if not agent:
        raise AgentNotFoundError(f"AgentSession not found: {session_id}")

    if not agent.is_alive():
        logger.info("[%s] Process not alive — attempting auto-revival", session_id)
        try:
            revived = await agent.revive()
            if revived:
                logger.info("[%s] ✅ Auto-revival successful", session_id)
                sl = _get_session_logger(session_id, create_if_missing=False)
                if sl is not None:
                    sl.log(
                        level=LogLevel.INFO,
                        message="Agent auto-revived after inactivity",
                        metadata={"event": "auto_revival", "session_id": session_id},
                    )
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
        effective_timeout = timeout or min(
            getattr(agent, "timeout", 21600.0) or 21600.0,
            _INTERACTIVE_TIMEOUT_S,
        )
        logger.info(
            "[Executor:%s] invoking agent (effective_timeout=%s, agent_type=%s)",
            session_id[:8], effective_timeout, type(agent).__name__,
        )
        invoke_result = await _invoke_bounded(
            agent,
            prompt=prompt,
            invoke_kwargs=invoke_kwargs,
            total_timeout=effective_timeout,
            session_logger=session_logger,
            session_id=session_id,
        )

        result_text = (
            invoke_result.get("output", "")
            if isinstance(invoke_result, dict)
            else str(invoke_result)
        )
        # A turn that died still returns text — "Error: you've hit your session
        # limit" — and this used to build a SUCCESSFUL result around it. The
        # session log then said the turn worked, and the chat room stored the
        # failure as a message from the agent, so the conversation showed the
        # agent announcing its own outage in its own voice. It reports what
        # the pipeline actually said about itself.
        invoke_failed = (
            isinstance(invoke_result, dict) and invoke_result.get("success") is False
        )
        invoke_error = (
            str(invoke_result.get("error") or result_text or "실행에 실패했습니다")
            if invoke_failed else ""
        )
        result_cost = (
            invoke_result.get("total_cost", 0.0)
            if isinstance(invoke_result, dict)
            else None
        )
        # Cycle 20260430_1 P0-2 — pull the per-turn tool log out of the
        # invoke envelope so `_notify_linked_vtuber` can build a real
        # payload for tool-only turns. Older invoke paths that don't
        # include the key fall back to an empty list — same shape as
        # before.
        result_tool_calls: List[Dict[str, Any]] = []
        if isinstance(invoke_result, dict):
            raw = invoke_result.get("tool_calls") or []
            if isinstance(raw, list):
                result_tool_calls = [
                    entry for entry in raw if isinstance(entry, dict)
                ]
        duration_ms = int((time.time() - start_time) * 1000)

        logger.info(
            "[Executor:%s] invoke returned: output_len=%d, cost=%s, duration=%dms",
            session_id[:8], len(result_text), result_cost, duration_ms,
        )

        # 3. Log response
        if session_logger:
            if invoke_failed:
                session_logger.log_response(
                    success=False,
                    error=invoke_error,
                    duration_ms=duration_ms,
                    cost_usd=result_cost,
                    env_id=log_env_id,
                    role=log_role,
                )
            else:
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

        # Files staged by SendUserFile during this turn → chat attachments.
        result_attachments: List[Dict[str, Any]] = []
        try:
            drain = getattr(agent, "consume_user_file_attachments", None)
            if callable(drain):
                result_attachments = drain() or []
        except Exception:  # noqa: BLE001 — delivery must never fail the turn
            logger.debug("user-file drain failed for %s", session_id, exc_info=True)

        result = ExecutionResult(
            success=not invoke_failed,
            session_id=session_id,
            output="" if invoke_failed else result_text,
            error=invoke_error or None,
            duration_ms=duration_ms,
            cost_usd=result_cost,
            tool_calls=result_tool_calls,
            attachments=result_attachments,
            spoken=(
                (invoke_result.get("spoken") or None)
                if isinstance(invoke_result, dict) and not invoke_failed
                else None
            ),
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
        # Pull the structured executor code off the exception so the
        # frontend can render via i18n key + Sentry can group cleanly.
        # The ``AgentSession`` catch block already stashed it on
        # ``_error_code`` for the session-info API; we duplicate the
        # extraction here so the SSE / response surface gets it
        # without an extra round-trip through the session manager.
        err_code: Optional[str] = None
        exc_type = f"{type(e).__module__}.{type(e).__name__}"
        try:
            from geny_executor import GenyExecutorError  # noqa: WPS433

            if isinstance(e, GenyExecutorError):
                code_attr = getattr(e, "code", None)
                if code_attr is not None:
                    err_code = getattr(code_attr, "value", str(code_attr))
        except Exception:  # noqa: BLE001 — diagnostics must never crash the catch
            pass
        logger.error(
            "❌ Execution failed for %s: %s (code=%s type=%s)",
            session_id, e, err_code or "n/a", exc_type, exc_info=True,
        )
        if session_logger:
            session_logger.log_response(
                success=False, error=str(e), duration_ms=duration_ms,
                env_id=log_env_id, role=log_role,
                error_code=err_code, exception_type=exc_type,
            )
        result = ExecutionResult(
            success=False,
            session_id=session_id,
            error=str(e),
            duration_ms=duration_ms,
            error_code=err_code,
            exception_type=exc_type,
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

    # 1a. Memory-readiness (bounded). A just-rehydrated session's long-term
    # layers warm in the background; a turn that races them retrieves PARTIAL
    # memory and the persona asserts "no record" of things it knows. Small
    # vaults are ready instantly; a 6k-note vault takes ~7s — so a short wait
    # makes almost every turn fully-informed. Past the cap we proceed (never
    # hold a user hostage) but tell the persona memory is still loading so it
    # re-checks instead of asserting absence.
    try:
        if hasattr(agent, "wait_memory_ready") and not await agent.wait_memory_ready(
            timeout=8.0
        ):
            logger.info(
                "[Executor:%s] memory warm-up still running — turn proceeds "
                "with warm-up notice", session_id[:8],
            )
            prompt = prompt + MEMORY_WARMUP_NOTICE
    except Exception:  # noqa: BLE001 — readiness must never break a turn
        pass

    # 1b. Record activity for VTuber thinking trigger
    #     Skip for trigger executions (would break adaptive backoff)
    if not is_trigger and getattr(agent, '_session_type', None) == 'vtuber':
        try:
            from service.vtuber.thinking_trigger import get_thinking_trigger_service
            get_thinking_trigger_service().record_activity(session_id)
        except Exception:
            pass  # best-effort

    # 2-4a. Admission critical section — held under the per-session lock so the
    # guard check, trigger preempt, holder register, AND task creation are atomic
    # (no concurrent execute_command can clobber the holder or slip a second turn
    # through across an await). The lock is released BEFORE awaiting the turn.
    exec_id = uuid.uuid4().hex
    async with _get_exec_lock(session_id):
        # 1c. Teardown gate — the session is being deleted/quiesced. Refuse
        # new turns under the same lock that registers holders, so a delete's
        # drain cannot have a fresh turn slip in behind it (checked here, atomic
        # with the holder register below).
        if session_id in _closing_sessions:
            raise SessionClosingError(
                f"Session {session_id} is being deleted"
            )

        # 2. Double-execution guard — with trigger preemption
        if is_executing(session_id):
            if not is_trigger and is_trigger_executing(session_id):
                # User message takes priority over trigger — abort the trigger
                logger.info(
                    "[Executor:%s] preempting trigger for user message",
                    session_id[:8],
                )
                aborted = await abort_trigger_execution(session_id)
                if not aborted or is_executing(session_id):
                    logger.warning("[Executor:%s] trigger preemption failed", session_id[:8])
                    raise AlreadyExecutingError(
                        f"Execution already in progress for session {session_id}"
                    )
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

        # 4a. Create the turn task INSIDE the lock so register+task are atomic —
        # a preempting caller can never observe a live holder whose task is None
        # (which would let the trigger's turn start after a "successful" abort).
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
        logger.info(
            "[Executor:%s] holder registered: exec_id=%s, cache_cursor=%d",
            session_id[:8], exec_id[:8], cache_cursor,
        )

    # 4b. Await the turn OUTSIDE the lock (so in-turn tool calls don't contend).
    try:
        result = await exec_task

        # 5. Emit avatar state (best-effort, never raises)
        await _emit_avatar_state(session_id, result)

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
        #    Runs after EVERY execution (including thinking triggers).
        #    Without this the Worker→VTuber [SUB_WORKER_RESULT] queued
        #    via `_notify_linked_vtuber`'s inbox fallback would only be
        #    drained when the user sent a fresh message — leaving the
        #    VTuber narrating "still waiting" while the result sits in
        #    the inbox. Re-entry is prevented by the `_draining_sessions`
        #    guard inside `_drain_inbox`; the drain itself invokes
        #    `execute_command` *without* `is_trigger=True`, so the
        #    drain's child execution can in turn drain again only after
        #    the guard releases at the outer drain's `finally`.
        if session_id not in _draining_sessions:
            spawn_background(
                _drain_inbox(session_id),
                name=f"inbox.drain:{session_id}",
                key=f"inbox.drain:{session_id}",
            )


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
    sl = _get_session_logger(session_id, create_if_missing=False)
    n_ok = 0
    n_err = 0
    n_dedup = 0
    started = False
    # Cycle 20260430_1 P1-2 — per-drain dedupe set. Captures
    # (sender_session_id, tag) pairs already processed in this drain so
    # repeated auto-fallback notifications (each carrying
    # tag="[SUB_WORKER_RESULT]") do not feed the VTuber the same empty
    # narration twice. The set is local to this drain pass, so
    # genuinely-fresh delegation cycles in later drains start clean.
    seen_tag_keys: Set[tuple] = set()
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

            if not started and sl is not None:
                sl.log(
                    level=LogLevel.INFO,
                    message="Draining inbox",
                    metadata={"event": "inbox.drain.start"},
                )
                started = True

            sender = msg.get("sender_name") or "Unknown"
            metadata = msg.get("metadata") or {}
            tag = metadata.get("tag") if isinstance(metadata, dict) else None
            if tag:
                key = (msg.get("sender_session_id") or "", tag)
                if key in seen_tag_keys:
                    n_dedup += 1
                    if sl is not None:
                        sl.log(
                            level=LogLevel.INFO,
                            message=(
                                f"Inbox drain skipped duplicate "
                                f"{tag} from {sender}"
                            ),
                            metadata={
                                "event": "inbox.drain.deduped",
                                "sender": sender,
                                "tag": tag,
                            },
                        )
                    logger.info(
                        "Drain dedupe %s: skipped %s from %s (msg=%s)",
                        session_id, tag, sender, msg.get("id"),
                    )
                    continue
                seen_tag_keys.add(key)

            prompt = f"[INBOX from {sender}]\n{msg['content']}"
            logger.info(
                "Draining inbox msg %s for %s (sender=%s, tag=%s)",
                msg.get("id"), session_id, sender, tag,
            )

            # Cycle 20260501_1 D — restore the InteractionEvent metadata
            # the inbox kept on this entry so the drained invoke's s18
            # records the same TASK_RESULT (with full payload) it
            # would have produced if the recipient hadn't been busy.
            preserved_metadata: Optional[Dict[str, Any]] = None
            if isinstance(metadata, dict):
                cand = metadata.get("interaction_event")
                if isinstance(cand, dict):
                    preserved_metadata = cand

            try:
                if preserved_metadata is not None:
                    result = await execute_command(
                        session_id, prompt, source_metadata=preserved_metadata,
                    )
                else:
                    result = await execute_command(session_id, prompt)
            except AlreadyExecutingError:
                # A concurrent execution took the slot. Its finally
                # block will re-trigger drain; bail to avoid racing.
                logger.debug(
                    "Drain for %s yielded to concurrent execution",
                    session_id,
                )
                return
            except Exception as drain_err:
                logger.debug(
                    "Drained execute_command failed for %s",
                    session_id, exc_info=True,
                )
                n_err += 1
                if sl is not None:
                    sl.log(
                        level=LogLevel.WARNING,
                        message=f"Inbox drain item failed: {drain_err}",
                        metadata={
                            "event": "inbox.drain.item_failed",
                            "sender": sender,
                            "error": str(drain_err),
                        },
                    )
                # Message already consumed — skip to next one.
                continue

            n_ok += 1
            if sl is not None:
                sl.log(
                    level=LogLevel.INFO,
                    message=f"Replayed inbox message from {sender}",
                    metadata={
                        "event": "inbox.drain.item_ok",
                        "sender": sender,
                    },
                )

            if result.success and result.output and result.output.strip():
                # An owned sub-agent's completion reaction is TTS-eligible;
                # other background drains stay suppressed.
                _drain_source = (
                    "subagent_result"
                    if tag == "[SUB_AGENT_RESULT]"
                    else "inbox_drain"
                )
                _save_drain_to_chat_room(session_id, result, source=_drain_source)
    finally:
        _draining_sessions.discard(session_id)
        if started and sl is not None:
            sl.log(
                level=LogLevel.INFO,
                message=(
                    f"Drain complete: {n_ok} ok, {n_err} failed, "
                    f"{n_dedup} deduped"
                ),
                metadata={
                    "event": "inbox.drain.complete",
                    "n_ok": n_ok,
                    "n_err": n_err,
                    "n_dedup": n_dedup,
                },
            )


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
        from service.utils.text_sanitizer import sanitize_for_display
        cleaned = sanitize_for_display(result.output) if result.success else ""
        if not cleaned:
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

        _reply_msg: Dict[str, Any] = {
            "type": "agent",
            "content": cleaned,
            "session_id": vtuber_session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "source": "sub_worker_reply",
            "spoken": result.spoken,
        }
        # Files the sub-worker delivered via SendUserFile (workspace-canvas P1)
        # ride along to the VTuber's chat room as attachments.
        if getattr(result, "attachments", None):
            _reply_msg["attachments"] = list(result.attachments)
        msg = store.add_message(chat_room_id, _reply_msg)

        logger.info(
            "[SubWorkerReply] Posted VTuber response to chat room %s "
            "(msg_id=%s, len=%d)",
            chat_room_id, msg.get("id", "?"), len(cleaned),
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


def _save_drain_to_chat_room(
    session_id: str, result: 'ExecutionResult', *, source: str = "inbox_drain",
) -> None:
    """
    Save an inbox-drain execution result to the session's chat room.
    Similar to ThinkingTriggerService._save_to_chat_room but usable
    from agent_executor without circular dependency.

    ``source`` tags the message for the frontend's auto-TTS policy. Most
    background drains use ``"inbox_drain"`` (TTS-suppressed). An owned
    sub-agent's completion reaction passes ``"subagent_result"`` — it arrives
    when the owner is idle / post-turn (never concurrent with a user turn), so
    it is TTS-eligible and the VTuber actually speaks it.
    """
    try:
        from service.utils.text_sanitizer import sanitize_for_display
        cleaned = sanitize_for_display(result.output) if result.success else ""
        if not cleaned:
            return

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

        _drain_msg: Dict[str, Any] = {
            "type": "agent",
            "content": cleaned,
            "session_id": session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            # TTS-fix (2026-04-26): tag the source so the frontend can
            # decide auto-TTS. Background drains stay suppressed; an owned
            # sub-agent completion (source="subagent_result") is TTS-eligible.
            "source": source,
            "spoken": result.spoken,
        }
        if getattr(result, "attachments", None):
            _drain_msg["attachments"] = list(result.attachments)
        store.add_message(chat_room_id, _drain_msg)

        # Notify SSE listeners
        try:
            from controller.chat_controller import _notify_room
            _notify_room(chat_room_id)
        except Exception:
            pass

        logger.info(
            "Inbox drain result saved to chat room %s (len=%d)",
            chat_room_id, len(cleaned),
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
        finally:
            # Schedule deferred cleanup: keep the holder alive for a grace
            # period so a reconnecting frontend can pick up the final result,
            # then remove it to prevent memory leaks.
            async def _deferred_cleanup():
                from service.config.sub_config.general.chat_config import ChatConfig
                _chat_cfg = ChatConfig.get_default_instance()
                await asyncio.sleep(_chat_cfg.holder_grace_period_s)
                cleanup_execution(session_id, exec_id=exec_id)

            spawn_background(
                _deferred_cleanup(), name=f"exec.cleanup:{exec_id}"
            )

            # Post-execution inbox drain
            if session_id not in _draining_sessions:
                spawn_background(
                    _drain_inbox(session_id),
                    name=f"inbox.drain:{session_id}",
                    key=f"inbox.drain:{session_id}",
                )

    spawn_background(_run(), name=f"exec.run:{session_id}:{exec_id}")
    return holder
