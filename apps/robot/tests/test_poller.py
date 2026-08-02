import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from max_robot.bridge import BridgeState
from max_robot.poller import CloudPoller, PollerError


class FakeResponse:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, _limit):
        return self.body


class CloudPollerTests(unittest.TestCase):
    def test_poll_acknowledges_only_a_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = BridgeState(Path(directory) / "poller.json")
            responses = [
                FakeResponse({
                    "schema_version": 1,
                    "motion_enabled": False,
                    "job": {
                        "schema_version": 1,
                        "mission_id": "mission-safe-0001",
                        "command_id": "command-safe-0001",
                        "destination": "home",
                        "dry_run": True,
                    },
                }),
                FakeResponse({"phase": "READY_TO_DISPATCH"}),
            ]
            with patch("max_robot.poller.urlopen", side_effect=responses) as request:
                poller = CloudPoller(
                    state,
                    base_url="https://max.example.test",
                    token="test-robot-token-123456789",
                )
                self.assertTrue(poller.poll_once())
            ack_request = request.call_args_list[1].args[0]
            body = json.loads(ack_request.data)
            self.assertTrue(body["dry_run"])
            self.assertFalse(body["motion_started"])

    def test_poll_rejects_a_backend_that_claims_motion_is_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            state = BridgeState(Path(directory) / "poller.json")
            with patch(
                "max_robot.poller.urlopen",
                return_value=FakeResponse({
                    "schema_version": 1,
                    "motion_enabled": True,
                    "job": None,
                }),
            ):
                poller = CloudPoller(
                    state,
                    base_url="https://max.example.test",
                    token="test-robot-token-123456789",
                )
                with self.assertRaisesRegex(PollerError, "safety contract"):
                    poller.poll_once()


if __name__ == "__main__":
    unittest.main()
