import json
import socket
import threading
import time

import pytest
import uvicorn
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

import max_api.main as main
from max_api.teleop import TeleopHub, TeleopSafetyStore
from max_robot.teleop_agent import TeleopInputState, TeleopTargetAgent


ADMIN_TOKEN = "full-stack-admin-token-1234567890"
ROBOT_TOKEN = "full-stack-robot-token-1234567890"
ORIGIN = "http://127.0.0.1:5173"


class ThreadSafeExecutor:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = set()
        self.events = []

    def press(self, key):
        with self.lock:
            if key not in self.active:
                self.active.add(key)
                self.events.append(("press", key))

    def release(self, key):
        with self.lock:
            if key in self.active:
                self.active.remove(key)
                self.events.append(("release", key))

    def release_all(self):
        with self.lock:
            for key in sorted(self.active):
                self.events.append(("release", key))
            self.active.clear()

    def close(self):
        self.release_all()

    def snapshot(self):
        with self.lock:
            return set(self.active)


def wait_until(operation, *, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if operation():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


def receive_type(websocket, expected, *, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = json.loads(websocket.recv(timeout=max(0.05, deadline - time.monotonic())))
        if value.get("type") == expected:
            return value
    raise AssertionError(f"did not receive {expected}")


def input_message(sequence, keys):
    return {
        "type": "input",
        "protocol_version": 1,
        "sequence": sequence,
        "sent_at_ms": int(time.time() * 1000),
        "keys": keys,
    }


def test_real_websocket_browser_to_backend_to_target_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("MAX_ROBOT_TOKEN", ROBOT_TOKEN)
    monkeypatch.setenv("MAX_WEB_ORIGIN", ORIGIN)
    monkeypatch.setattr(main, "recover_in_progress_attempts", lambda _session: None)
    hub = TeleopHub(
        store=TeleopSafetyStore(tmp_path / "teleop-state.json"),
        feature_enabled=True,
        deadman_ms=250,
        max_client_age_ms=750,
        controller_idle_seconds=3,
        agent_idle_seconds=5,
    )
    monkeypatch.setattr(main, "teleop_hub", hub)

    try:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
    except PermissionError:
        pytest.skip("localhost sockets are disabled")
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        main.app,
        host="127.0.0.1",
        port=port,
        lifespan="on",
        log_level="error",
    ))
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    server_thread.start()
    wait_until(lambda: server.started, timeout=5)

    executor = ThreadSafeExecutor()
    state = TeleopInputState(executor)
    target = TeleopTargetAgent(
        websocket_url=f"ws://127.0.0.1:{port}/api/teleop/ws/agent",
        token=ROBOT_TOKEN,
        agent_id="max-pi-full-stack",
        state=state,
    )
    target_error = []

    def run_target():
        try:
            target.run_connection()
        except Exception as exc:
            target_error.append(exc)
        finally:
            state.disconnect()

    target_thread = threading.Thread(target=run_target, daemon=True)
    target_thread.start()
    wait_until(lambda: hub.agent is not None)

    controller_url = f"ws://127.0.0.1:{port}/api/teleop/ws/controller"
    controller = connect(
        controller_url,
        origin=ORIGIN,
        open_timeout=3,
        close_timeout=1,
        ping_interval=1,
        ping_timeout=1,
        max_size=16_384,
        compression=None,
    )
    try:
        controller.send(json.dumps({
            "type": "auth",
            "protocol_version": 1,
            "token": ADMIN_TOKEN,
        }))
        assert receive_type(controller, "ready")["emergency_stop"] is False
        while True:
            status = receive_type(controller, "status")
            if status["controls_enabled"]:
                break

        controller.send(json.dumps(input_message(1, ["W"])))
        wait_until(lambda: executor.snapshot() == {"W"})

        controller.send(json.dumps(input_message(2, ["W", "A", "SPACE", "2", "4"])))
        wait_until(
            lambda: executor.snapshot() == {"W", "A", "SPACE", "2", "4"},
        )

        # Refreshing a held state does not create duplicate key-down events.
        events_before = len(executor.events)
        controller.send(json.dumps(input_message(3, ["W", "A", "SPACE", "2", "4"])))
        time.sleep(0.05)
        assert len(executor.events) == events_before

        controller.send(json.dumps(input_message(4, [])))
        wait_until(lambda: executor.snapshot() == set())

        controller.send(json.dumps(input_message(5, ["S", "D", "3", "5"])))
        wait_until(lambda: executor.snapshot() == {"S", "D", "3", "5"})
        controller.send(json.dumps({
            "type": "emergency_stop",
            "protocol_version": 1,
        }))
        wait_until(lambda: executor.snapshot() == set())
        wait_until(lambda: hub.emergency_stop is True)
    finally:
        controller.close()

    # A backend restart closes the agent channel; its finally path releases all.
    server.should_exit = True
    server_thread.join(timeout=5)
    listener.close()
    target_thread.join(timeout=5)
    assert executor.snapshot() == set()
    assert not target_thread.is_alive()
    assert not target_error or isinstance(target_error[0], ConnectionClosed)
