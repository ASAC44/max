from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from .poller import PollerError, control_url


PROTOCOL_VERSION = 1
AGENT_VERSION = "1.0.0"
ALLOWED_KEYS = frozenset({"W", "A", "S", "D", "SPACE", "1", "2", "3", "4", "5"})
OPPOSING_KEYS = (frozenset({"W", "S"}), frozenset({"A", "D"}))
DRIVE_MODES = frozenset({"1", "2", "3"})
AUDIO_MODES = frozenset({"4", "5"})
KEY_CODES = {
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "W": 17,
    "A": 30,
    "S": 31,
    "D": 32,
    "SPACE": 57,
}

logger = logging.getLogger("max.teleop_agent")


class TeleopAgentError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class KeyExecutor(Protocol):
    def press(self, key: str) -> None: ...

    def release(self, key: str) -> None: ...

    def release_all(self) -> None: ...

    def close(self) -> None: ...


class LinuxUInputExecutor:
    """Emit only the ten approved keys through a dedicated Linux input device."""

    EV_SYN = 0
    EV_KEY = 1
    SYN_REPORT = 0

    def __init__(
        self,
        *,
        device: str = "/dev/uinput",
        name: str = "Max Remote Teleop",
    ):
        if os.name != "posix" or not os.path.exists(device):
            raise TeleopAgentError("uinput_unavailable", f"{device} is unavailable")
        try:
            from evdev import UInput
        except ModuleNotFoundError as exc:
            raise TeleopAgentError(
                "uinput_library_unavailable",
                "python3-evdev is required",
            ) from exc
        self.lock = threading.RLock()
        self.active: set[str] = set()
        self.closed = False
        try:
            self.input = UInput(
                {self.EV_KEY: sorted(KEY_CODES.values())},
                name=name,
                vendor=0x1D6B,
                product=0x0104,
                version=1,
                devnode=device,
            )
        except OSError as exc:
            raise TeleopAgentError(
                "uinput_setup_failed",
                f"cannot create a virtual keyboard through {device}",
            ) from exc
        time.sleep(0.1)

    def _emit(self, key: str, value: int) -> None:
        if key not in KEY_CODES:
            raise TeleopAgentError("unknown_key", "unsupported key")
        self.input.write(self.EV_KEY, KEY_CODES[key], value)
        self.input.syn()

    def press(self, key: str) -> None:
        with self.lock:
            if self.closed:
                raise TeleopAgentError("executor_closed", "input executor is closed")
            if key in self.active:
                return
            self._emit(key, 1)
            self.active.add(key)

    def release(self, key: str) -> None:
        with self.lock:
            if self.closed or key not in self.active:
                return
            self._emit(key, 0)
            self.active.remove(key)

    def release_all(self) -> None:
        with self.lock:
            if self.closed:
                return
            for key in sorted(self.active):
                try:
                    self._emit(key, 0)
                except OSError as exc:
                    logger.error(
                        "teleop_release_failed key=%s error_class=%s",
                        key,
                        type(exc).__name__,
                    )
            self.active.clear()

    def close(self) -> None:
        with self.lock:
            if self.closed:
                return
            self.release_all()
            self.input.close()
            self.closed = True


@dataclass(frozen=True)
class AgentInput:
    server_sequence: int
    keys: tuple[str, ...]
    sent_at_ms: int
    expires_at_ms: int


def parse_agent_input(value: Any, *, now_ms: int | None = None) -> AgentInput:
    if not isinstance(value, dict):
        raise TeleopAgentError("malformed_input", "input must be an object")
    if set(value) != {
        "type",
        "protocol_version",
        "server_sequence",
        "keys",
        "sent_at_ms",
        "expires_at_ms",
        "reason",
    }:
        raise TeleopAgentError("malformed_input", "input fields are invalid")
    if value.get("type") != "input" or value.get("protocol_version") != PROTOCOL_VERSION:
        raise TeleopAgentError("protocol_mismatch", "input protocol mismatch")
    sequence = value.get("server_sequence")
    sent_at_ms = value.get("sent_at_ms")
    expires_at_ms = value.get("expires_at_ms")
    keys = value.get("keys")
    reason = value.get("reason")
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or not isinstance(sent_at_ms, int)
        or isinstance(sent_at_ms, bool)
        or not isinstance(expires_at_ms, int)
        or isinstance(expires_at_ms, bool)
    ):
        raise TeleopAgentError("malformed_input", "input timing or sequence is invalid")
    if not isinstance(reason, str) or not 1 <= len(reason) <= 64:
        raise TeleopAgentError("malformed_input", "input reason is invalid")
    if not isinstance(keys, list) or len(keys) > len(ALLOWED_KEYS):
        raise TeleopAgentError("malformed_input", "keys must be a bounded array")
    if (
        len(set(keys)) != len(keys)
        or any(not isinstance(key, str) or key not in ALLOWED_KEYS for key in keys)
    ):
        raise TeleopAgentError("unknown_key", "keys contain an invalid value")
    key_set = frozenset(keys)
    if (
        any(pair <= key_set for pair in OPPOSING_KEYS)
        or len(key_set & DRIVE_MODES) > 1
        or len(key_set & AUDIO_MODES) > 1
    ):
        raise TeleopAgentError("conflicting_keys", "conflicting key state is invalid")
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if expires_at_ms <= sent_at_ms or expires_at_ms - sent_at_ms > 1_000:
        raise TeleopAgentError("invalid_expiry", "input expiry interval is invalid")
    if current_ms > expires_at_ms or sent_at_ms - current_ms > 2_000:
        raise TeleopAgentError("expired_input", "input expired before execution")
    return AgentInput(
        server_sequence=sequence,
        keys=tuple(sorted(key_set)),
        sent_at_ms=sent_at_ms,
        expires_at_ms=expires_at_ms,
    )


class TeleopInputState:
    def __init__(self, executor: KeyExecutor):
        self.executor = executor
        self.active_keys: tuple[str, ...] = ()
        self.armed = False
        self.last_server_sequence = 0
        self.deadline = 0.0

    def _release_all(self) -> None:
        self.executor.release_all()
        self.active_keys = ()
        self.deadline = 0.0

    def emergency_stop(self, server_sequence: int) -> None:
        if (
            not isinstance(server_sequence, int)
            or isinstance(server_sequence, bool)
            or server_sequence < 1
        ):
            raise TeleopAgentError("malformed_estop", "emergency-stop sequence is invalid")
        self._release_all()
        self.armed = False
        self.last_server_sequence = max(self.last_server_sequence, server_sequence)

    def reset_estop(self, server_sequence: int) -> None:
        if (
            not isinstance(server_sequence, int)
            or isinstance(server_sequence, bool)
            or server_sequence <= self.last_server_sequence
        ):
            raise TeleopAgentError("out_of_order", "reset sequence is not newer")
        self._release_all()
        self.last_server_sequence = server_sequence
        self.armed = True

    def apply(self, value: Any, *, now_ms: int | None = None) -> tuple[str, ...]:
        try:
            parsed = parse_agent_input(value, now_ms=now_ms)
        except TeleopAgentError:
            self._release_all()
            raise
        if parsed.server_sequence < self.last_server_sequence:
            raise TeleopAgentError("out_of_order", "input sequence is older than current state")
        if parsed.server_sequence == self.last_server_sequence:
            if parsed.keys != self.active_keys:
                self._release_all()
                self.armed = False
                raise TeleopAgentError(
                    "conflicting_duplicate",
                    "duplicate sequence contains a different state",
                )
            self.deadline = time.monotonic() + max(
                0,
                (parsed.expires_at_ms - (now_ms or int(time.time() * 1000))) / 1_000,
            )
            return self.active_keys
        if not self.armed:
            self._release_all()
            raise TeleopAgentError("emergency_stop", "target input is not armed")
        desired = set(parsed.keys)
        current = set(self.active_keys)
        try:
            for key in sorted(current - desired):
                self.executor.release(key)
            for key in sorted(desired - current):
                self.executor.press(key)
        except Exception as exc:
            self._release_all()
            self.armed = False
            raise TeleopAgentError(
                "input_execution_failed",
                f"input execution failed: {type(exc).__name__}",
            ) from exc
        self.active_keys = parsed.keys
        self.last_server_sequence = parsed.server_sequence
        current_ms = int(time.time() * 1000) if now_ms is None else now_ms
        self.deadline = time.monotonic() + max(
            0,
            (parsed.expires_at_ms - current_ms) / 1_000,
        )
        return self.active_keys

    def tick(self, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if self.active_keys and current >= self.deadline:
            self._release_all()
            return True
        return False

    def disconnect(self) -> None:
        self._release_all()
        self.armed = False
        self.last_server_sequence = 0


def teleop_websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.query or parsed.fragment:
        raise PollerError("MAX_CONTROL_API_URL is invalid for teleoperation")
    return urlunparse((
        "wss" if parsed.scheme == "https" else "ws",
        parsed.netloc,
        "/api/teleop/ws/agent",
        "",
        "",
        "",
    ))


class TeleopTargetAgent:
    def __init__(
        self,
        *,
        websocket_url: str,
        token: str,
        agent_id: str,
        state: TeleopInputState,
    ):
        if len(token) < 24:
            raise PollerError("MAX_ROBOT_TOKEN must contain at least 24 characters")
        if (
            not 1 <= len(agent_id) <= 64
            or any(
                character
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                for character in agent_id
            )
        ):
            raise PollerError(
                "MAX_ROBOT_ID must contain 1-64 letters, numbers, underscores, or hyphens"
            )
        self.websocket_url = websocket_url
        self.token = token
        self.agent_id = agent_id
        self.state = state

    def _send(self, websocket, value: dict[str, Any]) -> None:
        websocket.send(json.dumps(value, separators=(",", ":")))

    def _handle(self, websocket, raw: str | bytes) -> None:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.state.emergency_stop(max(1, self.state.last_server_sequence))
            raise TeleopAgentError("invalid_json", "backend returned invalid JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise TeleopAgentError("malformed_message", "backend message is invalid")
        message_type = value["type"]
        sequence = value.get("server_sequence")
        if message_type == "ready":
            if (
                set(value) != {
                    "type",
                    "protocol_version",
                    "deadman_ms",
                    "emergency_stop",
                }
                or value.get("protocol_version") != PROTOCOL_VERSION
                or not isinstance(value.get("deadman_ms"), int)
                or isinstance(value.get("deadman_ms"), bool)
                or not 150 <= value["deadman_ms"] <= 1_000
                or not isinstance(value.get("emergency_stop"), bool)
            ):
                raise TeleopAgentError("protocol_mismatch", "backend protocol mismatch")
            return
        if message_type == "emergency_stop":
            if (
                set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                    "reason",
                }
                or value.get("protocol_version") != PROTOCOL_VERSION
                or not isinstance(value.get("reason"), str)
                or not 1 <= len(value["reason"]) <= 64
            ):
                self.state.disconnect()
                raise TeleopAgentError(
                    "malformed_estop",
                    "backend emergency-stop message is invalid",
                )
            self.state.emergency_stop(sequence)
            self._send(websocket, {
                "type": "estop_ack",
                "protocol_version": PROTOCOL_VERSION,
                "server_sequence": sequence,
            })
            return
        if message_type == "reset_estop":
            if (
                set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                    "reason",
                }
                or value.get("protocol_version") != PROTOCOL_VERSION
                or not isinstance(value.get("reason"), str)
                or not 1 <= len(value["reason"]) <= 64
            ):
                self.state.disconnect()
                raise TeleopAgentError(
                    "malformed_reset",
                    "backend reset message is invalid",
                )
            self.state.reset_estop(sequence)
            self._send(websocket, {
                "type": "reset_ack",
                "protocol_version": PROTOCOL_VERSION,
                "server_sequence": sequence,
            })
            return
        if message_type == "input":
            try:
                keys = self.state.apply(value)
            except TeleopAgentError as exc:
                self._send(websocket, {
                    "type": "input_nack",
                    "protocol_version": PROTOCOL_VERSION,
                    "server_sequence": sequence,
                    "code": exc.code,
                })
                raise
            self._send(websocket, {
                "type": "input_ack",
                "protocol_version": PROTOCOL_VERSION,
                "server_sequence": sequence,
                "keys": list(keys),
            })
            return
        if message_type == "error":
            if (
                set(value) != {
                    "type",
                    "protocol_version",
                    "code",
                    "message",
                }
                or value.get("protocol_version") != PROTOCOL_VERSION
                or not isinstance(value.get("code"), str)
                or not isinstance(value.get("message"), str)
            ):
                self.state.disconnect()
                raise TeleopAgentError(
                    "malformed_message",
                    "backend error message is invalid",
                )
            logger.warning(
                "teleop_backend_error code=%s",
                str(value.get("code", "unknown"))[:48],
            )
            return
        raise TeleopAgentError("unknown_message", "backend message type is unsupported")

    def run_connection(self) -> None:
        heartbeat_at = time.monotonic()
        with connect(
            self.websocket_url,
            open_timeout=10,
            close_timeout=2,
            ping_interval=10,
            ping_timeout=5,
            max_size=16_384,
            compression=None,
        ) as websocket:
            self._send(websocket, {
                "type": "auth",
                "protocol_version": PROTOCOL_VERSION,
                "token": self.token,
                "agent_id": self.agent_id,
                "agent_version": AGENT_VERSION,
            })
            while True:
                try:
                    raw = websocket.recv(timeout=0.05)
                    self._handle(websocket, raw)
                except TimeoutError:
                    if self.state.tick():
                        self._send(websocket, {
                            "type": "error",
                            "protocol_version": PROTOCOL_VERSION,
                            "code": "local_deadman_timeout",
                        })
                if time.monotonic() >= heartbeat_at:
                    self._send(websocket, {
                        "type": "heartbeat",
                        "protocol_version": PROTOCOL_VERSION,
                        "active_keys": list(self.state.active_keys),
                        "armed": self.state.armed,
                    })
                    heartbeat_at = time.monotonic() + 2

    def run_forever(self) -> None:
        delay = 0.5
        while True:
            try:
                self.run_connection()
                delay = 0.5
            except (ConnectionClosed, OSError, TimeoutError, TeleopAgentError) as exc:
                logger.error(
                    "teleop_connection_failed error_class=%s",
                    type(exc).__name__,
                )
            finally:
                self.state.disconnect()
            time.sleep(delay + random.uniform(0, delay / 4))
            delay = min(10, delay * 2)


def main() -> None:
    logging.basicConfig(
        level=os.getenv("MAX_TELEOP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if os.getenv("MAX_TELEOP_INPUT_ENABLED", "false").lower() != "true":
        raise PollerError("MAX_TELEOP_INPUT_ENABLED=true is required")
    executor = LinuxUInputExecutor(
        device=os.getenv("MAX_TELEOP_UINPUT_DEVICE", "/dev/uinput"),
        name=os.getenv("MAX_TELEOP_INPUT_DEVICE_NAME", "Max Remote Teleop"),
    )
    state = TeleopInputState(executor)
    target = TeleopTargetAgent(
        websocket_url=teleop_websocket_url(control_url()),
        token=os.getenv("MAX_ROBOT_TOKEN", ""),
        agent_id=os.getenv("MAX_ROBOT_ID", "max-pi"),
        state=state,
    )
    logger.info("teleop_target_agent_started agent_id=%s", target.agent_id)
    try:
        target.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.disconnect()
        executor.close()


if __name__ == "__main__":
    main()
