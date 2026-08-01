#!/usr/bin/env python3
"""Fail-closed safety boundary between Max navigation and Prava motor output."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum


class OdometrySource(str, Enum):
    NONE = "none"
    IMU_ONLY = "imu_only"
    TIMED_PWM = "timed_pwm"
    WHEEL_ENCODERS = "wheel_encoders"
    CAMERA_GPS_IMU_ROUTE = "camera_gps_imu_route"


@dataclass(frozen=True)
class Twist2D:
    linear_mps: float = 0.0
    angular_rps: float = 0.0


@dataclass(frozen=True)
class MotorCommand:
    left: float = 0.0
    right: float = 0.0


@dataclass
class PravaAutonomyGuard:
    """Validate navigation health before exposing normalized motor commands.

    Hardware output is disabled by default. Releasing an emergency stop never
    arms the robot, and arming requires a fresh command before motion is
    permitted.
    """

    heartbeat_timeout_s: float = 0.25
    max_temperature_c: float = 75.0
    hardware_output_enabled: bool = False
    armed: bool = False
    emergency_stop: bool = True
    localization_tracking: bool = False
    obstruction_clear: bool = False
    odometry_source: OdometrySource = OdometrySource.NONE
    route_replay_validated: bool = False
    physical_estop_verified: bool = False
    remote_supervisor_connected: bool = False
    temperature_c: float | None = None
    throttled_mask: int = 0
    command: Twist2D = field(default_factory=Twist2D)
    armed_at: float = 0.0
    heartbeats: dict[str, float] = field(
        default_factory=lambda: {
            "camera": 0.0,
            "odometry": 0.0,
            "localization": 0.0,
            "obstruction": 0.0,
            "controller": 0.0,
            "command": 0.0,
        }
    )

    def heartbeat(self, source: str, now: float | None = None) -> None:
        if source not in self.heartbeats:
            raise ValueError(f"unknown heartbeat source: {source}")
        self.heartbeats[source] = time.monotonic() if now is None else now

    def set_command(
        self,
        linear_mps: float,
        angular_rps: float,
        now: float | None = None,
    ) -> None:
        if not math.isfinite(linear_mps) or not math.isfinite(angular_rps):
            self.engage_emergency_stop()
            raise ValueError("velocity command must contain finite values")
        self.command = Twist2D(linear_mps, angular_rps)
        self.heartbeat("command", now)

    def engage_emergency_stop(self) -> None:
        self.emergency_stop = True
        self.armed = False
        self.command = Twist2D()

    def release_emergency_stop(self) -> None:
        self.emergency_stop = False
        self.armed = False
        self.command = Twist2D()

    def arm(self, now: float | None = None) -> None:
        self.armed = True
        self.armed_at = time.monotonic() if now is None else now
        self.command = Twist2D()

    def disarm(self) -> None:
        self.armed = False
        self.command = Twist2D()

    def blocking_reasons(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        reasons: list[str] = []
        if not self.hardware_output_enabled:
            reasons.append("hardware output disabled")
        if not self.armed:
            reasons.append("not armed")
        if self.emergency_stop:
            reasons.append("emergency stop active")
        route_replay_ready = (
            self.odometry_source is OdometrySource.CAMERA_GPS_IMU_ROUTE
            and self.route_replay_validated
            and self.remote_supervisor_connected
        )
        if (
            self.odometry_source is not OdometrySource.WHEEL_ENCODERS
            and not route_replay_ready
        ):
            reasons.append(
                "validated wheel odometry or supervised camera/GPS/IMU "
                f"route replay required; got {self.odometry_source}"
            )
        if not self.physical_estop_verified:
            reasons.append("physical motor-power emergency stop not verified")
        if (
            self.odometry_source is OdometrySource.CAMERA_GPS_IMU_ROUTE
            and not self.route_replay_validated
        ):
            reasons.append("route replay has not passed shadow validation")
        if (
            self.odometry_source is OdometrySource.CAMERA_GPS_IMU_ROUTE
            and not self.remote_supervisor_connected
        ):
            reasons.append("route replay supervisor disconnected")
        if not self.localization_tracking:
            reasons.append("localization not tracking")
        if not self.obstruction_clear:
            reasons.append("obstruction state not clear")
        if self.temperature_c is None:
            reasons.append("temperature unavailable")
        elif self.temperature_c >= self.max_temperature_c:
            reasons.append(
                f"temperature {self.temperature_c:.1f}C exceeds "
                f"{self.max_temperature_c:.1f}C limit"
            )
        if self.throttled_mask & 0xF:
            reasons.append(
                f"current Raspberry Pi throttle flags set: "
                f"0x{self.throttled_mask & 0xF:x}"
            )
        for source, timestamp in self.heartbeats.items():
            if timestamp <= 0 or now - timestamp > self.heartbeat_timeout_s:
                reasons.append(f"{source} heartbeat stale")
        if self.heartbeats["command"] <= self.armed_at:
            reasons.append("fresh command required after arming")
        return reasons

    def motor_command(
        self,
        *,
        track_width_m: float,
        max_wheel_speed_mps: float,
        now: float | None = None,
    ) -> MotorCommand:
        if track_width_m <= 0 or max_wheel_speed_mps <= 0:
            raise ValueError("drive geometry and maximum speed must be positive")
        if self.blocking_reasons(now):
            return MotorCommand()

        half_track = track_width_m / 2.0
        left_mps = self.command.linear_mps - self.command.angular_rps * half_track
        right_mps = self.command.linear_mps + self.command.angular_rps * half_track
        peak = max(abs(left_mps), abs(right_mps), max_wheel_speed_mps)
        scale = max_wheel_speed_mps / peak
        return MotorCommand(
            left=left_mps * scale / max_wheel_speed_mps,
            right=right_mps * scale / max_wheel_speed_mps,
        )
