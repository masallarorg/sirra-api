import json

import pytest

from app.core.config import settings
from app.schemas.fortune import GenericFortuneRequest
from app.services import openai_fortune


def _payload(fortune_type: str) -> dict:
    return {
        "fortune_id": f"{fortune_type}_v198",
        "type": fortune_type,
        "title": "Yakın gelecek yorumu",
        "summary": "Bekleyen konu daha açık bir yola giriyor.",
        "primary_message": "Önümüzdeki haftalarda haber ve karar enerjisi güçlenebilir.",
        "sections": [
            {"title": "Geçmişten gelen iz", "text": "Yarım kalan bir karar etkisini sürdürüyor."},
            {"title": "Bugünkü dönüm noktası", "text": "Daha net sınırlar oluşuyor."},
            {"title": "Yakın gelecek", "text": "Bir mesaj veya görüşme ihtimali güçleniyor."},
            {"title": "Umut veren yön", "text": "Gecikmenin ardından yeni bir kapı açılabilir."},
        ],
        "symbols": ["mesaj", "yol"],
        "cross_fortune_connections": [],
        "premium_locks": [
            {"key": "deep", "title": "Derin yorum", "teaser": "Ek işaretler."},
            {"key": "timing", "title": "Zamanlama", "teaser": "Yakın dönem."},
        ],
    }


@pytest.mark.asyncio
async def test_generic_fortune_uses_bounded_single_attempt(monkeypatch):
    observed = {}

    async def fake_responses(payload, **kwargs):
        observed.update(kwargs)
        return {"output_text": json.dumps(_payload("tarot"), ensure_ascii=False)}

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fake_responses)

    result = await openai_fortune.generate_generic_fortune(
        GenericFortuneRequest(type_id="tarot", focus="Aşk", payload={"cards": ["Ay"]}, profile={})
    )

    assert result.type == "tarot"
    assert observed["retries_override"] == 0
    assert observed["timeout_seconds"] <= 60.0


@pytest.mark.asyncio
async def test_generic_fortune_returns_safe_fallback_instead_of_hanging(monkeypatch):
    async def fake_responses(payload, **kwargs):
        raise TimeoutError("upstream stalled")

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fake_responses)

    result = await openai_fortune.generate_generic_fortune(
        GenericFortuneRequest(type_id="katina", focus="Gelecek", payload={"cards": ["Mesaj"]}, profile={})
    )

    assert result.type == "katina"
    assert result.summary
    assert result.primary_message
    assert len(result.sections) >= 4
