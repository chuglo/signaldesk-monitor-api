"""create monitor authority tables

Revision ID: 20260825_0001
Revises:
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa
revision = "20260825_0001"
down_revision = None
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.create_table("monitors", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("creator_id", sa.Uuid(), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("target", sa.String(2048), nullable=False), sa.Column("cadence_seconds", sa.Integer(), nullable=False), sa.Column("state", sa.String(16), nullable=False), sa.Column("alert_on_failure", sa.Boolean(), nullable=False), sa.Column("idempotency_key", sa.Uuid(), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False), sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.CheckConstraint("cadence_seconds BETWEEN 30 AND 86400", name="ck_monitor_cadence"), sa.CheckConstraint("state IN ('enabled', 'paused', 'deleted')", name="ck_monitor_state"), sa.UniqueConstraint("organization_id", "creator_id", "idempotency_key", name="uq_monitor_idempotency"))
    op.create_index("ix_monitors_organization_id", "monitors", ["organization_id"]); op.create_index("ix_monitors_creator_id", "monitors", ["creator_id"]); op.create_index("ix_monitors_next_run_at", "monitors", ["next_run_at"])
    op.create_table("monitor_runs", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("monitor_id", sa.Uuid(), sa.ForeignKey("monitors.id", ondelete="RESTRICT"), nullable=False), sa.Column("organization_id", sa.Uuid(), nullable=False), sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False), sa.Column("state", sa.String(24), nullable=False), sa.Column("lease_token_hash", sa.String(64)), sa.Column("lease_generation", sa.Integer(), nullable=False), sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("diagnostic_job_id", sa.Uuid()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.CheckConstraint("state IN ('pending', 'claimed', 'diagnostic_attached', 'completed', 'failed')", name="ck_monitor_run_state"), sa.CheckConstraint("lease_generation >= 0", name="ck_monitor_run_generation"), sa.CheckConstraint("(state = 'claimed' AND lease_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL AND diagnostic_job_id IS NULL) OR (state != 'claimed' AND lease_token_hash IS NULL AND lease_expires_at IS NULL)", name="ck_monitor_run_lease_coherence"), sa.UniqueConstraint("monitor_id", "scheduled_for", name="uq_monitor_run_slot"), sa.UniqueConstraint("diagnostic_job_id", name="uq_monitor_run_diagnostic"))
    op.create_index("ix_monitor_runs_organization_id", "monitor_runs", ["organization_id"]); op.create_index("ix_monitor_runs_monitor_id", "monitor_runs", ["monitor_id"]); op.create_index("ix_monitor_runs_state", "monitor_runs", ["state"]); op.create_index("ix_monitor_runs_active_monitor", "monitor_runs", ["monitor_id", "state"])
def downgrade() -> None:
    op.drop_table("monitor_runs"); op.drop_table("monitors")
