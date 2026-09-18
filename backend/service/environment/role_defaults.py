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

from service.sessions.models import SessionRole
from service.environment.templates import VTUBER_ENV_ID, WORKER_ENV_ID

__all__ = [
    "ROLE_DEFAULT_ENV_ID",
    "VTUBER_ENV_ID",
    "WORKER_ENV_ID",
    "resolve_env_id",
]


#: Kept so nothing that imports it breaks; every role runs the one
#: environment now, and what used to differ between them — persona, tools,
#: sub-agents — is attached to the session instead.
ROLE_DEFAULT_ENV_ID: dict[str, str] = {
    SessionRole.WORKER.value: WORKER_ENV_ID,
    SessionRole.DEVELOPER.value: WORKER_ENV_ID,
    SessionRole.RESEARCHER.value: WORKER_ENV_ID,
    SessionRole.PLANNER.value: WORKER_ENV_ID,
    SessionRole.VTUBER.value: WORKER_ENV_ID,
}


def resolve_env_id(
    role: Union[SessionRole, str, None],
    explicit: Optional[str],
) -> str:
    """The environment a session runs. There is one.

    It used to be a choice — three seeds and any number of custom copies —
    and the choice was never really about the pipeline: it was about the
    persona, the tool roster and the sub-agents, all of which a session now
    carries itself. So whatever is asked for, this answers with the one
    environment there is, including for sessions created before it was the
    only one.
    """
    # There is one environment. An `explicit` id is still accepted — sessions
    # created before this change carry ids of environments that no longer
    # exist, and pointing them at the one that does is what keeps them
    # working — but it never selects anything different.
    return WORKER_ENV_ID
