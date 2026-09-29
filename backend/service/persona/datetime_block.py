"""The date line in Geny's time zone.

The executor's ``DateTimeBlock`` reads ``GENY_TIMEZONE`` then ``TZ``. Geny's
own rule — the one its database, cron and memory stamps follow — is
``GENY_TIMEZONE``, then the legacy ``TIMEZONE``, then Asia/Seoul; the
production container sets only ``TIMEZONE``, so the executor's reading fell
through to UTC. Read on every render, so a timezone change in the settings
applies from the next turn.
"""

from __future__ import annotations

import os
from typing import Any

from geny_executor.stages.s03_system.artifact.default.builders import DateTimeBlock


def geny_timezone_name() -> str:
    return os.environ.get("GENY_TIMEZONE") or os.environ.get("TIMEZONE") or "Asia/Seoul"


class GenyDateTimeBlock(DateTimeBlock):
    def _zone(self) -> Any:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(geny_timezone_name())
        except Exception:  # noqa: BLE001 — an unknown zone: the executor's rule
            return super()._zone()


__all__ = ["GenyDateTimeBlock", "geny_timezone_name"]
