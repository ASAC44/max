import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from max_robot.payments import (
    PaymentGatewayError,
    PaymentService,
    PaymentValidationError,
)


class FakeSession:
    calls: list[dict] = []
    fails = False

    @classmethod
    def create(cls, **values):
        if cls.fails:
            raise RuntimeError("Stripe is unavailable")
        cls.calls.append(values)
        return {
            "id": "cs_test_demo",
            "url": "https://checkout.stripe.com/c/pay/cs_test_demo",
        }


class FakeWebhook:
    @staticmethod
    def construct_event(payload, signature, _secret):
        if signature != "valid":
            raise ValueError("bad signature")
        return json.loads(payload)


class FakeStripe:
    api_key = ""
    checkout = SimpleNamespace(Session=FakeSession)
    Webhook = FakeWebhook


class PaymentTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSession.calls.clear()
        FakeSession.fails = False
        self.temporary = tempfile.TemporaryDirectory()
        self.service = PaymentService(
            secret_key="sk_test_demo",
            webhook_secret="whsec_demo",
            api_key="agent-key-1234567890",
            public_base_url="http://127.0.0.1:8080",
            database=Path(self.temporary.name) / "payments.sqlite3",
            stripe_module=FakeStripe,
        )
        self.order = {
            "order_id": "ondc-order-123",
            "currency": "INR",
            "items": [
                {"name": "Demo product", "unit_price": "249.00", "quantity": 2}
            ],
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_creates_checkout_and_replays_by_order_id(self) -> None:
        payment, replayed = self.service.create_checkout(self.order)
        repeated, repeated_replayed = self.service.create_checkout(self.order)

        self.assertFalse(replayed)
        self.assertTrue(repeated_replayed)
        self.assertEqual(payment, repeated)
        self.assertEqual(payment["total_amount"], "498.00")
        self.assertEqual(len(FakeSession.calls), 1)
        request = FakeSession.calls[0]
        self.assertEqual(request["line_items"][0]["price_data"]["unit_amount"], 24900)
        self.assertEqual(request["payment_method_types"], ["card"])
        self.assertEqual(request["metadata"]["order_id"], "ondc-order-123")

    def test_rejects_invalid_orders(self) -> None:
        invalid = [
            {},
            {**self.order, "currency": "USD"},
            {**self.order, "items": []},
            {
                **self.order,
                "items": [
                    {"name": "Demo", "unit_price": "1.001", "quantity": 1}
                ],
            },
            {
                **self.order,
                "items": [{"name": "Demo", "unit_price": "NaN", "quantity": 1}],
            },
            {
                **self.order,
                "items": [{"name": "Demo", "unit_price": "1.00", "quantity": True}],
            },
            {**self.order, "unexpected": "field"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(
                PaymentValidationError
            ):
                self.service.create_checkout(payload)

    def test_rejects_live_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "test-mode"):
            PaymentService(
                secret_key="sk_live_demo",
                webhook_secret="whsec_demo",
                api_key="agent-key-1234567890",
                public_base_url="http://127.0.0.1:8080",
                database=Path(self.temporary.name) / "live.sqlite3",
                stripe_module=FakeStripe,
            )

    def test_failed_webhook_is_deduplicated_and_paid_never_regresses(self) -> None:
        payment, _ = self.service.create_checkout(self.order)
        metadata = {"payment_id": payment["payment_id"]}
        failed = {
            "id": "evt_failed",
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "metadata": metadata,
                    "last_payment_error": {
                        "decline_code": "generic_decline",
                        "message": "Your card was declined.",
                    },
                }
            },
        }
        result = self.service.handle_webhook(json.dumps(failed).encode(), "valid")
        duplicate = self.service.handle_webhook(
            json.dumps(failed).encode(), "valid"
        )
        self.assertEqual(result["status"], "payment_failed")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(
            self.service.get_payment(payment["payment_id"])["failure_code"],
            "generic_decline",
        )

        succeeded = {
            "id": "evt_paid",
            "type": "payment_intent.succeeded",
            "data": {"object": {"metadata": metadata}},
        }
        self.service.handle_webhook(json.dumps(succeeded).encode(), "valid")
        later_failure = {**failed, "id": "evt_late_failure"}
        self.service.handle_webhook(
            json.dumps(later_failure).encode(), "valid"
        )
        self.assertEqual(
            self.service.get_payment(payment["payment_id"])["status"], "paid"
        )

    def test_rejects_invalid_webhook_signature(self) -> None:
        with self.assertRaises(PaymentValidationError):
            self.service.handle_webhook(b"{}", "invalid")

    def test_gateway_failure_does_not_create_a_payment(self) -> None:
        FakeSession.fails = True
        with self.assertRaises(PaymentGatewayError):
            self.service.create_checkout(self.order)
        self.assertIsNone(self.service._find_by_order("ondc-order-123"))


if __name__ == "__main__":
    unittest.main()
