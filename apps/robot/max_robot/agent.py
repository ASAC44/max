from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .bridge import BridgeState
from .poller import PollerError, control_url

AGENT_VERSION = "0.3.0"
LIFECYCLE_BY_PHASE = {
    "READY_TO_DISPATCH": "AT_PICKUP",
    "AT_PICKUP": "ITEM_SECURED",
    "ITEM_SECURED": "RETURNING",
    "RETURNING": "COMPLETED",
}


class RobotBackend:
    def __init__(self, *, base_url: str, token: str):
        if len(token) < 24:
            raise PollerError("MAX_ROBOT_TOKEN must contain at least 24 characters")
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = (
            json.dumps(payload, separators=(",", ":")).encode()
            if payload is not None
            else None
        )
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": f"max-pi-agent/{AGENT_VERSION}",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(262_144)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise PollerError("control API request failed") from exc
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise PollerError("control API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise PollerError("control API returned an invalid response")
        return parsed


class HardwareProbes:
    """Presence probes only; they never claim that untested hardware is healthy."""

    @staticmethod
    def _device(path: str) -> str:
        candidate = Path(path)
        if not candidate.exists():
            return "unavailable"
        return "present" if os.access(candidate, os.R_OK) else "degraded"

    def snapshot(self) -> dict[str, str]:
        camera_path = os.getenv("MAX_CAMERA_DEVICE", "/dev/media0")
        gps_path = os.getenv("MAX_GPS_DEVICE", "/dev/serial0")
        imu_path = os.getenv("MAX_IMU_DEVICE", "/dev/i2c-1")
        audio_path = os.getenv("MAX_AUDIO_STATUS_FILE", "/proc/asound/cards")
        estop_path = os.getenv("MAX_ESTOP_DEVICE", "")
        return {
            "camera": self._device(camera_path),
            "gps": self._device(gps_path),
            "imu": self._device(imu_path),
            "audio": self._device(audio_path),
            "motors": "disabled",
            "emergency_stop": self._device(estop_path) if estop_path else "unavailable",
        }


class UnifiedRobotAgent:
    def __init__(
        self,
        *,
        backend: RobotBackend,
        state: BridgeState,
        probes: HardwareProbes | None = None,
        robot_id: str = "max-pi",
        rehearsal: bool = False,
    ):
        self.backend = backend
        self.state = state
        self.probes = probes or HardwareProbes()
        self.robot_id = robot_id
        self.rehearsal = rehearsal
        self.last_error: str | None = None

    def heartbeat(self) -> None:
        subsystems = self.probes.snapshot()
        degraded = any(
            value in {"degraded", "unavailable"}
            for name, value in subsystems.items()
            if name not in {"motors"}
        )
        self.backend.request(
            "POST",
            "/api/robot/v1/heartbeat",
            {
                "robot_id": self.robot_id,
                "agent_version": AGENT_VERSION,
                "mode": "dry_run",
                "status": "DEGRADED" if degraded else "READY",
                "subsystems": subsystems,
                "last_error": self.last_error,
            },
        )

    def sync_order_status(self) -> int:
        response = self.backend.request(
            "GET",
            f"/api/robot/v1/order-status?after={self.state.order_status_cursor}",
        )
        if (
            response.get("schema_version") != 1
            or response.get("motion_enabled") is not False
            or not isinstance(response.get("events"), list)
            or not isinstance(response.get("next_cursor"), int)
        ):
            raise PollerError("control API returned an invalid order status stream")
        try:
            self.state.record_order_status(
                response["events"],
                response["next_cursor"],
            )
        except ValueError as exc:
            raise PollerError("control API returned an invalid order status event") from exc
        return len(response["events"])

    @staticmethod
    def _validated_job(response: dict[str, Any]) -> dict[str, Any] | None:
        if response.get("schema_version") != 1:
            raise PollerError("control API schema mismatch")
        if response.get("motion_enabled") is not False:
            raise PollerError("control API safety contract mismatch")
        job = response.get("job")
        if job is None:
            return None
        if (
            not isinstance(job, dict)
            or job.get("schema_version") != 1
            or job.get("dry_run") is not True
        ):
            raise PollerError("control API returned an unsafe robot job")
        return job

    def _active_job(self) -> tuple[dict[str, Any] | None, bool]:
        current = self._validated_job(
            self.backend.request("GET", "/api/robot/v1/current")
        )
        if current:
            return current, True
        return (
            self._validated_job(self.backend.request("GET", "/api/robot/v1/next")),
            False,
        )

    def run_once(self) -> bool:
        job, resumed = self._active_job()
        if job is None:
            return False
        if not resumed:
            ack = self.state.dispatch(job)
            mission = self.backend.request(
                "POST",
                "/api/robot/v1/ack",
                {
                    "mission_id": ack.mission_id,
                    "command_id": ack.command_id,
                    "status": ack.status,
                    "dry_run": ack.dry_run,
                    "motion_started": ack.motion_started,
                },
            )
            job = {
                **job,
                "expected_version": mission["version"],
                "phase": mission["phase"],
                "job_status": "ACKNOWLEDGED",
            }
        if not self.rehearsal:
            return True
        stage = LIFECYCLE_BY_PHASE.get(str(job.get("phase")))
        if not stage:
            return True
        event_id = f"{job['command_id']}-{stage.lower().replace('_', '-')}"
        self.backend.request(
            "POST",
            "/api/robot/v1/lifecycle",
            {
                "mission_id": job["mission_id"],
                "command_id": job["command_id"],
                "event_id": event_id,
                "expected_version": job["expected_version"],
                "stage": stage,
                "dry_run": True,
                "motion_started": False,
            },
        )
        return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the unified, fail-closed Max Pi agent"
    )
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "MAX_ROBOT_AGENT_STATE_FILE",
            str(Path.home() / ".local/state/max-robot/agent.json"),
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("MAX_ROBOT_POLL_INTERVAL_SECONDS", "5")),
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=float(os.getenv("MAX_ROBOT_HEARTBEAT_INTERVAL_SECONDS", "10")),
    )
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        raise PollerError("poll interval must be between 1 and 60 seconds")
    if not 5 <= args.heartbeat_interval <= 60:
        raise PollerError("heartbeat interval must be between 5 and 60 seconds")
    if os.getenv("MAX_ROBOT_DRY_RUN", "true").lower() != "true":
        raise PollerError("unified Pi agent currently requires MAX_ROBOT_DRY_RUN=true")
    agent = UnifiedRobotAgent(
        backend=RobotBackend(
            base_url=control_url(),
            token=os.getenv("MAX_ROBOT_TOKEN", ""),
        ),
        state=BridgeState(Path(args.state_file)),
        robot_id=os.getenv("MAX_ROBOT_ID", "max-pi"),
        rehearsal=os.getenv("MAX_ROBOT_REHEARSAL", "false").lower() == "true",
    )
    print("Unified Max Pi agent started; physical motion disabled")
    next_heartbeat = 0.0
    while True:
        now = time.monotonic()
        try:
            if now >= next_heartbeat:
                agent.heartbeat()
                next_heartbeat = now + args.heartbeat_interval
            agent.sync_order_status()
            agent.run_once()
            agent.last_error = None
        except PollerError as exc:
            agent.last_error = str(exc)
            print(f"agent failed safely: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
