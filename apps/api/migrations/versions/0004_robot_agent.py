"""Add unified Pi agent heartbeat state."""

from alembic import op
import sqlalchemy as sa

revision = "0004_robot_agent"
down_revision = "0003_robot_poll"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "robot_nodes",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("agent_version", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("subsystems", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.String(128)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("robot_nodes")
