"""Move every environment onto the one harness. Once, at boot.

Collapsing the seeds was only half the job: writing three new templates left
the eight per-backend ones (``template-claude-code-worker-env``,
``template-openai-vtuber-env``, …) sitting on disk, and left every
user-created environment still naming the provider it was created with.

The effect was worse than cosmetic. A session bound to one of those runs its
turns through that provider directly — so it never reaches the route, never
fails over, and when that backend is out of quota every single turn fails
with the raw CLI error. That is exactly what production did: the live VTuber
session was on an env pinned to ``claude_code_cli``, the subscription had hit
its spend cap, and a working OpenAI account sat unused in the route.

So:

* the superseded per-backend SEED templates are deleted — they are ours, they
  exist only to offer a choice that no longer exists, and leaving them in the
  picker invites someone to pick one again;
* every remaining environment — seeds and the user's own — has Stage 6
  repointed at ``geny_router``. A user environment is a tool roster and a
  persona, which is kept exactly as it is; the provider inside it was the one
  field that is no longer an environment's business.

Idempotent: the second run finds nothing to do.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["SUPERSEDED_SEED_ENV_IDS", "migrate_environments_to_router"]

#: Seed environments whose only reason to exist was picking a backend. The
#: three that remain (worker / vtuber / vscode) differ by TOOLS and PERSONA,
#: which is a real difference; these differed by provider, which is now the
#: session's route.
SUPERSEDED_SEED_ENV_IDS = (
    "template-claude-code-worker-env",
    "template-claude-code-vtuber-env",
    "template-claude-worker-env",
    "template-claude-vtuber-env",
    "template-openai-worker-env",
    "template-openai-vtuber-env",
    "template-local-worker-env",
    "template-local-vtuber-env",
)

ROUTER_PROVIDER = "geny_router"


def _stage6_provider(manifest: Any) -> Optional[str]:
    for entry in manifest.stage_entries():
        if entry.order == 6 and entry.name == "api":
            return (
                (entry.config or {}).get("provider")
                or (entry.strategies or {}).get("provider")
                or None
            )
    return None


def _repoint(manifest: Any) -> bool:
    """Point Stage 6 at the router. True when something changed."""
    entries = manifest.stage_entries()
    changed = False
    for entry in entries:
        if entry.order != 6 or entry.name != "api":
            continue
        config = dict(entry.config or {})
        if config.get("provider") != ROUTER_PROVIDER:
            config["provider"] = ROUTER_PROVIDER
            entry.config = config
            changed = True
        # The legacy home. Leaving it behind would fail a strict manifest
        # load, and it is the exact field this migration exists to retire.
        strategies = dict(entry.strategies or {})
        if "provider" in strategies:
            strategies.pop("provider")
            entry.strategies = strategies
            changed = True
    if changed:
        manifest.set_stage_entries(entries)
    return changed


def migrate_environments_to_router(service: Any, *, rebind: Any = None) -> Dict[str, Any]:
    """Delete the superseded seeds, repoint everything else at the router.

    ``rebind`` is called with ``(old_env_id, new_env_id)`` for each session
    that was bound to a deleted seed, so the caller can move it rather than
    leaving it pointing at nothing.

    Never raises: a migration that stops the server is worse than one that
    leaves a stale environment for someone to notice.
    """
    result: Dict[str, Any] = {"deleted": [], "repointed": [], "rebound": 0}
    try:
        rows = service.list_all() or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("environment migration skipped: %s", exc)
        return result

    existing = {str(r.get("id") or r.get("env_id") or "") for r in rows}

    for env_id in SUPERSEDED_SEED_ENV_IDS:
        if env_id not in existing:
            continue
        # Move anything still bound to it BEFORE deleting, or the session
        # wakes up pointing at an environment that is not there.
        if rebind is not None:
            try:
                replacement = (
                    "template-vtuber-env" if "vtuber" in env_id else "template-worker-env"
                )
                result["rebound"] += int(rebind(env_id, replacement) or 0)
            except Exception as exc:  # noqa: BLE001
                logger.warning("environment migration: rebind from %s failed (%s)", env_id, exc)
        try:
            if service.delete(env_id):
                result["deleted"].append(env_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("environment migration: could not delete %s (%s)", env_id, exc)

    for row in rows:
        env_id = str(row.get("id") or row.get("env_id") or "")
        if not env_id or env_id in result["deleted"]:
            continue
        try:
            manifest = service.load_manifest(env_id)
            if manifest is None:
                continue
            before = _stage6_provider(manifest)
            if before == ROUTER_PROVIDER:
                continue
            if not _repoint(manifest):
                continue
            service._write_manifest(env_id, manifest)
            result["repointed"].append((env_id, before))
        except Exception as exc:  # noqa: BLE001
            logger.warning("environment migration: could not repoint %s (%s)", env_id, exc)

    if result["deleted"] or result["repointed"]:
        logger.info(
            "environments migrated to the one harness — deleted %d superseded seed(s), "
            "repointed %d environment(s) at %s (%s)",
            len(result["deleted"]), len(result["repointed"]), ROUTER_PROVIDER,
            ", ".join(f"{e}:{p}" for e, p in result["repointed"]) or "-",
        )
    return result
