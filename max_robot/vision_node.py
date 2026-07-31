from __future__ import annotations

import time
from pathlib import Path

from .obstruction import (
    ObstructionConfig,
    ObstructionMonitor,
    OpenCVObstructionDetector,
    VisionMeasurement,
)


def main(args: list[str] | None = None) -> None:
    import cv2
    import rclpy
    from cv_bridge import CvBridge
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from std_msgs.msg import Int32, String

    class ObstructionNode(Node):
        def __init__(self) -> None:
            super().__init__("max_obstruction")
            self.declare_parameter("reference_dir", "")
            self.declare_parameter("difference_ratio", 0.08)
            self.declare_parameter("ttc_seconds", 1.5)
            self.declare_parameter("minimum_tracks", 30)
            self.declare_parameter("confirmation_frames", 3)
            self.declare_parameter("clear_seconds", 5.0)
            directory = str(self.get_parameter("reference_dir").value)
            if not directory:
                raise RuntimeError("reference_dir parameter is required")
            self.reference_dir = Path(directory)
            self.monitor = ObstructionMonitor(
                ObstructionConfig(
                    difference_ratio=float(
                        self.get_parameter("difference_ratio").value
                    ),
                    ttc_seconds=float(self.get_parameter("ttc_seconds").value),
                    minimum_tracks=int(self.get_parameter("minimum_tracks").value),
                    confirmation_frames=int(
                        self.get_parameter("confirmation_frames").value
                    ),
                    clear_seconds=float(self.get_parameter("clear_seconds").value),
                )
            )
            self.detector = OpenCVObstructionDetector()
            self.bridge = CvBridge()
            self.waypoint = 0
            self.previous = None
            self.previous_time: float | None = None
            self.angular_velocity = 0.0
            self.reference = None
            self.publisher = self.create_publisher(
                String, "/obstruction/status", 10
            )
            self.create_subscription(
                Int32, "/route/waypoint_index", self.on_waypoint, 10
            )
            self.create_subscription(
                Image, "/camera/image_rect", self.on_image, 10
            )
            self.create_subscription(
                Odometry, "/wheel/odom", self.on_odometry, 10
            )

        def on_waypoint(self, message: Int32) -> None:
            if message.data != self.waypoint:
                self.previous = None
                self.previous_time = None
                self.reference = None
                self.monitor = ObstructionMonitor(self.monitor.config)
            self.waypoint = message.data

        def on_odometry(self, message: Odometry) -> None:
            self.angular_velocity = message.twist.twist.angular.z

        def on_image(self, message: Image) -> None:
            now = time.monotonic()
            try:
                current = self.bridge.imgmsg_to_cv2(message, "bgr8")
                if self.reference is None:
                    self.reference = cv2.imread(
                        str(self.reference_dir / f"{self.waypoint}.png")
                    )
                if self.reference is None:
                    raise RuntimeError(
                        f"missing reference image for waypoint {self.waypoint}"
                    )
                difference, aligned = self.detector.compare_reference(
                    self.reference, current
                )
                ttc, tracks = (None, None)
                if self.previous is not None and self.previous_time is not None:
                    ttc, tracks = self.detector.estimate_ttc(
                        self.previous,
                        current,
                        now - self.previous_time,
                        angular_velocity=self.angular_velocity,
                    )
                measurement = VisionMeasurement(
                    difference_ratio=difference,
                    ttc_seconds=ttc,
                    track_count=tracks,
                    alignment_ok=aligned,
                )
                state = self.monitor.update(measurement, now)
                self.previous = current
                self.previous_time = now
            except Exception as exc:
                self.get_logger().error(str(exc))
                self.monitor.force_stop(str(exc))
                state = self.monitor.state
            self.publisher.publish(String(data=str(state)))

    rclpy.init(args=args)
    node = ObstructionNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()


def record_reference(args: list[str] | None = None) -> None:
    """Save one camera frame after each requested waypoint index."""
    import cv2
    import rclpy
    from cv_bridge import CvBridge
    from rclpy.node import Node
    from sensor_msgs.msg import Image
    from std_msgs.msg import Int32

    class ReferenceRecorder(Node):
        def __init__(self) -> None:
            super().__init__("max_reference_recorder")
            self.declare_parameter("output_dir", "")
            self.declare_parameter("overwrite", False)
            output_dir = str(self.get_parameter("output_dir").value)
            if not output_dir:
                raise RuntimeError("output_dir parameter is required")
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.pending_index: int | None = None
            self.bridge = CvBridge()
            self.create_subscription(
                Int32, "/route/waypoint_index", self.on_waypoint, 10
            )
            self.create_subscription(
                Image, "/camera/image_rect", self.on_image, 10
            )

        def on_waypoint(self, message: Int32) -> None:
            self.pending_index = message.data

        def on_image(self, message: Image) -> None:
            if self.pending_index is None:
                return
            destination = self.output_dir / f"{self.pending_index}.png"
            if destination.exists() and not self.get_parameter("overwrite").value:
                self.get_logger().warning(f"{destination} exists; not overwriting")
                self.pending_index = None
                return
            image = self.bridge.imgmsg_to_cv2(message, "bgr8")
            if not cv2.imwrite(str(destination), image):
                self.get_logger().error(f"failed to write {destination}")
                return
            self.get_logger().info(f"saved {destination}")
            self.pending_index = None

    rclpy.init(args=args)
    node = ReferenceRecorder()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
