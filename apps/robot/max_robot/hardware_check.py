from __future__ import annotations

import argparse
import json
import time


def evaluate(frames: int, seconds: float, calibrated: bool, odometry: int) -> dict[str, object]:
    fps = frames / seconds if seconds > 0 else 0
    checks = {
        "camera_fps": round(fps, 1),
        "camera_rate_ok": fps >= 15,
        "camera_calibrated": calibrated,
        "wheel_odometry": odometry > 0,
    }
    return {**checks, "ready": all((checks["camera_rate_ok"], calibrated, odometry > 0))}


def main(args: list[str] | None = None) -> None:
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from sensor_msgs.msg import CameraInfo, Image

    parser = argparse.ArgumentParser(description="Fail-closed Max camera and odometry preflight")
    parser.add_argument("--seconds", type=float, default=10)
    options, ros_args = parser.parse_known_args(args)
    if options.seconds < 2:
        parser.error("--seconds must be at least 2")

    class CheckNode(Node):
        def __init__(self) -> None:
            super().__init__("max_hardware_check")
            self.frames = 0
            self.odometry = 0
            self.calibrated = False
            self.create_subscription(Image, "/camera/image_rect", self.on_image, 10)
            self.create_subscription(CameraInfo, "/camera/camera_info", self.on_info, 10)
            self.create_subscription(Odometry, "/wheel/odom", self.on_odom, 10)

        def on_image(self, _message: Image) -> None:
            self.frames += 1

        def on_info(self, message: CameraInfo) -> None:
            self.calibrated = any(message.k)

        def on_odom(self, _message: Odometry) -> None:
            self.odometry += 1

    rclpy.init(args=ros_args)
    node = CheckNode()
    started = time.monotonic()
    try:
        while time.monotonic() - started < options.seconds:
            rclpy.spin_once(node, timeout_sec=0.1)
        result = evaluate(node.frames, time.monotonic() - started, node.calibrated, node.odometry)
        print(json.dumps(result, sort_keys=True))
        if not result["ready"]:
            raise SystemExit(1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
