"""Add durable Telegram control-plane queues."""

from alembic import op
import sqlalchemy as sa

revision = "0002_telegram_control"
down_revision = "0001_phase3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("request_text", sa.Text()),
        sa.Column("callback_query_id", sa.String(128)),
        sa.Column("callback_data", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="SET NULL"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_class", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_telegram_updates_status_created",
        "telegram_updates",
        ["status", "created_at"],
    )
    op.create_table(
        "telegram_notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "mission_id",
            sa.String(36),
            sa.ForeignKey("missions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mission_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "mission_id",
            "mission_version",
            "kind",
            name="uq_telegram_notification_mission_version_kind",
        ),
    )


def downgrade() -> None:
    op.drop_table("telegram_notifications")
    op.drop_index("ix_telegram_updates_status_created", table_name="telegram_updates")
    op.drop_table("telegram_updates")
