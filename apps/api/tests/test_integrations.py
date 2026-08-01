import asyncio
import json

import httpx

from max_api.integrations import PravaClient, SwiggyClient
from max_api.schemas import Environment, Quote, QuoteLine


def test_swiggy_parsers_return_only_quote_safe_fields():
    payload = {
        "addresses": [{
            "addressId": "addr-safe",
            "addressCategory": "Home",
            "mobile": "must-not-escape",
            "lat": 12.34,
        }],
        "products": [{
            "displayName": "Amul Gold Milk 1 Ltr",
            "variations": [{
                "spinId": "S8PF9T8YLG",
                "isInStockAndAvailable": True,
                "price": {"offerPrice": "₹72"},
            }],
        }],
    }
    address = SwiggyClient._select_address(payload, "home")
    product = SwiggyClient._select_product(payload)
    assert address["addressId"] == "addr-safe"
    assert product == ("Amul Gold Milk 1 Ltr", "S8PF9T8YLG", 7200)
    assert "must-not-escape" not in json.dumps(product)


def test_prava_hosted_request_has_https_callback_and_discards_session_token(monkeypatch):
    monkeypatch.setenv("PRAVA_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("PRAVA_USER_ID", "owner-safe")
    monkeypatch.setenv("PRAVA_USER_EMAIL", "owner@example.test")
    monkeypatch.setenv("PRAVA_CALLBACK_URL", "https://max.example.test/payment-done")
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(201, json={
            "session_id": "ses_safe",
            "session_token": "must-not-be-returned",
            "iframe_url": "https://sandbox.collect.prava.space?session=ses_safe",
            "order_id": "ord_safe",
            "expires_at": "2026-08-01T12:15:00Z",
        })

    quote = Quote(
        revision=1,
        merchant="SWIGGY_INSTAMART",
        product_name="Milk",
        variant_id="spin-safe",
        quantity=2,
        amount_minor=14_700,
        currency="INR",
        destination="home",
        environment=Environment.PRODUCTION,
        expires_at="2026-08-01T12:15:00Z",
        line_items=[
            QuoteLine(description="Milk", unit_price_minor=7200, quantity=2),
            QuoteLine(description="Swiggy fees", unit_price_minor=300, quantity=1),
        ],
    )
    result = asyncio.run(PravaClient(httpx.MockTransport(handler)).create_session(quote))
    assert captured["integration_type"] == "full_checkout"
    assert captured["callback_url"].startswith("https://")
    assert captured["total_amount"] == "147.00"
    assert sum(
        int(float(line["unit_price"]) * 100) * line["quantity"]
        for line in captured["purchase_context"][0]["product_details"]
    ) == 14_700
    assert not hasattr(result, "session_token")
