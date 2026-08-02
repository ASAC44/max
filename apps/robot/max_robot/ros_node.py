from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from .core import (
    LocalizationState,
    MissionManager,
    MissionState,
    MOVING_STATES,
    ObstructionState,
    SafetyGate,
)
from .navigation import Pose2D, TagTracker, Waypoint, WaypointFollower
from .web import serve_in_thread


def main(args: list[str] | None = None) -> None:
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
    from apriltag_msgs.msg import AprilTagDetectionArray
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from std_msgs.msg import Bool, Int32, String

    class MaxControlNode(Node):
        def __init__(self) -> None:
            super().__init__("max_control")
            self.declare_parameter("route_file", "")
            self.declare_parameter("web_host", "127.0.0.1")
            self.declare_parameter("web_port", 8080)
            self.declare_parameter("max_linear_speed", 0.15)
            self.declare_parameter("minimum_tag_margin", 30.0)
            self.declare_parameter("runtime_mode", "simulation")
            route_file = self.get_parameter("route_file").value
            if not route_file:
                raise RuntimeError("route_file parameter is required")
            route = json.loads(Path(route_file).read_text())
            waypoints = [
                Waypoint(float(p["x"]), float(p["y"])) for p in route["waypoints"]
            ]
            self.pickup_tag = route.get("pickup_tag")
            self.home_tag = route.get("home_tag")
            self.tags = TagTracker()
            self.pending_tag: int | None = None
            self.follower = WaypointFollower(
                waypoints,
                max_linear=float(self.get_parameter("max_linear_speed").value),
            )
            self.pose: Pose2D | None = None
            self.safety = SafetyGate()
            runtime_mode = str(self.get_parameter("runtime_mode").value)
            if runtime_mode not in {"simulation", "physical"}:
                raise RuntimeError("runtime_mode must be simulation or physical")
            self.manager = MissionManager(self.safety, runtime_mode=runtime_mode)
            self.runtime_mode = runtime_mode
            self.last_state = self.manager.state

            self.velocity_publisher = self.create_publisher(Twist, "/cmd_vel", 10)
            self.waypoint_publisher = self.create_publisher(
                Int32, "/route/waypoint_index", 10
            )
            self.create_subscription(
                PoseWithCovarianceStamped,
                "/localization/pose",
                self.on_pose,
                10,
            )
            self.create_subscription(Odometry, "/wheel/odom", self.on_odometry, 10)
            self.create_subscription(Image, "/camera/image_rect", self.on_camera, 10)
            self.create_subscription(
                String, "/localization/status", self.on_localization, 10
            )
            self.create_subscription(
                String, "/obstruction/status", self.on_obstruction, 10
            )
            self.create_subscription(Bool, "/emergency_stop", self.on_estop, 10)
            self.create_subscription(String, "/motors/status", self.on_motors, 10)
            self.create_subscription(
                AprilTagDetectionArray,
                "/apriltag/detections",
                self.on_tags,
                10,
            )
            self.timer = self.create_timer(0.05, self.control)

            pin = os.environ.get("MAX_OPERATOR_PIN", "0000")
            if pin == "0000":
                raise RuntimeError("MAX_OPERATOR_PIN must be configured")
            self.web_server, _ = serve_in_thread(
                self.manager,
                host=str(self.get_parameter("web_host").value),
                port=int(self.get_parameter("web_port").value),
                operator_pin=pin,
            )

        def on_pose(self, message: PoseWithCovarianceStamped) -> None:
            q = message.pose.pose.orientation
            yaw = math.atan2(
                2 * (q.w * q.z + q.x * q.y),
                1 - 2 * (q.y * q.y + q.z * q.z),
            )
            p = message.pose.pose.position
            self.pose = Pose2D(p.x, p.y, yaw)
            self.safety.localization = LocalizationState.TRACKING
            self.safety.heartbeat("localization")

        def on_odometry(self, _: Odometry) -> None:
            self.safety.heartbeat("odometry")

        def on_camera(self, _: Image) -> None:
            self.safety.heartbeat("camera")

        def on_localization(self, message: String) -> None:
            try:
                self.safety.localization = LocalizationState(message.data)
            except ValueError:
                self.safety.localization = LocalizationState.LOST

        def on_obstruction(self, message: String) -> None:
            try:
                self.safety.obstruction = ObstructionState(message.data)
            except ValueError:
                self.safety.obstruction = ObstructionState.STOPPED
            self.safety.heartbeat("obstruction")

        def on_estop(self, message: Bool) -> None:
            self.safety.heartbeat("estop")
            if message.data:
                self.manager.emergency_stop()

        def on_motors(self, message: String) -> None:
            if message.data == "healthy":
                self.safety.heartbeat("motors")

        def on_tags(self, message: AprilTagDetectionArray) -> None:
            now = time.monotonic()
            for detection in message.detections:
                if (
                    float(detection.decision_margin)
                    >= float(self.get_parameter("minimum_tag_margin").value)
                ):
                    self.tags.observe(int(detection.id), now)
            if self.manager.state is MissionState.WAITING_FOR_CHECKPOINT:
                if self.tags.seen_recently(self.pending_tag, now=now):
                    self.manager.checkpoint_confirmed()
                    self.pending_tag = None

        def control(self) -> None:
            now = time.monotonic()
            self.safety.heartbeat("controller", now)
            if self.runtime_mode == "simulation":
                self.safety.heartbeat("motors", now)
                self.safety.heartbeat("estop", now)
            state = self.manager.state
            if state != self.last_state:
                if state is MissionState.OUTBOUND and (
                    self.follower.reversed
                    or self.last_state
                    in {
                        MissionState.IDLE,
                        MissionState.COMPLETE,
                        MissionState.CANCELLED,
                    }
                ):
                    self.follower.reset()
                elif state is MissionState.RETURNING and not self.follower.reversed:
                    self.follower.reset(reverse=True)
                self.last_state = state

            if state in MOVING_STATES and not self.safety.movement_allowed(now):
                reasons = self.safety.reasons(now)
                if "localization heartbeat stale" in reasons:
                    self.safety.localization = LocalizationState.LOST
                if "obstruction heartbeat stale" in reasons:
                    self.safety.obstruction = ObstructionState.STOPPED
                self.manager.safety_stop("; ".join(reasons))
                self.publish_stop()
                return
            if state not in MOVING_STATES or self.pose is None:
                self.publish_stop()
                return

            velocity = self.follower.command(self.pose)
            if self.follower.complete:
                expected = (
                    self.pickup_tag
                    if state is MissionState.OUTBOUND
                    else self.home_tag
                )
                if self.tags.seen_recently(expected, now=now):
                    self.manager.route_segment_complete()
                else:
                    self.pending_tag = expected
                    self.manager.await_checkpoint(
                        f"waiting for AprilTag {expected}"
                    )
                self.publish_stop()
                return
            self.waypoint_publisher.publish(
                Int32(data=self.follower.reference_index)
            )
            self.manager.waypoint_index = self.follower.reference_index
            command = Twist()
            command.linear.x = velocity.linear
            command.angular.z = velocity.angular
            self.velocity_publisher.publish(command)

        def publish_stop(self) -> None:
            self.velocity_publisher.publish(Twist())

        def destroy_node(self) -> bool:
            self.publish_stop()
            self.web_server.shutdown()
            self.web_server.server_close()
            return super().destroy_node()

    rclpy.init(args=args)
    node = MaxControlNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
