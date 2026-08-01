import unittest

from max_robot.motor_node import DriveConfig, mix


class MotorMixTests(unittest.TestCase):
    def test_forward_turn_and_cap(self) -> None:
        config = DriveConfig(axle_separation=0.24, max_wheel_speed=0.3)
        self.assertEqual(mix(0.3, 0, config), (0.25, 0.25))
        left, right = mix(0, 1, config)
        self.assertLess(left, 0)
        self.assertGreater(right, 0)
        self.assertLessEqual(max(abs(left), abs(right)), 0.25)

    def test_polarity_is_calibratable(self) -> None:
        config = DriveConfig(0.24, 0.3, left_polarity=-1)
        left, right = mix(0.1, 0, config)
        self.assertLess(left, 0)
        self.assertGreater(right, 0)

    def test_unsafe_calibration_is_rejected_before_hardware(self) -> None:
        with self.assertRaises(ValueError):
            DriveConfig(0.24, 0.3, max_duty=1.1)
        with self.assertRaises(ValueError):
            DriveConfig(0, 0.3)


if __name__ == "__main__":
    unittest.main()
