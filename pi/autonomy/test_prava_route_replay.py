from __future__ import annotations

import math
import unittest

from prava_route_replay import (
    Route,
    RoutePoint,
    RouteReplayController,
    SensorFrame,
)


class RouteReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.route = Route(
            name="eastbound",
            points=(
                RoutePoint(0.0, 0.0),
                RoutePoint(0.0, 0.000045),
                RoutePoint(0.0, 0.000090),
            ),
        )

    def frame(self, **overrides: object) -> SensorFrame:
        values: dict[str, object] = {
            "now": 10.0,
            "latitude": 0.0,
            "longitude": 0.0,
            "gps_fix": True,
            "gps_hdop": 1.0,
            "gps_timestamp": 9.9,
            "yaw_enu_rad": 0.0,
            "imu_timestamp": 9.99,
            "camera_steering": 0.0,
            "camera_confidence": 1.0,
            "camera_timestamp": 9.99,
            "obstruction_clear": True,
            "obstruction_timestamp": 9.99,
        }
        values.update(overrides)
        return SensorFrame(**values)

    def test_valid_route_drives_toward_next_point(self) -> None:
        intent = RouteReplayController(self.route).command(self.frame())
        self.assertTrue(intent.movement_allowed)
        self.assertGreater(intent.linear_mps, 0.0)
        self.assertAlmostEqual(intent.angular_rps, 0.0, places=3)

    def test_camera_path_error_steers_and_slows(self) -> None:
        controller = RouteReplayController(self.route)
        straight = controller.command(self.frame())
        correction = controller.command(self.frame(camera_steering=0.8))
        self.assertGreater(correction.angular_rps, 0.0)
        self.assertLess(correction.linear_mps, straight.linear_mps)

    def test_missing_gps_fix_stops(self) -> None:
        intent = RouteReplayController(self.route).command(
            self.frame(gps_fix=False)
        )
        self.assertFalse(intent.movement_allowed)
        self.assertEqual(intent.linear_mps, 0.0)

    def test_low_camera_confidence_stops(self) -> None:
        intent = RouteReplayController(self.route).command(
            self.frame(camera_confidence=0.5)
        )
        self.assertEqual(intent.reason, "camera path lock lost")

    def test_obstruction_stops(self) -> None:
        intent = RouteReplayController(self.route).command(
            self.frame(obstruction_clear=False)
        )
        self.assertEqual(intent.reason, "obstruction detected")

    def test_stale_imu_stops(self) -> None:
        intent = RouteReplayController(self.route).command(
            self.frame(imu_timestamp=9.0)
        )
        self.assertEqual(intent.reason, "IMU data stale")

    def test_large_heading_error_turns_in_place(self) -> None:
        intent = RouteReplayController(self.route).command(
            self.frame(yaw_enu_rad=math.pi)
        )
        self.assertTrue(intent.movement_allowed)
        self.assertEqual(intent.linear_mps, 0.0)
        self.assertNotEqual(intent.angular_rps, 0.0)

    def test_completes_at_final_point(self) -> None:
        controller = RouteReplayController(self.route)
        controller.index = len(self.route.points) - 1
        intent = controller.command(
            self.frame(longitude=self.route.points[-1].longitude)
        )
        self.assertTrue(intent.complete)
        self.assertFalse(intent.movement_allowed)

    def test_route_rejects_sparse_points(self) -> None:
        with self.assertRaises(ValueError):
            Route(
                points=(
                    RoutePoint(0.0, 0.0),
                    RoutePoint(0.0, 0.001),
                )
            )


if __name__ == "__main__":
    unittest.main()
