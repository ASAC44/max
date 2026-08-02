"""Add resumable delivery tracking state."""

from alembic import op
import sqlalchemy as sa

revision = "0006_delivery_tracking"
down_revision = "0005_order_status_bridge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("missions", sa.Column("delivery", sa.JSON()))


def downgrade() -> None:
    op.drop_column("missions", "delivery")
