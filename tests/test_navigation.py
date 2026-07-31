import math
import unittest

from max_robot.navigation import Pose2D, TagTracker, Waypoint, WaypointFollower


class NavigationTests(unittest.TestCase):
    def test_turns_before_driving_to_target_behind(self) -> None:
        follower = WaypointFollower([Waypoint(-1, 0)])
        command = follower.command(Pose2D(0, 0, 0))
        self.assertEqual(command.linear, 0)
        self.assertNotEqual(command.angular, 0)

    def test_completes_inside_tolerance(self) -> None:
        follower = WaypointFollower([Waypoint(0.05, 0)])
        command = follower.command(Pose2D(0, 0, math.pi))
        self.assertTrue(follower.complete)
        self.assertEqual((command.linear, command.angular), (0, 0))

    def test_reverse_route_uses_original_reference_indices(self) -> None:
        follower = WaypointFollower([Waypoint(0, 0), Waypoint(1, 0)])
        follower.reset(reverse=True)
        self.assertEqual(follower.reference_index, 1)
        follower.command(Pose2D(1, 0, 0))
        self.assertEqual(follower.reference_index, 1)

    def test_tag_observation_expires(self) -> None:
        tracker = TagTracker()
        tracker.observe(2, 10)
        self.assertTrue(tracker.seen_recently(2, now=10.5))
        self.assertFalse(tracker.seen_recently(2, now=11.1))


if __name__ == "__main__":
    unittest.main()
