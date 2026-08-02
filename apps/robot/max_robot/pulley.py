from __future__ import annotations

import os
import re
import stat
import termios
import time


class PulleyError(RuntimeError):
    pass


class PulleyClient:
    """Non-blocking client for the MAX_PULLEY serial protocol."""

    def __init__(self, device: str) -> None:
        device = os.path.realpath(device)
        if not device.startswith("/dev/"):
            raise PulleyError("pulley device must be an absolute /dev path")
        try:
            self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            if not stat.S_ISCHR(os.fstat(self.fd).st_mode):
                raise PulleyError("pulley device must be a character device")
            attributes = termios.tcgetattr(self.fd)
            attributes[0] = 0
            attributes[1] = 0
            attributes[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            attributes[3] = 0
            attributes[4] = termios.B115200
            attributes[5] = termios.B115200
            attributes[6][termios.VMIN] = 0
            attributes[6][termios.VTIME] = 0
            termios.tcsetattr(self.fd, termios.TCSANOW, attributes)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except (OSError, PulleyError) as exc:
            if hasattr(self, "fd"):
                os.close(self.fd)
            raise PulleyError(f"cannot open pulley controller: {exc}") from exc
        self.buffer = bytearray()
        self.ready = False
        self.fault_reason: str | None = None
        self.active_request_id: str | None = None
        self.active_direction: str | None = None
        self.completed_request_id: str | None = None
        self.last_ping_at = float("-inf")
        self.last_keepalive_at = float("-inf")
        self.started_at = 0.0
        self.acknowledged = False

    def poll(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self._read()
        if self.fault_reason:
            return
        if not self.ready:
            if now - self.last_ping_at >= 0.5:
                self._write("PING")
                self.last_ping_at = now
            return
        if not self.active_request_id:
            return
        if not self.acknowledged and now - self.started_at > 1.0:
            self._stop_and_fail("ACK_TIMEOUT")
            return
        if now - self.started_at > 20.0:
            self._stop_and_fail("PI_TRAVEL_TIMEOUT")
            return
        if now - self.last_keepalive_at >= 0.3:
            self._write(f"KEEPALIVE {self.active_request_id}")
            self.last_keepalive_at = now

    def start(self, request_id: str, direction: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.fault_reason:
            raise PulleyError(f"pulley controller fault: {self.fault_reason}")
        if not self.ready:
            raise PulleyError("pulley controller is not ready")
        if self.active_request_id:
            raise PulleyError("pulley controller is already moving")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", request_id):
            raise PulleyError("invalid pulley request id")
        if direction not in {"UP", "DOWN"}:
            raise PulleyError("invalid pulley direction")
        self.active_request_id = request_id
        self.active_direction = direction
        self.completed_request_id = None
        self.started_at = now
        self.last_keepalive_at = now
        self.acknowledged = False
        self._write(f"MOVE {request_id} {direction}")

    def stop(self) -> None:
        if self.active_request_id and not self.fault_reason:
            self._write(f"STOP {self.active_request_id}")

    def close(self) -> None:
        try:
            self.stop()
        finally:
            os.close(self.fd)

    def _read(self) -> None:
        while True:
            try:
                chunk = os.read(self.fd, 256)
            except BlockingIOError:
                break
            except OSError as exc:
                self._fail(f"SERIAL_READ_{exc.errno}")
                return
            if not chunk:
                self._fail("SERIAL_DISCONNECTED")
                return
            self.buffer.extend(chunk)
            if len(self.buffer) > 1024:
                self._fail("PROTOCOL_OVERFLOW")
                return
        while b"\n" in self.buffer:
            raw, _, remainder = self.buffer.partition(b"\n")
            self.buffer = bytearray(remainder)
            try:
                line = raw.rstrip(b"\r").decode("ascii")
            except UnicodeDecodeError:
                self._fail("NON_ASCII_RESPONSE")
                return
            self._consume(line)

    def _consume(self, line: str) -> None:
        parts = line.split()
        if parts == ["PONG", "1"]:
            self.ready = True
            return
        if parts == ["BOOT", "MAX_PULLEY", "1"]:
            if self.active_request_id:
                self._fail("CONTROLLER_REBOOTED")
            self.ready = False
            return
        if not parts or parts[0] in {"STATE"}:
            return
        if parts[0] in {"ERR", "FAULT"}:
            self._fail(parts[-1] if len(parts) > 1 else "CONTROLLER_ERROR")
            return
        if len(parts) < 3 or parts[1] != self.active_request_id:
            self._fail("RESPONSE_ID_MISMATCH")
            return
        if parts[0] == "ACK" and len(parts) == 4:
            if parts[2] != self.active_direction:
                self._fail("RESPONSE_DIRECTION_MISMATCH")
            else:
                self.acknowledged = True
            return
        if parts[0] == "DONE" and len(parts) == 4:
            if parts[2] != self.active_direction:
                self._fail("RESPONSE_DIRECTION_MISMATCH")
                return
            self.completed_request_id = self.active_request_id
            self.active_request_id = None
            self.active_direction = None
            self.acknowledged = False
            return
        if parts[0] == "STOPPED" and len(parts) == 3:
            self.active_request_id = None
            self.active_direction = None
            self.acknowledged = False
            return
        self._fail("INVALID_RESPONSE")

    def _write(self, line: str) -> None:
        payload = f"{line}\n".encode("ascii")
        try:
            written = os.write(self.fd, payload)
        except OSError as exc:
            self._fail(f"SERIAL_WRITE_{exc.errno}")
            return
        if written != len(payload):
            self._fail("SHORT_SERIAL_WRITE")

    def _stop_and_fail(self, reason: str) -> None:
        self._fail(reason)

    def _fail(self, reason: str) -> None:
        if self.fault_reason:
            return
        self.fault_reason = reason
        self.ready = False
        if self.active_request_id:
            try:
                os.write(self.fd, f"STOP {self.active_request_id}\n".encode("ascii"))
            except OSError:
                pass
