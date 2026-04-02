"""
Common utility functions.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# ── Legacy alias — kept for callers that import ``KST`` directly. ───
# It now resolves to the *configured* timezone at call time via the
# property-like helpers below.
KST = timezone(timedelta(hours=9))


def _configured_tz() -> ZoneInfo:
    """Return a ``ZoneInfo`` for the GENY_TIMEZONE env var (default Asia/Seoul)."""
    name = os.environ.get("GENY_TIMEZONE", "Asia/Seoul")
    try:
        return ZoneInfo(name)
    except (KeyError, Exception):
        return ZoneInfo("Asia/Seoul")


def _configured_tz_abbr() -> str:
    """Return a short abbreviation like KST, JST, UTC, etc."""
    return datetime.now(_configured_tz()).strftime("%Z")


def now_kst() -> datetime:
    """
    Return current time in the **configured** timezone.

    Despite the legacy name the function respects ``GENY_TIMEZONE``.

    Returns:
        datetime: Current time in the configured timezone.
    """
    return datetime.now(_configured_tz())


def to_kst(dt: datetime) -> datetime:
    """
    Convert given datetime to the **configured** timezone.

    Args:
        dt: datetime object to convert.

    Returns:
        datetime: datetime converted to the configured timezone.
    """
    if dt.tzinfo is None:
        # For naive datetime, assume UTC and convert
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_configured_tz())


def format_kst(dt: datetime) -> str:
    """
    Format datetime as a string in the **configured** timezone.

    Args:
        dt: datetime object to format.

    Returns:
        str: String in "YYYY-MM-DD HH:MM:SS <TZ>" format.
    """
    tz = _configured_tz()
    local_time = to_kst(dt)
    abbr = local_time.strftime("%Z")
    return local_time.strftime(f"%Y-%m-%d %H:%M:%S {abbr}")
