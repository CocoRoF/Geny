"""Remove the environments that no longer do anything.

There is one environment — the pipeline every agent runs. The others are
what is left of a system where you had to pick one before you could have an
agent: three seeds and a copy for every agent anyone wanted to give a
different persona to. Nothing reads them now. A session's persona, tools,
companion and sub-workers hang off the session itself, and
``migrate_session_attachments`` moved every inherited choice there before the
link was cut.

So they are unreachable rather than merely unused, which is the same thing
the room janitor deals with: no UI lists them, no session resolves through
them, and nothing can create another. They are backed up and removed.

Dry by default, and it refuses to delete without a backup path.

    python -m service.environment.prune                      # report only
    python -m service.environment.prune --apply --backup /data/envs.json
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def survey(service: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Which environment stays and which go."""
    from service.environment.templates import WORKER_ENV_ID

    keep: List[Dict[str, Any]] = []
    drop: List[Dict[str, Any]] = []
    for row in service.list_all() or []:
        (keep if row.get("id") == WORKER_ENV_ID else drop).append(row)
    return {"keep": keep, "drop": drop}


def sessions_still_pointing(session_store: Any, env_ids: set) -> List[str]:
    """Sessions whose record still names one of these.

    Not a blocker — every session resolves to the one environment whatever
    its record says — but worth printing, because it is the difference
    between "nothing references these" and "nothing USES these".
    """
    try:
        return [
            str(r.get("session_id"))
            for r in (session_store.list_all() or [])
            if r.get("env_id") in env_ids
        ]
    except Exception:  # noqa: BLE001
        logger.debug("could not list sessions", exc_info=True)
        return []


def prune(
    service: Any,
    *,
    apply: bool = False,
    backup: Optional[Path] = None,
    session_store: Any = None,
) -> Dict[str, Any]:
    plan = survey(service)
    drop = plan["drop"]
    result: Dict[str, Any] = {
        "kept": [r.get("id") for r in plan["keep"]],
        "dropped": [r.get("id") for r in drop],
        "pointing_sessions": [],
    }
    if session_store is not None and drop:
        result["pointing_sessions"] = sessions_still_pointing(
            session_store, {r.get("id") for r in drop},
        )
    if not apply or not drop:
        return result

    if backup is None:
        raise ValueError("refusing to delete environments without a backup path")

    payload = {
        "written_at": datetime.now(timezone.utc).isoformat(),
        "reason": "one environment — the rest no longer do anything",
        "environments": [],
    }
    for row in drop:
        env_id = row.get("id")
        try:
            payload["environments"].append(service.load(env_id) or row)
        except Exception:  # noqa: BLE001
            payload["environments"].append(row)
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("[environments] backed up %d to %s", len(drop), backup)

    for row in drop:
        env_id = row.get("id")
        try:
            service.delete(env_id)
            logger.info("[environments] removed %s (%s)", env_id, row.get("name"))
        except Exception:  # noqa: BLE001
            logger.error("[environments] could not remove %s", env_id, exc_info=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", default="/data/mcp/environment-prune-backup.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from service.database import APPLICATION_MODELS, AppDatabaseManager
    from service.environment.service import EnvironmentService
    from service.sessions.store import get_session_store

    # Environments live in PostgreSQL with a JSON copy on disk, and the
    # running server reads the database. A service that was never handed one
    # deletes the files and leaves the rows — the same trap the room janitor
    # fell into, and it looks exactly like a prune that did nothing.
    try:
        app_db = AppDatabaseManager()
        app_db.register_models(APPLICATION_MODELS)
        if not app_db.initialize_connection():
            print("could not connect to PostgreSQL — nothing was touched")
            return 2
    except Exception:  # noqa: BLE001
        logger.error("no database", exc_info=True)
        return 2

    service = EnvironmentService()
    service.set_database(app_db)
    sessions = get_session_store()
    sessions.set_database(app_db)
    if not service._db_available:
        print("the environment store is not reading from the database")
        return 2

    result = prune(
        service,
        apply=args.apply,
        backup=Path(args.backup) if args.apply else None,
        session_store=sessions,
    )
    print("keep   :", result["kept"])
    print("remove :", len(result["dropped"]), result["dropped"])
    if result["pointing_sessions"]:
        print(
            f"         {len(result['pointing_sessions'])} session(s) still name one; "
            "they resolve to the one environment regardless",
        )
    print("APPLIED" if args.apply else "DRY RUN — pass --apply to carry it out")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
