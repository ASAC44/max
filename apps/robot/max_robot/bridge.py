from __future__ import annotations

import argparse
import hmac
import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


class BridgeError(ValueError):
    pass


@dataclass(frozen=True)
class DispatchCommand:
    schema_version: int
    mission_id: str
    command_id: str
    destination: str
    dry_run: bool
    trigger_source: str = "OPERATOR"
    trigger_status: str = "PACKAGE_READY"


@dataclass(frozen=True)
class DispatchAck:
    mission_id: str
    command_id: str
    status: str
    dry_run: bool
    motion_started: bool
    acknowledged_at: str


class BridgeState:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.last_command: DispatchCommand | None = None
        self.last_ack: DispatchAck | None = None
        self.order_status_cursor = 0
        self.latest_order_status: dict[str, dict[str, Any]] = {}
        self._load()

    def dispatch(self, payload: dict[str, Any]) -> DispatchAck:
        command = self._parse(payload)
        with self.lock:
            if self.last_command and self.last_command.command_id == command.command_id:
                if self.last_command != command or self.last_ack is None:
                    raise BridgeError("command_id was already used for a different mission command")
                return self.last_ack
            if not command.dry_run:
                raise BridgeError("physical motion is disabled; use dry_run until navigation is validated")
            ack = DispatchAck(
                mission_id=command.mission_id,
                command_id=command.command_id,
                status="ACKNOWLEDGED",
                dry_run=True,
                motion_started=False,
                acknowledged_at=datetime.now(timezone.utc).isoformat(),
            )
            self.last_command = command
            self.last_ack = ack
            self._save()
            return ack

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": "ok",
                "schema_version": 1,
                "motion_enabled": False,
                "last_ack": asdict(self.last_ack) if self.last_ack else None,
                "last_command": asdict(self.last_command) if self.last_command else None,
                "order_status_cursor": self.order_status_cursor,
                "latest_order_status": self.latest_order_status,
            }

    def record_order_status(
        self,
        events: list[dict[str, Any]],
        next_cursor: int,
    ) -> None:
        with self.lock:
            if next_cursor < self.order_status_cursor:
                raise BridgeError("order status cursor moved backwards")
            for event in events:
                event_id = event.get("event_id")
                mission_id = event.get("mission_id")
                status = event.get("normalized_status")
                if (
                    not isinstance(event_id, int)
                    or event_id <= self.order_status_cursor
                    or event_id > next_cursor
                    or not isinstance(mission_id, str)
                    or not mission_id
                    or not isinstance(status, str)
                    or not status
                ):
                    raise BridgeError("invalid order status event")
                self.latest_order_status[mission_id] = dict(event)
            self.order_status_cursor = next_cursor
            self._save()

    @staticmethod
    def _parse(payload: dict[str, Any]) -> DispatchCommand:
        if payload.get("schema_version") != 1:
            raise BridgeError("unsupported schema_version")
        mission_id = payload.get("mission_id")
        command_id = payload.get("command_id")
        destination = payload.get("destination")
        dry_run = payload.get("dry_run")
        trigger_source = payload.get("trigger_source", "OPERATOR")
        trigger_status = payload.get("trigger_status", "PACKAGE_READY")
        if not isinstance(mission_id, str) or not 8 <= len(mission_id) <= 64:
            raise BridgeError("invalid mission_id")
        if not isinstance(command_id, str) or not 8 <= len(command_id) <= 64:
            raise BridgeError("invalid command_id")
        if not isinstance(destination, str) or not 1 <= len(destination) <= 100:
            raise BridgeError("invalid destination")
        if not isinstance(dry_run, bool):
            raise BridgeError("dry_run must be a boolean")
        if trigger_source not in {"OPERATOR", "SWIGGY"}:
            raise BridgeError("invalid trigger_source")
        if not isinstance(trigger_status, str) or not 1 <= len(trigger_status) <= 48:
            raise BridgeError("invalid trigger_status")
        return DispatchCommand(
            1,
            mission_id,
            command_id,
            destination,
            dry_run,
            trigger_source,
            trigger_status,
        )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "last_command": asdict(self.last_command) if self.last_command else None,
            "last_ack": asdict(self.last_ack) if self.last_ack else None,
            "order_status_cursor": self.order_status_cursor,
            "latest_order_status": self.latest_order_status,
        }
        with tempfile.NamedTemporaryFile(
            "w",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            delete=False,
        ) as handle:
            json.dump(value, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(self.path)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            value = json.loads(self.path.read_text())
            if value.get("last_command"):
                self.last_command = DispatchCommand(**value["last_command"])
            if value.get("last_ack"):
                self.last_ack = DispatchAck(**value["last_ack"])
            cursor = value.get("order_status_cursor", 0)
            latest = value.get("latest_order_status", {})
            if isinstance(cursor, int) and cursor >= 0 and isinstance(latest, dict):
                self.order_status_cursor = cursor
                self.latest_order_status = latest
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.last_command = None
            self.last_ack = None
            self.order_status_cursor = 0
            self.latest_order_status = {}


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        token: str,
        allowed_client: str,
        state: BridgeState,
    ):
        if len(token) < 24:
            raise ValueError("bridge token must contain at least 24 characters")
        self.token = token
        self.allowed_client = allowed_client
        self.state = state
        super().__init__(address, BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeServer

    def do_GET(self) -> None:
        if self.path == "/api/v1/health":
            self._json(HTTPStatus.OK, {"status": "ok", "schema_version": 1, "motion_enabled": False})
        elif self.path == "/api/v1/status":
            if self._authorized():
                self._json(HTTPStatus.OK, self.server.state.status())
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/v1/missions/dispatch":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise BridgeError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise BridgeError("request body must be an object")
            ack = self.server.state.dispatch(payload)
        except (BridgeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        self._json(HTTPStatus.OK, asdict(ack))

    def _authorized(self) -> bool:
        if self.server.allowed_client and self.client_address[0] != self.server.allowed_client:
            self._json(HTTPStatus.FORBIDDEN, {"error": "client is not allowed"})
            return False
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        if not hmac.compare_digest(supplied, expected):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid credential"})
            return False
        return True

    def _json(self, status: HTTPStatus, value: object) -> None:
        body = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the fail-closed Max Pi mission bridge")
    parser.add_argument("--host", default=os.getenv("MAX_BRIDGE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MAX_BRIDGE_PORT", "8081")))
    parser.add_argument(
        "--state-file",
        default=os.getenv(
            "MAX_BRIDGE_STATE_FILE",
            str(Path.home() / ".local/state/max-robot/bridge.json"),
        ),
    )
    args = parser.parse_args()
    token = os.getenv("MAX_ROBOT_TOKEN", "")
    allowed_client = os.getenv("MAX_BRIDGE_ALLOWED_CLIENT", "")
    server = BridgeServer(
        (args.host, args.port),
        token=token,
        allowed_client=allowed_client,
        state=BridgeState(Path(args.state_file)),
    )
    print(f"Max Pi bridge listening on http://{args.host}:{args.port}; motion disabled")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
