import pytest

from app.core.config import settings
from app.core.security import CurrentUser
from app.schemas.astrology import DailyHoroscopeRequest
from app.services.openai_astrology import generate_daily_horoscope, normalize_sign


@pytest.mark.asyncio
async def test_mock_daily_horoscope_is_detailed(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    result = await generate_daily_horoscope(DailyHoroscopeRequest(sign="koc"), CurrentUser(uid="u1"))
    assert result.sign == "Koc"
    assert result.energy_score >= 0
    assert result.full_reading
    assert len(result.do_list) >= 3
    assert len(result.symbol_connections) >= 1


def test_normalize_turkish_sign():
    assert normalize_sign("koç") == "Koc"


@pytest.mark.asyncio
async def test_mock_daily_horoscope_differs_by_sign(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    koc = await generate_daily_horoscope(DailyHoroscopeRequest(sign="koc"), CurrentUser(uid="u1"))
    boga = await generate_daily_horoscope(DailyHoroscopeRequest(sign="boga"), CurrentUser(uid="u1"))
    assert koc.sign == "Koc"
    assert boga.sign == "Boga"
    assert koc.full_reading != boga.full_reading
    assert koc.lucky_color != boga.lucky_color
