import unittest

from max_robot.core import ObstructionState
from max_robot.obstruction import ObstructionConfig, ObstructionMonitor, VisionMeasurement


CLEAR = VisionMeasurement(0.0, None, 100, True)
BLOCKED = VisionMeasurement(0.2, 1.0, 100, True)


class ObstructionTests(unittest.TestCase):
    def test_confirms_and_requires_clear_interval(self) -> None:
        monitor = ObstructionMonitor(
            ObstructionConfig(confirmation_frames=3, clear_seconds=5)
        )
        self.assertEqual(monitor.update(BLOCKED, 0), ObstructionState.SUSPECTED)
        monitor.update(BLOCKED, 0.1)
        self.assertEqual(monitor.update(BLOCKED, 0.2), ObstructionState.STOPPED)
        self.assertEqual(monitor.update(CLEAR, 1), ObstructionState.WAITING_FOR_CLEAR)
        self.assertEqual(
            monitor.update(CLEAR, 5.9), ObstructionState.WAITING_FOR_CLEAR
        )
        monitor.update(CLEAR, 6)
        self.assertEqual(monitor.state, ObstructionState.CLEAR)

    def test_low_confidence_stops(self) -> None:
        monitor = ObstructionMonitor(ObstructionConfig(confirmation_frames=1))
        state = monitor.update(VisionMeasurement(0, None, 5, True), 0)
        self.assertEqual(state, ObstructionState.STOPPED)
        self.assertEqual(monitor.reason, "insufficient visual tracks")

    def test_unavailable_first_flow_frame_is_not_low_confidence(self) -> None:
        monitor = ObstructionMonitor(ObstructionConfig(confirmation_frames=1))
        state = monitor.update(VisionMeasurement(0, None, None, True), 0)
        self.assertEqual(state, ObstructionState.CLEAR)

    def test_processing_failure_requires_full_clear_interval(self) -> None:
        monitor = ObstructionMonitor(ObstructionConfig(clear_seconds=5))
        monitor.force_stop("camera conversion failed")
        self.assertEqual(monitor.update(CLEAR, 1), ObstructionState.WAITING_FOR_CLEAR)
        self.assertEqual(
            monitor.update(CLEAR, 5.9), ObstructionState.WAITING_FOR_CLEAR
        )
        self.assertEqual(monitor.update(CLEAR, 6), ObstructionState.CLEAR)


if __name__ == "__main__":
    unittest.main()
