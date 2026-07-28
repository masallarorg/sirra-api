from datetime import UTC, datetime, timedelta

from app.services.monetization_guard import _is_subscription_active, _subscription_expires_at


def test_active_premium_requires_expiry_by_default():
    assert _is_subscription_active({"active": True, "entitlement": "premium"}) is False


def test_active_premium_accepts_future_expiry():
    future = datetime.now(UTC) + timedelta(days=3)
    assert _is_subscription_active({"active": True, "entitlement": "premium", "expires_at": future.isoformat()}) is True


def test_active_premium_rejects_expired_expiry():
    past = datetime.now(UTC) - timedelta(minutes=1)
    assert _is_subscription_active({"active": True, "entitlement": "premium", "expires_at": past.isoformat()}) is False


def test_legacy_product_duration_infers_expiry_from_created_at():
    created_at = datetime.now(UTC) - timedelta(days=10)
    data = {"active": True, "entitlement": "premium", "product_id": "sirra_premium_monthly", "created_at": created_at.isoformat()}
    expires = _subscription_expires_at(data)
    assert expires is not None
    assert expires.date() == (created_at + timedelta(days=30)).date()
    assert _is_subscription_active(data) is True


def test_lifetime_premium_is_explicit_only():
    assert _is_subscription_active({"active": True, "entitlement": "premium", "lifetime": True}) is True
