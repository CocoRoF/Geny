"""Role → default env_id mapping and resolution helper.

Every session role maps to one of two seed environments:
``template-worker-env`` (task work) or ``template-vtuber-env``
(conversation). :func:`resolve_env_id` is the single entrypoint that
session creation uses to decide which env to load — an explicit
``request.env_id`` always wins over the role default.

This module stays deliberately tiny. It is imported by
:class:`~service.executor.agent_session_manager.AgentSessionManager`
at session creation time, and is also exported for use by the env_id
validation layer in the REST controllers.
"""

from __future__ import annotations

from typing import Optional, Union

from service.claude_manager.models import SessionRole
from service.environment.templates import VTUBER_ENV_ID, WORKER_ENV_ID

__all__ = [
    "ROLE_DEFAULT_ENV_ID",
    "VTUBER_ENV_ID",
    "WORKER_ENV_ID",
    "resolve_env_id",
]


ROLE_DEFAULT_ENV_ID: dict[str, str] = {
    SessionRole.WORKER.value: WORKER_ENV_ID,
    SessionRole.DEVELOPER.value: WORKER_ENV_ID,
    SessionRole.RESEARCHER.value: WORKER_ENV_ID,
    SessionRole.PLANNER.value: WORKER_ENV_ID,
    SessionRole.VTUBER.value: VTUBER_ENV_ID,
}


def resolve_env_id(
    role: Union[SessionRole, str, None],
    explicit: Optional[str],
) -> str:
    """Resolve the env_id a session should use.

    An explicit value (the caller's ``request.env_id``) always wins.
    When no explicit value is given, the role's default from
    :data:`ROLE_DEFAULT_ENV_ID` is returned. Unknown roles fall back
    to :data:`WORKER_ENV_ID` — mirrors how unknown roles fall back to
    ``template-all-tools`` in tool_preset land today.
    """
    if explicit:
        return explicit
    if role is None:
        return WORKER_ENV_ID
    role_value = role.value if hasattr(role, "value") else str(role)
    return ROLE_DEFAULT_ENV_ID.get(role_value.lower(), WORKER_ENV_ID)
