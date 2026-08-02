from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect


PROTOCOL_VERSION = 1
ALLOWED_KEYS = frozenset({"W", "A", "S", "D", "SPACE", "1", "2", "3", "4", "5"})
MOVEMENT_OPPOSITES = (frozenset({"W", "S"}), frozenset({"A", "D"}))
DRIVE_MODES = frozenset({"1", "2", "3"})
AUDIO_MODES = frozenset({"4", "5"})
MAX_SEQUENCE = 9_007_199_254_740_991
AUTH_TIMEOUT_SECONDS = 5

logger = logging.getLogger("max.teleop")


class TeleopProtocolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TeleopConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class InputSnapshot:
    sequence: int
    sent_at_ms: int
    keys: tuple[str, ...]


class TeleopSafetyStore:
    """Persist only the safety latch; live key state must never survive a restart."""

    def __init__(self, path: Path):
        self.path = path

    def load_emergency_stop(self) -> bool:
        try:
            value = json.loads(self.path.read_text())
            if (
                value.get("schema_version") == PROTOCOL_VERSION
                and isinstance(value.get("emergency_stop"), bool)
            ):
                return value["emergency_stop"]
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        return True

    def save_emergency_stop(self, active: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = {
            "schema_version": PROTOCOL_VERSION,
            "emergency_stop": active,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with temporary.open("w") as stream:
                json.dump(payload, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def parse_auth_message(value: Any, expected_token: str, role: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TeleopProtocolError("malformed_auth", "authentication message must be an object")
    expected_fields = {
        "controller": {"type", "protocol_version", "token"},
        "agent": {
            "type",
            "protocol_version",
            "token",
            "agent_id",
            "agent_version",
        },
    }.get(role)
    if expected_fields is None or set(value) != expected_fields:
        raise TeleopProtocolError("malformed_auth", "authentication message fields are invalid")
    if value.get("type") != "auth" or value.get("protocol_version") != PROTOCOL_VERSION:
        raise TeleopProtocolError("malformed_auth", "unsupported authentication message")
    token = value.get("token")
    if not isinstance(token, str) or not hmac.compare_digest(token, expected_token):
        raise TeleopProtocolError("unauthorized", f"invalid {role} credential")
    return value


def parse_input_snapshot(
    value: Any,
    *,
    now_ms: int | None = None,
    max_client_age_ms: int = 1_000,
) -> InputSnapshot:
    if not isinstance(value, dict):
        raise TeleopProtocolError("malformed_input", "input message must be an object")
    if set(value) != {"type", "protocol_version", "sequence", "sent_at_ms", "keys"}:
        raise TeleopProtocolError("malformed_input", "input message fields are invalid")
    if value.get("type") != "input" or value.get("protocol_version") != PROTOCOL_VERSION:
        raise TeleopProtocolError("malformed_input", "unsupported input message")
    sequence = value.get("sequence")
    sent_at_ms = value.get("sent_at_ms")
    keys = value.get("keys")
    if (
        not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or not 1 <= sequence <= MAX_SEQUENCE
    ):
        raise TeleopProtocolError("malformed_input", "sequence must be a positive safe integer")
    if not isinstance(sent_at_ms, int) or isinstance(sent_at_ms, bool):
        raise TeleopProtocolError("malformed_input", "sent_at_ms must be an integer")
    if not isinstance(keys, list) or len(keys) > len(ALLOWED_KEYS):
        raise TeleopProtocolError("malformed_input", "keys must be a bounded array")
    if any(not isinstance(key, str) or key not in ALLOWED_KEYS for key in keys):
        raise TeleopProtocolError("unknown_key", "input contains an unsupported key")
    if len(set(keys)) != len(keys):
        raise TeleopProtocolError("malformed_input", "keys must not contain duplicates")
    key_set = frozenset(keys)
    if any(pair <= key_set for pair in MOVEMENT_OPPOSITES):
        raise TeleopProtocolError("conflicting_keys", "opposing movement keys are not allowed")
    if len(key_set & DRIVE_MODES) > 1 or len(key_set & AUDIO_MODES) > 1:
        raise TeleopProtocolError("conflicting_keys", "multiple mode keys are not allowed")
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    age_ms = current_ms - sent_at_ms
    if age_ms > max_client_age_ms or age_ms < -2_000:
        raise TeleopProtocolError("stale_input", "input message is outside the allowed time window")
    return InputSnapshot(
        sequence=sequence,
        sent_at_ms=sent_at_ms,
        keys=tuple(sorted(key_set)),
    )


def parse_simple_message(value: Any, expected_type: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != {"type", "protocol_version"}
        or value.get("type") != expected_type
        or value.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise TeleopProtocolError(
            "malformed_message",
            f"{expected_type} message fields are invalid",
        )


def parse_reported_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > len(ALLOWED_KEYS):
        raise TeleopProtocolError(
            "malformed_agent_message",
            "agent keys must be a bounded array",
        )
    if any(not isinstance(key, str) or key not in ALLOWED_KEYS for key in value):
        raise TeleopProtocolError(
            "malformed_agent_message",
            "agent keys contain an invalid value",
        )
    if len(set(value)) != len(value):
        raise TeleopProtocolError(
            "malformed_agent_message",
            "agent keys contain duplicates",
        )
    key_set = frozenset(value)
    if (
        any(pair <= key_set for pair in MOVEMENT_OPPOSITES)
        or len(key_set & DRIVE_MODES) > 1
        or len(key_set & AUDIO_MODES) > 1
    ):
        raise TeleopProtocolError(
            "malformed_agent_message",
            "agent keys contain a conflicting state",
        )
    return tuple(sorted(key_set))


async def authenticate_websocket(
    websocket: WebSocket,
    *,
    expected_token: str,
    role: str,
) -> dict[str, Any] | None:
    await websocket.accept()
    try:
        value = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=AUTH_TIMEOUT_SECONDS,
        )
        return parse_auth_message(value, expected_token, role)
    except asyncio.TimeoutError:
        await websocket.send_json({
            "type": "error",
            "code": "auth_timeout",
            "message": "authentication timed out",
        })
        await websocket.close(code=4408)
    except (TeleopProtocolError, json.JSONDecodeError) as exc:
        code = exc.code if isinstance(exc, TeleopProtocolError) else "malformed_auth"
        await websocket.send_json({
            "type": "error",
            "code": code,
            "message": "authentication failed",
        })
        await websocket.close(code=4401 if code == "unauthorized" else 4400)
    return None


class TeleopHub:
    """Single-process, single-controller relay with fail-closed state semantics."""

    def __init__(
        self,
        *,
        store: TeleopSafetyStore,
        feature_enabled: bool,
        deadman_ms: int,
        max_client_age_ms: int,
        controller_idle_seconds: float,
        agent_idle_seconds: float,
    ):
        self.store = store
        self.feature_enabled = feature_enabled
        self.deadman_ms = deadman_ms
        self.max_client_age_ms = max_client_age_ms
        self.controller_idle_seconds = controller_idle_seconds
        self.agent_idle_seconds = agent_idle_seconds
        self.emergency_stop = store.load_emergency_stop()
        self.controller: WebSocket | None = None
        self.controller_session_id: str | None = None
        self.controller_connected_at: float | None = None
        self.controller_last_seen = 0.0
        self.controller_last_sequence = 0
        self.controller_last_keys: tuple[str, ...] = ()
        self.agent: WebSocket | None = None
        self.agent_id: str | None = None
        self.agent_version: str | None = None
        self.agent_connected_at: float | None = None
        self.agent_last_seen = 0.0
        self.agent_armed = False
        self.active_keys: tuple[str, ...] = ()
        self.agent_keys: tuple[str, ...] = ()
        self.server_sequence = 0
        self.last_forwarded_at = 0.0
        self.last_agent_ack_at = 0.0
        self.reset_pending_sequence: int | None = None
        self.last_estop_sequence: int | None = None
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=25)
        self.lock = asyncio.Lock()
        self.watchdog_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.watchdog_task is None or self.watchdog_task.done():
            self.watchdog_task = asyncio.create_task(self._watchdog())

    async def stop(self) -> None:
        task = self.watchdog_task
        self.watchdog_task = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        async with self.lock:
            await self._force_release_locked("backend_shutdown")
            peers = [peer for peer in (self.controller, self.agent) if peer is not None]
            self.controller = None
            self.agent = None
            self.agent_armed = False
        for peer in peers:
            try:
                await peer.close(code=1012)
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        latency_ms = None
        if self.last_forwarded_at and self.last_agent_ack_at >= self.last_forwarded_at:
            latency_ms = round((self.last_agent_ack_at - self.last_forwarded_at) * 1000)
        return {
            "schema_version": PROTOCOL_VERSION,
            "feature_enabled": self.feature_enabled,
            "emergency_stop": self.emergency_stop,
            "reset_pending": self.reset_pending_sequence is not None,
            "controls_enabled": (
                self.feature_enabled
                and not self.emergency_stop
                and self.agent is not None
                and self.agent_armed
            ),
            "controller_online": self.controller is not None,
            "controller_session_id": self.controller_session_id,
            "controller_age_seconds": (
                round(now - self.controller_connected_at, 1)
                if self.controller_connected_at is not None
                else None
            ),
            "agent_online": self.agent is not None,
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "agent_armed": self.agent_armed,
            "agent_age_seconds": (
                round(now - self.agent_connected_at, 1)
                if self.agent_connected_at is not None
                else None
            ),
            "active_keys": list(self.active_keys),
            "agent_keys": list(self.agent_keys),
            "last_client_sequence": self.controller_last_sequence,
            "last_server_sequence": self.server_sequence,
            "round_trip_ms": latency_ms,
            "deadman_ms": self.deadman_ms,
            "last_event": self.recent_events[-1] if self.recent_events else None,
        }

    def _record(self, event: str, actor: str, **detail: Any) -> None:
        entry = {
            "event": event,
            "actor": actor,
            "at": datetime.now(timezone.utc).isoformat(),
            **detail,
        }
        self.recent_events.append(entry)
        logger.info(
            "teleop_event event=%s actor=%s detail=%s",
            event,
            actor,
            json.dumps(detail, separators=(",", ":"), sort_keys=True),
        )

    async def _send_controller(self, value: dict[str, Any]) -> bool:
        if self.controller is None:
            return False
        try:
            await self.controller.send_json(value)
            return True
        except Exception as exc:
            logger.warning(
                "teleop_send_failed peer=controller error_class=%s",
                type(exc).__name__,
            )
            return False

    async def _send_agent(self, value: dict[str, Any]) -> bool:
        if self.agent is None:
            return False
        try:
            await self.agent.send_json(value)
            return True
        except Exception as exc:
            logger.warning(
                "teleop_send_failed peer=agent error_class=%s",
                type(exc).__name__,
            )
            return False

    async def _broadcast_status_locked(self) -> None:
        await self._send_controller({"type": "status", **self.status()})

    async def attach_controller(self, websocket: WebSocket) -> None:
        async with self.lock:
            if self.controller is not None:
                raise TeleopConflict("another controller already owns the lease")
            self.controller = websocket
            self.controller_session_id = str(uuid4())
            self.controller_connected_at = time.monotonic()
            self.controller_last_seen = time.monotonic()
            self.controller_last_sequence = 0
            self.controller_last_keys = ()
            self._record(
                "controller_connected",
                "controller",
                session_id=self.controller_session_id,
            )
            await self._send_controller({
                "type": "ready",
                "protocol_version": PROTOCOL_VERSION,
                "session_id": self.controller_session_id,
                **self.status(),
            })

    async def detach_controller(self, websocket: WebSocket, reason: str) -> None:
        async with self.lock:
            if self.controller is not websocket:
                return
            session_id = self.controller_session_id
            self.controller = None
            self.controller_session_id = None
            self.controller_connected_at = None
            self.controller_last_seen = 0.0
            self.controller_last_sequence = 0
            self.controller_last_keys = ()
            await self._force_release_locked(reason)
            self._record(
                "controller_disconnected",
                "controller",
                session_id=session_id,
                reason=reason,
            )

    async def attach_agent(
        self,
        websocket: WebSocket,
        agent_id: str,
        agent_version: str,
    ) -> None:
        async with self.lock:
            if self.agent is not None:
                raise TeleopConflict("another target agent is already connected")
            self.agent = websocket
            self.agent_id = agent_id
            self.agent_version = agent_version
            self.agent_connected_at = time.monotonic()
            self.agent_last_seen = time.monotonic()
            self.agent_armed = False
            self.agent_keys = ()
            self.active_keys = ()
            self.reset_pending_sequence = None
            self._record(
                "agent_connected",
                "agent",
                agent_id=agent_id,
                agent_version=agent_version,
            )
            await self._send_agent({
                "type": "ready",
                "protocol_version": PROTOCOL_VERSION,
                "deadman_ms": self.deadman_ms,
                "emergency_stop": self.emergency_stop,
            })
            if self.emergency_stop:
                await self._send_emergency_stop_locked("agent_connected")
            else:
                await self._request_agent_reset_locked("agent_connected")
            await self._broadcast_status_locked()

    async def detach_agent(self, websocket: WebSocket, reason: str) -> None:
        async with self.lock:
            if self.agent is not websocket:
                return
            agent_id = self.agent_id
            self.agent = None
            self.agent_id = None
            self.agent_version = None
            self.agent_connected_at = None
            self.agent_last_seen = 0.0
            self.agent_armed = False
            self.agent_keys = ()
            self.reset_pending_sequence = None
            await self._force_release_locked(reason)
            self._record(
                "agent_disconnected",
                "agent",
                agent_id=agent_id,
                reason=reason,
            )
            await self._broadcast_status_locked()

    def _next_server_sequence(self) -> int:
        self.server_sequence += 1
        return self.server_sequence

    async def _forward_input_locked(
        self,
        keys: tuple[str, ...],
        *,
        reason: str,
    ) -> int:
        sequence = self._next_server_sequence()
        now_ms = int(time.time() * 1000)
        payload = {
            "type": "input",
            "protocol_version": PROTOCOL_VERSION,
            "server_sequence": sequence,
            "keys": list(keys),
            "sent_at_ms": now_ms,
            "expires_at_ms": now_ms + self.deadman_ms,
            "reason": reason,
        }
        self.last_forwarded_at = time.monotonic()
        if not await self._send_agent(payload):
            raise TeleopProtocolError("agent_offline", "target agent is offline")
        return sequence

    async def _force_release_locked(self, reason: str) -> None:
        had_keys = bool(self.active_keys or self.agent_keys)
        self.active_keys = ()
        self.controller_last_keys = ()
        if self.agent is not None and self.agent_armed:
            try:
                await self._forward_input_locked((), reason=reason)
            except TeleopProtocolError:
                pass
        if had_keys:
            self._record("keys_released", "backend", reason=reason)
        await self._broadcast_status_locked()

    async def _send_emergency_stop_locked(self, reason: str) -> None:
        self.active_keys = ()
        self.controller_last_keys = ()
        self.agent_armed = False
        self.agent_keys = ()
        self.reset_pending_sequence = None
        sequence = self._next_server_sequence()
        self.last_estop_sequence = sequence
        await self._send_agent({
            "type": "emergency_stop",
            "protocol_version": PROTOCOL_VERSION,
            "server_sequence": sequence,
            "reason": reason,
        })

    def _save_latch(self, active: bool) -> bool:
        try:
            self.store.save_emergency_stop(active)
            return True
        except OSError as exc:
            self._record(
                "safety_latch_persistence_failed",
                "backend",
                requested_state=active,
                error_class=type(exc).__name__,
            )
            return False

    async def _engage_emergency_stop_locked(self, reason: str, actor: str) -> None:
        self.emergency_stop = True
        await self._send_emergency_stop_locked(reason)
        self._save_latch(True)
        self._record("emergency_stop", actor, reason=reason)
        await self._broadcast_status_locked()

    async def emergency_stop_now(self, reason: str, actor: str = "operator") -> None:
        async with self.lock:
            await self._engage_emergency_stop_locked(reason, actor)

    async def _request_agent_reset_locked(self, reason: str) -> None:
        if self.agent is None:
            raise TeleopProtocolError("agent_offline", "target agent is offline")
        sequence = self._next_server_sequence()
        self.reset_pending_sequence = sequence
        if not await self._send_agent({
            "type": "reset_estop",
            "protocol_version": PROTOCOL_VERSION,
            "server_sequence": sequence,
            "reason": reason,
        }):
            self.reset_pending_sequence = None
            raise TeleopProtocolError("agent_offline", "target agent is offline")

    async def handle_controller_message(self, websocket: WebSocket, value: Any) -> None:
        async with self.lock:
            if self.controller is not websocket:
                raise TeleopProtocolError("lease_lost", "controller lease is no longer active")
            self.controller_last_seen = time.monotonic()
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                await self._force_release_locked("malformed_controller_message")
                raise TeleopProtocolError("malformed_message", "message must be an object")
            message_type = value["type"]
            if message_type == "heartbeat":
                try:
                    parse_simple_message(value, "heartbeat")
                except TeleopProtocolError:
                    await self._force_release_locked("malformed_heartbeat")
                    raise
                await self._broadcast_status_locked()
                return
            if message_type == "emergency_stop":
                try:
                    parse_simple_message(value, "emergency_stop")
                except TeleopProtocolError:
                    await self._force_release_locked("malformed_emergency_stop")
                    raise
                await self._engage_emergency_stop_locked(
                    "operator_emergency_stop",
                    "controller",
                )
                return
            if message_type == "reset_estop":
                try:
                    parse_simple_message(value, "reset_estop")
                except TeleopProtocolError:
                    await self._force_release_locked("malformed_reset")
                    raise
                if not self.feature_enabled:
                    raise TeleopProtocolError("feature_disabled", "teleoperation is disabled")
                if not self.emergency_stop:
                    await self._broadcast_status_locked()
                    return
                if self.reset_pending_sequence is not None:
                    await self._broadcast_status_locked()
                    return
                await self._request_agent_reset_locked("operator_reset")
                self._record("emergency_reset_requested", "controller")
                await self._broadcast_status_locked()
                return
            if message_type != "input":
                await self._force_release_locked("unknown_controller_message")
                raise TeleopProtocolError("unknown_message", "unsupported controller message")
            try:
                snapshot = parse_input_snapshot(
                    value,
                    max_client_age_ms=self.max_client_age_ms,
                )
            except TeleopProtocolError:
                await self._force_release_locked("invalid_input")
                raise
            if snapshot.sequence < self.controller_last_sequence:
                raise TeleopProtocolError("out_of_order", "input sequence is older than current state")
            if snapshot.sequence == self.controller_last_sequence:
                if snapshot.keys != self.controller_last_keys:
                    await self._force_release_locked("conflicting_duplicate")
                    raise TeleopProtocolError(
                        "conflicting_duplicate",
                        "duplicate sequence contains a different state",
                    )
                await self._send_controller({
                    "type": "input_ack",
                    "sequence": snapshot.sequence,
                    "duplicate": True,
                    "active_keys": list(self.active_keys),
                })
                return
            if not self.feature_enabled:
                await self._force_release_locked("feature_disabled")
                raise TeleopProtocolError("feature_disabled", "teleoperation is disabled")
            if self.emergency_stop or self.reset_pending_sequence is not None:
                await self._force_release_locked("emergency_stop_active")
                raise TeleopProtocolError("emergency_stop", "emergency stop is active")
            if self.agent is None or not self.agent_armed:
                await self._force_release_locked("agent_not_ready")
                raise TeleopProtocolError("agent_offline", "target agent is not ready")
            server_sequence = await self._forward_input_locked(
                snapshot.keys,
                reason="controller_state",
            )
            state_changed = snapshot.keys != self.active_keys
            self.controller_last_sequence = snapshot.sequence
            self.controller_last_keys = snapshot.keys
            self.active_keys = snapshot.keys
            if state_changed:
                self._record(
                    "input_state_changed",
                    "controller",
                    client_sequence=snapshot.sequence,
                    server_sequence=server_sequence,
                    keys=list(snapshot.keys),
                )
            await self._send_controller({
                "type": "input_ack",
                "sequence": snapshot.sequence,
                "server_sequence": server_sequence,
                "duplicate": False,
                "active_keys": list(snapshot.keys),
            })

    async def handle_agent_message(self, websocket: WebSocket, value: Any) -> None:
        async with self.lock:
            if self.agent is not websocket:
                raise TeleopProtocolError("lease_lost", "agent lease is no longer active")
            self.agent_last_seen = time.monotonic()
            if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                raise TeleopProtocolError("malformed_agent_message", "agent message must be an object")
            message_type = value["type"]
            if message_type == "heartbeat":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "active_keys",
                    "armed",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "agent heartbeat fields are invalid",
                    )
                heartbeat_keys = parse_reported_keys(value.get("active_keys"))
                heartbeat_armed = value.get("armed")
                if not isinstance(heartbeat_armed, bool):
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "agent heartbeat armed state is invalid",
                    )
                if (
                    heartbeat_keys != self.agent_keys
                    or heartbeat_armed != self.agent_armed
                ):
                    self._record(
                        "agent_state_mismatch",
                        "agent",
                        reported_keys=list(heartbeat_keys),
                        reported_armed=heartbeat_armed,
                    )
                    await self._engage_emergency_stop_locked(
                        "agent_state_mismatch",
                        "backend",
                    )
                    return
                await self._broadcast_status_locked()
                return
            if message_type == "reset_ack":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "reset acknowledgement fields are invalid",
                    )
                sequence = value.get("server_sequence")
                if sequence != self.reset_pending_sequence:
                    raise TeleopProtocolError("out_of_order", "reset acknowledgement is not current")
                self.reset_pending_sequence = None
                if not self._save_latch(False):
                    await self._engage_emergency_stop_locked(
                        "safety_latch_write_failed",
                        "backend",
                    )
                    return
                self.emergency_stop = False
                self.agent_armed = True
                self.agent_keys = ()
                self._record("emergency_stop_reset", "agent", server_sequence=sequence)
                await self._broadcast_status_locked()
                return
            if message_type == "estop_ack":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "emergency-stop acknowledgement fields are invalid",
                    )
                if value.get("server_sequence") != self.last_estop_sequence:
                    raise TeleopProtocolError(
                        "out_of_order",
                        "emergency-stop acknowledgement is not current",
                    )
                self.agent_armed = False
                self.agent_keys = ()
                await self._broadcast_status_locked()
                return
            if message_type == "input_ack":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                    "keys",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "input acknowledgement fields are invalid",
                    )
                sequence = value.get("server_sequence")
                if (
                    not isinstance(sequence, int)
                    or isinstance(sequence, bool)
                    or sequence < 1
                    or sequence > self.server_sequence
                ):
                    raise TeleopProtocolError("malformed_agent_message", "input acknowledgement is invalid")
                keys = parse_reported_keys(value.get("keys"))
                if sequence < self.server_sequence:
                    return
                if keys != self.active_keys:
                    self.agent_keys = keys
                    self._record(
                        "agent_state_mismatch",
                        "agent",
                        expected_keys=list(self.active_keys),
                        reported_keys=list(keys),
                    )
                    await self._engage_emergency_stop_locked(
                        "agent_state_mismatch",
                        "backend",
                    )
                    return
                self.agent_keys = keys
                self.last_agent_ack_at = time.monotonic()
                await self._send_controller({
                    "type": "agent_ack",
                    "server_sequence": sequence,
                    "keys": list(self.agent_keys),
                    "round_trip_ms": self.status()["round_trip_ms"],
                })
                return
            if message_type == "input_nack":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "server_sequence",
                    "code",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "input rejection fields are invalid",
                    )
                if (
                    not isinstance(value.get("server_sequence"), int)
                    or isinstance(value.get("server_sequence"), bool)
                    or not isinstance(value.get("code"), str)
                    or not 1 <= len(value["code"]) <= 48
                ):
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "input rejection values are invalid",
                    )
                self._record(
                    "agent_rejected_input",
                    "agent",
                    code=str(value.get("code", "unknown"))[:48],
                )
                await self._force_release_locked("agent_rejected_input")
                raise TeleopProtocolError("agent_rejected_input", "target agent rejected input")
            if message_type == "error":
                if set(value) != {
                    "type",
                    "protocol_version",
                    "code",
                } or value.get("protocol_version") != PROTOCOL_VERSION:
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "agent error fields are invalid",
                    )
                if (
                    not isinstance(value.get("code"), str)
                    or not 1 <= len(value["code"]) <= 48
                ):
                    raise TeleopProtocolError(
                        "malformed_agent_message",
                        "agent error code is invalid",
                    )
                self._record(
                    "agent_error",
                    "agent",
                    code=str(value.get("code", "unknown"))[:48],
                )
                await self._force_release_locked("agent_error")
                return
            raise TeleopProtocolError("unknown_agent_message", "unsupported agent message")

    async def controller_loop(self, websocket: WebSocket) -> None:
        try:
            while True:
                try:
                    value = await websocket.receive_json()
                    await self.handle_controller_message(websocket, value)
                except TeleopProtocolError as exc:
                    await self._send_controller({
                        "type": "error",
                        "protocol_version": PROTOCOL_VERSION,
                        "code": exc.code,
                        "message": str(exc),
                        "recoverable": exc.code not in {"lease_lost"},
                    })
        except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
            pass
        finally:
            await self.detach_controller(websocket, "controller_disconnected")

    async def agent_loop(self, websocket: WebSocket) -> None:
        try:
            while True:
                try:
                    value = await websocket.receive_json()
                    await self.handle_agent_message(websocket, value)
                except TeleopProtocolError as exc:
                    await self.emergency_stop_now(
                        "invalid_agent_message",
                        actor="backend",
                    )
                    await self._send_agent({
                        "type": "error",
                        "protocol_version": PROTOCOL_VERSION,
                        "code": exc.code,
                        "message": str(exc),
                    })
        except (WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
            pass
        finally:
            await self.detach_agent(websocket, "agent_disconnected")

    async def _watchdog(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(0.05, self.deadman_ms / 4_000))
                controller_to_close: WebSocket | None = None
                agent_to_close: WebSocket | None = None
                async with self.lock:
                    now = time.monotonic()
                    if (
                        self.active_keys
                        and now - self.last_forwarded_at > self.deadman_ms / 1_000
                    ):
                        await self._force_release_locked("deadman_timeout")
                        self._record("deadman_timeout", "backend")
                    if (
                        self.controller is not None
                        and now - self.controller_last_seen > self.controller_idle_seconds
                    ):
                        controller_to_close = self.controller
                        await self._force_release_locked("controller_idle")
                    if (
                        self.agent is not None
                        and now - self.agent_last_seen > self.agent_idle_seconds
                    ):
                        agent_to_close = self.agent
                        await self._force_release_locked("agent_idle")
                if controller_to_close is not None:
                    try:
                        await controller_to_close.close(code=4410)
                    except RuntimeError:
                        pass
                if agent_to_close is not None:
                    try:
                        await agent_to_close.close(code=4410)
                    except RuntimeError:
                        pass
        except asyncio.CancelledError:
            raise
