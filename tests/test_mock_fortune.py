import pytest

from app.core.config import settings
from app.services.openai_fortune import generate_coffee_fortune


@pytest.mark.asyncio
async def test_mock_coffee_fortune_has_symbols(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    result = await generate_coffee_fortune(user_id="u1", profile={}, image_count=3)
    assert result.type == "coffee"
    assert len(result.detected_symbols) >= 1
    assert result.detected_symbols[0].image_region.x >= 0
