"""What a session carries, now that an environment no longer carries it.

There used to be a choice of environments, and the choice was never really
about the pipeline — every one of them ran the same 21 stages. It was about
four things:

* a **persona** the agent wears
* the **tools** it may use
* whether it **owns a companion** sub-agent
* which **one-shot sub-workers** it can delegate to

All four belong to the agent, not to a template the agent was cut from, and
keeping them in a template is what made "give this one a different persona"
mean "build a whole new environment". So they hang off the session now, and
this module is the one place that says what a session gets when nobody
specifies: the defaults that used to be baked into the VTuber and worker
seeds, expressed as what they always were — consequences of the role.

A session may override any of them; these are only what it starts with.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

#: The GAPT control-plane tools. Heavy (nine schemas), so a persona agent
#: delegates to a sub-worker carrying them instead of holding them itself.
GAPT_TOOL_NAMES = [
    "gapt_overview",
    "gapt_list_projects",
    "gapt_create_project",
    "gapt_list_workspaces",
    "gapt_create_workspace",
    "gapt_manage_workspace",
    "gapt_run_command",
    "gapt_list_deployments",
    "gapt_deploy",
]


def _role_of(role: Union[str, Any, None]) -> str:
    if role is None:
        return ""
    return str(getattr(role, "value", role)).strip().lower()


def default_persona_preset_id(role: Union[str, Any, None]) -> Optional[str]:
    """The persona a session of this role starts with.

    A VTuber is a persona — the INTJ/반말 default, so a fresh one has a
    consistent character from its first word. Everything else starts with
    none, and the user attaches one when they want one.
    """
    if _role_of(role) != "vtuber":
        return None
    try:
        from service.persona_presets.templates import VTUBER_DEFAULT_PERSONA_ID

        return VTUBER_DEFAULT_PERSONA_ID
    except Exception:  # noqa: BLE001 — a missing preset must not block creation
        logger.debug("default persona preset unavailable", exc_info=True)
        return None


def default_owned_subagent(role: Union[str, Any, None]) -> Optional[Dict[str, Any]]:
    """Whether this session owns a persistent companion sub-agent.

    ``{"enabled": True}`` turns ownership on; the companion inherits the
    owner's tools, model and stages. Only a VTuber starts with one — it is
    what lets the persona hand work off and keep talking.
    """
    return {"enabled": True} if _role_of(role) == "vtuber" else None


def default_subworker_types(role: Union[str, Any, None]) -> List[Dict[str, Any]]:
    """The one-shot sub-workers this session can delegate to.

    A persona agent stays lean and sends GAPT (project / sandbox / deploy)
    work to a sub-worker that carries those nine tools. A worker holds them
    directly, so it needs no such helper.
    """
    if _role_of(role) != "vtuber":
        return []
    try:
        from service.environment.templates import _GAPT_SUBWORKER_PROMPT
        prompt = _GAPT_SUBWORKER_PROMPT
    except Exception:  # noqa: BLE001
        prompt = ""
    return [{
        "agent_type": "gapt",
        "description": (
            "GAPT operator — create/manage independent project & workspace "
            "(sandbox) spaces and deploy. Delegate any GAPT work here."
        ),
        "allowed_tools": list(GAPT_TOOL_NAMES),
        "system_prompt": prompt,
    }]


def defaults_for(role: Union[str, Any, None]) -> Dict[str, Any]:
    """Everything a new session of this role starts attached to.

    Only non-empty values are returned, so a caller can write this straight
    onto the session record without storing a row of nulls.
    """
    out: Dict[str, Any] = {}
    persona = default_persona_preset_id(role)
    if persona:
        out["persona_preset_id"] = persona
    owned = default_owned_subagent(role)
    if owned:
        out["owned_subagent"] = owned
    types = default_subworker_types(role)
    if types:
        out["subworker_types"] = types
    return out
