"""Move what an environment used to hold onto the sessions that used it.

There were environments — three seeds and any number of copies — and each
carried a persona for the agents built from it. There is one environment now,
and it carries no persona: a session does.

So before the link is cut, every session that was getting its persona from an
environment has that choice written onto its own record. Without this, an
agent with a custom persona (built by copying an environment and changing its
persona, which was the only way to do it) would quietly start speaking as
nobody the next time it was loaded.

Runs at boot, after the environment service is wired. Idempotent: a session
that already names its own persona is never touched, and a second run finds
nothing to do.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _env_persona(environment_service: Any, env_id: Optional[str]) -> Optional[str]:
    """The persona an environment declares, or None."""
    if not env_id or environment_service is None:
        return None
    try:
        manifest = environment_service.load_manifest(env_id)
        if manifest is None:
            return None
        extras = getattr(manifest.host_selections, "extras", None) or {}
        value = extras.get("persona_preset_id")
        return value.strip() if isinstance(value, str) and value.strip() else None
    except Exception:  # noqa: BLE001
        logger.debug("could not read persona from env %s", env_id, exc_info=True)
        return None


def migrate_session_attachments(session_store: Any, environment_service: Any) -> Dict[str, int]:
    """Write each session's inherited persona onto the session itself.

    Returns ``{"checked": n, "moved": n}``. Never raises: a migration that
    fails must not stop the server from starting.
    """
    moved = 0
    checked = 0
    try:
        records = session_store.list_all() or []
    except Exception:  # noqa: BLE001
        logger.warning("[attachments] could not list sessions", exc_info=True)
        return {"checked": 0, "moved": 0}

    for record in records:
        session_id = record.get("session_id")
        if not session_id:
            continue
        checked += 1
        own = record.get("persona_preset_id")
        if isinstance(own, str) and own.strip():
            continue  # already its own
        inherited = _env_persona(environment_service, record.get("env_id"))
        if not inherited:
            continue
        try:
            session_store.update(session_id, {"persona_preset_id": inherited})
            moved += 1
            logger.info(
                "[attachments] %s keeps persona %s (was its environment's)",
                str(session_id)[:8], inherited,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "[attachments] could not attach persona to %s", session_id, exc_info=True,
            )

    if moved:
        logger.info("[attachments] %d/%d sessions now carry their own persona", moved, checked)
    return {"checked": checked, "moved": moved}
