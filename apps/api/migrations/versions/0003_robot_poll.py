"""Add outbound Pi polling jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0003_robot_poll"
down_revision = "0002_telegram_control"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "robot_jobs",
        sa.Column("command_id", sa.String(64), primary_key=True),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("mission_id", name="uq_robot_job_mission"),
    )
    op.create_index(
        "ix_robot_jobs_status_created",
        "robot_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_robot_jobs_status_created", table_name="robot_jobs")
    op.drop_table("robot_jobs")
