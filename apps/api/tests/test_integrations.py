import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx

import max_api.integrations as integrations
from max_api.integrations import IntegrationError, PravaClient, SwiggyBrowserCheckout, SwiggyClient, _tool_arguments
from max_api.schemas import BudgetMeaning, Environment, Quote, QuoteLine, ShoppingIntent


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


def test_swiggy_live_update_cart_contract():
    tool = SimpleNamespace(inputSchema={
        "properties": {"selectedAddressId": {}, "items": {}},
        "required": ["selectedAddressId", "items"],
    })
    values = {
        "selectedAddressId": "addr-safe",
        "items": [{"spinId": "spin-safe", "quantity": 1}],
        "addressId": "old-contract",
    }
    assert _tool_arguments(tool, values) == {
        "selectedAddressId": "addr-safe",
        "items": [{"spinId": "spin-safe", "quantity": 1}],
    }


def test_swiggy_rejects_an_unserviceable_cart():
    try:
        SwiggyClient._assert_cart_serviceable({
            "data": {"cartWarning": {"statusCode": 135, "message": "The selected address is not serviceable."}},
            "message": "Do NOT proceed to checkout until it is resolved.",
        })
    except IntegrationError as exc:
        assert "not serviceable" in str(exc)
    else:
        raise AssertionError("unserviceable cart was accepted")


def test_swiggy_quote_clears_and_verifies_an_existing_cart(monkeypatch):
    def result(payload):
        return SimpleNamespace(isError=False, structuredContent=payload, content=[])

    class Session:
        calls = []
        cart_reads = 0

        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def initialize(self): pass
        async def list_tools(self):
            schemas = {
                "get_addresses": {}, "get_cart": {}, "clear_cart": {},
                "search_products": {"addressId": {}, "query": {}},
                "update_cart": {"selectedAddressId": {}, "items": {}},
            }
            return SimpleNamespace(tools=[
                SimpleNamespace(name=name, inputSchema={"properties": properties, "required": []})
                for name, properties in schemas.items()
            ])
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            if name == "get_addresses":
                return result({"addresses": [{"addressId": "addr-safe", "addressCategory": "Work"}]})
            if name == "get_cart":
                self.cart_reads += 1
                return result(({"totalItems": 1}, {"totalItems": 0}, {"cartTotalAmount": "72.00"})[self.cart_reads - 1])
            if name == "search_products":
                return result({"products": [{"displayName": "Milk", "variations": [{
                    "spinId": "spin-safe", "isInStockAndAvailable": True, "price": {"offerPrice": "₹72"},
                }]}]})
            return result({})

    session = Session()

    @asynccontextmanager
    async def stdio(*_args, **_kwargs):
        yield object(), object()

    monkeypatch.setattr(integrations, "stdio_client", stdio)
    monkeypatch.setattr(integrations, "ClientSession", lambda *_args: session)
    intent = ShoppingIntent(
        item="milk", quantity=1, budget_meaning=BudgetMeaning.MAXIMUM,
        budget_max_minor=30_000, destination="work",
    )
    quote = asyncio.run(SwiggyClient().quote(intent))
    assert quote.amount_minor == 7_200
    assert [name for name, _args in session.calls[:4]] == ["get_addresses", "get_cart", "clear_cart", "get_cart"]


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


def test_browser_amount_guard_accepts_only_the_approved_total():
    assert SwiggyBrowserCheckout._has_amount("To Pay ₹147.00", 14_700)
    assert not SwiggyBrowserCheckout._has_amount("To Pay ₹148.00", 14_700)
    assert SwiggyBrowserCheckout._cart_unavailable("This Instamart store is currently unserviceable")


def test_prava_callback_is_optional(monkeypatch):
    monkeypatch.setenv("PRAVA_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("PRAVA_USER_ID", "owner-safe")
    monkeypatch.setenv("PRAVA_USER_EMAIL", "owner@example.test")
    monkeypatch.delenv("PRAVA_CALLBACK_URL", raising=False)
    PravaClient(httpx.MockTransport(lambda _request: httpx.Response(200, json={})))


def test_prava_credential_stays_redacted_and_decline_is_reported(monkeypatch):
    monkeypatch.setenv("PRAVA_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("PRAVA_USER_ID", "owner-safe")
    monkeypatch.setenv("PRAVA_USER_EMAIL", "owner@example.test")
    monkeypatch.setenv("PRAVA_CALLBACK_URL", "https://max.example.test/payment-done")
    reported = False

    def handler(request: httpx.Request):
        nonlocal reported
        if request.method == "POST":
            assert json.loads(request.content) == {"txn_ref_id": "tli_safe", "txn_status": "DECLINED"}
            reported = True
            return httpx.Response(200, json={"status": "confirmed"})
        return httpx.Response(200, json={
            "status": "failed" if reported else "awaiting_result",
            "line_items": [{
                "txn_ref_id": "tli_safe",
                "token": "4111111111111111",
                "dynamic_cvv": "123",
                "expiry_month": "08",
                "expiry_year": "2030",
            }],
        })

    async def scenario():
        client = PravaClient(httpx.MockTransport(handler))
        credential = await client.credential("ses_safe")
        assert "4111111111111111" not in repr(credential)
        state = await client.report_result("ses_safe", credential.txn_ref_id, "DECLINED")
        assert state.status == "failed"

    asyncio.run(scenario())
