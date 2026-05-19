from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.daily_access_clock import daily_access_key


def test_daily_access_key_rolls_at_2359_istanbul():
    tz = ZoneInfo("Europe/Istanbul")
    assert daily_access_key(datetime(2026, 5, 19, 23, 58, 59, tzinfo=tz)) == "2026-05-19"
    assert daily_access_key(datetime(2026, 5, 19, 23, 59, 0, tzinfo=tz)) == "2026-05-20"
    assert daily_access_key(datetime(2026, 5, 20, 0, 0, 0, tzinfo=tz)) == "2026-05-20"
