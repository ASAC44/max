from __future__ import annotations

import unittest

from prava_autonomy_guard import OdometrySource, PravaAutonomyGuard


class PravaAutonomyGuardTests(unittest.TestCase):
    def healthy_guard(self, now: float = 10.0) -> PravaAutonomyGuard:
        guard = PravaAutonomyGuard(
            hardware_output_enabled=True,
            emergency_stop=False,
            localization_tracking=True,
            obstruction_clear=True,
            odometry_source=OdometrySource.WHEEL_ENCODERS,
            physical_estop_verified=True,
            temperature_c=55.0,
        )
        guard.arm(now)
        for source in (
            "camera",
            "odometry",
            "localization",
            "obstruction",
            "controller",
        ):
            guard.heartbeat(source, now + 0.01)
        guard.set_command(0.15, 0.0, now + 0.01)
        return guard

    def test_hardware_output_is_disabled_by_default(self) -> None:
        guard = PravaAutonomyGuard()
        self.assertIn("hardware output disabled", guard.blocking_reasons(1.0))
        self.assertEqual(guard.motor_command(
            track_width_m=0.4,
            max_wheel_speed_mps=0.15,
            now=1.0,
        ).left, 0.0)

    def test_imu_cannot_replace_wheel_odometry(self) -> None:
        guard = self.healthy_guard()
        guard.odometry_source = OdometrySource.IMU_ONLY
        reasons = guard.blocking_reasons(10.1)
        self.assertTrue(any("validated wheel odometry" in r for r in reasons))

    def test_route_replay_requires_validation_and_supervision(self) -> None:
        guard = self.healthy_guard()
        guard.odometry_source = OdometrySource.CAMERA_GPS_IMU_ROUTE
        reasons = guard.blocking_reasons(10.1)
        self.assertIn("route replay has not passed shadow validation", reasons)
        self.assertIn("route replay supervisor disconnected", reasons)

    def test_validated_supervised_route_replay_can_reach_guard_output(self) -> None:
        guard = self.healthy_guard()
        guard.odometry_source = OdometrySource.CAMERA_GPS_IMU_ROUTE
        guard.route_replay_validated = True
        guard.remote_supervisor_connected = True
        command = guard.motor_command(
            track_width_m=0.4,
            max_wheel_speed_mps=0.15,
            now=10.1,
        )
        self.assertAlmostEqual(command.left, 1.0)
        self.assertAlmostEqual(command.right, 1.0)

    def test_emergency_stop_requires_rearm_and_fresh_command(self) -> None:
        guard = self.healthy_guard()
        guard.engage_emergency_stop()
        guard.release_emergency_stop()
        self.assertIn("not armed", guard.blocking_reasons(10.1))
        guard.arm(10.2)
        self.assertIn(
            "fresh command required after arming",
            guard.blocking_reasons(10.21),
        )

    def test_stale_heartbeat_stops_output(self) -> None:
        guard = self.healthy_guard()
        command = guard.motor_command(
            track_width_m=0.4,
            max_wheel_speed_mps=0.15,
            now=10.5,
        )
        self.assertEqual(command.left, 0.0)
        self.assertEqual(command.right, 0.0)

    def test_high_temperature_stops_output(self) -> None:
        guard = self.healthy_guard()
        guard.temperature_c = 80.0
        self.assertTrue(any(
            "exceeds" in reason for reason in guard.blocking_reasons(10.1)
        ))

    def test_current_throttle_flag_stops_output(self) -> None:
        guard = self.healthy_guard()
        guard.throttled_mask = 0x8
        self.assertTrue(any(
            "throttle flags" in reason for reason in guard.blocking_reasons(10.1)
        ))

    def test_healthy_forward_command_reaches_both_motors(self) -> None:
        guard = self.healthy_guard()
        command = guard.motor_command(
            track_width_m=0.4,
            max_wheel_speed_mps=0.15,
            now=10.1,
        )
        self.assertAlmostEqual(command.left, 1.0)
        self.assertAlmostEqual(command.right, 1.0)

    def test_mixer_preserves_turn_ratio_when_saturated(self) -> None:
        guard = self.healthy_guard()
        guard.set_command(0.15, 0.75, 10.02)
        command = guard.motor_command(
            track_width_m=0.4,
            max_wheel_speed_mps=0.15,
            now=10.1,
        )
        self.assertAlmostEqual(command.left, 0.0)
        self.assertAlmostEqual(command.right, 1.0)


if __name__ == "__main__":
    unittest.main()
