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
"""

from __future__ import annotations

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
        "Get detailed profile of a specific team member (agent session) by ID. "
        "Returns their role, status, model, and creation time — like an employee profile card. "
        "Use this to check on a specific colleague's details before assigning work or inviting them."
    )

    def run(self, session_id: str) -> str:
        """Get a team member's profile.

        Args:
            session_id: The session ID of the team member to look up.
        """
        manager = _get_agent_manager()
        agent = manager.get_agent(session_id)

        if not agent:
            return json.dumps({"error": f"Session not found: {session_id}"})

        return json.dumps(_session_summary(agent), indent=2, ensure_ascii=False, default=str)


class GenySessionCreateTool(BaseTool):
    """Hire / bring in a new team member (create a new agent session).

    Like hiring a new employee for the company — you give them a name and
    assign a role.  The new member is immediately ready to work and can be
    invited to chat rooms or assigned tasks.
    """

    name = "geny_session_create"
    description = (
        "Hire a new team member — create a new agent session with a name and role. "
        "Roles: developer (coding), researcher (research/analysis), planner (planning/coordination), worker (general tasks). "
        "Use this when asked to: bring in someone new, hire an employee, add a developer to the team, "
        "get a researcher, recruit a new member, 직원 데려오기, 새 멤버 추가, etc. "
        "The new member is immediately available and can be invited to chat rooms afterwards."
    )

    def run(
        self,
        session_name: str,
        role: str = "worker",
        model: str = "claude-sonnet-4-20250514",
    ) -> str:
        """Hire a new team member by creating an agent session.

        Args:
            session_name: Name of the new team member (e.g. "김민수", "Alice", "Backend Developer Park").
            role: The member's role in the team — "developer" (coding/engineering), "researcher" (research/analysis), "planner" (planning/coordination), or "worker" (general tasks). Default: "worker".
            model: AI model to use (default: claude-sonnet-4-20250514). Usually no need to change.
        """
        import asyncio

        valid_roles = {"worker", "developer", "researcher", "planner"}
        if role not in valid_roles:
            return json.dumps({"error": f"Invalid role '{role}'. Valid: {sorted(valid_roles)}"})

        try:
            from service.claude_manager.models import CreateSessionRequest, SessionRole

            request = CreateSessionRequest(
                session_name=session_name,
                role=SessionRole(role),
                model=model,
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
        role: str = "worker",
        model: str = "claude-sonnet-4-20250514",
    ) -> str:
        """Hire a new team member by creating an agent session (async).

        Args:
            session_name: Name of the new team member (e.g. "김민수", "Alice", "Backend Developer Park").
            role: The member's role in the team — "developer" (coding/engineering), "researcher" (research/analysis), "planner" (planning/coordination), or "worker" (general tasks). Default: "worker".
            model: AI model to use (default: claude-sonnet-4-20250514). Usually no need to change.
        """
        valid_roles = {"worker", "developer", "researcher", "planner"}
        if role not in valid_roles:
            return json.dumps({"error": f"Invalid role '{role}'. Valid: {sorted(valid_roles)}"})

        try:
            from service.claude_manager.models import CreateSessionRequest, SessionRole

            request = CreateSessionRequest(
                session_name=session_name,
                role=SessionRole(role),
                model=model,
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
            session_ids: Comma-separated list of session IDs of members to include in the room.
        """
        ids = [s.strip() for s in session_ids.split(",") if s.strip()]
        if not ids:
            return json.dumps({"error": "At least one session_id is required."})

        # Validate that sessions exist
        manager = _get_agent_manager()
        valid_ids = []
        for sid in ids:
            if manager.get_agent(sid):
                valid_ids.append(sid)
            else:
                logger.warning("geny_room_create: session %s not found, skipping", sid)

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
            session_ids: Comma-separated list of session IDs of team members to invite.
        """
        ids_to_add = [s.strip() for s in session_ids.split(",") if s.strip()]
        if not ids_to_add:
            return json.dumps({"error": "At least one session_id is required."})

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
    personal inbox. They can read it using their inbox.
    """

    name = "geny_send_direct_message"
    description = (
        "Send a direct message (DM) to another team member privately. "
        "The message is delivered to their inbox — like a private chat or email. "
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
            target_session_id: The recipient team member's session ID.
            content: The message text to send.
            sender_session_id: Your session ID (so they know who sent it).
            sender_name: Your display name.
        """
        if not content.strip():
            return json.dumps({"error": "Message content cannot be empty."})

        # Validate target exists
        manager = _get_agent_manager()
        target = manager.get_agent(target_session_id)
        if not target:
            return json.dumps({"error": f"Target session not found: {target_session_id}"})

        inbox = _get_inbox_manager()
        msg = inbox.deliver(
            target_session_id=target_session_id,
            content=content.strip(),
            sender_session_id=sender_session_id,
            sender_name=sender_name,
        )

        return json.dumps({
            "success": True,
            "message_id": msg["id"],
            "delivered_to": target_session_id,
            "delivered_to_name": target.session_name,
            "timestamp": msg["timestamp"],
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
