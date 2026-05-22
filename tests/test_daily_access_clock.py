from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.daily_access_clock import daily_access_key


def test_daily_access_key_rolls_at_0001_istanbul():
    tz = ZoneInfo("Europe/Istanbul")
    assert daily_access_key(datetime(2026, 5, 19, 23, 59, 59, tzinfo=tz)) == "2026-05-19"
    assert daily_access_key(datetime(2026, 5, 20, 0, 0, 59, tzinfo=tz)) == "2026-05-19"
    assert daily_access_key(datetime(2026, 5, 20, 0, 1, 0, tzinfo=tz)) == "2026-05-20"
