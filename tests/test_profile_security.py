from app.api.v1.routes.profile import _payload_from_profile
from app.core.security import CurrentUser
from app.schemas.profile import UserProfile


def test_profile_payload_drops_financial_and_device_local_fields():
    profile = UserProfile(
        display_name="Test User",
        email="test@example.com",
        selfie_path="/data/user/0/app/cache/private.jpg",
        is_premium=True,
        premium_until="2099-01-01T00:00:00Z",
        notification_opt_in=True,
    )
    current = CurrentUser(uid="uid-1", email="verified@example.com", name="Verified")

    payload = _payload_from_profile(profile, current)

    assert "selfie_path" not in payload
    assert "is_premium" not in payload
    assert "premium_until" not in payload
    assert "credits" not in payload
    assert payload["uid"] == "uid-1"
    assert payload["notification_opt_in"] is True
