import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from max_api.db import Base, build_engine, get_session
from max_api.config import telegram_worker_interval_seconds
from max_api.main import app
from max_api.models import Mission, TelegramNotification, TelegramUpdate, utcnow
from max_api.telegram import (
    ControlApiClient,
    TelegramClient,
    TelegramError,
    TelegramWorker,
    _failure_message,
    _help_message,
    mission_message,
    parse_telegram_update,
)


def test_telegram_worker_interval_returns_configured_value(monkeypatch):
    monkeypatch.setenv("MAX_TELEGRAM_WORKER_INTERVAL_SECONDS", "2.5")
    assert telegram_worker_interval_seconds() == 2.5


def test_parse_telegram_update_keeps_only_required_owner_fields():
    inbound = parse_telegram_update({
        "update_id": 91,
        "message": {
            "from": {"id": 42, "username": "must-not-be-stored"},
            "chat": {"id": 42, "type": "private", "title": "must-not-be-stored"},
            "text": "get 1 milk under ₹300 for home",
        },
    })
    assert inbound is not None
    assert inbound.update_id == 91
    assert inbound.user_id == inbound.chat_id == 42
    assert inbound.request_text == "get 1 milk under ₹300 for home"
    assert "must-not-be-stored" not in repr(inbound)


async def webhook_scenario(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'telegram.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():
        with TestSession() as session:
            yield session

    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "safe_webhook_secret_123456789")
    monkeypatch.setenv("TELEGRAM_OWNER_USER_ID", "42")
    app.dependency_overrides[get_session] = override_session
    payload = {
        "update_id": 1001,
        "message": {
            "from": {"id": 42},
            "chat": {"id": 42, "type": "private"},
            "text": "get 1 milk under ₹300 for home",
        },
    }
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            bad_secret = await client.post(
                "/api/integrations/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
                json=payload,
            )
            assert bad_secret.status_code == 401

            accepted = await client.post(
                "/api/integrations/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "safe_webhook_secret_123456789"},
                json=payload,
            )
            assert accepted.status_code == 202
            assert accepted.json() == {"accepted": True, "duplicate": False}

            duplicate = await client.post(
                "/api/integrations/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "safe_webhook_secret_123456789"},
                json=payload,
            )
            assert duplicate.json() == {"accepted": True, "duplicate": True}

            not_owner = await client.post(
                "/api/integrations/telegram/webhook",
                headers={"X-Telegram-Bot-Api-Secret-Token": "safe_webhook_secret_123456789"},
                json={
                    **payload,
                    "update_id": 1002,
                    "message": {
                        **payload["message"],
                        "from": {"id": 99},
                    },
                },
            )
            assert not_owner.status_code == 202
            assert not_owner.json()["reason"] == "owner_not_allowed"

        with TestSession() as session:
            updates = session.scalars(select(TelegramUpdate)).all()
            assert len(updates) == 1
            assert updates[0].status == "PENDING"
            assert updates[0].request_text == payload["message"]["text"]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_owner_only_webhook_is_authenticated_and_idempotent(tmp_path, monkeypatch):
    asyncio.run(webhook_scenario(tmp_path, monkeypatch))


def test_exact_quote_message_requires_prava_and_has_cancel_button():
    mission = {
        "id": "mission-safe-0001",
        "version": 4,
        "phase": "PAYMENT_APPROVAL_REQUIRED",
        "quote": {
            "product_name": "Amul Milk 1 L",
            "quantity": 2,
            "amount_minor": 14_700,
            "currency": "INR",
            "destination": "home",
            "expires_at": (utcnow() + timedelta(minutes=10)).isoformat(),
        },
        "payment_action": {
            "approval_url": "https://sandbox.collect.prava.space/session-safe",
        },
    }
    text, markup = mission_message(mission)
    assert "₹147.00" in text
    assert "Quantity: 2" in text
    assert "No payment or checkout happens until" in text
    assert markup["inline_keyboard"][0][0]["url"].startswith("https://sandbox.collect.prava.space/")
    assert markup["inline_keyboard"][1][0]["callback_data"] == "cancel:mission-safe-0001:4"


def test_help_message_is_actionable_and_explains_approval_gate():
    text = _help_message()
    assert "Parle-G" in text
    assert "maximum total" in text
    assert "saved Home address" in text
    assert "only after you approve" in text
    assert "/status, /cancel, /help" in text


def test_payment_ready_message_is_explicit_when_auto_checkout_is_disabled(monkeypatch):
    monkeypatch.setenv("MAX_TELEGRAM_AUTO_CHECKOUT", "false")
    text, markup = mission_message({
        "id": "mission-safe-0001",
        "version": 5,
        "phase": "PAYMENT_PERMISSION_READY",
    })
    assert "approval received and recorded" in text
    assert "no merchant order or payment will be submitted" in text
    assert markup is None


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (
            "Swiggy quote exceeds the owner's maximum budget",
            "Reply with a higher maximum total budget",
        ),
        (
            "Swiggy MCP connection failed; complete OAuth setup and retry",
            "Reconnect Swiggy",
        ),
        (
            "No saved Swiggy address matches the requested destination",
            "exact saved label",
        ),
        (
            "Swiggy returned no purchasable result",
            "more specific product name",
        ),
        (
            "Selected Swiggy address is currently not serviceable; choose another address",
            "not serviceable right now",
        ),
    ],
)
def test_provider_failures_give_a_clear_next_action(reason, expected):
    text = _failure_message(TelegramError(reason))
    assert expected in text
    assert "No checkout or payment was attempted" in text


def test_telegram_messages_expose_only_staged_fail_closed_robot_actions():
    confirmed = {
        "id": "mission-safe-0001",
        "version": 8,
        "phase": "ORDER_CONFIRMED",
        "environment": "production",
    }
    text, markup = mission_message(confirmed)
    assert "separate staged workflow" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "stage:mission-safe-0001:8"

    ready = {
        "id": "staged-safe-0001",
        "version": 3,
        "phase": "READY_TO_DISPATCH",
        "environment": "staged_demo",
    }
    text, markup = mission_message(ready)
    assert "cannot start motor motion" in text
    assert markup["inline_keyboard"][0][0]["callback_data"] == "dispatch:staged-safe-0001:3"

    queued = {
        **ready,
        "robot_job": {
            "status": "PENDING",
            "trigger_source": "SWIGGY",
            "trigger_status": "ARRIVED_AT_DELIVERY_LOCATION",
        },
    }
    text, markup = mission_message(queued)
    assert "Pi job pending" in text
    assert "ARRIVED_AT_DELIVERY_LOCATION" in text
    assert markup is None

    completed = {
        "id": "staged-safe-0001",
        "version": 8,
        "phase": "COMPLETED",
        "environment": "staged_demo",
    }
    text, markup = mission_message(completed)
    assert "physical motion disabled" in text
    assert markup is None


def test_telegram_client_uses_bot_api_without_leaking_response(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:safe_test_token_value")
    captured = {}

    async def handler(request: httpx.Request):
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    asyncio.run(
        TelegramClient(httpx.MockTransport(handler)).send_message(
            42,
            "Safe status",
            reply_markup={"inline_keyboard": []},
        )
    )
    assert captured["path"].endswith("/sendMessage")
    assert captured["body"]["chat_id"] == 42
    assert captured["body"]["text"] == "Safe status"


def test_control_api_surfaces_safe_provider_error(monkeypatch):
    monkeypatch.setenv("MAX_ADMIN_TOKEN", "safe-admin-token-value-123456")
    monkeypatch.setenv("MAX_CONTROL_API_URL", "http://127.0.0.1:8000")

    async def handler(_request: httpx.Request):
        return httpx.Response(
            502,
            json={
                "detail": {
                    "message": "Swiggy quote exceeds the owner's maximum budget",
                    "mission_id": "mission-safe-0001",
                }
            },
        )

    with pytest.raises(
        TelegramError,
        match="Swiggy quote exceeds the owner's maximum budget",
    ):
        asyncio.run(
            ControlApiClient(httpx.MockTransport(handler)).request(
                "POST",
                "/api/missions/mission-safe-0001/commands/reply",
                json={},
            )
        )


def test_control_api_does_not_surface_untrusted_error_shapes(monkeypatch):
    monkeypatch.setenv("MAX_ADMIN_TOKEN", "safe-admin-token-value-123456")
    monkeypatch.setenv("MAX_CONTROL_API_URL", "http://127.0.0.1:8000")

    async def handler(_request: httpx.Request):
        return httpx.Response(
            502,
            json={"detail": {"message": "secret\nmust-not-be-forwarded"}},
        )

    with pytest.raises(TelegramError, match="Max control API rejected the request") as exc:
        asyncio.run(
            ControlApiClient(httpx.MockTransport(handler)).request(
                "POST",
                "/api/missions/mission-safe-0001/commands/reply",
                json={},
            )
        )
    assert "must-not-be-forwarded" not in str(exc.value)


def test_failed_notification_is_released_for_safe_retry(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'notification.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        session.add(Mission(
            id="mission-notification-0001",
            active_slot="active",
            version=3,
            phase="ORDER_CONFIRMED",
            environment="production",
            agent_mode="openai",
            request_text="safe test",
            commerce_status="SWIGGY_CONFIRMED",
            payment_status="PRAVA_COMPLETED",
            checkout_status="ORDER_CONFIRMED",
            fulfilment_status="NOT_STARTED",
            notification_status="NOT_STARTED",
        ))
        session.commit()
    monkeypatch.setattr("max_api.telegram.SessionLocal", TestSession)
    worker = TelegramWorker.__new__(TelegramWorker)
    attempts = 0

    async def send(_chat_id, _mission):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TelegramError("transient test failure")

    worker._send_mission = send
    mission = {"id": "mission-notification-0001", "version": 3}
    with pytest.raises(TelegramError):
        asyncio.run(
            worker._send_reserved_notification(
                mission,
                42,
                "swiggy_status",
            )
        )
    with TestSession() as session:
        assert session.scalar(select(TelegramNotification)) is None
    assert asyncio.run(
        worker._send_reserved_notification(
            mission,
            42,
            "swiggy_status",
        )
    ) is True
    assert asyncio.run(
        worker._send_reserved_notification(
            mission,
            42,
            "swiggy_status",
        )
    ) is False
    assert attempts == 2
    engine.dispose()


def test_payment_approval_advances_without_auto_checkout(monkeypatch):
    monkeypatch.setattr("max_api.telegram.telegram_auto_checkout", lambda: False)
    worker = TelegramWorker.__new__(TelegramWorker)
    worker.owner_chat_id = 42
    calls = []
    notifications = []
    awaiting = {
        "id": "mission-safe-0001",
        "version": 4,
        "phase": "PAYMENT_APPROVAL_REQUIRED",
    }
    ready = {
        "id": "mission-safe-0001",
        "version": 5,
        "phase": "PAYMENT_PERMISSION_READY",
    }

    async def active():
        return awaiting

    async def request(method, path, *, json=None, headers=None):
        calls.append((method, path, json))
        return ready

    async def notify(mission, chat_id, kind):
        notifications.append((mission, chat_id, kind))
        return True

    worker._active = active
    worker.control = type("Control", (), {"request": staticmethod(request)})()
    worker._send_reserved_notification = notify

    asyncio.run(worker.advance_payment())

    assert len(calls) == 1
    assert calls[0][1].endswith("/commands/refresh-payment")
    assert calls[0][2]["expected_version"] == 4
    assert notifications == [(ready, 42, "payment_ready")]
    assert all(not path.endswith("/commands/execute-checkout") for _, path, _ in calls)
