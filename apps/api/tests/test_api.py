import asyncio
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from max_api.agent import parse_simulated
from max_api.db import Base, build_engine, get_session
from max_api.integrations import PravaCredential, PravaPaymentState, PravaSession
from max_api.main import app
from max_api.models import Event, Mission, utcnow
from max_api.schemas import Environment, ProviderResult, Quote, QuoteLine


async def api_scenario(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():
        with TestSession() as session:
            yield session

    token = "test-operator-token-1234567890"
    monkeypatch.setenv("MAX_ADMIN_TOKEN", token)
    monkeypatch.setenv("MAX_AGENT_MODE", "simulated")
    app.dependency_overrides[get_session] = override_session
    headers = {"Authorization": f"Bearer {token}"}
    parse_calls = 0

    async def counting_parse(text):
        nonlocal parse_calls
        parse_calls += 1
        return parse_simulated(text)

    monkeypatch.setattr("max_api.main.parse_request", counting_parse)

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            unauthorized = await client.get("/api/missions/unknown")
            assert unauthorized.status_code == 401

            created = await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "api-create-0001"},
                json={"text": "get 1 milk under ₹300 for work"},
            )
            assert created.status_code == 200
            mission = created.json()
            assert mission["phase"] == "AWAITING_OWNER_APPROVAL"
            assert mission["approval"]["quote_hash"] is None

            blocked_create = await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "api-blocked-create"},
                json={"text": "get 1 juice under ₹200 for work"},
            )
            assert blocked_create.status_code == 409
            assert blocked_create.json()["detail"]["mission_id"] == mission["id"]

            approved = await client.post(
                f"/api/missions/{mission['id']}/commands/approve",
                headers=headers,
                json={
                    "expected_version": mission["version"],
                    "command_id": "api-approve-0001",
                    "quote_hash": mission["quote_hash"],
                    "simulated_outcome": "decline",
                },
            )
            assert approved.status_code == 200
            declined = approved.json()
            assert declined["phase"] == "PAYMENT_DECLINED"
            assert declined["payment_status"] == "FAILED"
            assert declined["checkout"]["latest_attempt"]["terminal"] is True

            replayed = await client.post(
                f"/api/missions/{mission['id']}/commands/approve",
                headers=headers,
                json={
                    "expected_version": mission["version"],
                    "command_id": "api-approve-0001",
                    "quote_hash": mission["quote_hash"],
                    "simulated_outcome": "decline",
                },
            )
            assert replayed.status_code == 200
            assert replayed.json()["version"] == declined["version"]

            changed_replay = await client.post(
                f"/api/missions/{mission['id']}/commands/approve",
                headers=headers,
                json={
                    "expected_version": mission["version"],
                    "command_id": "api-approve-0001",
                    "quote_hash": mission["quote_hash"],
                    "simulated_outcome": "unknown",
                },
            )
            assert changed_replay.status_code == 409

            stale = await client.post(
                f"/api/missions/{mission['id']}/commands/cancel",
                headers=headers,
                json={"expected_version": mission["version"], "command_id": "api-stale-cancel"},
            )
            assert stale.status_code == 409

            staged_response = await client.post(
                f"/api/missions/{declined['id']}/commands/start-staged",
                headers=headers,
                json={"expected_version": declined["version"], "command_id": "api-staged-0001"},
            )
            assert staged_response.status_code == 200
            staged = staged_response.json()
            assert staged["parent_mission_id"] == declined["id"]

            blocked = await client.post(
                f"/api/missions/{staged['id']}/commands/run-robot",
                headers=headers,
                json={"expected_version": staged["version"], "command_id": "api-blocked-robot"},
            )
            assert blocked.status_code == 409

            ready = (await client.post(
                f"/api/missions/{staged['id']}/commands/package-ready",
                headers=headers,
                json={"expected_version": staged["version"], "command_id": "api-package-0001"},
            )).json()
            completed = await client.post(
                f"/api/missions/{staged['id']}/commands/run-robot",
                headers=headers,
                json={"expected_version": ready["version"], "command_id": "api-robot-0001"},
            )
            assert completed.status_code == 200
            assert completed.json()["phase"] == "COMPLETED"

            reloaded_parent = (await client.get(f"/api/missions/{declined['id']}", headers=headers)).json()
            assert reloaded_parent["phase"] == "PAYMENT_DECLINED"

            incomplete = (await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "api-reply-create"},
                json={"text": "get milk"},
            )).json()
            assert incomplete["phase"] == "NEEDS_CLARIFICATION"
            calls_before_reply = parse_calls
            reply_body = {
                "text": "get 1 milk under ₹300 for work",
                "expected_version": incomplete["version"],
                "command_id": "api-reply-0001",
            }
            first_reply = await client.post(
                f"/api/missions/{incomplete['id']}/commands/reply", headers=headers, json=reply_body
            )
            second_reply = await client.post(
                f"/api/missions/{incomplete['id']}/commands/reply", headers=headers, json=reply_body
            )
            assert first_reply.status_code == second_reply.status_code == 200
            assert first_reply.json()["version"] == second_reply.json()["version"]
            assert parse_calls == calls_before_reply + 1

            replied = first_reply.json()
            cancelled_reply = await client.post(
                f"/api/missions/{replied['id']}/commands/cancel",
                headers=headers,
                json={"expected_version": replied["version"], "command_id": "api-reply-cancel"},
            )
            assert cancelled_reply.status_code == 200

            failure_calls = 0

            async def failing_parse(_text):
                nonlocal failure_calls
                failure_calls += 1
                raise RuntimeError("sensitive provider detail")

            monkeypatch.setattr("max_api.main.parse_request", failing_parse)
            failed = await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "api-failed-parse"},
                json={"text": "get 1 juice under ₹200 for work"},
            )
            assert failed.status_code == 502
            failed_detail = failed.json()["detail"]
            assert failed_detail["message"] == "request interpretation failed"
            with TestSession() as persisted:
                failed_mission = persisted.scalar(
                    select(Mission).where(Mission.request_text == "get 1 juice under ₹200 for work")
                )
                failure = persisted.scalar(
                    select(Event).where(
                        Event.mission_id == failed_mission.id,
                        Event.event_type == "AGENT_INTERPRETATION_FAILED",
                    )
                )
                assert failure.payload == {"error_class": "RuntimeError"}
                assert failed_detail["mission_id"] == failed_mission.id

            failed_replay = await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "api-failed-parse"},
                json={"text": "get 1 juice under ₹200 for work"},
            )
            assert failed_replay.status_code == 502
            assert failed_replay.json()["detail"]["mission_id"] == failed_detail["mission_id"]
            assert failure_calls == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_full_api_flow_and_conflicts(tmp_path, monkeypatch):
    asyncio.run(api_scenario(tmp_path, monkeypatch))


async def live_api_scenario(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'live-api.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    async def override_session():
        with TestSession() as session:
            yield session

    token = "test-live-operator-token-123456"
    monkeypatch.setenv("MAX_ADMIN_TOKEN", token)
    monkeypatch.setenv("MAX_AGENT_MODE", "simulated")
    monkeypatch.setenv("MAX_COMMERCE_MODE", "swiggy")
    monkeypatch.setenv("MAX_PAYMENT_MODE", "prava")
    monkeypatch.setenv("PRAVA_SECRET_KEY", "sk_test_safe")
    monkeypatch.setenv("PRAVA_USER_ID", "owner-safe")
    monkeypatch.setenv("PRAVA_USER_EMAIL", "owner@example.test")
    monkeypatch.setenv("PRAVA_CALLBACK_URL", "https://max.example.test/payment-done")

    async def fake_quote(_self, intent):
        return Quote(
            revision=1,
            merchant="SWIGGY_INSTAMART",
            product_name="Amul Gold Milk 1 Ltr",
            variant_id="spin-safe",
            quantity=intent.quantity,
            amount_minor=14_700,
            currency="INR",
            destination=intent.destination,
            environment=Environment.PRODUCTION,
            expires_at=utcnow() + timedelta(minutes=15),
            line_items=[
                QuoteLine(description="Amul Gold Milk 1 Ltr", unit_price_minor=7200, quantity=2),
                QuoteLine(description="Swiggy fees", unit_price_minor=300, quantity=1),
            ],
        )

    async def fake_session(_self, _quote):
        return PravaSession(
            "ses_safe",
            "ord_safe",
            "https://sandbox.collect.prava.space?session=ses_safe",
            "2026-08-01T12:15:00Z",
        )

    async def fake_state(_self, _session_id):
        return PravaPaymentState("awaiting_result", "tli_safe", True)

    async def fake_verify(_self, _quote):
        return None

    async def fake_credential(_self, _session_id):
        return PravaCredential("tli_safe", "4111111111111111", "123", "08", "30")

    async def fake_checkout(_self, _quote, credential):
        assert credential.token == "4111111111111111"
        return ProviderResult(
            provider="SWIGGY_BROWSER",
            operation="merchant_checkout",
            environment=Environment.PRODUCTION,
            status="DECLINED",
            terminal=True,
        )

    async def fake_report(_self, _session_id, txn_ref_id, status):
        assert (txn_ref_id, status) == ("tli_safe", "DECLINED")
        return PravaPaymentState("failed", "tli_safe", False)

    monkeypatch.setattr("max_api.main.SwiggyClient.quote", fake_quote)
    monkeypatch.setattr("max_api.main.PravaClient.create_session", fake_session)
    monkeypatch.setattr("max_api.main.PravaClient.payment_state", fake_state)
    monkeypatch.setattr("max_api.main.SwiggyClient.verify_quote", fake_verify)
    monkeypatch.setattr("max_api.main.PravaClient.credential", fake_credential)
    monkeypatch.setattr("max_api.main.SwiggyBrowserCheckout.checkout", fake_checkout)
    monkeypatch.setattr("max_api.main.PravaClient.report_result", fake_report)
    app.dependency_overrides[get_session] = override_session
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            callback = await client.get("/api/payments/prava/complete")
            assert callback.status_code == 200
            assert "continue automatically" in callback.text
            created = (await client.post(
                "/api/missions",
                headers={**headers, "Idempotency-Key": "live-create-001"},
                json={"text": "get 2 milk under ₹200 for home"},
            )).json()
            assert created["quote"]["merchant"] == "SWIGGY_INSTAMART"
            assert created["quote"]["environment"] == "production"
            assert created["phase"] == "PAYMENT_APPROVAL_REQUIRED"
            assert created["approval"]["quote_hash"] is None
            assert created["payment_action"]["approval_url"].startswith("https://sandbox.collect.prava.space")
            refreshed = (await client.post(
                f"/api/missions/{created['id']}/commands/refresh-payment",
                headers=headers,
                json={"expected_version": created["version"], "command_id": "live-refresh-001"},
            )).json()
            assert refreshed["phase"] == "PAYMENT_PERMISSION_READY"
            assert refreshed["approval"]["quote_hash"] == refreshed["quote_hash"]
            serialized = str(refreshed)
            assert "dynamic_cvv" not in serialized
            assert "must-not-be-returned" not in serialized
            declined = (await client.post(
                f"/api/missions/{created['id']}/commands/execute-checkout",
                headers=headers,
                json={"expected_version": refreshed["version"], "command_id": "live-checkout-001"},
            )).json()
            assert declined["phase"] == "PAYMENT_DECLINED"
            assert declined["checkout_status"] == "DECLINED"
            assert declined["payment_status"] == "PRAVA_FAILED"
            assert "4111111111111111" not in str(declined)
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_live_provider_boundary_is_wired_without_exposing_credentials(tmp_path, monkeypatch):
    asyncio.run(live_api_scenario(tmp_path, monkeypatch))
