import tempfile
import unittest
from pathlib import Path

from max_robot.agent import HardwareProbes, LocalRobot, UnifiedRobotAgent
from max_robot.bridge import BridgeState
from max_robot.poller import PollerError


class FakeBackend:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {path}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeProbes(HardwareProbes):
    def snapshot(self):
        return {
            "camera": "present",
            "gps": "present",
            "imu": "present",
            "audio": "present",
            "motors": "disabled",
            "emergency_stop": "present",
        }


class FakeLocalRobot:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.started = []
        self.cancelled = 0
        self.estopped = 0

    def status(self):
        if not self.statuses:
            raise AssertionError("unexpected local status request")
        return self.statuses.pop(0)

    def start(self, mission_id):
        self.started.append(mission_id)
        return {"runtime_mode": "physical", "mission": "OUTBOUND", "mission_id": mission_id}

    def cancel(self):
        self.cancelled += 1

    def emergency_stop(self):
        self.estopped += 1


READY = {
    "runtime_mode": "physical",
    "mission": "IDLE",
    "mission_id": None,
    "ready": True,
    "localization": "TRACKING",
    "obstruction": "CLEAR",
    "emergency_stop": False,
    "safety_reasons": [],
}


class UnifiedRobotAgentTests(unittest.TestCase):
    def test_physical_control_url_must_be_loopback(self):
        with self.assertRaisesRegex(PollerError, "loopback"):
            LocalRobot(base_url="https://example.com", operator_pin="1234")

    def test_every_order_status_is_persisted_with_cursor(self):
        backend = FakeBackend(
            [{
                "schema_version": 1,
                "motion_enabled": False,
                "next_cursor": 12,
                "events": [
                    {
                        "event_id": 11,
                        "mission_id": "mission-safe-0001",
                        "normalized_status": "OUT_FOR_DELIVERY",
                        "robot_action": "WAIT",
                    },
                    {
                        "event_id": 12,
                        "mission_id": "mission-safe-0001",
                        "normalized_status": "ARRIVED_AT_DELIVERY_LOCATION",
                        "robot_action": "QUEUE_DRY_RUN_DISPATCH",
                    },
                ],
            }]
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.json"
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(path),
            )
            self.assertEqual(agent.sync_order_status(), 2)
            reloaded = BridgeState(path)
        self.assertEqual(reloaded.order_status_cursor, 12)
        self.assertEqual(
            reloaded.latest_order_status["mission-safe-0001"]["normalized_status"],
            "ARRIVED_AT_DELIVERY_LOCATION",
        )
        self.assertIn("after=0", backend.requests[0][1])

    def test_heartbeat_never_enables_motion(self):
        backend = FakeBackend(
            [{"schema_version": 1, "accepted": True, "motion_enabled": False}]
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                probes=FakeProbes(),
            )
            agent.heartbeat()
        payload = backend.requests[0][2]
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["subsystems"]["motors"], "disabled")

    def test_physical_heartbeat_reports_navigation_safety(self):
        backend = FakeBackend(
            [{"schema_version": 1, "accepted": True, "motion_enabled": True}]
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                physical=True,
                local_robot=FakeLocalRobot([READY]),
            )
            agent.heartbeat()
        payload = backend.requests[0][2]
        self.assertEqual(payload["mode"], "physical")
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["subsystems"]["odometry"], "healthy")
        self.assertNotIn("gps", payload["subsystems"])

    def test_new_job_is_acknowledged_without_motion(self):
        backend = FakeBackend(
            [
                {"schema_version": 1, "motion_enabled": False, "job": None},
                {
                    "schema_version": 1,
                    "motion_enabled": False,
                    "job": {
                        "schema_version": 1,
                        "mission_id": "mission-safe-0001",
                        "command_id": "command-safe-0001",
                        "destination": "home",
                        "dry_run": True,
                        "expected_version": 3,
                    },
                },
                {
                    "id": "mission-safe-0001",
                    "version": 4,
                    "phase": "READY_TO_DISPATCH",
                },
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
            )
            self.assertTrue(agent.run_once())
        ack = backend.requests[-1][2]
        self.assertTrue(ack["dry_run"])
        self.assertFalse(ack["motion_started"])

    def test_rehearsal_resumes_current_job_one_stage_at_a_time(self):
        backend = FakeBackend(
            [
                {
                    "schema_version": 1,
                    "motion_enabled": False,
                    "job": {
                        "schema_version": 1,
                        "mission_id": "mission-safe-0001",
                        "command_id": "command-safe-0001",
                        "destination": "home",
                        "dry_run": True,
                        "expected_version": 4,
                        "phase": "READY_TO_DISPATCH",
                        "job_status": "ACKNOWLEDGED",
                    },
                },
                {"phase": "AT_PICKUP", "version": 5},
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                rehearsal=True,
            )
            self.assertTrue(agent.run_once())
        lifecycle = backend.requests[-1][2]
        self.assertEqual(lifecycle["stage"], "AT_PICKUP")
        self.assertTrue(lifecycle["dry_run"])
        self.assertFalse(lifecycle["motion_started"])

    def test_backend_motion_flag_fails_closed(self):
        backend = FakeBackend(
            [{"schema_version": 1, "motion_enabled": True, "job": None}]
        )
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
            )
            with self.assertRaisesRegex(PollerError, "safety contract"):
                agent.run_once()

    def test_physical_job_starts_local_mission_before_ack(self):
        backend = FakeBackend([
            {"schema_version": 1, "motion_enabled": True, "job": None},
            {
                "schema_version": 1,
                "motion_enabled": True,
                "job": {
                    "schema_version": 1,
                    "mission_id": "mission-live-0001",
                    "command_id": "command-live-0001",
                    "destination": "home",
                    "dry_run": False,
                    "expected_version": 3,
                },
            },
            {"id": "mission-live-0001", "version": 4, "phase": "EN_ROUTE_TO_PICKUP"},
        ])
        local = FakeLocalRobot([READY, {**READY, "mission": "OUTBOUND", "ready": False}])
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                physical=True,
                local_robot=local,
            )
            self.assertTrue(agent.run_once())
        self.assertEqual(local.started, ["mission-live-0001"])
        self.assertEqual(backend.requests[-1][2]["motion_started"], True)
        self.assertEqual(backend.requests[-1][2]["dry_run"], False)

    def test_physical_lifecycle_follows_observed_local_state(self):
        backend = FakeBackend([
            {
                "schema_version": 1,
                "motion_enabled": True,
                "job": {
                    "schema_version": 1,
                    "mission_id": "mission-live-0001",
                    "command_id": "command-live-0001",
                    "destination": "home",
                    "dry_run": False,
                    "expected_version": 4,
                    "phase": "EN_ROUTE_TO_PICKUP",
                    "job_status": "ACKNOWLEDGED",
                },
            },
            {"phase": "AT_PICKUP", "version": 5},
        ])
        local = FakeLocalRobot([{**READY, "mission": "AT_PICKUP", "ready": False}])
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                physical=True,
                local_robot=local,
            )
            self.assertTrue(agent.run_once())
        report = backend.requests[-1][2]
        self.assertEqual(report["stage"], "AT_PICKUP")
        self.assertFalse(report["dry_run"])
        self.assertTrue(report["motion_started"])

    def test_physical_ack_failure_cancels_local_motion(self):
        backend = FakeBackend([
            {"schema_version": 1, "motion_enabled": True, "job": None},
            {
                "schema_version": 1,
                "motion_enabled": True,
                "job": {
                    "schema_version": 1,
                    "mission_id": "mission-live-0001",
                    "command_id": "command-live-0001",
                    "destination": "home",
                    "dry_run": False,
                    "expected_version": 3,
                },
            },
            PollerError("backend unavailable"),
        ])
        local = FakeLocalRobot([READY])
        with tempfile.TemporaryDirectory() as directory:
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(Path(directory) / "agent.json"),
                physical=True,
                local_robot=local,
            )
            with self.assertRaises(PollerError):
                agent.run_once()
        self.assertEqual(local.cancelled, 1)


if __name__ == "__main__":
    unittest.main()
