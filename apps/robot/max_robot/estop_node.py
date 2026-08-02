from __future__ import annotations


def main(args: list[str] | None = None) -> None:
    import rclpy
    from gpiozero import DigitalInputDevice
    from rclpy.node import Node
    from std_msgs.msg import Bool

    class EmergencyStopNode(Node):
        def __init__(self) -> None:
            super().__init__("max_estop")
            self.declare_parameter("gpio", -1)
            gpio = int(self.get_parameter("gpio").value)
            if gpio < 0:
                raise RuntimeError("emergency-stop GPIO must be configured")
            # Normally closed: a low signal or disconnected wire asserts stop.
            self.input = DigitalInputDevice(
                gpio,
                pull_up=False,
                active_state=False,
                bounce_time=0.05,
            )
            self.publisher = self.create_publisher(Bool, "/emergency_stop", 10)
            self.create_timer(0.05, self.publish)

        def publish(self) -> None:
            self.publisher.publish(Bool(data=self.input.is_active))

        def destroy_node(self) -> bool:
            self.input.close()
            return super().destroy_node()

    rclpy.init(args=args)
    node = EmergencyStopNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
