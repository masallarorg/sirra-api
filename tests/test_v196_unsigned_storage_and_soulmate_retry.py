import base64

import pytest

from app.core.config import settings
from app.services import object_storage, openai_fortune


def _configure_unsigned(monkeypatch):
    monkeypatch.setattr(settings, "cloudinary_enabled", True)
    monkeypatch.setattr(settings, "storage_provider", "cloudinary")
    monkeypatch.setattr(settings, "cloudinary_url", None)
    monkeypatch.setattr(settings, "cloudinary_cloud_name", "sirrafal")
    monkeypatch.setattr(settings, "cloudinary_api_key", None)
    monkeypatch.setattr(settings, "cloudinary_api_secret", None)
    monkeypatch.setattr(settings, "cloudinary_unsigned_upload_preset", "sirra_portraits_unsigned")
    monkeypatch.setattr(settings, "cloudinary_folder_root", "sirra")


def test_unsigned_preset_enables_storage_without_api_secret(monkeypatch):
    _configure_unsigned(monkeypatch)
    status = object_storage.storage_status()
    assert object_storage.storage_enabled() is True
    assert status["upload_auth"] == "unsigned_upload_preset"
    assert status["unsigned_preset_configured"] is True
    assert status["credentials_configured"] is False
    assert status["private_delivery"] is False


def test_unsigned_upload_path_returns_secure_url(monkeypatch):
    _configure_unsigned(monkeypatch)
    calls = {}

    def fake_unsigned(**kwargs):
        calls.update(kwargs)
        return {
            "public_id": kwargs["public_id"],
            "format": "jpg",
            "secure_url": "https://res.cloudinary.com/sirrafal/image/upload/test.jpg",
        }

    monkeypatch.setattr(object_storage, "_upload_with_unsigned_preset", fake_unsigned)
    stored = object_storage.upload_user_bytes(
        user_id="uid-1",
        category="soulmate_portraits",
        object_id="fortune-1",
        data=b"portrait",
        content_type="image/jpeg",
        extension="jpg",
    )

    assert stored is not None
    assert stored.url.endswith("/test.jpg")
    assert calls["cloud_name"] == "sirrafal"
    assert calls["upload_preset"] == "sirra_portraits_unsigned"
    assert calls["public_id"] == "sirra/users/uid-1/soulmate_portraits/fortune-1"


@pytest.mark.asyncio
async def test_soulmate_retries_invalid_structured_output_with_larger_budget(monkeypatch):
    calls = []
    valid = openai_fortune._fallback_soulmate_result(profile={"focus": "Aşk"}).model_dump(mode="json")

    async def fake_responses(payload, **kwargs):
        calls.append(payload["max_output_tokens"])
        if len(calls) == 1:
            return {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "output_text": "{\"fortune_id\": \"cut",
            }
        return {"status": "completed", "output_parsed": valid}

    async def fake_image(**kwargs):
        return base64.b64encode(b"jpeg-result").decode("ascii"), "image/jpeg"

    monkeypatch.setattr(settings, "mock_ai", False)
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_fortune, "call_openai_responses", fake_responses)
    monkeypatch.setattr(openai_fortune, "call_openai_image_generate", fake_image)

    result = await openai_fortune.generate_soulmate_fortune(
        user_id="user-retry",
        profile={"focus": "Aşk", "gender_identity": "Erkek"},
        image_bytes=b"selfie",
    )

    assert calls == [5200, 7600]
    assert result.type == "soulmate"
    assert result.portrait_image_base64
