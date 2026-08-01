import unittest

from max_robot.hardware_check import evaluate


class HardwareCheckTests(unittest.TestCase):
    def test_requires_camera_rate_calibration_and_odometry(self) -> None:
        self.assertTrue(evaluate(160, 10, True, 100)["ready"])
        self.assertFalse(evaluate(149, 10, True, 100)["ready"])
        self.assertFalse(evaluate(160, 10, False, 100)["ready"])
        self.assertFalse(evaluate(160, 10, True, 0)["ready"])


if __name__ == "__main__":
    unittest.main()
