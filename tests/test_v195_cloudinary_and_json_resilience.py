import io
import sys
import types

from app.services import object_storage
from app.services.openai_client import extract_output_json


def _configure_cloudinary(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "cloudinary_enabled", True)
    monkeypatch.setattr(object_storage.settings, "storage_provider", "cloudinary")
    monkeypatch.setattr(object_storage.settings, "cloudinary_url", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_cloud_name", "sirrafal")
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_key", "123456789012345")
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_secret", "secret-not-logged")
    monkeypatch.setattr(object_storage.settings, "cloudinary_folder_root", "sirra")


def test_cloudinary_sdk_authorization_error_retries_basic_auth(monkeypatch):
    _configure_cloudinary(monkeypatch)
    calls = {}

    cloudinary_module = types.ModuleType("cloudinary")
    cloudinary_module.__path__ = []
    cloudinary_module.config = lambda **kwargs: calls.setdefault("config", kwargs)

    uploader_module = types.ModuleType("cloudinary.uploader")

    def fake_upload(payload: io.BytesIO, **kwargs):
        assert payload.read() == b"portrait"
        raise RuntimeError("AuthorizationRequired")

    uploader_module.upload = fake_upload
    cloudinary_module.uploader = uploader_module

    utils_module = types.ModuleType("cloudinary.utils")
    utils_module.cloudinary_url = lambda public_id, **kwargs: (
        "https://signed.example/portrait.jpg",
        {},
    )

    monkeypatch.setitem(sys.modules, "cloudinary", cloudinary_module)
    monkeypatch.setitem(sys.modules, "cloudinary.uploader", uploader_module)
    monkeypatch.setitem(sys.modules, "cloudinary.utils", utils_module)

    def fake_basic_auth_upload(**kwargs):
        calls["basic"] = kwargs
        return {
            "public_id": kwargs["public_id"],
            "format": "jpg",
            "version": 7,
        }

    monkeypatch.setattr(object_storage, "_upload_with_basic_auth", fake_basic_auth_upload)

    stored = object_storage.upload_user_bytes(
        user_id="uid-1",
        category="soulmate_portraits",
        object_id="fortune-1",
        data=b"portrait",
        content_type="image/jpeg",
        extension="jpg",
    )

    assert stored is not None
    assert stored.url == "https://signed.example/portrait.jpg"
    assert calls["basic"]["cloud_name"] == "sirrafal"
    assert calls["basic"]["api_key"] == "123456789012345"
    assert calls["basic"]["api_secret"] == "secret-not-logged"


def test_cloudinary_environment_values_are_normalized(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "cloudinary_enabled", True)
    monkeypatch.setattr(object_storage.settings, "cloudinary_url", None)
    monkeypatch.setattr(object_storage.settings, "cloudinary_cloud_name", '"CLOUDINARY_CLOUD_NAME=sirrafal"')
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_key", "CLOUDINARY_API_KEY=123456")
    monkeypatch.setattr(object_storage.settings, "cloudinary_api_secret", "'CLOUDINARY_API_SECRET=abc-secret'")
    assert object_storage.settings.cloudinary_credentials == (
        "sirrafal",
        "123456",
        "abc-secret",
    )


def test_structured_output_json_accepts_markdown_fence():
    response = {
        "output_text": "```json\n{\"fortune_id\": \"soulmate_1\", \"type\": \"soulmate\"}\n```"
    }
    parsed = extract_output_json(response)
    assert parsed["fortune_id"] == "soulmate_1"


def test_structured_output_json_accepts_leading_and_trailing_text():
    response = {
        "output_text": "Hazırlanan sonuç:\n{\"fortune_id\": \"soulmate_2\", \"type\": \"soulmate\"}\nTamamlandı."
    }
    parsed = extract_output_json(response)
    assert parsed["fortune_id"] == "soulmate_2"


def test_structured_output_json_prefers_parsed_object():
    response = {"output_parsed": {"fortune_id": "soulmate_3", "type": "soulmate"}}
    parsed = extract_output_json(response)
    assert parsed["fortune_id"] == "soulmate_3"
