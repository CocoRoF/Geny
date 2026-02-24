"""
Common utility functions.
"""
from datetime import datetime, timezone, timedelta

# Asia/Seoul timezone (UTC+9)
KST = timezone(timedelta(hours=9))

def now_kst() -> datetime:
    """
    Return current time in KST (Asia/Seoul, UTC+9) timezone.

    Returns:
        datetime: Current time in KST timezone.
    """
    return datetime.now(KST)

def to_kst(dt: datetime) -> datetime:
    """
    Convert given datetime to KST timezone.

    Args:
        dt: datetime object to convert.

    Returns:
        datetime: datetime converted to KST timezone.
    """
    if dt.tzinfo is None:
        # For naive datetime, assume UTC and convert to KST
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)

def format_kst(dt: datetime) -> str:
    """
    Format datetime as KST string.

    Args:
        dt: datetime object to format.

    Returns:
        str: String in "YYYY-MM-DD HH:MM:SS KST" format.
    """
    kst_time = to_kst(dt)
    return kst_time.strftime("%Y-%m-%d %H:%M:%S KST")
