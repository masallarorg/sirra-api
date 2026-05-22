from datetime import UTC, datetime, timedelta

from app.services.monetization_guard import latest_credit_balance


def test_latest_credit_balance_allows_newer_admin_decrease():
    old = datetime(2026, 5, 22, 8, 0, tzinfo=UTC)
    new = old + timedelta(minutes=5)

    assert latest_credit_balance(
        {"credits": 20, "credits_updated_at": old},
        {"credits": 5, "updated_at": new},
        default=7,
    ) == 5


def test_latest_credit_balance_keeps_highest_when_versions_unknown():
    assert latest_credit_balance({"credits": 20}, {"credits": 5}, default=7) == 20


def test_latest_credit_balance_uses_single_existing_document():
    assert latest_credit_balance(None, {"credits": 3}, default=7) == 3
