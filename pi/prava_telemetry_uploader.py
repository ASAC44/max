#!/usr/bin/env python3
"""Relay the current stream endpoint and GPS fix to Prava."""

from __future__ import annotations

import argparse
import json
import signal
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import serial


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def nmea_coordinate(raw: str, hemisphere: str) -> float:
    degree_digits = 2 if hemisphere in {"N", "S"} else 3
    degrees = float(raw[:degree_digits])
    minutes = float(raw[degree_digits:])
    value = degrees + minutes / 60.0
    return -value if hemisphere in {"S", "W"} else value


class GpsReader:
    def __init__(self, device: str, status_file: Path):
        self.device = device
        self.status_file = status_file
        self.running = True
        self.lock = threading.Lock()
        self.latest: dict[str, Any] | None = None
        self.fix_type = "3d"
        self.status: dict[str, Any] = {
            "fix": False,
            "fixQuality": 0,
            "fixType": "none",
            "satellitesUsed": 0,
            "satellitesInView": {},
            "hdop": None,
            "latitude": None,
            "longitude": None,
            "altitudeMeters": None,
            "speedKnots": None,
            "courseDegrees": None,
            "antenna": "unknown",
            "updatedAt": None,
        }
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        self.thread.join(timeout=2)

    def snapshot(self) -> dict[str, Any] | None:
        with self.lock:
            if not self.latest:
                return None
            if time.monotonic() - self.latest["_receivedMonotonic"] > 15:
                return None
            return {key: value for key, value in self.latest.items() if not key.startswith("_")}

    def _write_status(self) -> None:
        with self.lock:
            payload = dict(self.status)
            payload["satellitesInView"] = dict(self.status["satellitesInView"])
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.status_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.status_file)

    def _parse(self, sentence: str) -> None:
        fields = sentence.split("*", 1)[0].split(",")
        message = fields[0][-3:]
        talker = fields[0][1:3]
        if message == "TXT" and len(fields) > 4:
            with self.lock:
                self.status["antenna"] = fields[4]
                self.status["updatedAt"] = utc_now()
            self._write_status()
            return
        if message == "GSV" and len(fields) > 3:
            with self.lock:
                self.status["satellitesInView"][talker] = int(fields[3] or 0)
                self.status["updatedAt"] = utc_now()
            self._write_status()
            return
        if message == "RMC" and len(fields) > 8:
            with self.lock:
                self.status["speedKnots"] = float(fields[7]) if fields[7] else None
                self.status["courseDegrees"] = (
                    float(fields[8]) if fields[8] else None
                )
                self.status["updatedAt"] = utc_now()
            self._write_status()
            return
        if message == "GSA" and len(fields) > 2:
            if fields[2] in {"2", "3"}:
                self.fix_type = "3d" if fields[2] == "3" else "2d"
            else:
                self.fix_type = "none"
            with self.lock:
                self.status["fixType"] = self.fix_type
                self.status["updatedAt"] = utc_now()
            self._write_status()
            return
        if message != "GGA" or len(fields) < 10:
            return
        fix_quality = int(fields[6] or 0)
        satellites = int(fields[7] or 0)
        hdop = float(fields[8]) if fields[8] else None
        has_fix = (
            fix_quality > 0
            and bool(fields[2])
            and bool(fields[3])
            and bool(fields[4])
            and bool(fields[5])
        )
        with self.lock:
            self.status.update(
                {
                    "fix": has_fix,
                    "fixQuality": fix_quality,
                    "fixType": self.fix_type if has_fix else "none",
                    "satellitesUsed": satellites,
                    "hdop": hdop,
                    "latitude": (
                        nmea_coordinate(fields[2], fields[3]) if has_fix else None
                    ),
                    "longitude": (
                        nmea_coordinate(fields[4], fields[5]) if has_fix else None
                    ),
                    "altitudeMeters": (
                        float(fields[9]) if has_fix and fields[9] else None
                    ),
                    "updatedAt": utc_now(),
                }
            )
            if not has_fix:
                self.latest = None
        self._write_status()
        if not has_fix:
            return

        fix = {
            "latitude": nmea_coordinate(fields[2], fields[3]),
            "longitude": nmea_coordinate(fields[4], fields[5]),
            "altitudeMeters": float(fields[9]) if fields[9] else None,
            "satellites": int(fields[7] or 0),
            "hdop": float(fields[8]) if fields[8] else None,
            "fixType": self.fix_type,
            "observedAt": utc_now(),
            "_receivedMonotonic": time.monotonic(),
        }
        with self.lock:
            self.latest = fix

    def _run(self) -> None:
        while self.running:
            try:
                with serial.Serial(self.device, 9600, timeout=1) as gps:
                    print(f"GPS reader active on {self.device}", flush=True)
                    while self.running:
                        sentence = gps.readline().decode("ascii", errors="ignore").strip()
                        if sentence.startswith("$"):
                            try:
                                self._parse(sentence)
                            except (ValueError, IndexError):
                                continue
            except serial.SerialException as exc:
                print(f"GPS unavailable ({exc}); retrying.", flush=True)
                time.sleep(2)


class TelemetryUploader:
    def __init__(
        self,
        endpoint: str,
        token_file: Path,
        stream_url_file: Path,
        gps_status_file: Path,
        interval: float,
        gps_device: str,
    ):
        self.endpoint = endpoint.rstrip("/") + "/api/live/telemetry"
        self.token = token_file.read_text(encoding="utf-8").strip()
        if len(self.token) < 32:
            raise ValueError("Telemetry token is missing or too short")
        self.stream_url_file = stream_url_file
        self.interval = interval
        self.running = True
        self.gps = GpsReader(gps_device, gps_status_file)

    def stop(self) -> None:
        self.running = False

    def close(self) -> None:
        self.gps.stop()

    def stream_details(self) -> dict[str, Any] | None:
        try:
            stream_url = self.stream_url_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        if not stream_url.startswith("https://") or not stream_url.endswith("/"):
            return None
        return {
            "url": stream_url,
            "width": 1920,
            "height": 1080,
            "fps": 30,
            "protocol": "hls",
        }

    def upload_once(self) -> None:
        payload = {
            "source": "pi5",
            "capturedAt": utc_now(),
            "frame": None,
            "stream": self.stream_details(),
            "location": self.gps.snapshot(),
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "Prava-Pi5-Telemetry/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200:
                raise RuntimeError(f"Upload returned HTTP {response.status}")
        location = payload["location"]
        gps_status = (
            f"{location['fixType']} / {location['satellites']} satellites"
            if location
            else "no GPS fix"
        )
        stream_status = "1080p30 stream ready" if payload["stream"] else "stream waiting"
        print(f"Telemetry sent ({stream_status}; {gps_status})", flush=True)

    def run(self) -> None:
        self.gps.start()
        failures = 0
        while self.running:
            started = time.monotonic()
            try:
                self.upload_once()
                failures = 0
            except (OSError, RuntimeError, urllib.error.URLError) as exc:
                failures += 1
                print(f"Telemetry upload failed: {exc}", flush=True)
            elapsed = time.monotonic() - started
            delay = min(30.0, self.interval * max(1, failures))
            time.sleep(max(0.1, delay - elapsed))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path.home() / ".config/prava/telemetry.token",
    )
    parser.add_argument(
        "--stream-url-file",
        type=Path,
        default=Path.home() / ".local/state/prava/stream-url",
    )
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--gps-device", default="/dev/ttyAMA0")
    parser.add_argument(
        "--gps-status-file",
        type=Path,
        default=Path.home() / ".local/state/prava/gps-status.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    uploader = TelemetryUploader(
        args.endpoint,
        args.token_file,
        args.stream_url_file,
        args.gps_status_file,
        args.interval,
        args.gps_device,
    )

    def stop_from_signal(_signum: int, _frame: object) -> None:
        uploader.stop()

    signal.signal(signal.SIGINT, stop_from_signal)
    signal.signal(signal.SIGTERM, stop_from_signal)
    try:
        uploader.run()
    finally:
        uploader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
