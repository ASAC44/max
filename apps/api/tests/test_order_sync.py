import asyncio
from datetime import timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import max_api.order_sync as order_sync
from max_api.db import Base, build_engine, get_session
from max_api.integrations import IntegrationError, SwiggyOrderSnapshot
from max_api.main import app
from max_api.models import Event, Mission, RobotJob, utcnow
from max_api.order_sync import apply_order_snapshot, normalize_swiggy_status
from max_api.schemas import Environment, Quote, QuoteLine


def production_order() -> Mission:
    quote = Quote(
        revision=1,
        merchant="SWIGGY_INSTAMART",
        product_name="Meal",
        variant_id="meal-safe",
        quantity=1,
        amount_minor=10_000,
        currency="INR",
        destination="home",
        environment=Environment.PRODUCTION,
        expires_at=utcnow() + timedelta(minutes=15),
        line_items=[
            QuoteLine(
                description="Meal",
                unit_price_minor=10_000,
                quantity=1,
            )
        ],
    )
    return Mission(
        id="mission-order-status-0001",
        active_slot="active",
        version=7,
        phase="ORDER_CONFIRMED",
        environment="production",
        agent_mode="openai",
        request_text="get one meal",
        quote=quote.model_dump(mode="json"),
        commerce_status="ORDER_CONFIRMED",
        payment_status="PRAVA_COMPLETED",
        checkout_status="ORDER_CONFIRMED",
        fulfilment_status="NOT_STARTED",
        notification_status="NOT_STARTED",
    )


def test_status_normalization_covers_delivery_lifecycle():
    assert normalize_swiggy_status("Order placed") == "ORDER_PLACED"
    assert normalize_swiggy_status("Restaurant is preparing your order") == "PREPARING"
    assert normalize_swiggy_status("Out for delivery") == "OUT_FOR_DELIVERY"
    assert (
        normalize_swiggy_status("Delivery partner has arrived")
        == "ARRIVED_AT_DELIVERY_LOCATION"
    )
    assert normalize_swiggy_status("Delivered") == "DELIVERED"
    assert normalize_swiggy_status("Cancelled by merchant") == "CANCELLED"


def test_every_status_reaches_robot_stream_and_only_arrival_queues_job(
    tmp_path,
    monkeypatch,
):
    engine = build_engine(f"sqlite:///{tmp_path / 'status.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        session.add(production_order())
        session.commit()
        for raw in (
            "Order confirmed",
            "Preparing your order",
            "Out for delivery",
        ):
            apply_order_snapshot(
                session,
                "mission-order-status-0001",
                SwiggyOrderSnapshot("order-safe-0001", raw, "10 min"),
            )
            assert session.scalar(select(RobotJob)) is None
        apply_order_snapshot(
            session,
            "mission-order-status-0001",
            SwiggyOrderSnapshot(
                "order-safe-0001",
                "Delivery partner has arrived",
                "now",
            ),
        )
        # Replaying the provider status must not duplicate the staged job.
        apply_order_snapshot(
            session,
            "mission-order-status-0001",
            SwiggyOrderSnapshot(
                "order-safe-0001",
                "Delivery partner has arrived",
                "now",
            ),
        )
        job = session.scalar(select(RobotJob))
        assert job is not None
        assert job.dry_run is True
        assert job.trigger_source == "SWIGGY"
        assert job.trigger_status == "ARRIVED_AT_DELIVERY_LOCATION"
        assert session.scalar(select(Mission).where(
            Mission.parent_mission_id == "mission-order-status-0001"
        )).phase == "READY_TO_DISPATCH"
        assert len(session.scalars(select(Event).where(
            Event.event_type.like("SWIGGY_ORDER_%")
        )).all()) == 4

    async def override_session():
        with TestSession() as session:
            yield session

    monkeypatch.setenv("MAX_ROBOT_TOKEN", "robot-order-status-token-123456")
    monkeypatch.setenv("MAX_ADMIN_TOKEN", "admin-order-status-token-123456")
    monkeypatch.setenv("MAX_ROBOT_MODE", "pi_poll")
    app.dependency_overrides[get_session] = override_session

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            headers = {
                "Authorization": "Bearer robot-order-status-token-123456"
            }
            admin_headers = {
                "Authorization": "Bearer admin-order-status-token-123456"
            }
            first = (
                await client.get(
                    "/api/robot/v1/order-status?after=0",
                    headers=headers,
                )
            ).json()
            assert [event["normalized_status"] for event in first["events"]] == [
                "CONFIRMED",
                "PREPARING",
                "OUT_FOR_DELIVERY",
                "ARRIVED_AT_DELIVERY_LOCATION",
            ]
            assert first["events"][-1]["robot_action"] == "QUEUE_DRY_RUN_DISPATCH"
            second = (
                await client.get(
                    f"/api/robot/v1/order-status?after={first['next_cursor']}",
                    headers=headers,
                )
            ).json()
            assert second["events"] == []
            job = (await client.get("/api/robot/v1/next", headers=headers)).json()["job"]
            assert job["trigger_source"] == "SWIGGY"
            assert job["trigger_status"] == "ARRIVED_AT_DELIVERY_LOCATION"
            assert job["dry_run"] is True
            active = (
                await client.get("/api/missions/active", headers=admin_headers)
            ).json()
            assert active["robot_job"]["command_id"] == job["command_id"]
            assert len(active["source_order_events"]) == 4
            acknowledged = (
                await client.post(
                    "/api/robot/v1/ack",
                    headers=headers,
                    json={
                        "mission_id": job["mission_id"],
                        "command_id": job["command_id"],
                        "status": "ACKNOWLEDGED",
                        "dry_run": True,
                        "motion_started": False,
                    },
                )
            ).json()
            unsafe_replay = await client.post(
                "/api/robot/v1/ack",
                headers=headers,
                json={
                    "mission_id": job["mission_id"],
                    "command_id": job["command_id"],
                    "status": "ACKNOWLEDGED",
                    "dry_run": True,
                    "motion_started": True,
                },
            )
            assert unsafe_replay.status_code == 409
            version = acknowledged["version"]
            final = acknowledged
            for stage in ("AT_PICKUP", "ITEM_SECURED", "RETURNING", "COMPLETED"):
                final = (
                    await client.post(
                        "/api/robot/v1/lifecycle",
                        headers=headers,
                        json={
                            "mission_id": job["mission_id"],
                            "command_id": job["command_id"],
                            "event_id": f"status-e2e-{stage.lower()}",
                            "expected_version": version,
                            "stage": stage,
                            "dry_run": True,
                            "motion_started": False,
                        },
                    )
                ).json()
                version = final["version"]
            assert final["phase"] == "COMPLETED"
            assert final["robot_job"]["status"] == "COMPLETED"
            assert len(final["source_order_events"]) == 4

    try:
        asyncio.run(scenario())
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_status_regression_does_not_replace_current_state(session):
    session.add(production_order())
    session.commit()
    apply_order_snapshot(
        session,
        "mission-order-status-0001",
        SwiggyOrderSnapshot("order-safe-0001", "Out for delivery"),
    )
    mission = apply_order_snapshot(
        session,
        "mission-order-status-0001",
        SwiggyOrderSnapshot("order-safe-0001", "Preparing your order"),
    )
    assert mission.commerce_status == "SWIGGY_OUT_FOR_DELIVERY"
    event = session.scalar(select(Event).where(
        Event.event_type == "SWIGGY_ORDER_PREPARING"
    ))
    assert event.payload["applied_to_current"] is False


def test_provider_cancellation_revokes_queued_job(session):
    session.add(production_order())
    session.commit()
    apply_order_snapshot(
        session,
        "mission-order-status-0001",
        SwiggyOrderSnapshot(
            "order-safe-0001",
            "Delivery partner has arrived",
        ),
    )
    apply_order_snapshot(
        session,
        "mission-order-status-0001",
        SwiggyOrderSnapshot("order-safe-0001", "Cancelled by merchant"),
    )
    child = session.scalar(select(Mission).where(
        Mission.parent_mission_id == "mission-order-status-0001"
    ))
    job = session.scalar(select(RobotJob).where(RobotJob.mission_id == child.id))
    assert child.phase == "CANCELLED"
    assert child.commerce_status == "SWIGGY_CANCELLED"
    assert job.status == "CANCELLED"


def test_worker_isolates_one_order_failure_and_skips_terminal_orders(
    tmp_path,
    monkeypatch,
):
    engine = build_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    with TestSession() as session:
        first = production_order()
        first.id = "mission-worker-failure"
        first.active_slot = None
        first.quote = {**first.quote, "product_name": "Failure"}
        terminal = production_order()
        terminal.id = "mission-worker-terminal"
        terminal.active_slot = None
        terminal.commerce_status = "SWIGGY_DELIVERED"
        second = production_order()
        second.id = "mission-worker-success"
        second.active_slot = None
        second.quote = {**second.quote, "product_name": "Success"}
        session.add_all([first, terminal, second])
        session.commit()

    class Client:
        calls = []

        async def order_snapshot(self, *, provider_order_id, quote):
            self.calls.append(quote.product_name)
            if quote.product_name == "Failure":
                raise IntegrationError("safe test failure")
            return SwiggyOrderSnapshot(
                f"order-{quote.product_name.lower()}",
                "Order confirmed",
            )

    monkeypatch.setattr(order_sync, "SessionLocal", TestSession)
    summary = asyncio.run(order_sync.sync_once(Client()))
    assert summary.candidates == 2
    assert summary.processed == 1
    assert summary.failures == 1
    assert set(Client.calls) == {"Failure", "Success"}
    assert "Meal" not in Client.calls
    with TestSession() as session:
        assert session.get(
            Mission,
            "mission-worker-success",
        ).commerce_status == "SWIGGY_CONFIRMED"
        assert session.get(
            Mission,
            "mission-worker-terminal",
        ).commerce_status == "SWIGGY_DELIVERED"
    engine.dispose()


def test_worker_readiness_reports_success_failure_and_stale_state(
    tmp_path,
):
    state_path = tmp_path / "worker.json"
    order_sync._write_worker_state(
        order_sync.SyncSummary(1, 1, 0),
        path=state_path,
    )
    assert order_sync.order_sync_worker_readiness(state_path)["connected"] is True
    order_sync._write_worker_state(
        order_sync.SyncSummary(1, 0, 1, "IntegrationError"),
        path=state_path,
    )
    failed = order_sync.order_sync_worker_readiness(state_path)
    assert failed["connected"] is False
    assert failed["running"] is True
