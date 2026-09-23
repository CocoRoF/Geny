"""위임 결과를 호출자(VTuber) 에게 전달하는 헬퍼.

pump_task 가 turn_complete / error / cancelled 시 호출. 동작:

1. ``[EXTERNAL_TASK_RESULT]`` 봉투 페이로드 구성
2. ``inbox.deliver`` 로 호출자 세션에 메시지 도착
3. ``execute_command`` 로 호출자가 paraphrase turn 실행 → assistant 응답 생성
4. 그 응답을 호출자의 ``_chat_room_id`` 에 broadcast → 사용자 화면에 노출

기존 ``_save_subworker_reply_to_chat_room`` 와 평행 구조. fire-and-forget
asyncio task 로 실행 (pump_task 는 곧 자기 종료 단계라 이 task 를 await
하면 lifecycle 이 꼬일 수 있음).

InteractionEvent 분류:
  - 봉투 첫 줄 ``[EXTERNAL_TASK_RESULT]`` 가 ``geny_tools._classify_outgoing_dm``
    / ``_build_recipient_dm_metadata`` 의 외부 sender 분기 (Phase 2) 로
    Kind.EXTERNAL_TASK_RESULT + EXTERNAL_AGENT 로 기록됨.
"""
from __future__ import annotations

import asyncio
from service.utils.background import spawn_background
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from service.blog_agent.registry import BlogTaskState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


_BLOG_SENDER_PREFIX = "blog:"
_EXTERNAL_RESULT_TAG = "[EXTERNAL_TASK_RESULT]"


def build_external_result_payload(state: BlogTaskState, *, kind: str) -> str:
    """봉투 형식 페이로드 생성. paraphrase prompt 와 InteractionEvent 분류
    양쪽이 첫 줄 태그를 본다.
    """
    activity_lines = []
    for tool, count in sorted(state.tool_call_counts.items(), key=lambda kv: -kv[1])[:8]:
        activity_lines.append(f"- {tool}: {count}회")
    activity_block = "\n".join(activity_lines) if activity_lines else "- (no tool calls)"

    duration = round(state.elapsed_s, 1)
    if kind == "done":
        body = state.final_text or state.last_assistant_chunk or "(no text)"
        status_line = "Status: done"
    elif kind == "cancelled":
        body = state.last_assistant_chunk or "(작업이 도중에 취소되었습니다)"
        status_line = "Status: cancelled"
    elif kind == "error":
        body = (state.last_assistant_chunk or "") + (
            f"\n\n[error] {state.error}" if state.error else ""
        )
        status_line = "Status: error"
    else:
        body = state.last_assistant_chunk
        status_line = f"Status: {kind}"

    return (
        f"{_EXTERNAL_RESULT_TAG}\n"
        f"From: {_BLOG_SENDER_PREFIX}{state.blog_session_uid}\n"
        f"Task: {state.task_id}\n"
        f"{status_line}\n\n"
        f"{body}\n\n"
        f"--- Activity Summary ---\n"
        f"- duration: {duration}s\n"
        f"- output: {len(body)} chars\n"
        f"{activity_block}\n"
    )


def _build_paraphrase_prompt(state: BlogTaskState, payload: str, kind: str) -> str:
    """Trigger prompt that asks the caller to paraphrase an external result."""
    if kind == "done":
        directive = (
            "The external blog AI has finished the delegated task. Tell the user "
            "it's done and give the key result in 1-3 sentences. If there's a slug "
            "or URL, show it clearly. Do not copy the body verbatim — paraphrase "
            "it in natural language."
        )
    elif kind == "cancelled":
        directive = (
            "The delegated task was cancelled. Tell the user in one sentence."
        )
    else:
        directive = (
            "The delegated task failed. Tell the user the cause of the error in "
            "1-2 sentences and judge whether a retry is needed."
        )
    return (
        f"[SYSTEM] {directive}\n\n"
        f"Original user request: {state.task_summary}\n\n"
        f"{payload}"
    )


async def deliver_external_result(state: BlogTaskState, kind: str) -> None:
    """pump_task 가 호출하는 진입점. fire-and-forget 백그라운드 task 로
    paraphrase 트리거를 띄우고 즉시 반환.
    """
    try:
        await _do_deliver(state, kind)
    except Exception:  # noqa: BLE001 — pump 가 죽지 않도록 흡수
        logger.exception(
            "deliver_external_result failed task=%s kind=%s",
            state.task_id, kind,
        )


async def _do_deliver(state: BlogTaskState, kind: str) -> None:
    payload = build_external_result_payload(state, kind=kind)
    sender_id = f"{_BLOG_SENDER_PREFIX}{state.blog_session_uid}"
    sender_name = "Blog Agent"

    # 1) inbox 에 명시적으로 deliver — UI / 디버그에서 메시지가 도착했음을
    #    볼 수 있게.
    try:
        from service.chat.inbox import get_inbox_manager
        get_inbox_manager().deliver(
            target_session_id=state.geny_session_id,
            content=payload,
            sender_session_id=sender_id,
            sender_name=sender_name,
            metadata={
                "tag": _EXTERNAL_RESULT_TAG,
                "task_id": state.task_id,
                "external_kind": kind,
            },
        )
    except Exception:
        logger.warning(
            "inbox deliver failed for external result task=%s",
            state.task_id, exc_info=True,
        )

    # 2) paraphrase trigger — fire-and-forget. execute_command 는 내부적으로
    #    AlreadyExecuting 등을 raise 할 수 있으므로 별도 task 로 분리.
    try:
        spawn_background(
            _trigger_paraphrase(state, payload, kind),
            name=f"blog_paraphrase:{state.task_id[:8]}",
        )
    except RuntimeError:
        logger.warning(
            "no running loop — cannot trigger paraphrase task=%s",
            state.task_id,
        )


async def _trigger_paraphrase(
    state: BlogTaskState,
    payload: str,
    kind: str,
) -> None:
    """호출자(VTuber) 세션에 paraphrase turn 을 트리거 + chat_room broadcast."""
    from service.execution.agent_executor import (
        AlreadyExecutingError,
        AgentNotFoundError,
        execute_command,
    )

    prompt = _build_paraphrase_prompt(state, payload, kind)

    try:
        from service.memory.interaction_event import (
            CounterpartRole,
            Direction,
            Kind,
            make_event_metadata,
        )
        source_metadata: Optional[Dict[str, Any]] = make_event_metadata(
            kind=Kind.EXTERNAL_TASK_RESULT,
            direction=Direction.IN,
            counterpart_id=f"{_BLOG_SENDER_PREFIX}{state.blog_session_uid}",
            counterpart_role=CounterpartRole.EXTERNAL_AGENT,
        )
    except Exception:
        # Phase 2 enum 이 아직 머지 안 됐을 때 fallback. 실제 운영시엔 도달 X.
        source_metadata = None

    try:
        result = await execute_command(
            session_id=state.geny_session_id,
            prompt=prompt,
            source_metadata=source_metadata,
        )
    except AlreadyExecutingError:
        # 호출자가 다른 turn 을 돌고 있다면 inbox 에 이미 deliver 됐으니
        # drain 경로가 결국 처리. 추가 작업 없음.
        logger.info(
            "paraphrase skipped — caller already executing task=%s",
            state.task_id,
        )
        return
    except AgentNotFoundError:
        logger.warning(
            "paraphrase skipped — caller session gone task=%s",
            state.task_id,
        )
        return
    except Exception:
        logger.exception(
            "paraphrase execute_command failed task=%s",
            state.task_id,
        )
        return

    if not result.success or not (result.output or "").strip():
        logger.info(
            "paraphrase produced no output task=%s",
            state.task_id,
        )
        return

    _save_external_reply_to_chat_room(state.geny_session_id, result)


def _save_external_reply_to_chat_room(
    geny_session_id: str,
    result: "Any",
) -> None:
    """``_save_subworker_reply_to_chat_room`` 의 외부 결과 버전.

    파일 분리: 같은 chat_store 인터페이스를 쓰지만 ``source="blog_agent_reply"``
    로 출처를 구분 — 운영 / 디버그가 사용자 화면 메시지의 출처를 즉시 안다.
    """
    try:
        from service.utils.text_sanitizer import sanitize_for_display

        cleaned = sanitize_for_display(result.output) if result.success else ""
        if not cleaned:
            return

        from service.executor import get_agent_session_manager

        agent = get_agent_session_manager().get_agent(geny_session_id)
        if agent is None:
            return

        chat_room_id = getattr(agent, "_chat_room_id", None)
        if not chat_room_id:
            return

        from service.chat.conversation_store import get_chat_store

        store = get_chat_store()
        session_name = getattr(agent, "_session_name", None) or geny_session_id
        role_val = getattr(agent, "_role", None)
        role = role_val.value if hasattr(role_val, "value") else str(role_val or "vtuber")

        msg = store.add_message(chat_room_id, {
            "type": "agent",
            "content": cleaned,
            "session_id": geny_session_id,
            "session_name": session_name,
            "role": role,
            "duration_ms": getattr(result, "duration_ms", None),
            "cost_usd": getattr(result, "cost_usd", None),
            "source": "blog_agent_reply",
            "spoken": getattr(result, "spoken", None),
        })

        logger.info(
            "[BlogAgentReply] posted reply to chat_room=%s msg=%s len=%d",
            chat_room_id, msg.get("id", "?"), len(cleaned),
        )

        try:
            from controller.chat_controller import _notify_room
            _notify_room(chat_room_id)
        except Exception:
            logger.warning(
                "[BlogAgentReply] _notify_room failed chat_room=%s",
                chat_room_id, exc_info=True,
            )
    except Exception:
        logger.warning(
            "[BlogAgentReply] failed to post reply to chat_room",
            exc_info=True,
        )
