import pytest
from pydantic import ValidationError

from app.schemas.live_guide import LiveGuideRequest
from app.services.natal_chart import calculate_natal_summary


SIGNS = {"Koç", "Boğa", "İkizler", "Yengeç", "Aslan", "Başak", "Terazi", "Akrep", "Yay", "Oğlak", "Kova", "Balık"}


def test_natal_summary_returns_complete_turkish_signs():
    result = calculate_natal_summary(
        birth_date="1992-05-12",
        birth_time="14:30",
        latitude=41.0082,
        longitude=28.9784,
        timezone_name="Europe/Istanbul",
    )
    assert result.sun_sign == "Boğa"
    assert result.moon_sign in SIGNS
    assert result.rising_sign in SIGNS
    assert result.quality in {"ephemeris", "approximate"}
    assert result.timezone == "Europe/Istanbul"


def test_live_guide_payload_is_limited_and_cleaned():
    request = LiveGuideRequest(
        message="  Bugünü yorumla  ",
        request_id="request_1234",
        conversation_id="conversation_1234",
        guide_style="mistik",
        persona_tags=[" ifade ", ""],
        profile={
            "display_name": " Aylin ",
            "moon_sign": "Yengeç",
            "credits": 999,
            "automatic_personalization": True,
        },
    )
    assert request.message == "Bugünü yorumla"
    assert request.persona_tags == ["ifade"]
    assert request.profile["display_name"] == "Aylin"
    assert "credits" not in request.profile


def test_live_guide_rejects_unknown_style():
    with pytest.raises(ValidationError):
        LiveGuideRequest(
            message="Merhaba",
            request_id="request_1234",
            conversation_id="conversation_1234",
            guide_style="unsupported",
        )
