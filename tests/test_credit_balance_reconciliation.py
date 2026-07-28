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
