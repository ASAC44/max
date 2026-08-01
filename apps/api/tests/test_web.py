import http.client
import json
import unittest

from max_api.blinkit_prava import BlinkitPravaService
from max_api.web import serve_in_thread
from test_blinkit_prava import FakePrava, cart


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prava = FakePrava()
        self.service = BlinkitPravaService(
            self.prava,
            public_base_url="http://127.0.0.1:8090",
            sandbox_enabled=True,
        )
        try:
            self.server, self.thread = serve_in_thread(
                self.service, "agent-key-1234567890", port=0
            )
        except PermissionError:
            self.skipTest("localhost sockets are disabled")

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, method, path, payload=None, key="agent-key-1234567890"):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        body = json.dumps(payload) if payload is not None else None
        headers = {"Authorization": f"Bearer {key}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if raw else None
        connection.close()
        return response.status, result

    def test_authenticated_robot_workflow(self) -> None:
        payload = {
            "user_id": "max-owner",
            "user_email": "owner@example.com",
            "share_url": "https://link.blinkit.com/bln/demo123",
            "cart": cart(),
        }
        self.assertEqual(self.request("POST", "/api/blinkit-prava/workflows", payload, "bad")[0], 401)
        status, workflow = self.request("POST", "/api/blinkit-prava/workflows", payload)
        self.assertEqual(status, 201)
        workflow_id = workflow["workflow_id"]
        status, verified = self.request(
            "POST", f"/api/blinkit-prava/workflows/{workflow_id}/imported-cart", cart()
        )
        self.assertEqual(status, 200)
        self.assertEqual(verified["state"], "browser_quote_verified")
        status, session = self.request(
            "POST", f"/api/blinkit-prava/workflows/{workflow_id}/prava-session"
        )
        self.assertEqual(status, 200)
        self.assertIn("/approve?token=", session["approval_url"])
        self.assertNotIn("session_token", json.dumps(session))


if __name__ == "__main__":
    unittest.main()
