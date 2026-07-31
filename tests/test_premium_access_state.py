from app.schemas.fortune import FortuneAccessState


def test_premium_exhausted_access_state_exposes_credit_notice():
    access = FortuneAccessState(
        credits=12,
        charged_credits=5,
        access_kind="credits",
        premium_daily_used=5,
        premium_used=5,
        premium_daily_limit=5,
        premium_daily_remaining=0,
        premium_daily_exhausted=True,
        standard_free_daily_used=0,
        free_used=0,
        daily_date="2026-05-21",
        is_premium=True,
        user_message="Bugünkü 5 premium fal hakkın bitti. Bu falda 5 kredi kullanılıyor.",
    )

    data = access.model_dump()
    assert data["access_kind"] == "credits"
    assert data["charged_credits"] == 5
    assert data["premium_daily_exhausted"] is True
    assert data["premium_daily_remaining"] == 0
    assert "kredi kullanılıyor" in data["user_message"]
    assert data["daily_reset_timezone"] == "Europe/Istanbul"



def test_premium_access_state_preserves_entitlement_metadata_after_fortune():
    """Regression: image/text fortune response models must not strip premium expiry.

    The mobile app applies the access object returned after every interpretation.
    Dropping these fields caused an active premium user to appear standard after
    the first successful reading.
    """
    access = FortuneAccessState(
        credits=9,
        charged_credits=0,
        access_kind="premium_daily",
        premium_daily_used=1,
        premium_used=1,
        premium_daily_limit=5,
        premium_daily_remaining=4,
        daily_date="2026-07-31",
        is_premium=True,
        expires_at="2026-08-30T12:00:00+00:00",
        premium_until="2026-08-30T12:00:00+00:00",
        lifetime=False,
        lifetime_premium=False,
        authoritative_subscription_state=True,
        subscription_provider="admin",
    )

    data = access.model_dump()
    assert data["is_premium"] is True
    assert data["charged_credits"] == 0
    assert data["access_kind"] == "premium_daily"
    assert data["premium_daily_remaining"] == 4
    assert data["expires_at"] == "2026-08-30T12:00:00+00:00"
    assert data["premium_until"] == data["expires_at"]
    assert data["authoritative_subscription_state"] is True
