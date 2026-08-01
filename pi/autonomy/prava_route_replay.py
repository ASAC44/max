#!/usr/bin/env python3
"""Fail-closed controller core for a taught GPS/camera/IMU route.

This module produces drive intents only. It does not access GPIO or command the
motors.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path


EARTH_RADIUS_M = 6_371_000.0


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def distance_m(
    first_lat: float,
    first_lon: float,
    second_lat: float,
    second_lon: float,
) -> float:
    lat1 = math.radians(first_lat)
    lat2 = math.radians(second_lat)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second_lon - first_lon)
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def target_yaw_enu(
    first_lat: float,
    first_lon: float,
    second_lat: float,
    second_lon: float,
) -> float:
    """Return target yaw in ROS ENU convention: east=0, left/CCW positive."""

    lat1 = math.radians(first_lat)
    lat2 = math.radians(second_lat)
    delta_lon = math.radians(second_lon - first_lon)
    east = math.sin(delta_lon) * math.cos(lat2)
    north = (
        math.cos(lat1) * math.sin(lat2)
        - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    )
    compass_bearing = math.atan2(east, north)
    return normalize_angle(math.pi / 2.0 - compass_bearing)


@dataclass(frozen=True)
class RoutePoint:
    latitude: float
    longitude: float
    label: str = ""


@dataclass(frozen=True)
class Route:
    points: tuple[RoutePoint, ...]
    name: str = "unnamed"

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            raise ValueError("route requires at least two points")
        for point in self.points:
            if not -90.0 <= point.latitude <= 90.0:
                raise ValueError("route latitude is invalid")
            if not -180.0 <= point.longitude <= 180.0:
                raise ValueError("route longitude is invalid")
        for first, second in zip(self.points, self.points[1:]):
            spacing = distance_m(
                first.latitude,
                first.longitude,
                second.latitude,
                second.longitude,
            )
            if not 1.0 <= spacing <= 10.0:
                raise ValueError(
                    f"route point spacing must be 1-10m; got {spacing:.2f}m"
                )

    @classmethod
    def load(cls, path: Path) -> "Route":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("unsupported route version")
        points = tuple(
            RoutePoint(
                latitude=float(point["latitude"]),
                longitude=float(point["longitude"]),
                label=str(point.get("label", "")),
            )
            for point in data["points"]
        )
        return cls(points=points, name=str(data.get("name", "unnamed")))


@dataclass(frozen=True)
class SensorFrame:
    now: float
    latitude: float
    longitude: float
    gps_fix: bool
    gps_hdop: float | None
    gps_timestamp: float
    # Fused camera/GPS/gyro yaw. Raw MPU6050 gyro integration is not absolute yaw.
    yaw_enu_rad: float
    imu_timestamp: float
    camera_steering: float
    camera_confidence: float
    camera_timestamp: float
    obstruction_clear: bool
    obstruction_timestamp: float


@dataclass(frozen=True)
class DriveIntent:
    linear_mps: float = 0.0
    angular_rps: float = 0.0
    route_index: int = 0
    movement_allowed: bool = False
    complete: bool = False
    reason: str = ""


class RouteReplayController:
    """Combine coarse GPS progress with IMU heading and camera path alignment."""

    def __init__(
        self,
        route: Route,
        *,
        max_linear_mps: float = 0.12,
        max_angular_rps: float = 0.8,
        waypoint_radius_m: float = 3.0,
        max_route_error_m: float = 8.0,
        minimum_camera_confidence: float = 0.70,
        maximum_hdop: float = 2.5,
    ) -> None:
        self.route = route
        self.max_linear_mps = max_linear_mps
        self.max_angular_rps = max_angular_rps
        self.waypoint_radius_m = waypoint_radius_m
        self.max_route_error_m = max_route_error_m
        self.minimum_camera_confidence = minimum_camera_confidence
        self.maximum_hdop = maximum_hdop
        self.index = 1

    def reset(self) -> None:
        self.index = 1

    def _blocked(self, frame: SensorFrame) -> str:
        if not frame.gps_fix:
            return "GPS fix unavailable"
        if frame.gps_hdop is None or frame.gps_hdop > self.maximum_hdop:
            return "GPS dilution too high"
        if frame.now - frame.gps_timestamp > 2.0:
            return "GPS data stale"
        if frame.now - frame.imu_timestamp > 0.25:
            return "IMU data stale"
        if frame.now - frame.camera_timestamp > 0.25:
            return "camera data stale"
        if frame.now - frame.obstruction_timestamp > 0.25:
            return "obstruction data stale"
        if not frame.obstruction_clear:
            return "obstruction detected"
        if not 0.0 <= frame.camera_confidence <= 1.0:
            return "camera confidence invalid"
        if frame.camera_confidence < self.minimum_camera_confidence:
            return "camera path lock lost"
        if not -1.0 <= frame.camera_steering <= 1.0:
            return "camera steering invalid"
        if not all(
            math.isfinite(value)
            for value in (
                frame.latitude,
                frame.longitude,
                frame.yaw_enu_rad,
                frame.camera_steering,
            )
        ):
            return "sensor value is not finite"
        nearby = self.route.points[
            max(0, self.index - 2) : min(len(self.route.points), self.index + 3)
        ]
        nearest = min(
            distance_m(
                frame.latitude,
                frame.longitude,
                point.latitude,
                point.longitude,
            )
            for point in nearby
        )
        if nearest > self.max_route_error_m:
            return f"robot is {nearest:.1f}m away from taught route"
        return ""

    def command(self, frame: SensorFrame) -> DriveIntent:
        blocked = self._blocked(frame)
        if blocked:
            return DriveIntent(route_index=self.index, reason=blocked)

        target = self.route.points[self.index]
        target_distance = distance_m(
            frame.latitude,
            frame.longitude,
            target.latitude,
            target.longitude,
        )
        while (
            target_distance <= self.waypoint_radius_m
            and self.index < len(self.route.points) - 1
        ):
            self.index += 1
            target = self.route.points[self.index]
            target_distance = distance_m(
                frame.latitude,
                frame.longitude,
                target.latitude,
                target.longitude,
            )

        if (
            self.index == len(self.route.points) - 1
            and target_distance <= self.waypoint_radius_m
        ):
            return DriveIntent(
                route_index=self.index,
                movement_allowed=False,
                complete=True,
                reason="route complete",
            )

        desired_yaw = target_yaw_enu(
            frame.latitude,
            frame.longitude,
            target.latitude,
            target.longitude,
        )
        heading_error = normalize_angle(desired_yaw - frame.yaw_enu_rad)
        angular = 1.2 * heading_error + 0.7 * frame.camera_steering
        angular = max(-self.max_angular_rps, min(self.max_angular_rps, angular))

        heading_scale = max(0.0, math.cos(heading_error))
        camera_scale = max(0.0, 1.0 - 0.7 * abs(frame.camera_steering))
        linear = (
            self.max_linear_mps
            * heading_scale
            * camera_scale
            * frame.camera_confidence
        )
        if abs(heading_error) > math.radians(60):
            linear = 0.0

        return DriveIntent(
            linear_mps=linear,
            angular_rps=angular,
            route_index=self.index,
            movement_allowed=True,
        )
