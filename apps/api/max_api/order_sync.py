from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import (
    order_sync_error_interval_seconds,
    order_sync_interval_seconds,
    order_sync_state_file,
    robot_dry_run,
)
from .db import SessionLocal
from .integrations import IntegrationError, SwiggyClient, SwiggyOrderSnapshot
from .models import Event, Mission, RobotJob
from .robot_jobs import stage_robot_job
from .schemas import Phase, Quote
from .workflow import (
    Conflict,
    cancel,
    package_ready,
    record_swiggy_order_status,
    start_staged_fulfilment,
)

ARRIVAL_TRIGGER = "ARRIVED_AT_DELIVERY_LOCATION"
TERMINAL_STATUSES = {"SWIGGY_DELIVERED", "SWIGGY_CANCELLED", "SWIGGY_FAILED"}


@dataclass(frozen=True)
class SyncSummary:
    candidates: int
    processed: int
    failures: int
    last_error_class: str | None = None


def _read_worker_state(path: Path | None = None) -> dict:
    path = path or order_sync_state_file()
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_worker_state(
    summary: SyncSummary,
    *,
    path: Path | None = None,
) -> None:
    path = path or order_sync_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    previous = _read_worker_state(path)
    value = {
        **asdict(summary),
        "cycle_at": now,
        "last_full_success_at": (
            now
            if summary.failures == 0
            else previous.get("last_full_success_at")
        ),
    }
    with tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        json.dump(value, handle, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _safe_write_worker_state(summary: SyncSummary) -> None:
    try:
        _write_worker_state(summary)
    except OSError:
        print("Swiggy status worker could not persist its health heartbeat")


def order_sync_worker_readiness(path: Path | None = None) -> dict:
    value = _read_worker_state(path)
    try:
        cycle_at = datetime.fromisoformat(value["cycle_at"])
        if cycle_at.tzinfo is None:
            cycle_at = cycle_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - cycle_at).total_seconds()
        fresh = age <= max(90, order_sync_error_interval_seconds() * 3)
        failures = int(value.get("failures", 0))
    except (KeyError, TypeError, ValueError):
        return {
            "connected": False,
            "error": "Swiggy order status worker has not reported",
        }
    connected = fresh and failures == 0
    result = {
        "connected": connected,
        "running": fresh,
        "candidates": int(value.get("candidates", 0)),
        "processed": int(value.get("processed", 0)),
        "failures": failures,
        "last_full_success_at": value.get("last_full_success_at"),
    }
    if not fresh:
        result["error"] = "Swiggy order status worker heartbeat is stale"
    elif failures:
        result["error"] = "Swiggy order status worker last cycle had failures"
    return result


def normalize_swiggy_status(raw_status: str) -> str:
    value = " ".join(raw_status.upper().replace("-", " ").replace("_", " ").split())
    if any(token in value for token in ("CANCEL",)):
        return "CANCELLED"
    if any(token in value for token in ("FAIL", "REJECT", "REFUND")):
        return "FAILED"
    if "DELIVERED" in value:
        return "DELIVERED"
    if (
        "ARRIVED" in value
        or "AT DESTINATION" in value
        or "REACHED DELIVERY" in value
        or "REACHED YOUR LOCATION" in value
    ):
        return ARRIVAL_TRIGGER
    if any(
        token in value
        for token in (
            "OUT FOR DELIVERY",
            "PICKED UP",
            "ON THE WAY",
            "RIDER ASSIGNED",
            "DELIVERY PARTNER ASSIGNED",
        )
    ):
        return "OUT_FOR_DELIVERY"
    if any(token in value for token in ("READY", "PACKED")):
        return "READY_FOR_PICKUP"
    if any(token in value for token in ("PREPAR", "PROCESS", "PACKING")):
        return "PREPARING"
    if any(token in value for token in ("CONFIRM", "ACCEPT")):
        return "CONFIRMED"
    if any(token in value for token in ("PLACED", "CREATED")):
        return "ORDER_PLACED"
    return "UNKNOWN"


def _command_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]
    return f"{prefix}-{digest}"


def latest_provider_order_id(session: Session, mission_id: str) -> str | None:
    events = session.scalars(
        select(Event)
        .where(
            Event.mission_id == mission_id,
            Event.event_type.like("SWIGGY_ORDER_%"),
        )
        .order_by(Event.sequence.desc())
    ).all()
    for event in events:
        value = event.payload.get("provider_order_id")
        if isinstance(value, str) and value:
            return value
    return None


def apply_order_snapshot(
    session: Session,
    mission_id: str,
    snapshot: SwiggyOrderSnapshot,
) -> Mission:
    mission = session.get(Mission, mission_id, populate_existing=True)
    if not mission:
        raise Conflict("Swiggy status mission no longer exists")
    normalized = normalize_swiggy_status(snapshot.raw_status)
    status_command = _command_id(
        "swiggy-status",
        mission.id,
        snapshot.provider_order_id,
        snapshot.raw_status,
        normalized,
    )
    mission = record_swiggy_order_status(
        session,
        mission.id,
        mission.version,
        status_command,
        provider_order_id=snapshot.provider_order_id,
        raw_status=snapshot.raw_status,
        normalized_status=normalized,
        eta_text=snapshot.eta_text,
    )
    applied_status = mission.commerce_status == f"SWIGGY_{normalized}"
    child = session.scalar(
        select(Mission).where(Mission.parent_mission_id == mission.id)
    )
    if normalized in {"CANCELLED", "FAILED"} and applied_status:
        if child is not None:
            job = session.scalar(
                select(RobotJob).where(RobotJob.mission_id == child.id)
            )
            if job and job.status != "COMPLETED":
                job.status = "CANCELLED"
                session.commit()
            if child.phase in {Phase.ORDER_CONFIRMED, Phase.READY_TO_DISPATCH}:
                cancel(
                    session,
                    child.id,
                    child.version,
                    _command_id(
                        "swiggy-cancel",
                        child.id,
                        snapshot.provider_order_id,
                        normalized,
                    ),
                    source="swiggy_status",
                    source_status=normalized,
                )
        return mission
    if normalized != ARRIVAL_TRIGGER or not applied_status:
        return mission

    if child is None:
        child = start_staged_fulfilment(
            session,
            mission.id,
            mission.version,
            _command_id("swiggy-stage", mission.id, snapshot.provider_order_id),
            source="swiggy_status",
            source_status=normalized,
        )
    if child.phase == Phase.ORDER_CONFIRMED:
        child = package_ready(
            session,
            child.id,
            child.version,
            _command_id("swiggy-ready", child.id, snapshot.provider_order_id),
            source="swiggy_status",
            source_status=normalized,
        )
    job = session.scalar(select(RobotJob).where(RobotJob.mission_id == child.id))
    if job is None:
        stage_robot_job(
            session,
            child,
            expected_version=child.version,
            command_id=_command_id(
                "swiggy-dispatch",
                child.id,
                snapshot.provider_order_id,
            ),
            dry_run=robot_dry_run(),
            trigger_source="SWIGGY",
            trigger_status=normalized,
        )
    return mission


async def sync_once(client: SwiggyClient | None = None) -> SyncSummary:
    client = client or SwiggyClient()
    with SessionLocal() as session:
        candidates = session.scalars(
            select(Mission)
            .where(
                Mission.environment == "production",
                Mission.phase == Phase.ORDER_CONFIRMED,
                Mission.commerce_status.notin_(TERMINAL_STATUSES),
            )
            .order_by(Mission.created_at)
        ).all()
        work = [
            (
                mission.id,
                latest_provider_order_id(session, mission.id),
                Quote.model_validate(mission.quote),
            )
            for mission in candidates
            if mission.quote
        ]

    processed = 0
    failures = 0
    last_error_class = None
    for mission_id, provider_order_id, quote in work:
        try:
            snapshot = await asyncio.wait_for(
                client.order_snapshot(
                    provider_order_id=provider_order_id,
                    quote=quote,
                ),
                timeout=30,
            )
            with SessionLocal() as session:
                apply_order_snapshot(session, mission_id, snapshot)
            processed += 1
        except Exception as exc:
            failures += 1
            last_error_class = type(exc).__name__
    return SyncSummary(
        candidates=len(work),
        processed=processed,
        failures=failures,
        last_error_class=last_error_class,
    )


def main() -> None:
    print(f"Swiggy order status worker started; robot mode={'dry_run' if robot_dry_run() else 'physical'}")
    while True:
        delay = order_sync_interval_seconds()
        try:
            summary = asyncio.run(sync_once())
            _safe_write_worker_state(summary)
            if summary.failures:
                delay = order_sync_error_interval_seconds()
                print(
                    "Swiggy status sync cycle had failures; "
                    f"count={summary.failures} class={summary.last_error_class}"
                )
        except Exception as exc:
            delay = order_sync_error_interval_seconds()
            _safe_write_worker_state(
                SyncSummary(
                    candidates=0,
                    processed=0,
                    failures=1,
                    last_error_class=type(exc).__name__,
                )
            )
            print(f"Swiggy status sync failed safely: {type(exc).__name__}")
        time.sleep(delay)


if __name__ == "__main__":
    main()
