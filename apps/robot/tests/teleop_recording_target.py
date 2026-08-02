"""Local browser-verification target; production uses LinuxUInputExecutor."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from max_robot.teleop_agent import (
    TeleopInputState,
    TeleopTargetAgent,
    teleop_websocket_url,
)


class RecordingExecutor:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.active: set[str] = set()
        self.events: list[dict] = []
        self._write("started", None)

    def _write(self, action: str, key: str | None) -> None:
        event = {
            "at_ms": int(time.time() * 1000),
            "action": action,
            "key": key,
            "active_keys": sorted(self.active),
        }
        self.events.append(event)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.events, separators=(",", ":")))
        os.replace(temporary, self.path)

    def press(self, key: str) -> None:
        with self.lock:
            if key not in self.active:
                self.active.add(key)
                self._write("press", key)

    def release(self, key: str) -> None:
        with self.lock:
            if key in self.active:
                self.active.remove(key)
                self._write("release", key)

    def release_all(self) -> None:
        with self.lock:
            for key in sorted(self.active):
                self.active.remove(key)
                self._write("release", key)

    def close(self) -> None:
        self.release_all()


def main() -> None:
    executor = RecordingExecutor(Path(os.environ["MAX_TELEOP_RECORDING_FILE"]))
    state = TeleopInputState(executor)
    target = TeleopTargetAgent(
        websocket_url=teleop_websocket_url(os.environ["MAX_CONTROL_API_URL"]),
        token=os.environ["MAX_ROBOT_TOKEN"],
        agent_id="browser-test-agent",
        state=state,
    )
    try:
        target.run_forever()
    finally:
        state.disconnect()
        executor.close()


if __name__ == "__main__":
    main()
