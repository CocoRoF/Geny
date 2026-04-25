"""Read-only admin endpoints (G13).

- GET /api/permissions/list  — current rule list with source breakdown
- GET /api/hooks/list        — current hook config + env opt-in status

Skills are already covered by /api/skills/list (G7.4).

These endpoints exist so the operator UI can answer "what's loaded?"
without tailing the server log. Hand-edit YAML is still the only
write path; an editor UI is a follow-up.
"""

from __future__ import annotations

import os
from logging import getLogger
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from controller.auth_controller import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api", tags=["admin"])


# ── Permissions ────────────────────────────────────────────────────


class PermissionRuleInfo(BaseModel):
    tool_name: str
    pattern: Optional[str] = None
    behavior: str
    source: str
    reason: Optional[str] = None


class PermissionListResponse(BaseModel):
    mode: str = Field(..., description="advisory | enforce")
    rules: List[PermissionRuleInfo]
    sources_consulted: List[str] = Field(
        default_factory=list,
        description="Paths the loader inspected — useful for debugging \"my rule isn't loaded\"",
    )


@router.get(
    "/permissions/list",
    response_model=PermissionListResponse,
    summary="Inspect the loaded permission matrix",
)
async def list_permissions(_auth: dict = Depends(require_auth)):
    """Returns every PermissionRule the install layer would forward
    to attach_runtime, plus the resolved mode (advisory / enforce)
    and the candidate paths the loader checked."""
    from service.permission.install import (
        _candidate_paths,
        install_permission_rules,
    )

    rules, mode = install_permission_rules()
    paths = [str(p) for p, _src in _candidate_paths()]
    return PermissionListResponse(
        mode=mode,
        rules=[
            PermissionRuleInfo(
                tool_name=r.tool_name,
                pattern=r.pattern,
                behavior=getattr(r.behavior, "value", str(r.behavior)),
                source=getattr(r.source, "value", str(r.source)),
                reason=r.reason,
            )
            for r in rules
        ],
        sources_consulted=paths,
    )


# ── Hooks ───────────────────────────────────────────────────────────


class HookEntryInfo(BaseModel):
    event: str
    command: List[str]
    timeout_ms: Optional[int] = None
    tool_filter: List[str] = Field(default_factory=list)


class HookListResponse(BaseModel):
    enabled: bool
    env_opt_in: bool = Field(..., description="GENY_ALLOW_HOOKS truthy?")
    config_path: str
    entries: List[HookEntryInfo]


@router.get(
    "/hooks/list",
    response_model=HookListResponse,
    summary="Inspect the loaded HookConfig",
)
async def list_hooks(_auth: dict = Depends(require_auth)):
    """Returns the HookConfig that install_hook_runner would build
    plus the env opt-in status. Both gates must be open for hooks
    to actually fire."""
    from service.hooks.install import hooks_yaml_path

    env_opt_in = os.environ.get("GENY_ALLOW_HOOKS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
    path = hooks_yaml_path()

    enabled = False
    entries: List[HookEntryInfo] = []
    try:
        from geny_executor.hooks import load_hooks_config

        cfg = load_hooks_config(path)
        enabled = bool(getattr(cfg, "enabled", False))
        for event, event_entries in (cfg.entries or {}).items():
            event_name = getattr(event, "value", str(event))
            for ent in event_entries:
                entries.append(
                    HookEntryInfo(
                        event=event_name,
                        command=list(getattr(ent, "command", []) or []),
                        timeout_ms=getattr(ent, "timeout_ms", None),
                        tool_filter=list(getattr(ent, "tool_filter", []) or []),
                    )
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_hooks: load failed: %s", exc)

    return HookListResponse(
        enabled=enabled,
        env_opt_in=env_opt_in,
        config_path=str(path),
        entries=entries,
    )
