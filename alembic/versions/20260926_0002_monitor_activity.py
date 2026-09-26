"""Add tenant-scoped monitor configuration activity.

Revision ID: 20260926_0002
Revises: 20260825_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260926_0002"
down_revision = "20260825_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitor_activity",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("monitor_id", sa.Uuid(), sa.ForeignKey("monitors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("action IN ('created', 'updated', 'paused', 'resumed', 'deleted')", name="ck_monitor_activity_action"),
    )
    op.create_index("ix_monitor_activity_org_monitor_id", "monitor_activity", ["organization_id", "monitor_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_monitor_activity_org_monitor_id", table_name="monitor_activity")
    op.drop_table("monitor_activity")
