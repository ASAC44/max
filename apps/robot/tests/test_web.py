import json
import unittest
import urllib.error
import urllib.request

from max_robot.core import LocalizationState, MissionManager, SafetyGate
from max_robot.web import serve_in_thread


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        gate = SafetyGate(localization=LocalizationState.TRACKING, heartbeat_timeout_s=60)
        for source in gate.heartbeats:
            gate.heartbeat(source)
        self.manager = MissionManager(gate)
        try:
            self.server, self.thread = serve_in_thread(
                self.manager, port=0, operator_pin="1234"
            )
        except PermissionError:
            self.skipTest("localhost sockets are disabled")
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def post(self, action: str, pin: str | None = "1234", mission_id: str | None = None) -> tuple[int, dict]:
        headers = {} if pin is None else {"X-Operator-Pin": pin}
        if mission_id:
            headers["X-Mission-Id"] = mission_id
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

    def test_duplicate_start_for_same_mission_is_safe(self) -> None:
        self.assertEqual(self.post("start", mission_id="mission-1")[0], 200)
        self.assertEqual(self.post("start", mission_id="mission-1")[0], 200)
        self.assertEqual(self.manager.status()["mission_id"], "mission-1")

    def test_short_pin_is_rejected_at_startup(self) -> None:
        with self.assertRaises(ValueError):
            serve_in_thread(self.manager, port=0, operator_pin="")


if __name__ == "__main__":
    unittest.main()
