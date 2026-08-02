#!/usr/bin/env python3
"""Manual authenticated teleop smoke test.

Movement mode must only be used while the physical drive service is verified
stopped. The script always releases all keys and re-latches emergency stop.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from websockets.sync.client import connect


PROTOCOL_VERSION = 1


def receive_until(websocket, predicate, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = json.loads(websocket.recv(timeout=0.5))
        except TimeoutError:
            continue
        if isinstance(value, dict) and predicate(value):
            return value
    raise TimeoutError("expected WebSocket state was not received")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--origin", required=True)
    parser.add_argument(
        "--movement-recorder-test",
        action="store_true",
        help="emit movement keys; requires the physical drive service to be stopped",
    )
    args = parser.parse_args()
    token = os.getenv("MAX_ADMIN_TOKEN", "")
    if len(token) < 24:
        raise RuntimeError("MAX_ADMIN_TOKEN must be provided in the environment")

    websocket = connect(
        args.url,
        origin=args.origin,
        open_timeout=10,
        close_timeout=2,
        ping_interval=10,
        ping_timeout=5,
        max_size=16_384,
        compression=None,
    )
    sequence = 0

    def send(value: dict) -> None:
        websocket.send(json.dumps(value, separators=(",", ":")))

    def send_simple(message_type: str) -> None:
        send({
            "type": message_type,
            "protocol_version": PROTOCOL_VERSION,
        })

    def snapshot(keys: list[str], hold_seconds: float = 0.0) -> None:
        nonlocal sequence
        deadline = time.monotonic() + hold_seconds
        first = True
        while first or time.monotonic() < deadline:
            first = False
            sequence += 1
            send({
                "type": "input",
                "protocol_version": PROTOCOL_VERSION,
                "sequence": sequence,
                "sent_at_ms": int(time.time() * 1000),
                "keys": sorted(keys),
            })
            time.sleep(0.1)
        sequence += 1
        send({
            "type": "input",
            "protocol_version": PROTOCOL_VERSION,
            "sequence": sequence,
            "sent_at_ms": int(time.time() * 1000),
            "keys": [],
        })
        time.sleep(0.15)

    result = {"ready": False, "controls_enabled": False, "estop_relatched": False}
    try:
        send({
            "type": "auth",
            "protocol_version": PROTOCOL_VERSION,
            "token": token,
        })
        ready = receive_until(websocket, lambda value: value.get("type") == "ready")
        result["ready"] = True
        if ready.get("agent_online") is not True:
            raise RuntimeError("target agent is offline")

        send_simple("reset_estop")
        receive_until(
            websocket,
            lambda value: (
                value.get("type") == "status"
                and value.get("controls_enabled") is True
                and value.get("emergency_stop") is False
            ),
        )
        result["controls_enabled"] = True

        if args.movement_recorder_test:
            for key in ["W", "A", "S", "D"]:
                snapshot([key], hold_seconds=0.4)
            snapshot(["W", "A", "SPACE", "2", "4"], hold_seconds=0.5)
            snapshot(["S", "D", "3", "5"], hold_seconds=0.5)
        else:
            for key in ["1", "2", "3", "4", "5"]:
                snapshot([key])
            snapshot(["SPACE"], hold_seconds=0.5)
            snapshot(["1"])
    finally:
        try:
            snapshot([])
            send_simple("emergency_stop")
            receive_until(
                websocket,
                lambda value: (
                    value.get("type") == "status"
                    and value.get("emergency_stop") is True
                    and value.get("active_keys") == []
                    and value.get("agent_keys") == []
                ),
            )
            result["estop_relatched"] = True
        finally:
            websocket.close()
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
