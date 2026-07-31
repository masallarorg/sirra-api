import json

import pytest

from app.core.config import settings
from app.services import openai_fortune


def _generic_payload(fortune_type: str) -> dict:
    return {
        "fortune_id": f"{fortune_type}_runtime_1",
        "type": fortune_type,
        "title": "Görsel yorum",
        "summary": "Fotoğraf analizi tamamlandı.",
        "primary_message": "Semboller dengeli görünüyor.",
        "sections": [
            {"title": "Görünen işaret", "text": "Ana çizgi ve ışık dengesi belirgin."},
            {"title": "Yakın dönem", "text": "Daha net bir karar alanı oluşuyor."},
            {"title": "Duygusal tema", "text": "Sakin iletişim öne çıkıyor."},
            {"title": "Öneri", "text": "Acele etmeden gözlem yap."},
        ],
        "symbols": ["denge", "ışık"],
        "cross_fortune_connections": [],
        "premium_locks": [
            {"key": "deep", "title": "Derin katman", "teaser": "İkinci sembol katmanı."},
            {"key": "timing", "title": "Zamanlama", "teaser": "Yakın dönem ritmi."},
        ],
    }


@pytest.mark.asyncio
async def test_palm_uses_vision_model_and_extended_timeout(monkeypatch):
    observed = {}

    async def fake_responses(payload, **kwargs):
        observed["model"] = payload["model"]
        observed["timeout"] = kwargs.get("timeout_seconds")
        return {"output_text": json.dumps(_generic_payload("palm"), ensure_ascii=False)}

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(settings, "openai_vision_model", "vision-test-model")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fake_responses)

    await openai_fortune.generate_palm_fortune(
        user_id="image_user_123456",
        profile={"focus": "Genel enerji"},
        right_image_bytes=b"right-image",
        left_image_bytes=b"left-image",
    )

    assert observed["model"] == "vision-test-model"
    assert observed["timeout"] >= 120.0
