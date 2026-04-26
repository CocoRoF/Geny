"""Notifications + SendMessage channel viewer (Cycle G).

Read-only surface for what's currently registered in the executor's
NotificationEndpointRegistry and SendMessageChannelRegistry. Wiring
mutation is deliberately deferred — the channel registry is host-code
mostly (operator can't add a Discord channel from the UI without also
shipping the impl). The notifications endpoint side already has the
framework_settings PATCH path through PR-F.1.5 schema.

Endpoints:
  GET /api/notifications/endpoints  — registered NotificationEndpoint rows
  GET /api/notifications/channels   — registered SendMessage channels
"""

from __future__ import annotations

from logging import getLogger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from service.auth.auth_middleware import require_auth

logger = getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationEndpointRow(BaseModel):
    name: str
    type: Optional[str] = None
    target: Optional[str] = None
    enabled: bool = True
    extra: Dict[str, Any] = Field(default_factory=dict)


class NotificationEndpointsResponse(BaseModel):
    endpoints: List[NotificationEndpointRow] = Field(default_factory=list)


class SendMessageChannelRow(BaseModel):
    name: str
    impl: Optional[str] = None


class SendMessageChannelsResponse(BaseModel):
    channels: List[SendMessageChannelRow] = Field(default_factory=list)


def _endpoint_to_row(ep: Any) -> NotificationEndpointRow:
    name = str(getattr(ep, "name", "") or "")
    type_ = getattr(ep, "type", None) or getattr(ep, "endpoint_type", None)
    target = getattr(ep, "target", None) or getattr(ep, "url", None)
    enabled = bool(getattr(ep, "enabled", True))
    extra = {}
    for attr in ("events", "tags", "metadata"):
        val = getattr(ep, attr, None)
        if val is not None:
            extra[attr] = val
    return NotificationEndpointRow(
        name=name,
        type=str(type_) if type_ else None,
        target=str(target) if target else None,
        enabled=enabled,
        extra=extra,
    )


@router.get("/endpoints", response_model=NotificationEndpointsResponse)
async def list_endpoints(
    request: Request,
    _auth: dict = Depends(require_auth),
):
    registry = getattr(request.app.state, "notification_endpoints", None)
    rows: List[NotificationEndpointRow] = []
    if registry is not None and hasattr(registry, "list"):
        try:
            for ep in registry.list():
                rows.append(_endpoint_to_row(ep))
        except Exception as exc:  # noqa: BLE001
            logger.warning("notifications_endpoint_list_failed: %s", exc)
    return NotificationEndpointsResponse(endpoints=rows)


@router.get("/channels", response_model=SendMessageChannelsResponse)
async def list_channels(
    request: Request,
    _auth: dict = Depends(require_auth),
):
    registry = getattr(request.app.state, "send_message_channels", None)
    rows: List[SendMessageChannelRow] = []
    if registry is not None and hasattr(registry, "list"):
        try:
            entries = registry.list()
            for entry in entries:
                # Registry list returns either {name: impl_instance}
                # or [(name, impl)] depending on executor version —
                # handle both.
                if isinstance(entries, dict):
                    name, impl = entry, entries[entry]
                else:
                    name, impl = entry if isinstance(entry, tuple) else (str(entry), None)
                rows.append(SendMessageChannelRow(
                    name=str(name),
                    impl=type(impl).__name__ if impl is not None else None,
                ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("send_message_channels_list_failed: %s", exc)
    return SendMessageChannelsResponse(channels=rows)
