"""Add Swiggy trigger provenance to robot jobs."""

from alembic import op
import sqlalchemy as sa

revision = "0005_order_status_bridge"
down_revision = "0004_robot_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("missions") as batch:
        batch.alter_column(
            "commerce_status",
            existing_type=sa.String(32),
            type_=sa.String(48),
            existing_nullable=False,
        )
    with op.batch_alter_table("robot_jobs") as batch:
        batch.add_column(
            sa.Column(
                "trigger_source",
                sa.String(24),
                nullable=False,
                server_default="OPERATOR",
            )
        )
        batch.add_column(
            sa.Column(
                "trigger_status",
                sa.String(48),
                nullable=False,
                server_default="PACKAGE_READY",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("robot_jobs") as batch:
        batch.drop_column("trigger_status")
        batch.drop_column("trigger_source")
    with op.batch_alter_table("missions") as batch:
        batch.alter_column(
            "commerce_status",
            existing_type=sa.String(48),
            type_=sa.String(32),
            existing_nullable=False,
        )
