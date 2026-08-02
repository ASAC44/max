from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class DriveConfig:
    axle_separation: float
    max_wheel_speed: float
    max_duty: float = 0.25
    left_polarity: float = 1.0
    right_polarity: float = 1.0

    def __post_init__(self) -> None:
        if self.axle_separation <= 0 or self.max_wheel_speed <= 0:
            raise ValueError("axle separation and max wheel speed must be positive")
        if not 0 < self.max_duty <= 1:
            raise ValueError("max duty must be greater than zero and no more than one")
        if self.left_polarity not in {-1.0, 1.0} or self.right_polarity not in {-1.0, 1.0}:
            raise ValueError("motor polarity must be -1 or 1")


def mix(linear: float, angular: float, config: DriveConfig) -> tuple[float, float]:
    left = (linear - angular * config.axle_separation / 2) / config.max_wheel_speed
    right = (linear + angular * config.axle_separation / 2) / config.max_wheel_speed
    scale = max(1.0, abs(left), abs(right))
    return (
        max(-config.max_duty, min(config.max_duty, left / scale * config.max_duty * config.left_polarity)),
        max(-config.max_duty, min(config.max_duty, right / scale * config.max_duty * config.right_polarity)),
    )


class BTS7960:
    def __init__(self, rpwm: int, lpwm: int, r_enable: int, l_enable: int) -> None:
        from gpiozero import DigitalOutputDevice, PWMOutputDevice

        self.rpwm = PWMOutputDevice(rpwm, frequency=1000, initial_value=0)
        self.lpwm = PWMOutputDevice(lpwm, frequency=1000, initial_value=0)
        self.enables = (
            DigitalOutputDevice(r_enable, initial_value=False),
            DigitalOutputDevice(l_enable, initial_value=False),
        )
        self._direction = 0

    def enable(self) -> None:
        for enable in self.enables:
            enable.on()

    def command(self, duty: float) -> None:
        direction = (duty > 0) - (duty < 0)
        self.rpwm.value = 0
        self.lpwm.value = 0
        if direction and self._direction and direction != self._direction:
            time.sleep(0.002)
        if duty >= 0:
            self.rpwm.value = min(1.0, duty)
        else:
            self.lpwm.value = min(1.0, -duty)
        self._direction = direction

    def close(self) -> None:
        self.command(0)
        for enable in self.enables:
            enable.off()
        for device in (*self.enables, self.rpwm, self.lpwm):
            device.close()


def main(args: list[str] | None = None) -> None:
    import rclpy
    from geometry_msgs.msg import Twist
    from rclpy.node import Node
    from std_msgs.msg import String

    class MotorNode(Node):
        def __init__(self) -> None:
            super().__init__("max_motors")
            for side in ("left", "right"):
                for name in ("rpwm", "lpwm", "r_enable", "l_enable"):
                    self.declare_parameter(f"{side}_{name}", -1)
            self.declare_parameter("axle_separation", 0.24)
            self.declare_parameter("max_wheel_speed", 0.3)
            self.declare_parameter("max_duty", 0.25)
            self.declare_parameter("left_polarity", 1.0)
            self.declare_parameter("right_polarity", 1.0)
            pins = {
                f"{side}_{name}": int(self.get_parameter(f"{side}_{name}").value)
                for side in ("left", "right")
                for name in ("rpwm", "lpwm", "r_enable", "l_enable")
            }
            if any(pin < 0 for pin in pins.values()) or len(set(pins.values())) != len(pins):
                raise RuntimeError("all eight distinct BTS7960 BCM GPIO pins must be configured")
            self.config = DriveConfig(
                axle_separation=float(self.get_parameter("axle_separation").value),
                max_wheel_speed=float(self.get_parameter("max_wheel_speed").value),
                max_duty=float(self.get_parameter("max_duty").value),
                left_polarity=float(self.get_parameter("left_polarity").value),
                right_polarity=float(self.get_parameter("right_polarity").value),
            )
            self.left = BTS7960(**{key.removeprefix("left_"): value for key, value in pins.items() if key.startswith("left_")})
            try:
                self.right = BTS7960(**{key.removeprefix("right_"): value for key, value in pins.items() if key.startswith("right_")})
            except Exception:
                self.left.close()
                raise
            self.left.enable()
            self.right.enable()
            self.last_command = 0.0
            self.status_publisher = self.create_publisher(String, "/motors/status", 10)
            self.create_subscription(Twist, "/cmd_vel", self.on_command, 10)
            self.create_timer(0.05, self.watchdog)
            self.create_timer(0.1, self.publish_status)

        def publish_status(self) -> None:
            self.status_publisher.publish(String(data="healthy"))

        def on_command(self, message: Twist) -> None:
            left, right = mix(message.linear.x, message.angular.z, self.config)
            self.left.command(left)
            self.right.command(right)
            self.last_command = time.monotonic()

        def watchdog(self) -> None:
            if self.last_command and time.monotonic() - self.last_command > 0.25:
                self.left.command(0)
                self.right.command(0)
                self.last_command = 0.0

        def destroy_node(self) -> bool:
            self.left.close()
            self.right.close()
            return super().destroy_node()

    rclpy.init(args=args)
    node = MotorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
