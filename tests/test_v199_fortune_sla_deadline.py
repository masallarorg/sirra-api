from pathlib import Path

from app.api.v1.routes import fortunes
from app.schemas.fortune import GenericFortuneRequest
from app.services.openai_fortune import (
    build_deadline_generic_fallback,
    build_deadline_soulmate_fallback,
)


def test_generation_deadlines_fit_premium_one_minute_window():
    assert fortunes.TEXT_GENERATION_DEADLINE_SECONDS <= 35
    assert fortunes.IMAGE_GENERATION_DEADLINE_SECONDS <= 40
    assert fortunes.PROFILE_ENRICHMENT_DEADLINE_SECONDS <= 3


def test_local_fallbacks_are_complete_and_immediate():
    request = GenericFortuneRequest(
        type_id="tarot",
        focus="Aşk",
        payload={"cards": ["Güneş"]},
        profile={"display_name": "Test"},
    )
    result = build_deadline_generic_fallback(request, reason="test")
    assert result.fortune_id
    assert result.type == "tarot"
    assert result.summary
    assert result.primary_message
    assert result.sections

    soulmate = build_deadline_soulmate_fallback(
        user_id="test-user",
        profile={
            "focus": "Aşk",
            "gender_identity": "Erkek",
            "soulmate_portrait_preference": "Karşı cins (otomatik)",
        },
        reason="test",
    )
    assert soulmate.type == "soulmate"
    assert soulmate.portrait_image_base64
    assert soulmate.portrait_mime_type == "image/jpeg"


def test_cloudinary_and_history_are_after_response_tasks():
    source = Path(fortunes.__file__).read_text(encoding="utf-8")
    assert "background_tasks.add_task(_finalize_soulmate_after_response" in source
    assert "await asyncio.wait_for(" in source
    assert "Cloudinary is intentionally after-response" in source
