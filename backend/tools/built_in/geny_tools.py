"""
Geny Platform Tools — Built-in tools for team collaboration.

The Geny platform is modelled as a virtual company / organization:
  - Sessions = team members / employees (each with a name and role)
  - Rooms    = meeting rooms / group channels
  - Creating a session = hiring / bringing in a new team member
  - Adding to a room   = inviting a colleague to a meeting / channel
  - DM inbox           = private email / direct messages between members

Tool categories:
  - Team management: list members, view profiles, hire new members
  - Room management: list rooms, create rooms, invite members
  - Communication:   post in rooms, send DMs, read messages, check inbox

These tools are auto-loaded by MCPLoader (matches *_tools.py pattern)
and registered as built-in tools under the ``_builtin_tools`` server.

Architecture:
  - All tool operations go through the same singletons used by REST APIs
  - Direct messages use a lightweight file-based inbox per session
  - Room broadcasts re-use the existing ChatConversationStore
  - DMs auto-trigger the recipient session to read and respond
"""

from __future__ import annotations

import asyncio
import json
from logging import getLogger

from tools.base import BaseTool

logger = getLogger(__name__)


# ============================================================================
# Helpers — access Geny singletons safely
# ============================================================================


def _get_agent_manager():
    """Lazy import to avoid circular imports at module load time."""
    from service.langgraph import get_agent_session_manager
    return get_agent_session_manager()


def _get_chat_store():
    from service.chat.conversation_store import get_chat_store
    return get_chat_store()


def _get_inbox_manager():
    from service.chat.inbox import get_inbox_manager
    return get_inbox_manager()


def _session_summary(agent) -> dict:
    """Extract a compact summary dict from an AgentSession."""
    info = agent.get_session_info()
    return {
        "session_id": info.session_id,
        "session_name": info.session_name,
        "status": info.status.value if hasattr(info.status, "value") else str(info.status),
        "role": info.role or "worker",
        "model": info.model,
        "created_at": str(info.created_at) if info.created_at else None,
    }


def _resolve_session(name_or_id: str):
    """Resolve a session by ID or name. Returns (agent, resolved_session_id) or (None, None)."""
    manager = _get_agent_manager()
    agent = manager.resolve_session(name_or_id)
    if agent:
        return agent, agent.session_id
    return None, None


def _trigger_dm_response(
    target_session_id: str,
    sender_name: str,
    sender_session_id: str,
    content: str,
    message_id: str,
) -> None:
    """Fire-and-forget: trigger the recipient session to process a DM.

    Launches a background asyncio task that calls ``execute_command``
    on the target session with a prompt telling it to read and respond
    to the incoming DM.  The response is then delivered back to the
    sender's inbox automatically.
    """
    from service.execution.agent_executor import (
        execute_command,
        AlreadyExecutingError,
        AgentNotFoundError,
        AgentNotAliveError,
    )

    async def _deliver_and_respond():
        try:
            # Build the prompt: system instruction on top, then the DM content
            prompt = (
                f"[SYSTEM] You received a direct message from {sender_name} (session: {sender_session_id}). "
                f"Read the message below and take appropriate action — respond to questions, "
                f"perform requested tasks, etc. "
                f"Only reply via 'geny_send_direct_message' if a response is explicitly needed or expected. "
                f"Do NOT reply just to acknowledge receipt — focus on completing the task if one was requested.\n\n"
                f"[DM from {sender_name}]: {content}"
            )

            result = await execute_command(
                session_id=target_session_id,
                prompt=prompt,
            )

            if result.success and result.output and result.output.strip():
                logger.info(
                    "DM auto-response from %s completed (%dms): %s",
                    target_session_id,
                    result.duration_ms or 0,
                    result.output[:100],
                )
            else:
                logger.warning(
                    "DM auto-response from %s: no output (success=%s, error=%s)",
                    target_session_id, result.success, result.error,
                )

        except AlreadyExecutingError:
            logger.info(
                "DM trigger skipped — session %s is already executing. "
                "Message %s will stay in inbox for later.",
                target_session_id, message_id,
            )
        except (AgentNotFoundError, AgentNotAliveError) as e:
            logger.warning(
                "DM trigger failed for session %s: %s",
                target_session_id, e,
            )
        except Exception as e:
            logger.error(
                "DM trigger unexpected error for session %s: %s",
                target_session_id, e, exc_info=True,
            )

    # Schedule in the running event loop (fire-and-forget)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_deliver_and_respond())
        logger.info(
            "DM trigger scheduled: %s → %s (msg=%s)",
            sender_name, target_session_id, message_id,
        )
    except RuntimeError:
        logger.warning(
            "No running event loop — cannot trigger DM response for %s",
            target_session_id,
        )


# ============================================================================
# Session Tools
# ============================================================================


class GenySessionListTool(BaseTool):
    """List all team members (agent sessions) currently working in the company.

    In the Geny platform, each agent session represents a team member / employee.
    Use this to see who is available — their names, roles, and current status.
    """

    name = "geny_session_list"
    description = (
        "List all team members (agent sessions) currently in the company. "
        "Each session is like an employee with a name, role (developer/researcher/planner/worker), and status. "
        "Use this when you need to: check who's available, find colleagues, "
        "see which team members exist, or look up someone before inviting them to a room. "
        "Think of it as viewing the company directory or employee roster."
    )

    def run(self) -> str:
        """List all team members currently in the company.

        Returns a JSON list of all active sessions with their names, roles, and statuses.
        """
        manager = _get_agent_manager()
        agents = manager.list_agents()

        if not agents:
            return json.dumps({"sessions": [], "message": "No active sessions."})

        sessions = [_session_summary(a) for a in agents]
        return json.dumps({
            "total": len(sessions),
            "sessions": sessions,
        }, indent=2, ensure_ascii=False, default=str)


class GenySessionInfoTool(BaseTool):
    """Get detailed profile of a specific team member (agent session).

    Like looking up an employee's profile — see their role, speciality,
    current status, and when they joined.
    """

    name = "geny_session_info"
    description = (
        "Get detailed profile of a specific team member (agent session) by name or ID. "
        "Returns their role, status, model, and creation time — like an employee profile card. "
        "Use this to check on a specific colleague's details before assigning work or inviting them."
    )

    def run(self, session_id: str) -> str:
        """Get a team member's profile.

        Args:
            session_id: The session name or ID of the team member to look up.
        """
        agent, _ = _resolve_session(session_id)

        if not agent:
            return json.dumps({"error": f"Session not found: {session_id}"})

        return json.dumps(_session_summary(agent), indent=2, ensure_ascii=False, default=str)


def _get_config_model() -> str:
    """Return the currently configured default model name."""
    try:
        from service.config.manager import get_config_manager
        mgr = get_config_manager()
        api_cfg = mgr.get_config("api")
        return api_cfg.anthropic_model or "claude-sonnet-4-6"
    except Exception:
        return "claude-sonnet-4-6"


def _get_model_options() -> list[dict]:
    """Return the list of available model options from config."""
    try:
        from service.config.sub_config.general.api_config import MODEL_OPTIONS
        return MODEL_OPTIONS
    except Exception:
        return []


# Valid role enum values — mirrors frontend Create Session dialog
VALID_ROLES = ["developer", "worker", "researcher", "planner"]


class GenySessionCreateTool(BaseTool):
    """Hire / bring in a new team member (create a new agent session).

    Like hiring a new employee for the company — you give them a name and
    assign a role.  The new member is immediately ready to work and can be
    invited to chat rooms or assigned tasks.
    """

    name = "geny_session_create"
    description = (
        "Hire a new team member — create a new agent session. "
        "Only session_name is required. Role defaults to 'developer' and model uses the system default — "
        "do NOT specify role or model unless the user explicitly requests a different one. "
        "Use this when asked to: bring in someone new, hire an employee, add a developer to the team, "
        "get a researcher, recruit a new member, 직원 데려오기, 새 멤버 추가, etc. "
        "The new member is immediately available and can be invited to chat rooms afterwards."
    )

    def __init__(self):
        super().__init__()
        # Build parameter schema with enum constraints dynamically
        model_values = [opt["value"] for opt in _get_model_options()]
        default_model = _get_config_model()
        self.parameters = {
            "type": "object",
            "properties": {
                "session_name": {
                    "type": "string",
                    "description": "Name of the new team member (e.g. \"김민수\", \"Alice\", \"Backend Developer Park\").",
                },
                "role": {
                    "type": "string",
                    "description": (
                        "Optional. Defaults to 'developer'. Only change if explicitly requested. "
                        "developer: coding/engineering, worker: general tasks, "
                        "researcher: research/analysis, planner: planning/coordination."
                    ),
                    "enum": VALID_ROLES,
                    "default": "developer",
                },
                "model": {
                    "type": "string",
                    "description": (
                        f"Optional. Defaults to system config ({default_model}). "
                        "Do NOT specify unless the user explicitly asks for a different model."
                    ),
                    **({"enum": model_values} if model_values else {}),
                    "default": default_model,
                },
            },
            "required": ["session_name"],
        }

    def run(
        self,
        session_name: str,
        role: str = "developer",
        model: str | None = None,
    ) -> str:
        """Hire a new team member by creating an agent session.

        Args:
            session_name: Name of the new team member (e.g. "김민수", "Alice", "Backend Developer Park").
            role: The member's role — "developer", "worker", "researcher", or "planner". Default: "developer".
            model: AI model to use. Default: config default. Usually no need to change.
        """
        import asyncio

        if role not in VALID_ROLES:
            return json.dumps({"error": f"Invalid role '{role}'. Valid: {VALID_ROLES}"})

        # Resolve model: None/empty → config default
        resolved_model = model if model else _get_config_model()

        try:
            from service.claude_manager.models import CreateSessionRequest, SessionRole

            request = CreateSessionRequest(
                session_name=session_name,
                role=SessionRole(role),
                model=resolved_model,
            )

            manager = _get_agent_manager()

            # Bridge async creation from sync tool context
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    agent = pool.submit(
                        asyncio.run,
                        manager.create_agent_session(request),
                    ).result(timeout=120)
            else:
                agent = asyncio.run(manager.create_agent_session(request))

            return json.dumps({
                "success": True,
                "message": f"Session '{session_name}' created successfully.",
                **_session_summary(agent),
            }, indent=2, ensure_ascii=False, default=str)

        except Exception as e:
            logger.error("geny_session_create failed: %s", e, exc_info=True)
            return json.dumps({"error": f"Failed to create session: {e}"})

    async def arun(
        self,
        session_name: str,
        role: str = "developer",
        model: str | None = None,
    ) -> str:
        """Hire a new team member by creating an agent session (async).

        Args:
            session_name: Name of the new team member (e.g. "김민수", "Alice", "Backend Developer Park").
            role: The member's role — "developer", "worker", "researcher", or "planner". Default: "developer".
            model: AI model to use. Default: config default. Usually no need to change.
        """
        if role not in VALID_ROLES:
            return json.dumps({"error": f"Invalid role '{role}'. Valid: {VALID_ROLES}"})

        # Resolve model: None/empty → config default
        resolved_model = model if model else _get_config_model()

        try:
            from service.claude_manager.models import CreateSessionRequest, SessionRole

            request = CreateSessionRequest(
                session_name=session_name,
                role=SessionRole(role),
                model=resolved_model,
            )

            manager = _get_agent_manager()
            agent = await manager.create_agent_session(request)

            return json.dumps({
                "success": True,
                "message": f"Session '{session_name}' created successfully.",
                **_session_summary(agent),
            }, indent=2, ensure_ascii=False, default=str)

        except Exception as e:
            logger.error("geny_session_create failed: %s", e, exc_info=True)
            return json.dumps({"error": f"Failed to create session: {e}"})


# ============================================================================
# Room Tools
# ============================================================================


class GenyRoomListTool(BaseTool):
    """List all chat rooms (meeting rooms / group channels) in the company.

    See which rooms exist, who's in them, and how active they are.
    """

    name = "geny_room_list"
    description = (
        "List all chat rooms in the company — like viewing available meeting rooms or group channels. "
        "Returns room names, member lists, and message counts. "
        "Use this to find where the team is collaborating, check existing rooms before creating new ones, "
        "or find the right room to invite someone to."
    )

    def run(self) -> str:
        """List all chat rooms in the company.

        Returns a JSON list of all rooms with names, members, and message counts.
        """
        store = _get_chat_store()
        rooms = store.list_rooms()

        if not rooms:
            return json.dumps({"rooms": [], "message": "No rooms exist."})

        summaries = []
        for r in rooms:
            summaries.append({
                "room_id": r["id"],
                "name": r["name"],
                "session_ids": r.get("session_ids", []),
                "member_count": len(r.get("session_ids", [])),
                "message_count": r.get("message_count", 0),
                "updated_at": r.get("updated_at"),
            })

        return json.dumps({
            "total": len(summaries),
            "rooms": summaries,
        }, indent=2, ensure_ascii=False, default=str)


class GenyRoomCreateTool(BaseTool):
    """Create a new chat room — like setting up a meeting room or team channel.

    Bring team members together by creating a room and adding them as members.
    """

    name = "geny_room_create"
    description = (
        "Create a new chat room and add team members to it — like setting up a meeting room or team channel. "
        "Provide a room name and comma-separated session IDs of members to include. "
        "Use this when asked to: set up a discussion, create a project channel, "
        "make a room for the team, gather people for a meeting, etc. "
        "Tip: use geny_session_list first to find member IDs, or geny_session_create to hire new members."
    )

    def run(self, room_name: str, session_ids: str) -> str:
        """Create a new chat room and add team members.

        Args:
            room_name: Name for the new room (e.g. "Project Alpha", "개발팀 채널").
            session_ids: Comma-separated list of session IDs or names of members to include.
        """
        raw_ids = [s.strip() for s in session_ids.split(",") if s.strip()]
        if not raw_ids:
            return json.dumps({"error": "At least one session_id or name is required."})

        # Resolve each entry by name or ID
        valid_ids = []
        for entry in raw_ids:
            agent, resolved_id = _resolve_session(entry)
            if agent:
                valid_ids.append(resolved_id)
            else:
                logger.warning("geny_room_create: session %s not found, skipping", entry)

        if not valid_ids:
            return json.dumps({"error": "None of the specified sessions exist."})

        store = _get_chat_store()
        room = store.create_room(name=room_name, session_ids=valid_ids)

        return json.dumps({
            "success": True,
            "message": f"Room '{room_name}' created with {len(valid_ids)} members.",
            "room_id": room["id"],
            "name": room["name"],
            "session_ids": room["session_ids"],
        }, indent=2, ensure_ascii=False, default=str)


class GenyRoomInfoTool(BaseTool):
    """Get detailed information about a specific chat room."""

    name = "geny_room_info"
    description = (
        "Get detailed information about a chat room by ID. "
        "Returns the room name, member session IDs, message count, "
        "and timestamps."
    )

    def run(self, room_id: str) -> str:
        """Get detailed info about a chat room.

        Args:
            room_id: The room's ID to look up.
        """
        store = _get_chat_store()
        room = store.get_room(room_id)

        if not room:
            return json.dumps({"error": f"Room not found: {room_id}"})

        # Enrich with session names
        manager = _get_agent_manager()
        members = []
        for sid in room.get("session_ids", []):
            agent = manager.get_agent(sid)
            if agent:
                members.append({
                    "session_id": sid,
                    "session_name": agent.session_name,
                    "role": agent.role.value if hasattr(agent.role, "value") else str(agent.role),
                    "status": agent.status.value if hasattr(agent.status, "value") else str(agent.status),
                })
            else:
                members.append({"session_id": sid, "session_name": None, "status": "deleted"})

        return json.dumps({
            "room_id": room["id"],
            "name": room["name"],
            "members": members,
            "message_count": room.get("message_count", 0),
            "created_at": room.get("created_at"),
            "updated_at": room.get("updated_at"),
        }, indent=2, ensure_ascii=False, default=str)


class GenyRoomAddMembersTool(BaseTool):
    """Invite / add team members to an existing chat room."""

    name = "geny_room_add_members"
    description = (
        "Invite team members to an existing chat room — like adding colleagues to a group chat or meeting. "
        "Provide the room ID and comma-separated session IDs of members to add. "
        "Use this when asked to: invite someone to a room, add a member to the channel, "
        "bring someone into the conversation, 채팅방에 초대, 멤버 추가, etc. "
        "Tip: use geny_session_list to find member IDs, and geny_room_list to find room IDs."
    )

    def run(self, room_id: str, session_ids: str) -> str:
        """Invite team members to an existing chat room.

        Args:
            room_id: The room to add members to.
            session_ids: Comma-separated list of session IDs or names of team members to invite.
        """
        raw_ids = [s.strip() for s in session_ids.split(",") if s.strip()]
        if not raw_ids:
            return json.dumps({"error": "At least one session_id or name is required."})

        # Resolve each entry by name or ID
        ids_to_add = []
        not_found = []
        for entry in raw_ids:
            agent, resolved_id = _resolve_session(entry)
            if agent:
                ids_to_add.append(resolved_id)
            else:
                not_found.append(entry)

        if not_found:
            return json.dumps({"error": f"Sessions not found: {', '.join(not_found)}"})

        store = _get_chat_store()
        room = store.get_room(room_id)
        if not room:
            return json.dumps({"error": f"Room not found: {room_id}"})

        existing = set(room.get("session_ids", []))
        merged = list(existing | set(ids_to_add))

        store.update_room_sessions(room_id, merged)
        added = [sid for sid in ids_to_add if sid not in existing]

        return json.dumps({
            "success": True,
            "room_id": room_id,
            "added": added,
            "total_members": len(merged),
        }, indent=2, ensure_ascii=False, default=str)


# ============================================================================
# Messaging Tools
# ============================================================================


class GenySendRoomMessageTool(BaseTool):
    """Post a message in a chat room — like speaking in a group channel.

    The message is saved to the room's history so all members can see it.
    This does NOT trigger responses from other agents — it simply records
    your message. Other agents can read it via geny_read_room_messages.
    """

    name = "geny_send_room_message"
    description = (
        "Post a message in a chat room as this agent — like speaking in a team channel. "
        "The message is saved to the room's history for all members to see. "
        "Use this to share updates, ask questions, or communicate with the team in a room."
    )

    def run(self, room_id: str, content: str, sender_session_id: str = "", sender_name: str = "") -> str:
        """Post a message in a chat room.

        Args:
            room_id: The room to post the message in.
            content: The message text to send.
            sender_session_id: Your session ID (for attribution).
            sender_name: Your display name (for the message header).
        """
        if not content.strip():
            return json.dumps({"error": "Message content cannot be empty."})

        store = _get_chat_store()
        room = store.get_room(room_id)
        if not room:
            return json.dumps({"error": f"Room not found: {room_id}"})

        msg = store.add_message(room_id, {
            "type": "agent",
            "content": content.strip(),
            "session_id": sender_session_id or None,
            "session_name": sender_name or None,
            "role": "agent",
        })

        return json.dumps({
            "success": True,
            "message_id": msg.get("id"),
            "room_id": room_id,
            "timestamp": msg.get("timestamp"),
        }, indent=2, ensure_ascii=False, default=str)


class GenySendDirectMessageTool(BaseTool):
    """Send a direct (private) message to another team member.

    Like sending a DM or private chat — the message goes to the target's
    personal inbox AND automatically triggers the recipient to read and
    respond to it.
    """

    name = "geny_send_direct_message"
    description = (
        "Send a direct message (DM) to another team member privately. "
        "You can specify the recipient by session name or session ID. "
        "The message is delivered to their inbox AND the recipient is automatically "
        "notified so they can read and respond. "
        "Use this for 1:1 communication, sending tasks to a specific colleague, "
        "or private coordination that doesn't need to be in a group room."
    )

    def run(
        self,
        target_session_id: str,
        content: str,
        sender_session_id: str = "",
        sender_name: str = "",
    ) -> str:
        """Send a private message to another team member.

        Args:
            target_session_id: The recipient's session ID or session name.
            content: The message text to send.
            sender_session_id: Your session ID (so they know who sent it).
            sender_name: Your display name.
        """
        if not content.strip():
            return json.dumps({"error": "Message content cannot be empty."})

        # Resolve target by ID or name
        target, resolved_id = _resolve_session(target_session_id)
        if not target:
            return json.dumps({"error": f"Target session not found: {target_session_id}"})

        inbox = _get_inbox_manager()
        msg = inbox.deliver(
            target_session_id=resolved_id,
            content=content.strip(),
            sender_session_id=sender_session_id,
            sender_name=sender_name,
        )

        # Auto-trigger the recipient to process the DM
        _trigger_dm_response(
            target_session_id=resolved_id,
            sender_session_id=sender_session_id,
            sender_name=sender_name or sender_session_id[:8],
            content=content.strip(),
            message_id=msg["id"],
        )

        return json.dumps({
            "success": True,
            "message_id": msg["id"],
            "delivered_to": resolved_id,
            "delivered_to_name": target.session_name,
            "timestamp": msg["timestamp"],
            "auto_triggered": True,
        }, indent=2, ensure_ascii=False, default=str)


class GenyReadRoomMessagesTool(BaseTool):
    """Read recent messages from a chat room — catch up on the conversation.

    Returns the latest messages with who said what and when.
    """

    name = "geny_read_room_messages"
    description = (
        "Read messages from a chat room — like scrolling through a group chat history. "
        "Returns recent messages with sender names, roles, and timestamps. "
        "Use this to catch up on a conversation, check what the team discussed, "
        "or review decisions made in a room."
    )

    def run(self, room_id: str, limit: int = 20) -> str:
        """Read recent messages from a chat room.

        Args:
            room_id: The room to read messages from.
            limit: Maximum number of recent messages to return (default: 20, max: 100).
        """
        limit = min(max(1, limit), 100)

        store = _get_chat_store()
        room = store.get_room(room_id)
        if not room:
            return json.dumps({"error": f"Room not found: {room_id}"})

        all_msgs = store.get_messages(room_id)
        recent = all_msgs[-limit:] if len(all_msgs) > limit else all_msgs

        formatted = []
        for m in recent:
            formatted.append({
                "id": m.get("id"),
                "type": m.get("type"),
                "content": m.get("content"),
                "sender_session_id": m.get("session_id"),
                "sender_name": m.get("session_name"),
                "role": m.get("role"),
                "timestamp": m.get("timestamp"),
            })

        return json.dumps({
            "room_id": room_id,
            "room_name": room["name"],
            "total_in_room": len(all_msgs),
            "returned": len(formatted),
            "messages": formatted,
        }, indent=2, ensure_ascii=False, default=str)


class GenyReadInboxTool(BaseTool):
    """Check your inbox — read private messages from other team members.

    Like checking your email or DM inbox. See who sent you messages
    and what they said. Can filter for unread only.
    """

    name = "geny_read_inbox"
    description = (
        "Check your inbox for direct messages from other team members. "
        "Returns recent DMs with sender info — like checking your email or private messages. "
        "Use unread_only=true to see only new messages, and mark_read=true to mark them as read."
    )

    def run(
        self,
        session_id: str,
        limit: int = 20,
        unread_only: bool = False,
        mark_read: bool = False,
    ) -> str:
        """Check inbox for direct messages.

        Args:
            session_id: Your session ID (identifies which inbox to read).
            limit: Maximum number of messages to return (default: 20, max: 100).
            unread_only: If true, return only unread/new messages.
            mark_read: If true, mark returned messages as read after retrieval.
        """
        limit = min(max(1, limit), 100)

        inbox = _get_inbox_manager()
        messages = inbox.read(
            session_id=session_id,
            limit=limit,
            unread_only=unread_only,
        )

        if mark_read and messages:
            msg_ids = [m["id"] for m in messages]
            inbox.mark_read(session_id, msg_ids)

        return json.dumps({
            "session_id": session_id,
            "total_returned": len(messages),
            "unread_only": unread_only,
            "messages": messages,
        }, indent=2, ensure_ascii=False, default=str)


# =============================================================================
# Export list — MCPLoader auto-collects these
# =============================================================================

TOOLS = [
    # Session management
    GenySessionListTool(),
    GenySessionInfoTool(),
    GenySessionCreateTool(),
    # Room management
    GenyRoomListTool(),
    GenyRoomCreateTool(),
    GenyRoomInfoTool(),
    GenyRoomAddMembersTool(),
    # Messaging
    GenySendRoomMessageTool(),
    GenySendDirectMessageTool(),
    GenyReadRoomMessagesTool(),
    GenyReadInboxTool(),
]
