"""LangGraph Integration Module.

Integrates Claude CLI with LangGraph to provide state-driven execution
with resilience (context guard, model fallback, completion detection)
and session memory (long-term / short-term).

Key components:
    - ClaudeCLIChatModel: wraps ClaudeProcess as a LangChain ChatModel
    - AgentSession: CompiledStateGraph-based agent session
    - AgentSessionManager: manages AgentSession lifecycle
    - AutonomousGraph: difficulty-based autonomous execution graph
    - AgentState / AutonomousState: enhanced state schemas (from state.py)

Usage::

    # Option 1: Create AgentSession directly
    from service.langgraph import AgentSession

    agent = await AgentSession.create(
        working_dir="/path/to/project",
        model_name="claude-sonnet-4-20250514",
    )
    result = await agent.invoke("Hello")

    # Option 2: Use AgentSessionManager
    from service.langgraph import get_agent_session_manager

    manager = get_agent_session_manager()
    agent = await manager.create_agent_session(request)
    result = await agent.invoke("Hello")

    # Option 3: Use AutonomousGraph directly
    from service.langgraph import AutonomousGraph

    graph = AutonomousGraph(model)
    compiled = graph.build()
    result = await compiled.ainvoke({"input": "Complex task..."})
"""

from service.langgraph.claude_cli_model import ClaudeCLIChatModel
from service.langgraph.agent_session import AgentSession
from service.langgraph.agent_session_manager import (
    AgentSessionManager,
    get_agent_session_manager,
    reset_agent_session_manager,
)
from service.langgraph.autonomous_graph import AutonomousGraph
from service.langgraph.checkpointer import create_checkpointer
from service.langgraph.state import (
    AgentState,
    AutonomousState,
    CompletionSignal,
    Difficulty,
    ReviewResult,
    TodoItem,
    TodoStatus,
)

__all__ = [
    # Model
    "ClaudeCLIChatModel",
    # Session
    "AgentSession",
    "AgentState",
    # Manager
    "AgentSessionManager",
    "get_agent_session_manager",
    "reset_agent_session_manager",
    # Autonomous Graph
    "AutonomousGraph",
    "AutonomousState",
    "CompletionSignal",
    "Difficulty",
    "ReviewResult",
    "TodoItem",
    "TodoStatus",
    # Checkpointer
    "create_checkpointer",
]
