import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from max_robot.core import LocalizationState, MissionManager, SafetyGate
from max_robot.payments import PaymentService
from max_robot.web import serve_in_thread


class FakeStripe:
    api_key = ""
    checkout = SimpleNamespace(
        Session=SimpleNamespace(
            create=lambda **_: {
                "id": "cs_test_web",
                "url": "https://checkout.stripe.com/c/pay/cs_test_web",
            }
        )
    )
    Webhook = SimpleNamespace(construct_event=lambda *_: {})


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        gate = SafetyGate(localization=LocalizationState.TRACKING, heartbeat_timeout_s=60)
        for source in gate.heartbeats:
            gate.heartbeat(source)
        self.manager = MissionManager(gate)
        self.temporary = tempfile.TemporaryDirectory()
        self.payments = PaymentService(
            secret_key="sk_test_demo",
            webhook_secret="whsec_demo",
            api_key="agent-key-1234567890",
            public_base_url="http://127.0.0.1:8080",
            database=Path(self.temporary.name) / "payments.sqlite3",
            stripe_module=FakeStripe,
        )
        try:
            self.server, self.thread = serve_in_thread(
                self.manager,
                port=0,
                operator_pin="1234",
                payments=self.payments,
            )
        except PermissionError:
            self.skipTest("localhost sockets are disabled")
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def post(self, action: str, pin: str | None = "1234") -> tuple[int, dict]:
        headers = {} if pin is None else {"X-Operator-Pin": pin}
        request = urllib.request.Request(
            f"{self.base}/api/mission/{action}", method="POST", headers=headers
        )
        try:
            response = urllib.request.urlopen(request)
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.load(exc)
            finally:
                exc.close()
        with response:
            return response.status, json.load(response)

    def test_pin_and_emergency_stop(self) -> None:
        self.assertEqual(self.post("start", "bad")[0], 401)
        self.assertEqual(self.post("start")[0], 200)
        self.assertEqual(self.post("emergency-stop", None)[0], 200)
        self.assertTrue(self.manager.safety.emergency_stop)

    def test_unknown_action_is_404(self) -> None:
        self.assertEqual(self.post("launch-missiles")[0], 404)

    def test_short_pin_is_rejected_at_startup(self) -> None:
        with self.assertRaises(ValueError):
            serve_in_thread(self.manager, port=0, operator_pin="")

    def test_payment_checkout_requires_bearer_key(self) -> None:
        body = json.dumps(
            {
                "order_id": "web-order",
                "currency": "INR",
                "items": [
                    {"name": "Demo", "unit_price": "10.00", "quantity": 1}
                ],
            }
        ).encode()

        def request(key: str) -> tuple[int, dict]:
            call = urllib.request.Request(
                f"{self.base}/api/payments/checkout",
                data=body,
                method="POST",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                response = urllib.request.urlopen(call)
            except urllib.error.HTTPError as exc:
                try:
                    return exc.code, json.load(exc)
                finally:
                    exc.close()
            with response:
                return response.status, json.load(response)

        self.assertEqual(request("wrong")[0], 401)
        status, payment = request("agent-key-1234567890")
        self.assertEqual(status, 201)
        self.assertEqual(payment["status"], "checkout_created")
        self.assertEqual(request("agent-key-1234567890")[0], 200)

        status_request = urllib.request.Request(
            f"{self.base}/api/payments/{payment['payment_id']}",
            headers={"Authorization": "Bearer agent-key-1234567890"},
        )
        with urllib.request.urlopen(status_request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["order_id"], "web-order")


if __name__ == "__main__":
    unittest.main()
