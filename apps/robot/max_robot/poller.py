from __future__ import annotations

import argparse
import json
import os
import time
from ipaddress import ip_address
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .bridge import BridgeState


class PollerError(RuntimeError):
    pass


def control_url() -> str:
    value = os.getenv("MAX_CONTROL_API_URL", "").rstrip("/")
    parsed = urlparse(value)
    try:
        host = ip_address(parsed.hostname or "")
        private_http = parsed.scheme == "http" and (host.is_private or host.is_loopback)
    except ValueError:
        private_http = parsed.scheme == "http" and parsed.hostname in {"localhost"}
    if parsed.scheme != "https" and not private_http:
        raise PollerError("MAX_CONTROL_API_URL must use HTTPS or private-network HTTP")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PollerError("MAX_CONTROL_API_URL must not contain credentials, query, or fragment")
    return value


class CloudPoller:
    def __init__(self, state: BridgeState, *, base_url: str, token: str):
        if len(token) < 24:
            raise PollerError("MAX_ROBOT_TOKEN must contain at least 24 characters")
        self.state = state
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "max-pi-poller/1",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(65_536)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise PollerError("control API request failed") from exc
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError as exc:
            raise PollerError("control API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise PollerError("control API returned an invalid response")
        return parsed

    def poll_once(self) -> bool:
        response = self._request("GET", "/api/robot/v1/next")
        if response.get("schema_version") != 1 or response.get("motion_enabled") is not False:
            raise PollerError("control API safety contract mismatch")
        job = response.get("job")
        if job is None:
            return False
        if not isinstance(job, dict):
            raise PollerError("control API returned an invalid robot job")
        ack = self.state.dispatch(job)
        self._request(
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
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll the Max backend for fail-closed Pi jobs")
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "MAX_BRIDGE_STATE_FILE",
            str(Path.home() / ".local/state/max-robot/poller.json"),
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("MAX_ROBOT_POLL_INTERVAL_SECONDS", "5")),
    )
    args = parser.parse_args()
    if not 1 <= args.interval <= 60:
        raise PollerError("poll interval must be between 1 and 60 seconds")
    poller = CloudPoller(
        BridgeState(Path(args.state_file)),
        base_url=control_url(),
        token=os.getenv("MAX_ROBOT_TOKEN", ""),
    )
    print("Max Pi poller started; physical motion disabled")
    while True:
        try:
            poller.poll_once()
        except PollerError as exc:
            print(f"poll failed safely: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
