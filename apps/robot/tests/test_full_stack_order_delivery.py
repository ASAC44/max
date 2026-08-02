import socket
import tempfile
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
import uvicorn
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from max_api.db import Base, build_engine, get_session
from max_api.integrations import SwiggyOrderSnapshot
from max_api.main import app
from max_api.models import Mission, RobotJob, RobotNode, utcnow
from max_api.order_sync import apply_order_snapshot
from max_api.schemas import Environment, Quote, QuoteLine
from max_robot.agent import RobotBackend, UnifiedRobotAgent
from max_robot.bridge import BridgeState


def _production_order() -> Mission:
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
        id="mission-full-stack-0001",
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


def test_real_http_status_to_pi_to_backend_lifecycle(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'full-stack.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        session.add(_production_order())
        session.commit()
        for raw in (
            "Order confirmed",
            "Preparing your order",
            "Out for delivery",
            "Delivery partner has arrived",
        ):
            apply_order_snapshot(
                session,
                "mission-full-stack-0001",
                SwiggyOrderSnapshot("order-full-stack-0001", raw),
            )

    async def override_session():
        with TestSession() as session:
            yield session

    monkeypatch.setenv("MAX_ROBOT_TOKEN", "full-stack-robot-token-123456")
    monkeypatch.setenv("MAX_ROBOT_MODE", "pi_poll")
    app.dependency_overrides[get_session] = override_session
    try:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
    except PermissionError:
        engine.dispose()
        app.dependency_overrides.clear()
        pytest.skip("localhost sockets are disabled")

    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        lifespan="off",
        log_level="error",
    ))
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        engine.dispose()
        app.dependency_overrides.clear()
        raise AssertionError("test control API did not start")

    try:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "agent.json"
            backend = RobotBackend(
                base_url=f"http://127.0.0.1:{port}",
                token="full-stack-robot-token-123456",
            )
            agent = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(state_path),
                robot_id="max-pi-full-stack",
            )
            agent.heartbeat()
            assert agent.sync_order_status() == 4
            assert agent.run_once() is True
            rehearsal = UnifiedRobotAgent(
                backend=backend,
                state=BridgeState(state_path),
                robot_id="max-pi-full-stack",
                rehearsal=True,
            )
            for _ in range(4):
                assert rehearsal.run_once() is True
            reloaded = BridgeState(state_path)
            assert reloaded.order_status_cursor > 0
            assert (
                reloaded.latest_order_status["mission-full-stack-0001"][
                    "normalized_status"
                ]
                == "ARRIVED_AT_DELIVERY_LOCATION"
            )

        with TestSession() as session:
            child = session.scalar(select(Mission).where(
                Mission.parent_mission_id == "mission-full-stack-0001"
            ))
            job = session.scalar(select(RobotJob).where(
                RobotJob.mission_id == child.id
            ))
            node = session.get(RobotNode, "max-pi-full-stack")
            assert child.phase == "COMPLETED"
            assert child.fulfilment_status == "DRY_RUN_COMPLETED"
            assert job.status == "COMPLETED"
            assert job.trigger_source == "SWIGGY"
            assert node.mode == "dry_run"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        app.dependency_overrides.clear()
        engine.dispose()
