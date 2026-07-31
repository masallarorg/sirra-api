import io
import sys
import types

from app.services import object_storage, push_notifications


def test_storage_status_is_safe_without_credentials(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "cloudinary_enabled", True)
    monkeypatch.setattr(object_storage.settings, "cloudinary_url", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_cloud_name", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_key", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_secret", None)
    status = object_storage.storage_status()
    assert status["provider"] == "cloudinary"
    assert status["enabled"] is False
    assert status["private_delivery"] is True


def test_cloudinary_url_credentials_are_parsed(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "cloudinary_enabled", True)
    monkeypatch.setattr(
        object_storage.settings,
        "cloudinary_url",
        "cloudinary://12345:secret-value@sample-cloud",
    )
    monkeypatch.setattr(object_storage.settings, "cloudinary_cloud_name", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_key", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_secret", None)
    assert object_storage.settings.cloudinary_credentials == (
        "sample-cloud",
        "12345",
        "secret-value",
    )
    assert object_storage.storage_enabled() is True


def test_cloudinary_upload_uses_authenticated_delivery(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "cloudinary_enabled", True)
    monkeypatch.setattr(object_storage.settings, "storage_provider", "cloudinary")
    monkeypatch.setattr(object_storage.settings, "cloudinary_url", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_cloud_name", "sample-cloud")
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_key", "123")
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_secret", "secret")
    monkeypatch.setattr(object_storage.settings, "cloudinary_folder_root", "sirra")

    calls: dict[str, object] = {}

    cloudinary_module = types.ModuleType("cloudinary")
    cloudinary_module.__path__ = []

    def fake_config(**kwargs):
        calls["config"] = kwargs

    cloudinary_module.config = fake_config

    uploader_module = types.ModuleType("cloudinary.uploader")

    def fake_upload(payload: io.BytesIO, **kwargs):
        calls["upload"] = kwargs
        assert payload.read() == b"image-bytes"
        return {
            "public_id": kwargs["public_id"],
            "format": "png",
            "version": 42,
        }

    uploader_module.upload = fake_upload
    cloudinary_module.uploader = uploader_module

    utils_module = types.ModuleType("cloudinary.utils")

    def fake_cloudinary_url(public_id: str, **kwargs):
        calls["url"] = {"public_id": public_id, **kwargs}
        return "https://signed.example/portrait.png", {}

    utils_module.cloudinary_url = fake_cloudinary_url

    monkeypatch.setitem(sys.modules, "cloudinary", cloudinary_module)
    monkeypatch.setitem(sys.modules, "cloudinary.uploader", uploader_module)
    monkeypatch.setitem(sys.modules, "cloudinary.utils", utils_module)

    stored = object_storage.upload_user_bytes(
        user_id="uid-1",
        category="soulmate_portraits",
        object_id="fortune-1",
        data=b"image-bytes",
        content_type="image/png",
        extension="png",
    )

    assert stored is not None
    assert stored.provider == "cloudinary"
    assert stored.key == "sirra/users/uid-1/soulmate_portraits/fortune-1"
    assert stored.url == "https://signed.example/portrait.png"
    assert calls["upload"]["type"] == "authenticated"
    assert calls["url"]["sign_url"] is True
    assert calls["url"]["type"] == "authenticated"


def test_push_audio_profiles_are_type_specific():
    coffee = push_notifications._audio_profile(message_type="fortune_ready", fortune_type="coffee")
    tarot = push_notifications._audio_profile(message_type="fortune_ready", fortune_type="tarot")
    premium = push_notifications._audio_profile(message_type="premium", fortune_type=None)
    assert coffee != tarot
    assert premium[1] == "sirra_premium_voice"
