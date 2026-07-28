import pytest

from app.core.config import settings
from app.services.sirra_compass import build_sirra_compass, record_fortune_feedback


@pytest.mark.asyncio
async def test_sirra_compass_demo_is_transparent(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    payload = await build_sirra_compass("u1")
    assert payload["daily_symbol"]["display_name"]
    assert "takip" in payload["trust_message"].lower()
    assert payload["daily_loop"]
    assert payload["probability_map_30d"]


@pytest.mark.asyncio
async def test_record_feedback_demo_accepts_status(monkeypatch):
    monkeypatch.setattr(settings, "mock_ai", True)
    payload = await record_fortune_feedback(user_id="u1", fortune_id="f1", status="realized", note="Oldu")
    assert payload["fortune_id"] == "f1"
    assert payload["feedback_status"] == "realized"
