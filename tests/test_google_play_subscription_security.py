from app.api.v1.routes.subscriptions import _subscription_product_ids_from_google


def test_extracts_verified_subscription_product_ids():
    data = {
        "lineItems": [
            {"productId": "sirra_premium_monthly", "expiryTime": "2099-01-01T00:00:00Z"},
            {"productId": "sirra_premium_yearly"},
            {"productId": ""},
            "invalid",
        ]
    }
    assert _subscription_product_ids_from_google(data) == {
        "sirra_premium_monthly",
        "sirra_premium_yearly",
    }


def test_missing_line_items_never_trusts_client_product_id():
    assert _subscription_product_ids_from_google({}) == set()
    assert _subscription_product_ids_from_google({"lineItems": "bad"}) == set()
