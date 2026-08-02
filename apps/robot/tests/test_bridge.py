import tempfile
import unittest
from pathlib import Path

from max_robot.bridge import BridgeError, BridgeState


class BridgeStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "bridge.json"
        self.state = BridgeState(self.path)
        self.payload = {
            "schema_version": 1,
            "mission_id": "mission-safe-0001",
            "command_id": "command-safe-0001",
            "destination": "home",
            "dry_run": True,
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_dry_run_is_persisted_and_idempotent(self) -> None:
        first = self.state.dispatch(self.payload)
        second = self.state.dispatch(self.payload)
        reloaded = BridgeState(self.path)
        self.assertEqual(first, second)
        self.assertEqual(reloaded.last_ack, first)
        self.assertFalse(first.motion_started)

    def test_command_id_cannot_be_reused_for_different_payload(self) -> None:
        self.state.dispatch(self.payload)
        changed = {**self.payload, "destination": "work"}
        with self.assertRaisesRegex(BridgeError, "already used"):
            self.state.dispatch(changed)

    def test_physical_motion_is_fail_closed(self) -> None:
        with self.assertRaisesRegex(BridgeError, "invalid motion mode"):
            self.state.dispatch({**self.payload, "dry_run": False})

    def test_physical_ack_requires_confirmed_local_motion(self) -> None:
        ack = self.state.dispatch(
            {**self.payload, "dry_run": False},
            motion_started=True,
        )
        self.assertFalse(ack.dry_run)
        self.assertTrue(ack.motion_started)


if __name__ == "__main__":
    unittest.main()
