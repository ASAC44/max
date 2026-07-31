from __future__ import annotations


def main(args: list[str] | None = None) -> None:
    import rclpy
    from geometry_msgs.msg import TransformStamped
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from tf2_ros import TransformBroadcaster

    class OdometryTransformNode(Node):
        def __init__(self) -> None:
            super().__init__("odom_tf")
            self.broadcaster = TransformBroadcaster(self)
            self.create_subscription(Odometry, "/wheel/odom", self.on_odometry, 20)

        def on_odometry(self, message: Odometry) -> None:
            transform = TransformStamped()
            transform.header = message.header
            transform.header.frame_id = message.header.frame_id or "odom"
            transform.child_frame_id = message.child_frame_id or "base_link"
            transform.transform.translation.x = message.pose.pose.position.x
            transform.transform.translation.y = message.pose.pose.position.y
            transform.transform.translation.z = message.pose.pose.position.z
            transform.transform.rotation = message.pose.pose.orientation
            self.broadcaster.sendTransform(transform)

    rclpy.init(args=args)
    node = OdometryTransformNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
