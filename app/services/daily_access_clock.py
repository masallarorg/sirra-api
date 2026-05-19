from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ACCESS_TIMEZONE = ZoneInfo("Europe/Istanbul")
DAILY_RESET_HOUR = 23
DAILY_RESET_MINUTE = 59


def daily_access_key(now: datetime | None = None) -> str:
    """Return the entitlement day key used for daily limits.

    Premium users must have a fresh 5-right allowance every day at 23:59
    Turkey time.  We intentionally roll the key to the next calendar day once
    local time reaches 23:59, so a user with 2/5 remaining immediately sees
    a full 5/5 allowance at that time.
    """
    current = now or datetime.now(ACCESS_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ACCESS_TIMEZONE)
    local = current.astimezone(ACCESS_TIMEZONE)
    if (local.hour, local.minute) >= (DAILY_RESET_HOUR, DAILY_RESET_MINUTE):
        local = local + timedelta(days=1)
    return local.date().isoformat()


def local_calendar_day_key(now: datetime | None = None) -> str:
    current = now or datetime.now(ACCESS_TIMEZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=ACCESS_TIMEZONE)
    return current.astimezone(ACCESS_TIMEZONE).date().isoformat()
