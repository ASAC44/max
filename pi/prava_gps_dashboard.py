#!/usr/bin/env python3
"""Continuously display the GPS state written by the telemetry service."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def age_seconds(timestamp: str | None) -> float | None:
    if not timestamp:
        return None
    try:
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - observed).total_seconds())


def value(payload: dict[str, Any], key: str, suffix: str = "") -> str:
    current = payload.get(key)
    return "—" if current is None else f"{current}{suffix}"


def render(payload: dict[str, Any], path: Path) -> str:
    fix = bool(payload.get("fix"))
    quality = "VALID FIX" if fix else "SEARCHING"
    age = age_seconds(payload.get("updatedAt"))
    age_text = "—" if age is None else f"{age:.1f}s"
    constellations = payload.get("satellitesInView") or {}
    satellites = "  ".join(
        f"{talker}:{count}" for talker, count in sorted(constellations.items())
    )
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    map_url = (
        f"https://maps.google.com/?q={latitude},{longitude}"
        if latitude is not None and longitude is not None
        else "waiting for coordinates"
    )
    return "\n".join(
        (
            "PRAVA GPS — LIVE",
            "=" * 50,
            f"State             {quality}",
            f"Fix quality       {value(payload, 'fixQuality')}",
            f"Fix type          {value(payload, 'fixType')}",
            f"Satellites used    {value(payload, 'satellitesUsed')}",
            f"Satellites visible {satellites or '—'}",
            f"HDOP               {value(payload, 'hdop')}",
            f"Latitude           {value(payload, 'latitude')}",
            f"Longitude          {value(payload, 'longitude')}",
            f"Altitude           {value(payload, 'altitudeMeters', ' m')}",
            f"Speed              {value(payload, 'speedKnots', ' kn')}",
            f"Course             {value(payload, 'courseDegrees', '°')}",
            f"Antenna            {value(payload, 'antenna')}",
            f"Data age           {age_text}",
            "-" * 50,
            map_url,
            f"Source: {path}",
            "Press Ctrl-C to close.",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--status-file",
        type=Path,
        default=Path.home() / ".local/state/prava/gps-status.json",
    )
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    try:
        while True:
            try:
                payload = json.loads(args.status_file.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                payload = {}
            if os.isatty(1):
                print("\033[2J\033[H", end="")
            print(render(payload, args.status_file), flush=True)
            time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
