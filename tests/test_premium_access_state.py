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
