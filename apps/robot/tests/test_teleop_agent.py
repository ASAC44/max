import json
import time
import unittest

from max_robot.teleop_agent import (
    ALLOWED_KEYS,
    LinuxUInputExecutor,
    TeleopAgentError,
    TeleopInputState,
    TeleopTargetAgent,
    parse_agent_input,
    teleop_websocket_url,
)


class RecordingExecutor:
    def __init__(self):
        self.active = set()
        self.events = []
        self.closed = False

    def press(self, key):
        if key not in self.active:
            self.active.add(key)
            self.events.append(("press", key))

    def release(self, key):
        if key in self.active:
            self.active.remove(key)
            self.events.append(("release", key))

    def release_all(self):
        for key in sorted(self.active):
            self.events.append(("release", key))
        self.active.clear()

    def close(self):
        self.release_all()
        self.closed = True


class FakeSocket:
    def __init__(self):
        self.sent = []

    def send(self, value):
        self.sent.append(json.loads(value))


def input_message(sequence, keys, *, now_ms=None, ttl_ms=350):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return {
        "type": "input",
        "protocol_version": 1,
        "server_sequence": sequence,
        "keys": keys,
        "sent_at_ms": now_ms,
        "expires_at_ms": now_ms + ttl_ms,
        "reason": "test",
    }


class TeleopInputStateTests(unittest.TestCase):
    def setUp(self):
        self.executor = RecordingExecutor()
        self.state = TeleopInputState(self.executor)
        self.state.reset_estop(1)

    def test_all_keys_press_hold_refresh_and_release(self):
        sequence = 1
        for key in sorted(ALLOWED_KEYS):
            sequence += 1
            active = self.state.apply(input_message(sequence, [key]))
            self.assertEqual(active, (key,))
            self.assertEqual(self.executor.active, {key})
            events_before_refresh = list(self.executor.events)

            sequence += 1
            self.state.apply(input_message(sequence, [key]))
            self.assertEqual(self.executor.events, events_before_refresh)

            sequence += 1
            self.state.apply(input_message(sequence, []))
            self.assertEqual(self.executor.active, set())

    def test_simultaneous_keys_change_only_the_delta(self):
        self.state.apply(input_message(2, ["W", "A", "SPACE", "2", "4"]))
        self.assertEqual(self.executor.active, {"W", "A", "SPACE", "2", "4"})
        events_before = list(self.executor.events)
        self.state.apply(input_message(3, ["W", "D", "SPACE", "2", "4"]))
        self.assertEqual(self.executor.active, {"W", "D", "SPACE", "2", "4"})
        self.assertEqual(
            self.executor.events[len(events_before):],
            [("release", "A"), ("press", "D")],
        )

    def test_deadman_disconnect_and_emergency_stop_release_every_key(self):
        self.state.apply(input_message(2, ["W", "SPACE"]))
        self.assertTrue(self.state.tick(now=self.state.deadline + 0.001))
        self.assertEqual(self.executor.active, set())

        self.state.apply(input_message(3, ["A", "3"]))
        self.state.disconnect()
        self.assertEqual(self.executor.active, set())
        self.assertFalse(self.state.armed)
        self.assertEqual(self.state.last_server_sequence, 0)

        self.state.reset_estop(1)
        self.state.apply(input_message(2, ["S", "D"]))
        self.state.emergency_stop(3)
        self.assertEqual(self.executor.active, set())
        self.assertFalse(self.state.armed)

    def test_duplicate_delayed_and_out_of_order_commands_are_safe(self):
        now = int(time.time() * 1000)
        message = input_message(2, ["W"], now_ms=now)
        self.state.apply(message, now_ms=now)
        event_count = len(self.executor.events)
        self.state.apply(message, now_ms=now)
        self.assertEqual(len(self.executor.events), event_count)

        with self.assertRaisesRegex(TeleopAgentError, "older"):
            self.state.apply(input_message(1, ["A"], now_ms=now), now_ms=now)
        self.assertEqual(self.executor.active, {"W"})

        with self.assertRaisesRegex(TeleopAgentError, "expired"):
            self.state.apply(
                input_message(3, ["D"], now_ms=now - 2_000),
                now_ms=now,
            )

    def test_conflicting_duplicate_disarms_executor(self):
        now = int(time.time() * 1000)
        self.state.apply(input_message(2, ["W"], now_ms=now), now_ms=now)
        with self.assertRaisesRegex(TeleopAgentError, "different state"):
            self.state.apply(input_message(2, ["A"], now_ms=now), now_ms=now)
        self.assertEqual(self.executor.active, set())
        self.assertFalse(self.state.armed)

    def test_malformed_and_conflicting_input_is_rejected(self):
        now = 1_000_000
        for keys in (["W", "S"], ["A", "D"], ["1", "2"], ["4", "5"]):
            with self.assertRaisesRegex(TeleopAgentError, "conflicting"):
                parse_agent_input(
                    input_message(2, keys, now_ms=now),
                    now_ms=now,
                )
        unknown = input_message(2, ["X"], now_ms=now)
        with self.assertRaises(TeleopAgentError) as caught:
            parse_agent_input(unknown, now_ms=now)
        self.assertEqual(caught.exception.code, "unknown_key")


class TeleopTargetAgentTests(unittest.TestCase):
    def setUp(self):
        self.executor = RecordingExecutor()
        self.state = TeleopInputState(self.executor)
        self.socket = FakeSocket()
        self.agent = TeleopTargetAgent(
            websocket_url="ws://127.0.0.1:8000/api/teleop/ws/agent",
            token="robot-target-token-1234567890",
            agent_id="max-pi",
            state=self.state,
        )

    def handle(self, value):
        self.agent._handle(self.socket, json.dumps(value))

    def test_reset_input_ack_and_emergency_ack(self):
        self.handle({
            "type": "reset_estop",
            "protocol_version": 1,
            "server_sequence": 1,
            "reason": "test",
        })
        self.assertTrue(self.state.armed)
        self.assertEqual(self.socket.sent[-1]["type"], "reset_ack")

        self.handle(input_message(2, ["W", "A", "SPACE"]))
        self.assertEqual(self.socket.sent[-1]["type"], "input_ack")
        self.assertEqual(set(self.socket.sent[-1]["keys"]), {"W", "A", "SPACE"})

        self.handle({
            "type": "emergency_stop",
            "protocol_version": 1,
            "server_sequence": 3,
            "reason": "test",
        })
        self.assertEqual(self.socket.sent[-1]["type"], "estop_ack")
        self.assertFalse(self.state.armed)
        self.assertEqual(self.executor.active, set())

    def test_expired_input_returns_nack_and_releases(self):
        self.state.reset_estop(1)
        self.state.apply(input_message(2, ["W"]))
        expired = input_message(3, ["A"], now_ms=int(time.time() * 1000) - 2_000)
        with self.assertRaises(TeleopAgentError):
            self.handle(expired)
        self.assertEqual(self.socket.sent[-1]["type"], "input_nack")
        self.state.disconnect()
        self.assertEqual(self.executor.active, set())

    def test_url_conversion_is_scoped_to_agent_route(self):
        self.assertEqual(
            teleop_websocket_url("https://max.example.com"),
            "wss://max.example.com/api/teleop/ws/agent",
        )
        self.assertEqual(
            teleop_websocket_url("http://127.0.0.1:8000"),
            "ws://127.0.0.1:8000/api/teleop/ws/agent",
        )

    def test_uinput_executor_is_scoped_to_approved_key_codes(self):
        self.assertEqual(set(LinuxUInputExecutor.__dict__.keys()) & {"type_text", "move_mouse"}, set())
        self.assertEqual(
            set(ALLOWED_KEYS),
            {"W", "A", "S", "D", "SPACE", "1", "2", "3", "4", "5"},
        )


if __name__ == "__main__":
    unittest.main()
