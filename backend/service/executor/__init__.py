"""Agent Session Module.

Provides geny-executor Pipeline-based agent session management.

Key components:
    - AgentSession: Pipeline-based agent session
    - AgentSessionManager: manages AgentSession lifecycle

Usage::

    from service.executor import AgentSession

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
    )
    result = await agent.invoke("Hello")
"""

from service.executor.agent_session import AgentSession
from service.executor.agent_session_manager import (
    AgentSessionManager,
    get_agent_session_manager,
    reset_agent_session_manager,
)

__all__ = [
    "AgentSession",
    "AgentSessionManager",
    "get_agent_session_manager",
    "reset_agent_session_manager",
]
