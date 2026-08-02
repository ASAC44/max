from __future__ import annotations

import argparse
import json
import os
import time
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from .bridge import BridgeState
from .poller import PollerError, control_url

AGENT_VERSION = "0.5.0"
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


class LocalRobot:
    def __init__(self, *, base_url: str, operator_pin: str):
        if len(operator_pin) < 4:
            raise PollerError("MAX_OPERATOR_PIN must contain at least four characters")
        parsed = urlparse(base_url)
        try:
            host = ip_address(parsed.hostname or "")
        except ValueError as exc:
            raise PollerError("MAX_LOCAL_ROBOT_URL must use a loopback IP") from exc
        if (
            parsed.scheme != "http"
            or not host.is_loopback
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise PollerError("MAX_LOCAL_ROBOT_URL must be a plain loopback HTTP URL")
        self.base_url = base_url.rstrip("/")
        self.operator_pin = operator_pin

    def request(
        self,
        method: str,
        path: str,
        *,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        headers = {"X-Operator-Pin": self.operator_pin}
        if mission_id:
            headers["X-Mission-Id"] = mission_id
        try:
            with urlopen(
                Request(f"{self.base_url}{path}", method=method, headers=headers),
                timeout=3,
            ) as response:
                value = json.loads(response.read(65_536))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise PollerError("local robot control request failed") from exc
        if not isinstance(value, dict):
            raise PollerError("local robot control returned an invalid response")
        return value

    def status(self) -> dict[str, Any]:
        return self.request("GET", "/api/status")

    def start(self, mission_id: str) -> dict[str, Any]:
        return self.request("POST", "/api/mission/start", mission_id=mission_id)

    def cancel(self) -> None:
        self.request("POST", "/api/mission/cancel")

    def emergency_stop(self) -> None:
        self.request("POST", "/api/mission/emergency-stop")


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
        physical: bool = False,
        local_robot: LocalRobot | None = None,
    ):
        self.backend = backend
        self.state = state
        self.probes = probes or HardwareProbes()
        self.robot_id = robot_id
        self.rehearsal = rehearsal
        self.physical = physical
        self.local_robot = local_robot
        if physical and local_robot is None:
            raise PollerError("physical mode requires local robot control")
        self.last_error: str | None = None

    def heartbeat(self) -> None:
        local = self.local_robot.status() if self.physical else None
        subsystems = self._physical_subsystems(local) if local else self.probes.snapshot()
        degraded = any(
            value in {"degraded", "unavailable"}
            for name, value in subsystems.items()
            if name not in ({"motors"} if not self.physical else set())
        )
        status = "READY"
        if local and local.get("emergency_stop"):
            status = "EMERGENCY_STOP"
        elif degraded:
            status = "DEGRADED"
        elif local and local.get("mission") not in {"IDLE", "COMPLETE", "CANCELLED"}:
            status = "BUSY"
        self.backend.request(
            "POST",
            "/api/robot/v1/heartbeat",
            {
                "robot_id": self.robot_id,
                "agent_version": AGENT_VERSION,
                "mode": "physical" if self.physical else "dry_run",
                "status": status,
                "subsystems": subsystems,
                "last_error": self.last_error,
            },
        )

    @staticmethod
    def _physical_subsystems(status: dict[str, Any]) -> dict[str, str]:
        reasons = " ".join(str(value) for value in status.get("safety_reasons", []))
        healthy = lambda name: "degraded" if name in reasons else "healthy"
        subsystems = {
            "camera": healthy("camera"),
            "odometry": healthy("odometry"),
            "localization": "healthy" if status.get("localization") == "TRACKING" and "localization" not in reasons else "degraded",
            "obstruction": "healthy" if status.get("obstruction") == "CLEAR" and "obstruction" not in reasons else "degraded",
            "motors": healthy("motors") if status.get("runtime_mode") == "physical" else "unavailable",
            "controller": healthy("controller"),
            "emergency_stop": (
                "degraded"
                if status.get("emergency_stop") or "estop" in reasons
                else "healthy"
            ),
        }
        if status.get("pulley_required"):
            subsystems["pulley"] = (
                "healthy"
                if status.get("pulley_status") in {"ready", "moving"}
                else "degraded"
            )
        return subsystems

    def sync_order_status(self) -> int:
        response = self.backend.request(
            "GET",
            f"/api/robot/v1/order-status?after={self.state.order_status_cursor}",
        )
        if (
            response.get("schema_version") != 1
            or response.get("motion_enabled") != self.physical
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

    def _validated_job(self, response: dict[str, Any]) -> dict[str, Any] | None:
        if response.get("schema_version") != 1:
            raise PollerError("control API schema mismatch")
        if response.get("motion_enabled") != self.physical:
            raise PollerError("control API safety contract mismatch")
        job = response.get("job")
        if job is None:
            return None
        if (
            not isinstance(job, dict)
            or job.get("schema_version") != 1
            or job.get("dry_run") != (not self.physical)
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
        if job.get("job_status") == "CANCEL_REQUESTED":
            if not self.physical:
                raise PollerError("dry-run job cannot request a physical stop")
            self.local_robot.cancel()
            stopped = self.local_robot.status()
            if (
                stopped.get("mission") != "CANCELLED"
                or stopped.get("mission_id") != job["mission_id"]
            ):
                raise PollerError("local robot did not confirm cancellation")
            self.backend.request(
                "POST",
                "/api/robot/v1/lifecycle",
                {
                    "mission_id": job["mission_id"],
                    "command_id": job["command_id"],
                    "event_id": f"{job['command_id']}-cancelled",
                    "expected_version": job["expected_version"],
                    "stage": "CANCELLED",
                    "dry_run": False,
                    "motion_started": True,
                },
            )
            return True
        if not resumed:
            motion_started = False
            if self.physical:
                status = self.local_robot.status()
                if status.get("runtime_mode") != "physical" or status.get("ready") is not True:
                    raise PollerError("local physical robot is not ready")
                started = self.local_robot.start(job["mission_id"])
                if started.get("mission") != "OUTBOUND" or started.get("mission_id") != job["mission_id"]:
                    raise PollerError("local physical robot did not start the mission")
                motion_started = True
            try:
                ack = self.state.dispatch(job, motion_started=motion_started)
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
            except Exception as exc:
                if self.physical:
                    try:
                        self.local_robot.cancel()
                    except PollerError:
                        self.local_robot.emergency_stop()
                if isinstance(exc, PollerError):
                    raise
                raise PollerError("dispatch acknowledgement failed") from exc
            job = {
                **job,
                "expected_version": mission["version"],
                "phase": mission["phase"],
                "job_status": "ACKNOWLEDGED",
            }
        if self.physical:
            local = self.local_robot.status()
            phase = str(job.get("phase"))
            local_phase = str(local.get("mission"))
            stage = (
                "CANCELLED" if local_phase == "CANCELLED"
                else "AT_PICKUP" if phase == "EN_ROUTE_TO_PICKUP" and local_phase in {"AT_PICKUP", "RETURNING", "COMPLETE"}
                else "ITEM_SECURED" if phase == "AT_PICKUP" and local_phase in {"RETURNING", "COMPLETE"}
                else "RETURNING" if phase == "ITEM_SECURED" and local_phase in {"RETURNING", "COMPLETE"}
                else "COMPLETED" if phase == "RETURNING" and local_phase == "COMPLETE"
                else None
            )
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
                    "dry_run": False,
                    "motion_started": True,
                },
            )
            return True
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

    def fail_safe(self) -> None:
        if not self.physical:
            return
        try:
            self.local_robot.emergency_stop()
        except PollerError:
            pass


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
    physical = os.getenv("MAX_ROBOT_DRY_RUN", "true").lower() == "false"
    agent = UnifiedRobotAgent(
        backend=RobotBackend(
            base_url=control_url(),
            token=os.getenv("MAX_ROBOT_TOKEN", ""),
        ),
        state=BridgeState(Path(args.state_file)),
        robot_id=os.getenv("MAX_ROBOT_ID", "max-pi"),
        rehearsal=os.getenv("MAX_ROBOT_REHEARSAL", "false").lower() == "true",
        physical=physical,
        local_robot=(
            LocalRobot(
                base_url=os.getenv("MAX_LOCAL_ROBOT_URL", "http://127.0.0.1:8080"),
                operator_pin=os.getenv("MAX_OPERATOR_PIN", ""),
            )
            if physical
            else None
        ),
    )
    print(f"Unified Max Pi agent started; mode={'physical' if physical else 'dry_run'}")
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
            agent.fail_safe()
            print(f"agent failed safely: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
