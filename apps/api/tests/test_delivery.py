import asyncio
from datetime import timedelta

from sqlalchemy.orm import sessionmaker

import max_api.main as api
from max_api.db import Base, build_engine
from max_api.integrations import SwiggyDelivery
from max_api.models import Mission, utcnow


def test_due_armed_delivery_dispatches_once(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'delivery.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        session.add(Mission(
            id="mission-safe", active_slot="active", version=1, phase="ORDER_CONFIRMED",
            environment="production", agent_mode="simulated", request_text="milk",
            commerce_status="ORDER_CONFIRMED", payment_status="COMPLETED",
            checkout_status="ORDER_CONFIRMED", fulfilment_status="ARMED_FOR_DISPATCH",
            notification_status="NOT_STARTED", delivery={
                "order_id": "order-safe", "order_reference": "…safe",
                "latitude": 12.9, "longitude": 77.5, "status": "TRACKING",
                "armed": True, "robot_status": "NOT_STARTED",
            },
        ))
        session.commit()

    class Swiggy:
        async def track_order(self, _order):
            return SwiggyDelivery("ON_THE_WAY", utcnow() + timedelta(seconds=1))

    calls = []

    class Response:
        def json(self):
            return {
                "mission": "IDLE", "mission_id": None, "safety_reasons": [],
            }

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, url):
            calls.append(("GET", url))
            return Response()
        async def post(self, url, headers):
            calls.append(("POST", url, headers["X-Mission-Id"]))
            return Response()

    monkeypatch.setattr(api, "SessionLocal", TestSession)
    monkeypatch.setattr(api.httpx, "AsyncClient", Client)
    monkeypatch.setenv("MAX_ROBOT_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MAX_ROBOT_OPERATOR_PIN", "1234")
    monkeypatch.setenv("MAX_ROBOT_OUTBOUND_SECONDS", "1")
    monkeypatch.setenv("MAX_DISPATCH_BUFFER_SECONDS", "0")
    asyncio.run(api.delivery_tick(Swiggy()))

    with TestSession() as session:
        mission = session.get(Mission, "mission-safe")
        assert mission.phase == "EN_ROUTE_TO_PICKUP"
        assert mission.delivery["robot_status"] == "OUTBOUND"
    assert [call[0] for call in calls] == ["GET", "POST"]
    engine.dispose()


def test_ambiguous_start_failure_is_not_retried(tmp_path, monkeypatch):
    engine = build_engine(f"sqlite:///{tmp_path / 'unknown.db'}")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    with TestSession() as session:
        session.add(Mission(
            id="mission-unknown", active_slot="active", version=1, phase="ORDER_CONFIRMED",
            environment="production", agent_mode="simulated", request_text="milk",
            commerce_status="ORDER_CONFIRMED", payment_status="COMPLETED",
            checkout_status="ORDER_CONFIRMED", fulfilment_status="ARMED_FOR_DISPATCH",
            notification_status="NOT_STARTED", delivery={
                "order_id": "order-unknown", "order_reference": "…nown",
                "latitude": 12.9, "longitude": 77.5, "status": "TRACKING",
                "armed": True, "robot_status": "NOT_STARTED",
            },
        ))
        session.commit()

    class Swiggy:
        async def track_order(self, _order):
            return SwiggyDelivery("ON_THE_WAY", utcnow() + timedelta(seconds=1))

    posts = 0

    class Response:
        def json(self):
            return {"mission": "IDLE", "mission_id": None, "safety_reasons": []}

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **_kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get(self, _url): return Response()
        async def post(self, _url, _headers=None, **_kwargs):
            nonlocal posts
            posts += 1
            raise api.httpx.ReadTimeout("unknown", request=api.httpx.Request("POST", "http://robot/start"))

    monkeypatch.setattr(api, "SessionLocal", TestSession)
    monkeypatch.setattr(api.httpx, "AsyncClient", Client)
    monkeypatch.setenv("MAX_ROBOT_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("MAX_ROBOT_OPERATOR_PIN", "1234")
    monkeypatch.setenv("MAX_ROBOT_OUTBOUND_SECONDS", "1")
    monkeypatch.setenv("MAX_DISPATCH_BUFFER_SECONDS", "0")
    asyncio.run(api.delivery_tick(Swiggy()))
    asyncio.run(api.delivery_tick(Swiggy()))

    with TestSession() as session:
        delivery = session.get(Mission, "mission-unknown").delivery
        assert delivery["robot_status"] == "START_UNKNOWN"
        assert "do not retry" in delivery["alert"]
    assert posts == 1
    engine.dispose()
