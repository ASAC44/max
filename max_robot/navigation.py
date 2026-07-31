from __future__ import annotations

import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Pose2D:
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class Waypoint:
    x: float
    y: float


@dataclass(frozen=True)
class Velocity:
    linear: float
    angular: float


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class WaypointFollower:
    def __init__(
        self,
        waypoints: list[Waypoint],
        *,
        max_linear: float = 0.15,
        max_angular: float = 0.8,
        goal_tolerance: float = 0.12,
    ) -> None:
        if not waypoints:
            raise ValueError("at least one waypoint is required")
        self._outbound = tuple(waypoints)
        self.waypoints = list(self._outbound)
        self.max_linear = max_linear
        self.max_angular = max_angular
        self.goal_tolerance = goal_tolerance
        self.index = 0
        self._reverse = False

    @property
    def complete(self) -> bool:
        return self.index >= len(self.waypoints)

    @property
    def reversed(self) -> bool:
        return self._reverse

    @property
    def reference_index(self) -> int:
        if self.complete:
            raise ValueError("completed route has no active reference")
        if self._reverse:
            return min(len(self._outbound) - 1, len(self._outbound) - self.index)
        return max(0, self.index - 1)

    def reset(self, reverse: bool = False) -> None:
        self._reverse = reverse
        self.waypoints = list(reversed(self._outbound) if reverse else self._outbound)
        self.index = 0

    def command(self, pose: Pose2D) -> Velocity:
        while not self.complete:
            target = self.waypoints[self.index]
            dx, dy = target.x - pose.x, target.y - pose.y
            distance = math.hypot(dx, dy)
            if distance > self.goal_tolerance:
                break
            self.index += 1

        if self.complete:
            return Velocity(0.0, 0.0)

        heading_error = normalize_angle(math.atan2(dy, dx) - pose.yaw)
        angular = max(-self.max_angular, min(self.max_angular, 2.0 * heading_error))
        linear = self.max_linear * max(0.0, math.cos(heading_error))
        if abs(heading_error) > math.pi / 3:
            linear = 0.0
        return Velocity(linear, angular)


class TagTracker:
    def __init__(self) -> None:
        self._seen: dict[int, float] = {}

    def observe(self, tag_id: int, now: float | None = None) -> None:
        self._seen[tag_id] = time.monotonic() if now is None else now

    def seen_recently(
        self, tag_id: int | None, *, max_age_s: float = 1.0, now: float | None = None
    ) -> bool:
        if tag_id is None:
            return True
        now = time.monotonic() if now is None else now
        return now - self._seen.get(tag_id, float("-inf")) <= max_age_s
