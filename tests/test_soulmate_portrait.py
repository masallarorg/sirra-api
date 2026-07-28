import base64

import pytest

from app.core.config import settings
from app.services.openai_fortune import generate_soulmate_portrait_image


@pytest.mark.asyncio
async def test_mock_soulmate_portrait_is_valid_jpeg() -> None:
    previous = settings.mock_ai
    settings.mock_ai = True
    try:
        encoded, mime = await generate_soulmate_portrait_image(
            user_id="user_test",
            profile={"focus": "Aşk", "zodiac_sign": "Boğa"},
            image_bytes=b"not-used-in-mock",
            target_gender="male",
            portrait_style="Sinematik ve doğal",
        )
    finally:
        settings.mock_ai = previous

    raw = base64.b64decode(encoded)
    assert mime == "image/jpeg"
    assert raw[:2] == b"\xff\xd8"
    assert raw[-2:] == b"\xff\xd9"
    assert len(raw) > 5_000


@pytest.mark.asyncio
async def test_mock_soulmate_portrait_accepts_surprise_preference() -> None:
    previous = settings.mock_ai
    settings.mock_ai = True
    try:
        encoded, mime = await generate_soulmate_portrait_image(
            user_id="user_test",
            profile={},
            image_bytes=b"ignored",
            target_gender="surprise",
            portrait_style="Suluboya",
        )
    finally:
        settings.mock_ai = previous

    assert mime == "image/jpeg"
    assert base64.b64decode(encoded).startswith(b"\xff\xd8")
