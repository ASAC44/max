"""Create Phase 3A mission tables."""

from alembic import op
import sqlalchemy as sa

revision = "0001_phase3a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parent_mission_id", sa.String(36), sa.ForeignKey("missions.id", ondelete="RESTRICT")),
        sa.Column("active_slot", sa.String(16)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(48), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("agent_mode", sa.String(24), nullable=False),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("intent", sa.JSON()),
        sa.Column("clarification_question", sa.Text()),
        sa.Column("quote", sa.JSON()),
        sa.Column("quote_hash", sa.String(64)),
        sa.Column("approval_quote_hash", sa.String(64)),
        sa.Column("commerce_status", sa.String(32), nullable=False),
        sa.Column("payment_status", sa.String(32), nullable=False),
        sa.Column("checkout_status", sa.String(32), nullable=False),
        sa.Column("fulfilment_status", sa.String(32), nullable=False),
        sa.Column("notification_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 0", name="ck_mission_version_nonnegative"),
        sa.UniqueConstraint("parent_mission_id", name="uq_mission_parent"),
        sa.UniqueConstraint("active_slot", name="uq_mission_active_slot"),
    )
    op.create_index("ix_missions_parent", "missions", ["parent_mission_id"])
    op.create_index("ix_missions_phase_updated", "missions", ["phase", "updated_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mission_id", sa.String(36), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(64)),
        sa.Column("command_scope", sa.String(48), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("component", sa.String(48), nullable=False),
        sa.Column("provider", sa.String(48)),
        sa.Column("human_intervened", sa.Boolean(), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("phase_before", sa.String(48), nullable=False),
        sa.Column("phase_after", sa.String(48), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("mission_id", "sequence", name="uq_event_mission_sequence"),
        sa.UniqueConstraint("command_id", name="uq_event_command"),
    )
    op.create_index("ix_events_mission_created", "events", ["mission_id", "created_at"])

    op.create_table(
        "external_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("mission_id", sa.String(36), sa.ForeignKey("missions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("command_id", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(48), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("terminal", sa.Boolean()),
        sa.Column("redacted_reference", sa.String(128)),
        sa.Column("error_class", sa.String(64)),
        sa.Column("retry_eligible", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_attempts_mission_started", "external_attempts", ["mission_id", "started_at"])
    op.create_index("ix_attempts_status", "external_attempts", ["status"])


def downgrade() -> None:
    op.drop_table("external_attempts")
    op.drop_table("events")
    op.drop_table("missions")
