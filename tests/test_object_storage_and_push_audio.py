from app.services import object_storage, push_notifications


def test_storage_status_is_safe_without_credentials(monkeypatch):
    monkeypatch.setattr(object_storage.settings, "r2_enabled", False)
    status = object_storage.storage_status()
    assert status["provider"] == "r2"
    assert status["enabled"] is False


def test_push_audio_profiles_are_type_specific():
    coffee = push_notifications._audio_profile(message_type="fortune_ready", fortune_type="coffee")
    tarot = push_notifications._audio_profile(message_type="fortune_ready", fortune_type="tarot")
    premium = push_notifications._audio_profile(message_type="premium", fortune_type=None)
    assert coffee != tarot
    assert premium[1] == "sirra_premium_voice"
