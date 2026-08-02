import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import max_api.main as main
from max_api.teleop import (
    ALLOWED_KEYS,
    TeleopHub,
    TeleopProtocolError,
    TeleopSafetyStore,
    parse_auth_message,
    parse_input_snapshot,
)


ADMIN_TOKEN = "teleop-admin-token-1234567890"
ROBOT_TOKEN = "teleop-robot-token-1234567890"
ORIGIN = "http://127.0.0.1:5173"


def new_hub(tmp_path, *, deadman_ms=200):
    return TeleopHub(
        store=TeleopSafetyStore(tmp_path / "teleop-state.json"),
        feature_enabled=True,
        deadman_ms=deadman_ms,
        max_client_age_ms=500,
        controller_idle_seconds=3,
        agent_idle_seconds=5,
    )


@pytest.fixture
def teleop_client(tmp_path, monkeypatch):
    hub = new_hub(tmp_path)
    monkeypatch.setattr(main, "teleop_hub", hub)
    monkeypatch.setenv("MAX_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("MAX_ROBOT_TOKEN", ROBOT_TOKEN)
    monkeypatch.setenv("MAX_WEB_ORIGIN", ORIGIN)
    monkeypatch.setattr(main, "recover_in_progress_attempts", lambda _session: None)
    with TestClient(main.app) as client:
        yield client, hub


def authenticate_agent(client):
    socket = client.websocket_connect("/api/teleop/ws/agent")
    socket.__enter__()
    socket.send_json({
        "type": "auth",
        "protocol_version": 1,
        "token": ROBOT_TOKEN,
        "agent_id": "max-pi",
        "agent_version": "test-1.0",
    })
    assert socket.receive_json()["type"] == "ready"
    reset = socket.receive_json()
    assert reset["type"] == "reset_estop"
    socket.send_json({
        "type": "reset_ack",
        "protocol_version": 1,
        "server_sequence": reset["server_sequence"],
    })
    return socket


def authenticate_controller(client):
    socket = client.websocket_connect(
        "/api/teleop/ws/controller",
        headers={"origin": ORIGIN},
    )
    socket.__enter__()
    socket.send_json({
        "type": "auth",
        "protocol_version": 1,
        "token": ADMIN_TOKEN,
    })
    ready = socket.receive_json()
    assert ready["type"] == "ready"
    return socket


def receive_type(socket, expected, limit=20):
    for _ in range(limit):
        value = socket.receive_json()
        if value.get("type") == expected:
            return value
    raise AssertionError(f"did not receive {expected}")


def reset_estop(controller, agent):
    controller.send_json({"type": "reset_estop", "protocol_version": 1})
    while True:
        status = receive_type(controller, "status")
        if status["emergency_stop"] is False and status["agent_armed"] is True:
            return


def input_message(sequence, keys, *, sent_at_ms=None):
    return {
        "type": "input",
        "protocol_version": 1,
        "sequence": sequence,
        "sent_at_ms": sent_at_ms or int(time.time() * 1000),
        "keys": keys,
    }


def test_protocol_rejects_unknown_conflicting_stale_and_malformed_inputs():
    now = 1_000_000
    assert parse_input_snapshot(
        input_message(1, ["W", "A", "SPACE"], sent_at_ms=now),
        now_ms=now,
    ).keys == ("A", "SPACE", "W")
    for keys, code in [
        (["X"], "unknown_key"),
        (["W", "S"], "conflicting_keys"),
        (["A", "D"], "conflicting_keys"),
        (["1", "2"], "conflicting_keys"),
        (["4", "5"], "conflicting_keys"),
        (["W", "W"], "malformed_input"),
    ]:
        with pytest.raises(TeleopProtocolError) as caught:
            parse_input_snapshot(
                input_message(1, keys, sent_at_ms=now),
                now_ms=now,
            )
        assert caught.value.code == code
    with pytest.raises(TeleopProtocolError, match="time window"):
        parse_input_snapshot(
            input_message(1, ["W"], sent_at_ms=now - 2_000),
            now_ms=now,
            max_client_age_ms=500,
        )


def test_authentication_rejects_wrong_token_without_echoing_it():
    with pytest.raises(TeleopProtocolError) as caught:
        parse_auth_message(
            {"type": "auth", "protocol_version": 1, "token": "wrong"},
            ADMIN_TOKEN,
            "controller",
        )
    assert caught.value.code == "unauthorized"
    assert "wrong" not in str(caught.value)


def test_every_key_combination_hold_release_and_emergency_stop(teleop_client):
    client, hub = teleop_client
    agent = authenticate_agent(client)
    controller = authenticate_controller(client)
    try:
        reset_estop(controller, agent)
        sequence = 0
        for key in sorted(ALLOWED_KEYS):
            sequence += 1
            controller.send_json(input_message(sequence, [key]))
            forwarded = receive_type(agent, "input")
            assert forwarded["keys"] == [key]
            agent.send_json({
                "type": "input_ack",
                "protocol_version": 1,
                "server_sequence": forwarded["server_sequence"],
                "keys": [key],
            })
            sequence += 1
            controller.send_json(input_message(sequence, []))
            released = receive_type(agent, "input")
            assert released["keys"] == []
            agent.send_json({
                "type": "input_ack",
                "protocol_version": 1,
                "server_sequence": released["server_sequence"],
                "keys": [],
            })

        sequence += 1
        combination = ["W", "A", "SPACE", "2", "4"]
        controller.send_json(input_message(sequence, combination))
        combined = receive_type(agent, "input")
        assert set(combined["keys"]) == set(combination)

        # A held state expires unless the browser continues refreshing it.
        deadman_release = receive_type(agent, "input")
        assert deadman_release["keys"] == []
        assert deadman_release["reason"] == "deadman_timeout"

        sequence += 1
        controller.send_json(input_message(sequence, ["D"]))
        assert receive_type(agent, "input")["keys"] == ["D"]
        controller.send_json({"type": "emergency_stop", "protocol_version": 1})
        stop = receive_type(agent, "emergency_stop")
        agent.send_json({
            "type": "estop_ack",
            "protocol_version": 1,
            "server_sequence": stop["server_sequence"],
        })
        assert hub.emergency_stop is True
        assert hub.active_keys == ()
        assert TeleopSafetyStore(hub.store.path).load_emergency_stop() is True
    finally:
        controller.__exit__(None, None, None)
        agent.__exit__(None, None, None)


def test_duplicates_out_of_order_and_stale_messages_never_reapply_state(teleop_client):
    client, hub = teleop_client
    agent = authenticate_agent(client)
    controller = authenticate_controller(client)
    try:
        reset_estop(controller, agent)
        message = input_message(1, ["W"])
        controller.send_json(message)
        first = receive_type(agent, "input")
        assert first["keys"] == ["W"]

        controller.send_json(message)
        duplicate = receive_type(controller, "input_ack")
        while duplicate.get("sequence") != 1 or not duplicate.get("duplicate"):
            duplicate = receive_type(controller, "input_ack")
        assert hub.server_sequence == first["server_sequence"]

        controller.send_json(input_message(2, ["A"]))
        second = receive_type(agent, "input")
        assert second["keys"] == ["A"]
        controller.send_json(input_message(1, ["D"]))
        error = receive_type(controller, "error")
        assert error["code"] == "out_of_order"
        assert hub.active_keys == ("A",)

        controller.send_json(input_message(
            3,
            ["S"],
            sent_at_ms=int(time.time() * 1000) - 2_000,
        ))
        release = receive_type(agent, "input")
        assert release["keys"] == []
        assert hub.active_keys == ()
        assert receive_type(controller, "error")["code"] == "stale_input"
    finally:
        controller.__exit__(None, None, None)
        agent.__exit__(None, None, None)


def test_browser_close_agent_restart_exclusivity_and_authorization(teleop_client):
    client, hub = teleop_client

    unauthorized = client.websocket_connect(
        "/api/teleop/ws/controller",
        headers={"origin": ORIGIN},
    )
    unauthorized.__enter__()
    unauthorized.send_json({
        "type": "auth",
        "protocol_version": 1,
        "token": "invalid-controller-token",
    })
    assert unauthorized.receive_json()["code"] == "unauthorized"
    with pytest.raises(WebSocketDisconnect):
        unauthorized.receive_json()
    unauthorized.__exit__(None, None, None)

    wrong_origin = client.websocket_connect(
        "/api/teleop/ws/controller",
        headers={"origin": "https://evil.example"},
    )
    with pytest.raises(WebSocketDisconnect) as denied:
        wrong_origin.__enter__()
    assert denied.value.code == 4403

    agent = authenticate_agent(client)
    controller = authenticate_controller(client)
    reset_estop(controller, agent)

    second = client.websocket_connect(
        "/api/teleop/ws/controller",
        headers={"origin": ORIGIN},
    )
    second.__enter__()
    second.send_json({
        "type": "auth",
        "protocol_version": 1,
        "token": ADMIN_TOKEN,
    })
    assert second.receive_json()["code"] == "controller_conflict"
    with pytest.raises(WebSocketDisconnect):
        second.receive_json()
    second.__exit__(None, None, None)

    controller.send_json(input_message(1, ["W", "D"]))
    assert set(receive_type(agent, "input")["keys"]) == {"W", "D"}
    controller.__exit__(None, None, None)
    closed_release = receive_type(agent, "input")
    assert closed_release["keys"] == []
    assert closed_release["reason"] == "controller_disconnected"

    agent.__exit__(None, None, None)
    assert hub.active_keys == ()


def test_authenticated_http_emergency_stop_is_a_websocket_fallback(teleop_client):
    client, hub = teleop_client
    agent = authenticate_agent(client)
    controller = authenticate_controller(client)
    try:
        reset_estop(controller, agent)
        controller.send_json(input_message(1, ["W", "SPACE"]))
        assert set(receive_type(agent, "input")["keys"]) == {"W", "SPACE"}

        assert client.post("/api/teleop/emergency-stop").status_code == 401
        response = client.post(
            "/api/teleop/emergency-stop",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert response.status_code == 200
        assert response.json()["emergency_stop"] is True
        assert response.json()["active_keys"] == []
        stop = receive_type(agent, "emergency_stop")
        assert stop["reason"] == "operator_http_emergency_stop"
        agent.send_json({
            "type": "estop_ack",
            "protocol_version": 1,
            "server_sequence": stop["server_sequence"],
        })
        assert hub.emergency_stop is True
    finally:
        controller.__exit__(None, None, None)
        agent.__exit__(None, None, None)


def test_safety_store_defaults_clear_and_only_persists_explicit_latch(tmp_path):
    path = tmp_path / "state.json"
    first = TeleopSafetyStore(path)
    assert first.load_emergency_stop() is False
    first.save_emergency_stop(True)
    assert TeleopSafetyStore(path).load_emergency_stop() is True
    path.write_text("{broken")
    assert TeleopSafetyStore(path).load_emergency_stop() is False


def test_agent_state_mismatch_releases_and_rearms_without_latching_estop(teleop_client):
    client, hub = teleop_client
    agent = authenticate_agent(client)
    controller = authenticate_controller(client)
    try:
        reset_estop(controller, agent)
        controller.send_json(input_message(1, ["W"]))
        forwarded = receive_type(agent, "input")
        assert forwarded["keys"] == ["W"]

        agent.send_json({
            "type": "input_ack",
            "protocol_version": 1,
            "server_sequence": forwarded["server_sequence"],
            "keys": [],
        })
        release = receive_type(agent, "input")
        assert release["keys"] == []
        reset = receive_type(agent, "reset_estop")
        agent.send_json({
            "type": "reset_ack",
            "protocol_version": 1,
            "server_sequence": reset["server_sequence"],
        })

        while True:
            status = receive_type(controller, "status")
            if status["agent_armed"] and not status["reset_pending"]:
                break
        assert status["emergency_stop"] is False
        assert hub.emergency_stop is False
        assert hub.active_keys == ()
    finally:
        controller.__exit__(None, None, None)
        agent.__exit__(None, None, None)


def test_shutdown_releases_active_state(tmp_path):
    async def scenario():
        hub = new_hub(tmp_path)
        hub.active_keys = ("W",)
        await hub.start()
        await hub.stop()
        assert hub.active_keys == ()
        assert hub.watchdog_task is None

    asyncio.run(scenario())
