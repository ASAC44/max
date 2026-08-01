import json
import unittest

from max_api.blinkit_prava import (
    BlinkitPravaService,
    CartSnapshot,
    ValidationError,
    WorkflowStateError,
    compare_carts,
)


def cart(total: str = "97.00") -> dict[str, object]:
    return {
        "merchant": "Blinkit",
        "merchant_url": "https://blinkit.com/",
        "address_label": "Home",
        "currency": "INR",
        "items": [
            {
                "product_id": "206572",
                "name": "Sunfeast Dark Fantasy Bourbon Biscuits",
                "variant": "99 g",
                "unit_price": "15.00",
                "quantity": 1,
            },
            {
                "product_id": "480925",
                "name": "Lay's Sizzling Hot Potato Chips",
                "variant": "52.9 g",
                "unit_price": "20.00",
                "quantity": 1,
            },
        ],
        "fees": [
            {"name": "Delivery charge", "amount": "30.00"},
            {"name": "Handling charge", "amount": "12.00"},
            {"name": "Small cart charge", "amount": "20.00"},
        ],
        "discounts": [],
        "total": total,
        "observed_at": "2026-08-01T13:00:00+00:00",
    }


class FakePrava:
    def __init__(self) -> None:
        self.created: list[dict[str, object]] = []
        self.reported: list[tuple[str, str, str]] = []
        self.revoked: list[str] = []
        self.result: dict[str, object] = {"status": "pending"}

    def create_session(self, snapshot, **values):
        self.created.append({"cart": snapshot, **values})
        return {
            "session_id": "ses_1234567890abcdef",
            "session_token": "must-never-escape",
            "iframe_url": "https://sandbox.collect.prava.space/?session=ses_demo",
            "order_id": "ord_1234567890abcdef",
            "expires_at": "2026-08-01T13:15:00Z",
        }

    def payment_result(self, _session_id):
        return self.result

    def report_status(self, session_id, txn_ref_id, status):
        self.reported.append((session_id, txn_ref_id, status))
        return {"status": "confirmed"}

    def revoke(self, session_id):
        self.revoked.append(session_id)
        return {"success": True}


class BlinkitPravaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prava = FakePrava()
        self.service = BlinkitPravaService(
            self.prava,
            public_base_url="http://127.0.0.1:8090",
            sandbox_enabled=True,
            credential_injection_enabled=True,
        )
        self.payload = {
            "user_id": "max-owner",
            "user_email": "owner@example.com",
            "share_url": "https://link.blinkit.com/bln/demo123",
            "cart": cart(),
        }

    def workflow(self) -> str:
        return self.service.create_workflow(self.payload)["workflow_id"]

    def test_public_url_rejects_localhost_lookalikes(self) -> None:
        for url in ("http://localhost.example:8090", "http://127.0.0.1.example:8090"):
            with self.assertRaisesRegex(ValueError, "localhost"):
                BlinkitPravaService(self.prava, public_base_url=url)

    def ready_workflow(self) -> str:
        workflow_id = self.workflow()
        self.service.verify_import(workflow_id, cart())
        self.service.create_prava_session(workflow_id)
        self.prava.result = {
            "status": "awaiting_result",
            "transactions": [
                {
                    "line_items": [
                        {
                            "status": "awaiting_result",
                            "txn_ref_id": "tli_demo",
                            "token": "4111111111111111",
                            "expiry_month": "12",
                            "expiry_year": "2030",
                            "dynamic_cvv": "123",
                        }
                    ]
                }
            ],
        }
        public = self.service.poll(workflow_id)
        self.assertTrue(public["credential_ready"])
        self.assertNotIn("4111111111111111", json.dumps(public))
        self.assertNotIn("must-never-escape", json.dumps(public))
        return workflow_id

    def test_cart_arithmetic_and_order_independent_parity(self) -> None:
        expected = CartSnapshot.parse(cart())
        reordered = cart()
        reordered["items"].reverse()
        reordered["fees"].reverse()
        self.assertEqual(compare_carts(expected, CartSnapshot.parse(reordered)), [])
        with self.assertRaisesRegex(ValidationError, "arithmetic mismatch"):
            CartSnapshot.parse(cart("96.00"))

    def test_mismatch_stops_before_prava(self) -> None:
        workflow_id = self.workflow()
        changed = cart()
        changed["address_label"] = "Office"
        result = self.service.verify_import(workflow_id, changed)
        self.assertEqual(result["state"], "quote_mismatch")
        self.assertEqual(result["differences"][0]["field"], "address_label")
        with self.assertRaises(WorkflowStateError):
            self.service.create_prava_session(workflow_id)
        self.assertEqual(self.prava.created, [])

    def test_session_is_idempotent_and_secrets_are_redacted(self) -> None:
        workflow_id = self.workflow()
        self.service.verify_import(workflow_id, cart())
        first = self.service.create_prava_session(workflow_id)
        second = self.service.create_prava_session(workflow_id)
        self.assertEqual(len(self.prava.created), 1)
        self.assertEqual(first, second)
        encoded = json.dumps(first)
        self.assertNotIn("must-never-escape", encoded)
        self.assertNotIn("sandbox.collect.prava.space", encoded)
        self.assertIn("/approve?token=", first["approval_url"])

    def test_credential_is_consumed_once_and_result_is_reported(self) -> None:
        workflow_id = self.ready_workflow()
        seen = []
        self.service.consume_credential(
            workflow_id, lambda number, month, year, cvv: seen.append((number, month, year, cvv))
        )
        self.assertEqual(len(seen), 1)
        with self.assertRaises(WorkflowStateError):
            self.service.consume_credential(workflow_id, lambda *_: None)
        result = self.service.record_merchant_result(workflow_id, "DECLINED")
        self.assertEqual(result["state"], "reconciled")
        self.assertEqual(self.prava.reported[-1][-1], "DECLINED")

    def test_unknown_merchant_result_is_not_reported_or_retried(self) -> None:
        workflow_id = self.ready_workflow()
        self.service.consume_credential(workflow_id, lambda *_: None)
        result = self.service.record_merchant_result(workflow_id, "UNKNOWN")
        self.assertEqual(result["state"], "merchant_unknown")
        self.assertEqual(self.prava.reported, [])
        with self.assertRaises(WorkflowStateError):
            self.service.record_merchant_result(workflow_id, "DECLINED")

    def test_injection_defaults_to_disabled(self) -> None:
        service = BlinkitPravaService(
            self.prava,
            public_base_url="http://localhost:8090",
            sandbox_enabled=True,
        )
        workflow_id = service.create_workflow(self.payload)["workflow_id"]
        service.verify_import(workflow_id, cart())
        service.create_prava_session(workflow_id)
        self.prava.result = {
            "status": "awaiting_result",
            "transactions": [{"line_items": [{
                "status": "awaiting_result",
                "txn_ref_id": "tli_demo",
                "token": "4111111111111111",
                "expiry_month": "12",
                "expiry_year": "2030",
                "dynamic_cvv": "123",
            }]}],
        }
        service.poll(workflow_id)
        with self.assertRaisesRegex(WorkflowStateError, "disabled"):
            service.consume_credential(workflow_id, lambda *_: None)


if __name__ == "__main__":
    unittest.main()
