from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Mission, RobotJob, RobotNode, utcnow
from .schemas import Quote, RobotHeartbeat, RobotLifecycleReport, RobotPollAck
from .workflow import (
    Conflict,
    record_robot_dispatch_acknowledgement,
    record_robot_lifecycle,
)


def stage_robot_job(
    session: Session,
    mission: Mission,
    *,
    expected_version: int,
    command_id: str,
    dry_run: bool,
    trigger_source: str = "OPERATOR",
    trigger_status: str = "PACKAGE_READY",
) -> RobotJob:
    if (
        mission.version != expected_version
        or mission.environment != "staged_demo"
        or mission.phase != "READY_TO_DISPATCH"
        or mission.fulfilment_status not in {"PACKAGE_READY", "ROBOT_DRY_RUN_ACKNOWLEDGED"}
    ):
        raise Conflict("robot dispatch is blocked until staged PACKAGE_READY")
    if trigger_source not in {"OPERATOR", "SWIGGY"}:
        raise Conflict("unsupported robot job trigger source")
    if not trigger_status or len(trigger_status) > 48:
        raise Conflict("invalid robot job trigger status")
    quote = Quote.model_validate(mission.quote)
    existing = session.get(RobotJob, command_id)
    if existing:
        if (
            existing.mission_id != mission.id
            or existing.expected_version != expected_version
            or existing.destination != quote.destination
            or existing.dry_run != dry_run
            or existing.trigger_source != trigger_source
            or existing.trigger_status != trigger_status
        ):
            raise Conflict("robot command_id was already used for another job")
        return existing
    job = RobotJob(
        command_id=command_id,
        mission_id=mission.id,
        expected_version=expected_version,
        destination=quote.destination,
        dry_run=dry_run,
        trigger_source=trigger_source,
        trigger_status=trigger_status,
        status="PENDING",
    )
    session.add(job)
    try:
        session.commit()
        return job
    except IntegrityError as exc:
        session.rollback()
        existing = session.scalar(select(RobotJob).where(RobotJob.mission_id == mission.id))
        if existing and existing.command_id == command_id:
            return existing
        if existing:
            raise Conflict("a robot job is already queued for this mission") from exc
        raise Conflict("robot job could not be staged") from exc


def next_robot_job(session: Session, *, dry_run: bool | None = None) -> RobotJob | None:
    query = select(RobotJob).where(RobotJob.status.in_(("PENDING", "DELIVERED")))
    if dry_run is not None:
        query = query.where(RobotJob.dry_run == dry_run)
    job = session.scalar(
        query
        .order_by(RobotJob.created_at)
        .limit(1)
    )
    if not job:
        return None
    job.status = "DELIVERED"
    job.delivered_at = utcnow()
    session.commit()
    return job


def current_robot_job(session: Session) -> RobotJob | None:
    return session.scalar(
        select(RobotJob)
        .where(
            RobotJob.status.in_(
                ("ACKNOWLEDGED", "AT_PICKUP", "ITEM_SECURED", "RETURNING")
            )
        )
        .order_by(RobotJob.created_at)
        .limit(1)
    )


def acknowledge_robot_job(session: Session, ack: RobotPollAck) -> Mission:
    job = session.get(RobotJob, ack.command_id)
    if not job or job.mission_id != ack.mission_id:
        raise Conflict("robot acknowledgement does not match a queued job")
    if ack.dry_run != job.dry_run or ack.motion_started == ack.dry_run:
        raise Conflict("unsafe or mismatched robot acknowledgement")
    if job.status == "ACKNOWLEDGED":
        return session.get(Mission, job.mission_id)
    if job.status != "DELIVERED":
        raise Conflict("robot job has not been delivered")
    mission = record_robot_dispatch_acknowledgement(
        session,
        job.mission_id,
        job.expected_version,
        job.command_id,
        dry_run=ack.dry_run,
        motion_started=ack.motion_started,
    )
    job = session.get(RobotJob, ack.command_id)
    job.status = "ACKNOWLEDGED"
    job.acknowledged_at = utcnow()
    session.commit()
    return mission


def record_robot_heartbeat(session: Session, heartbeat: RobotHeartbeat) -> RobotNode:
    node = session.get(RobotNode, heartbeat.robot_id)
    if not node:
        node = RobotNode(id=heartbeat.robot_id)
        session.add(node)
    node.agent_version = heartbeat.agent_version
    node.mode = heartbeat.mode
    node.status = heartbeat.status
    node.subsystems = heartbeat.subsystems
    node.last_error = heartbeat.last_error
    node.last_seen_at = utcnow()
    session.commit()
    session.refresh(node)
    return node


def latest_robot_node(session: Session) -> RobotNode | None:
    return session.scalar(
        select(RobotNode).order_by(RobotNode.last_seen_at.desc()).limit(1)
    )


def record_robot_lifecycle_report(
    session: Session,
    report: RobotLifecycleReport,
) -> Mission:
    job = session.get(RobotJob, report.command_id)
    if not job or job.mission_id != report.mission_id:
        raise Conflict("robot lifecycle report does not match a queued job")
    if report.dry_run != job.dry_run or report.motion_started == report.dry_run:
        raise Conflict("unsafe or mismatched robot lifecycle report")
    if job.status not in {
        "ACKNOWLEDGED",
        "AT_PICKUP",
        "ITEM_SECURED",
        "RETURNING",
        "COMPLETED",
    }:
        raise Conflict("robot job has not been acknowledged")
    progression = {
        "ACKNOWLEDGED": 0,
        "AT_PICKUP": 1,
        "ITEM_SECURED": 2,
        "RETURNING": 3,
        "COMPLETED": 4,
        "CANCELLED": 5,
    }
    mission = record_robot_lifecycle(
        session,
        report.mission_id,
        report.expected_version,
        report.event_id,
        stage=report.stage,
        dry_run=report.dry_run,
        motion_started=report.motion_started,
    )
    job = session.get(RobotJob, report.command_id)
    if progression[report.stage] > progression[job.status]:
        job.status = report.stage
    session.commit()
    return mission
