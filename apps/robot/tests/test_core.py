import unittest

from max_robot.core import (
    InvalidTransition,
    LocalizationState,
    MissionManager,
    MissionState,
    ObstructionState,
    SafetyGate,
)


def ready_gate(now: float = 10.0) -> SafetyGate:
    gate = SafetyGate(localization=LocalizationState.TRACKING)
    for source in gate.heartbeats:
        gate.heartbeat(source, now)
    return gate


class MissionTests(unittest.TestCase):
    def test_pickup_and_return(self) -> None:
        manager = MissionManager(ready_gate())
        manager.start(10.0)
        self.assertEqual(manager.state, MissionState.OUTBOUND)
        manager.route_segment_complete()
        manager.confirm_pickup()
        self.assertEqual(manager.state, MissionState.RETURNING)
        manager.route_segment_complete()
        self.assertEqual(manager.state, MissionState.COMPLETE)

    def test_stale_heartbeat_blocks_start(self) -> None:
        manager = MissionManager(ready_gate())
        with self.assertRaisesRegex(InvalidTransition, "camera heartbeat stale"):
            manager.start(11.0)

    def test_obstruction_requires_safe_resume(self) -> None:
        gate = ready_gate()
        manager = MissionManager(gate)
        manager.start(10.0)
        gate.obstruction = ObstructionState.STOPPED
        manager.safety_stop("box")
        self.assertEqual(manager.state, MissionState.OBSTRUCTION_STOP)
        with self.assertRaises(InvalidTransition):
            manager.resume(10.0)
        gate.obstruction = ObstructionState.CLEAR
        manager.resume(10.0)
        self.assertEqual(manager.state, MissionState.OUTBOUND)

    def test_emergency_stop_never_auto_resumes(self) -> None:
        manager = MissionManager(ready_gate())
        manager.start(10.0)
        manager.emergency_stop()
        self.assertEqual(manager.state, MissionState.EMERGENCY_STOP)
        manager.release_emergency_stop()
        self.assertEqual(manager.state, MissionState.PAUSED)
        self.assertFalse(manager.status(10.0)["movement_allowed"])

    def test_checkpoint_waits_for_confirmation(self) -> None:
        manager = MissionManager(ready_gate())
        manager.start(10.0)
        manager.await_checkpoint("waiting for AprilTag 2")
        self.assertEqual(manager.state, MissionState.WAITING_FOR_CHECKPOINT)
        manager.checkpoint_confirmed()
        self.assertEqual(manager.state, MissionState.AT_PICKUP)

    def test_idle_emergency_stop_releases_to_idle(self) -> None:
        manager = MissionManager(ready_gate())
        manager.emergency_stop()
        manager.release_emergency_stop()
        self.assertEqual(manager.state, MissionState.IDLE)

    def test_same_mission_start_is_idempotent(self) -> None:
        manager = MissionManager(ready_gate())
        manager.start(10.0, "mission-1")
        manager.start(10.0, "mission-1")
        self.assertEqual(manager.status(10.0)["mission_id"], "mission-1")
        with self.assertRaises(InvalidTransition):
            manager.start(10.0, "mission-2")


if __name__ == "__main__":
    unittest.main()
