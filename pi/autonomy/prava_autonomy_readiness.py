#!/usr/bin/env python3
"""Audit Raspberry Pi readiness without enabling autonomous motor output."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path


def command_output(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def read_temperature() -> float | None:
    match = re.search(
        r"(-?\d+(?:\.\d+)?)",
        command_output(["/usr/bin/vcgencmd", "measure_temp"]),
    )
    return float(match.group(1)) if match else None


def read_throttled() -> int | None:
    match = re.search(
        r"0x([0-9a-fA-F]+)",
        command_output(["/usr/bin/vcgencmd", "get_throttled"]),
    )
    return int(match.group(1), 16) if match else None


def load_hardware(path: Path) -> dict[str, bool]:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "mpu6050_wired",
        "wheel_encoders_installed",
        "physical_estop_installed",
        "depth_or_lidar_installed",
        "active_cooling_installed",
        "gps_route_recorded",
        "camera_obstruction_validated",
        "route_replay_shadow_validated",
        "remote_supervisor_ready",
    }
    missing = expected.difference(data)
    if missing:
        raise ValueError(f"missing hardware declarations: {sorted(missing)}")
    return {key: bool(data[key]) for key in expected}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--hardware",
        type=Path,
        default=Path(__file__).with_name("hardware.json"),
    )
    parser.add_argument(
        "--mode",
        choices=("route-replay", "general-autonomy"),
        default="route-replay",
    )
    args = parser.parse_args()
    hardware = load_hardware(args.hardware)
    temperature = read_temperature()
    throttled = read_throttled()

    route_replay = args.mode == "route-replay"
    ros2_available = shutil.which("ros2") is not None
    navigation_source_ready = (
        hardware["wheel_encoders_installed"]
        or (
            route_replay
            and hardware["gps_route_recorded"]
            and hardware["route_replay_shadow_validated"]
        )
    )
    obstacle_system_ready = (
        hardware["depth_or_lidar_installed"]
        or (
            route_replay
            and hardware["camera_obstruction_validated"]
            and hardware["remote_supervisor_ready"]
        )
    )

    checks: dict[str, dict[str, object]] = {
        "ros2_runtime": {
            "pass": route_replay or ros2_available,
            "available": ros2_available,
            "detail": (
                "ROS 2 is optional for the direct Python route-replay mode and "
                "required for the original general-autonomy stack"
            ),
        },
        "header_i2c": {
            "pass": Path("/dev/i2c-1").exists(),
            "detail": "GPIO2/GPIO3 I2C bus must be enabled",
        },
        "mpu6050": {
            "pass": hardware["mpu6050_wired"],
            "detail": "MPU6050 must be wired, detected, and calibrated",
        },
        "wheel_odometry": {
            "pass": navigation_source_ready,
            "detail": (
                "Use measured wheel encoders, or a recorded route that has passed "
                "camera/GPS/IMU shadow replay in route-replay mode"
            ),
        },
        "physical_estop": {
            "pass": hardware["physical_estop_installed"],
            "detail": "A physical motor-power emergency stop is mandatory",
        },
        "obstacle_sensor": {
            "pass": obstacle_system_ready,
            "detail": (
                "Use depth/lidar, or validated camera stopping with a connected "
                "supervisor in route-replay mode"
            ),
        },
        "active_cooling": {
            "pass": hardware["active_cooling_installed"],
            "detail": "Sustained VSLAM requires verified active cooling",
        },
        "temperature": {
            "pass": temperature is not None and temperature < 75.0,
            "value_c": temperature,
            "detail": "Temperature must remain below the 75C autonomy limit",
        },
        "not_throttled": {
            "pass": throttled is not None and not (throttled & 0xF),
            "value": f"0x{throttled:x}" if throttled is not None else None,
            "detail": "Current undervoltage, thermal, or frequency throttling blocks motion",
        },
    }
    ready = all(bool(check["pass"]) for check in checks.values())
    print(
        json.dumps(
            {
                "autonomous_motor_output_enabled": False,
                "ready_for_physical_autonomy": ready,
                "mode": args.mode,
                "checks": checks,
            },
            indent=2,
        )
    )
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
