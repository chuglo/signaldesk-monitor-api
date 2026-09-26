from __future__ import annotations
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

class Monitor(Base):
    __tablename__ = "monitors"
    __table_args__ = (UniqueConstraint("organization_id", "creator_id", "idempotency_key", name="uq_monitor_idempotency"), CheckConstraint("cadence_seconds BETWEEN 30 AND 86400", name="ck_monitor_cadence"), CheckConstraint("state IN ('enabled', 'paused', 'deleted')", name="ck_monitor_state"))
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    creator_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    name: Mapped[str] = mapped_column(String(200))
    target: Mapped[str] = mapped_column(String(2048))
    cadence_seconds: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(16), default="enabled")
    alert_on_failure: Mapped[bool] = mapped_column(default=True)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class MonitorActivity(Base):
    __tablename__ = "monitor_activity"
    __table_args__ = (
        CheckConstraint("action IN ('created', 'updated', 'paused', 'resumed', 'deleted')", name="ck_monitor_activity_action"),
        Index("ix_monitor_activity_org_monitor_id", "organization_id", "monitor_id", "id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    monitor_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("monitors.id", ondelete="RESTRICT"))
    actor_user_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(16))
    changed_fields: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class MonitorRun(Base):
    __tablename__ = "monitor_runs"
    __table_args__ = (
        UniqueConstraint("monitor_id", "scheduled_for", name="uq_monitor_run_slot"), UniqueConstraint("diagnostic_job_id", name="uq_monitor_run_diagnostic"),
        CheckConstraint("state IN ('pending', 'claimed', 'diagnostic_attached', 'completed', 'failed')", name="ck_monitor_run_state"),
        CheckConstraint("lease_generation >= 0", name="ck_monitor_run_generation"),
        CheckConstraint("(state = 'claimed' AND lease_token_hash IS NOT NULL AND lease_expires_at IS NOT NULL AND diagnostic_job_id IS NULL) OR (state != 'claimed' AND lease_token_hash IS NULL AND lease_expires_at IS NULL)", name="ck_monitor_run_lease_coherence"),
        Index("ix_monitor_runs_active_monitor", "monitor_id", "state"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    monitor_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("monitors.id", ondelete="RESTRICT"), index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    diagnostic_job_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
