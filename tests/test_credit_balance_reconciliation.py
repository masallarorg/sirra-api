<<<<<<< HEAD
from app.services.monetization_guard import latest_credit_balance


def test_monetization_document_is_always_authoritative():
    assert latest_credit_balance(
        {"credits": 20},
        {"credits": 999999, "financial_source": "client"},
        default=7,
    ) == 20


def test_untrusted_users_document_cannot_mint_credits():
    assert latest_credit_balance(None, {"credits": 999999}, default=7) == 7


def test_trusted_migration_fallback_is_supported():
    assert latest_credit_balance(
        None,
        {"credits": 3, "financial_source": "admin_migration_v2"},
        default=7,
    ) == 3


def test_default_is_clamped_to_zero():
    assert latest_credit_balance(None, None, default=-10) == 0
=======
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
>>>>>>> 5d0b703df471b4dc80f84320abb737f4a7605041
