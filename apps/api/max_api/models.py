from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_mission_version_nonnegative"),
        UniqueConstraint("parent_mission_id", name="uq_mission_parent"),
        UniqueConstraint("active_slot", name="uq_mission_active_slot"),
        Index("ix_missions_parent", "parent_mission_id"),
        Index("ix_missions_phase_updated", "phase", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id", ondelete="RESTRICT"))
    active_slot: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    phase: Mapped[str] = mapped_column(String(48), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    agent_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    clarification_question: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quote_hash: Mapped[str | None] = mapped_column(String(64))
    approval_quote_hash: Mapped[str | None] = mapped_column(String(64))
    commerce_status: Mapped[str] = mapped_column(String(48), nullable=False)
    payment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    checkout_status: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfilment_status: Mapped[str] = mapped_column(String(32), nullable=False)
    notification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    delivery: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence", name="uq_event_mission_sequence"),
        UniqueConstraint("command_id", name="uq_event_command"),
        Index("ix_events_mission_created", "mission_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    command_id: Mapped[str | None] = mapped_column(String(64))
    command_scope: Mapped[str] = mapped_column(String(48), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    component: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(48))
    human_intervened: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    phase_before: Mapped[str] = mapped_column(String(48), nullable=False)
    phase_after: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ExternalAttempt(Base):
    __tablename__ = "external_attempts"
    __table_args__ = (
        Index("ix_attempts_mission_started", "mission_id", "started_at"),
        Index("ix_attempts_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False)
    command_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    operation: Mapped[str] = mapped_column(String(48), nullable=False)
    environment: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    terminal: Mapped[bool | None] = mapped_column(Boolean)
    redacted_reference: Mapped[str | None] = mapped_column(String(128))
    error_class: Mapped[str | None] = mapped_column(String(64))
    retry_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramUpdate(Base):
    __tablename__ = "telegram_updates"
    __table_args__ = (
        Index("ix_telegram_updates_status_created", "status", "created_at"),
    )

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_text: Mapped[str | None] = mapped_column(Text)
    callback_query_id: Mapped[str | None] = mapped_column(String(128))
    callback_data: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id", ondelete="SET NULL"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_class: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramNotification(Base):
    __tablename__ = "telegram_notifications"
    __table_args__ = (
        UniqueConstraint(
            "mission_id",
            "mission_version",
            "kind",
            name="uq_telegram_notification_mission_version_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mission_version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RobotJob(Base):
    __tablename__ = "robot_jobs"
    __table_args__ = (
        UniqueConstraint("mission_id", name="uq_robot_job_mission"),
        Index("ix_robot_jobs_status_created", "status", "created_at"),
    )

    command_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    mission_id: Mapped[str] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
    )
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    destination: Mapped[str] = mapped_column(String(100), nullable=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_source: Mapped[str] = mapped_column(String(24), nullable=False, default="OPERATOR")
    trigger_status: Mapped[str] = mapped_column(String(48), nullable=False, default="PACKAGE_READY")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RobotNode(Base):
    __tablename__ = "robot_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    subsystems: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(String(128))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
