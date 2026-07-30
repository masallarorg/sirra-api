import json

import pytest

from app.core.config import settings
from app.services import openai_fortune


@pytest.mark.asyncio
async def test_real_palm_generation_uses_function_profile_not_mock_request(monkeypatch):
    """Regression: production palm flow must not reference mock-only `request`."""

    async def fake_responses(payload, **kwargs):
        assert payload["model"] == settings.openai_model
        content = payload["input"][0]["content"]
        prompt = json.loads(content[0]["text"])
        assert prompt["profile"]["focus"] == "Aşk"
        assert prompt["focus"] == "Aşk"
        return {
            "output_text": json.dumps(
                {
                    "fortune_id": "palm_regression_1",
                    "type": "palm",
                    "title": "İki Elin Çizgileri",
                    "summary": "İki elde de dengeli fakat farklılaşan çizgiler görülüyor.",
                    "primary_message": "Aşk odağında sabır ve net iletişim öne çıkıyor.",
                    "sections": [
                        {"title": "Sağ el", "text": "Sağ elde karar enerjisi belirgin."},
                        {"title": "Sol el", "text": "Sol elde duygusal derinlik öne çıkıyor."},
                        {"title": "Kalp çizgisi", "text": "İlişkide netlik ihtiyacı görülüyor."},
                        {"title": "Yakın dönem", "text": "Bir konuşma ihtimali güçleniyor."},
                    ],
                    "symbols": ["kalp_cizgisi", "denge"],
                    "cross_fortune_connections": [],
                    "premium_locks": [
                        {"key": "deep_love", "title": "Aşk Detayı", "teaser": "Derin ilişki katmanı."},
                        {"key": "timing", "title": "Zamanlama", "teaser": "Yakın dönem ritmi."},
                    ],
                },
                ensure_ascii=False,
            )
        }

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fake_responses)

    result = await openai_fortune.generate_palm_fortune(
        user_id="user_12345678",
        profile={"focus": "Aşk", "display_name": "Test"},
        right_image_bytes=b"right-palm",
        left_image_bytes=b"left-palm",
    )

    assert result.fortune_id == "palm_regression_1"
    assert result.type == "palm"
    assert result.follow_up_questions
    assert "aşk" in result.daily_ritual_prompt.lower()


@pytest.mark.asyncio
async def test_mock_palm_generation_still_works(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)

    result = await openai_fortune.generate_palm_fortune(
        user_id="user_1",
        profile={"focus": "Kariyer"},
        right_image_bytes=b"right",
        left_image_bytes=b"left",
    )

    assert result.type == "palm"
    assert result.sections
    assert result.symbols
