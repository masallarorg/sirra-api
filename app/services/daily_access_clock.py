from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ACCESS_TIMEZONE = ZoneInfo("Europe/Istanbul")
DAILY_RESET_HOUR = 0
DAILY_RESET_MINUTE = 1


def daily_access_key(now: datetime | None = None) -> str:
    """Return the entitlement day key used for daily limits.

    Premium users receive a fresh 5-right allowance every day at 00:01
    Turkey time. Between 00:00:00 and 00:00:59 we still use the previous
    calendar day, so the visible reset happens at exactly 00:01.
    """
    current = now or datetime.now(ACCESS_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ACCESS_TIMEZONE)
    local = current.astimezone(ACCESS_TIMEZONE)
    if (local.hour, local.minute) < (DAILY_RESET_HOUR, DAILY_RESET_MINUTE):
        local = local - timedelta(days=1)
    return local.date().isoformat()


def local_calendar_day_key(now: datetime | None = None) -> str:
    current = now or datetime.now(ACCESS_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ACCESS_TIMEZONE)
    return current.astimezone(ACCESS_TIMEZONE).date().isoformat()
