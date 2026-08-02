from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum


class LocalizationState(StrEnum):
    INITIALIZING = "INITIALIZING"
    TRACKING = "TRACKING"
    DEGRADED = "DEGRADED"
    LOST = "LOST"


class ObstructionState(StrEnum):
    CLEAR = "CLEAR"
    SUSPECTED = "SUSPECTED"
    STOPPED = "STOPPED"
    WAITING_FOR_CLEAR = "WAITING_FOR_CLEAR"


class MissionState(StrEnum):
    IDLE = "IDLE"
    OUTBOUND = "OUTBOUND"
    AT_PICKUP = "AT_PICKUP"
    RETURNING = "RETURNING"
    PAUSED = "PAUSED"
    WAITING_FOR_CHECKPOINT = "WAITING_FOR_CHECKPOINT"
    OBSTRUCTION_STOP = "OBSTRUCTION_STOP"
    LOCALIZATION_LOST = "LOCALIZATION_LOST"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


MOVING_STATES = {MissionState.OUTBOUND, MissionState.RETURNING}


@dataclass
class SafetyGate:
    localization: LocalizationState = LocalizationState.INITIALIZING
    obstruction: ObstructionState = ObstructionState.CLEAR
    emergency_stop: bool = False
    heartbeat_timeout_s: float = 0.25
    heartbeats: dict[str, float] = field(
        default_factory=lambda: {
            "camera": 0.0,
            "odometry": 0.0,
            "localization": 0.0,
            "obstruction": 0.0,
            "controller": 0.0,
            "motors": 0.0,
            "estop": 0.0,
        }
    )

    def heartbeat(self, source: str, now: float | None = None) -> None:
        if source not in self.heartbeats:
            raise ValueError(f"unknown heartbeat source: {source}")
        self.heartbeats[source] = time.monotonic() if now is None else now

    def reasons(self, now: float | None = None) -> list[str]:
        now = time.monotonic() if now is None else now
        reasons: list[str] = []
        if self.emergency_stop:
            reasons.append("emergency stop active")
        if self.localization is not LocalizationState.TRACKING:
            reasons.append(f"localization is {self.localization}")
        if self.obstruction is not ObstructionState.CLEAR:
            reasons.append(f"obstruction is {self.obstruction}")
        for source, timestamp in self.heartbeats.items():
            if timestamp <= 0 or now - timestamp > self.heartbeat_timeout_s:
                reasons.append(f"{source} heartbeat stale")
        return reasons

    def movement_allowed(self, now: float | None = None) -> bool:
        return not self.reasons(now)


class InvalidTransition(ValueError):
    pass


class MissionManager:
    """Thread-safe mission state machine shared by ROS and the web API."""

    def __init__(
        self,
        safety: SafetyGate | None = None,
        *,
        runtime_mode: str = "unknown",
        pulley_required: bool = False,
    ) -> None:
        self.safety = safety or SafetyGate()
        self.runtime_mode = runtime_mode
        self.waypoint_index = 0
        self.state = MissionState.IDLE
        self.last_reason = ""
        self.mission_id: str | None = None
        self.pulley_required = pulley_required
        self.pulley_status = "connecting" if pulley_required else "not_configured"
        self._resume_state: MissionState | None = None
        self._lock = threading.RLock()

    def start(self, now: float | None = None, mission_id: str | None = None) -> None:
        with self._lock:
            if self.state is MissionState.OUTBOUND and mission_id and mission_id == self.mission_id:
                return
            if self.state not in {
                MissionState.IDLE,
                MissionState.COMPLETE,
                MissionState.CANCELLED,
            }:
                raise InvalidTransition(f"cannot start from {self.state}")
            self._require_safe(now)
            self.mission_id = mission_id
            self.state = MissionState.OUTBOUND
            self.last_reason = ""

    def pause(self, reason: str = "operator stop") -> None:
        with self._lock:
            if self.state not in MOVING_STATES:
                raise InvalidTransition(f"cannot pause from {self.state}")
            self._resume_state = self.state
            self.state = MissionState.PAUSED
            self.last_reason = reason

    def resume(self, now: float | None = None) -> None:
        with self._lock:
            if self.state not in {
                MissionState.PAUSED,
                MissionState.OBSTRUCTION_STOP,
                MissionState.LOCALIZATION_LOST,
            }:
                raise InvalidTransition(f"cannot resume from {self.state}")
            self._require_safe(now)
            if self._resume_state not in MOVING_STATES:
                raise InvalidTransition("no route segment to resume")
            self.state = self._resume_state
            self.last_reason = ""

    def route_segment_complete(self) -> None:
        with self._lock:
            if self.state is MissionState.OUTBOUND:
                self.state = MissionState.AT_PICKUP
            elif self.state is MissionState.RETURNING:
                self.state = MissionState.COMPLETE
            else:
                raise InvalidTransition(f"no active route segment in {self.state}")
            self._resume_state = None

    def await_checkpoint(self, reason: str) -> None:
        with self._lock:
            if self.state not in MOVING_STATES:
                raise InvalidTransition(f"cannot await checkpoint from {self.state}")
            self._resume_state = self.state
            self.state = MissionState.WAITING_FOR_CHECKPOINT
            self.last_reason = reason

    def checkpoint_confirmed(self) -> None:
        with self._lock:
            if (
                self.state is not MissionState.WAITING_FOR_CHECKPOINT
                or self._resume_state not in MOVING_STATES
            ):
                raise InvalidTransition(f"no checkpoint pending in {self.state}")
            self.state = self._resume_state
            self.route_segment_complete()
            self._resume_state = None
            self.last_reason = ""

    def confirm_pickup(self) -> None:
        with self._lock:
            if self.state is not MissionState.AT_PICKUP:
                raise InvalidTransition(f"cannot confirm pickup from {self.state}")
            self.state = MissionState.RETURNING
            self.last_reason = ""

    def safety_stop(self, reason: str) -> None:
        with self._lock:
            if self.state in MOVING_STATES:
                self._resume_state = self.state
            if self.safety.emergency_stop:
                self.state = MissionState.EMERGENCY_STOP
            elif self.safety.obstruction is not ObstructionState.CLEAR:
                self.state = MissionState.OBSTRUCTION_STOP
            elif self.safety.localization is not LocalizationState.TRACKING:
                self.state = MissionState.LOCALIZATION_LOST
            else:
                self.state = MissionState.PAUSED
            self.last_reason = reason

    def emergency_stop(self) -> None:
        with self._lock:
            if self.state in MOVING_STATES:
                self._resume_state = self.state
            self.safety.emergency_stop = True
            self.state = MissionState.EMERGENCY_STOP
            self.last_reason = "emergency stop"

    def release_emergency_stop(self) -> None:
        with self._lock:
            self.safety.emergency_stop = False
            if self._resume_state in MOVING_STATES:
                self.state = MissionState.PAUSED
                self.last_reason = "emergency stop released; resume required"
            else:
                self.state = MissionState.IDLE
                self.last_reason = ""

    def cancel(self, reason: str = "operator cancel") -> None:
        with self._lock:
            self.state = MissionState.CANCELLED
            self._resume_state = None
            self.last_reason = reason

    def status(self, now: float | None = None) -> dict[str, object]:
        with self._lock:
            reasons = self.safety.reasons(now)
            return {
                "runtime_mode": self.runtime_mode,
                "mission": self.state,
                "mission_id": self.mission_id,
                "waypoint_index": self.waypoint_index,
                "localization": self.safety.localization,
                "obstruction": self.safety.obstruction,
                "emergency_stop": self.safety.emergency_stop,
                "pulley_required": self.pulley_required,
                "pulley_status": self.pulley_status,
                "movement_allowed": self.state in MOVING_STATES and not reasons,
                "ready": self.state in {MissionState.IDLE, MissionState.COMPLETE, MissionState.CANCELLED} and not reasons,
                "safety_reasons": reasons,
                "last_reason": self.last_reason,
            }

    def _require_safe(self, now: float | None) -> None:
        reasons = self.safety.reasons(now)
        if reasons:
            raise InvalidTransition("; ".join(reasons))
