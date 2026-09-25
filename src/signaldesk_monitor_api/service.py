from __future__ import annotations
import hashlib, json, secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .models import Monitor, MonitorRun
from .schemas import MonitorCreate, MonitorUpdate

def utcnow() -> datetime: return datetime.now(timezone.utc)


def database_now(session: Session) -> datetime:
    """Return the clock authoritative for scheduling and leases.

    PostgreSQL owns time in production so API-worker clock skew cannot move a
    monitor's schedule or lease window.  SQLite deliberately uses ``utcnow``
    so unit tests can control a deterministic clock without a database server.
    """
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        now = session.scalar(select(func.now()))
        assert now is not None
    else:
        now = utcnow()
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
def fingerprint(request: MonitorCreate) -> str:
    payload = request.model_dump(mode="json", exclude={"idempotency_key"})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
def token_hash(token: str) -> str: return hashlib.sha256(token.encode()).hexdigest()

def public_monitor(session: Session, monitor_id: UUID, org: UUID, *, lock: bool = False) -> Monitor:
    statement = select(Monitor).where(Monitor.id == monitor_id, Monitor.organization_id == org, Monitor.state != "deleted")
    monitor = session.scalar(statement.with_for_update() if lock else statement)
    if not monitor: raise LookupError("monitor not found")
    return monitor

def create_monitor(session: Session, org: UUID, creator: UUID, request: MonitorCreate) -> tuple[Monitor, bool]:
    existing = session.scalar(select(Monitor).where(Monitor.organization_id == org, Monitor.creator_id == creator, Monitor.idempotency_key == request.idempotency_key))
    digest = fingerprint(request)
    if existing:
        if existing.request_fingerprint != digest: raise ValueError("idempotency key conflicts with prior request")
        return existing, False
    monitor = Monitor(organization_id=org, creator_id=creator, name=request.name, target=str(request.target), cadence_seconds=request.cadence_seconds, alert_on_failure=request.alert_on_failure, idempotency_key=request.idempotency_key, request_fingerprint=digest, next_run_at=database_now(session))
    try:
        with session.begin_nested():
            session.add(monitor)
            session.flush()
    except IntegrityError:
        existing = session.scalar(select(Monitor).where(Monitor.organization_id == org, Monitor.creator_id == creator, Monitor.idempotency_key == request.idempotency_key))
        if existing is None: raise
        if existing.request_fingerprint != digest: raise ValueError("idempotency key conflicts with prior request")
        return existing, False
    return monitor, True

def claim_due(session: Session, lease_seconds: int) -> tuple[MonitorRun, Monitor, str] | None:
    # PostgreSQL's database time and SKIP LOCKED make concurrent workers non-blocking.
    now = database_now(session)
    run = session.scalar(select(MonitorRun).where(MonitorRun.state.in_(("pending", "claimed")), ((MonitorRun.state == "pending") | (MonitorRun.lease_expires_at < now))).order_by(MonitorRun.scheduled_for).with_for_update(skip_locked=True))
    monitor: Monitor | None = None
    if run:
        monitor = session.scalar(select(Monitor).where(Monitor.id == run.monitor_id).with_for_update())
        if not monitor or monitor.state != "enabled":
            if monitor and monitor.state != "enabled":
                run.state, run.lease_token_hash, run.lease_expires_at = "failed", None, None
            return None
    else:
        active_run = exists(select(MonitorRun.id).where(MonitorRun.monitor_id == Monitor.id, MonitorRun.state.in_(("pending", "claimed", "diagnostic_attached"))))
        monitor = session.scalar(select(Monitor).where(Monitor.state == "enabled", Monitor.next_run_at <= now, ~active_run).order_by(Monitor.next_run_at).with_for_update(skip_locked=True))
        if not monitor: return None
        scheduled = monitor.next_run_at
        run = MonitorRun(monitor_id=monitor.id, organization_id=monitor.organization_id, scheduled_for=scheduled)
        session.add(run); session.flush()
        # bounded catch-up: avoid an unbounded sequence after outages.
        monitor.next_run_at = max(now, scheduled) + timedelta(seconds=monitor.cadence_seconds)
    raw = secrets.token_urlsafe(32)
    run.state, run.lease_token_hash, run.lease_generation, run.lease_expires_at = "claimed", token_hash(raw), run.lease_generation + 1, now + timedelta(seconds=lease_seconds)
    session.flush()
    return run, monitor, raw

def attach(session: Session, run_id: UUID, diagnostic_id: UUID, token: str, generation: int) -> MonitorRun:
    run = session.scalar(select(MonitorRun).where(MonitorRun.id == run_id).with_for_update())
    if not run: raise PermissionError("stale lease")
    if run.diagnostic_job_id:
        if run.diagnostic_job_id == diagnostic_id: return run
        raise ValueError("diagnostic already attached")
    now = database_now(session)
    if run.lease_generation != generation or not run.lease_token_hash or not secrets.compare_digest(run.lease_token_hash, token_hash(token)) or not run.lease_expires_at or run.lease_expires_at <= now: raise PermissionError("stale lease")
    if run.state != "claimed": raise ValueError("run cannot attach diagnostic")
    run.diagnostic_job_id, run.state, run.lease_token_hash, run.lease_expires_at = diagnostic_id, "diagnostic_attached", None, None
    session.flush(); return run

def update_monitor(session: Session, monitor_id: UUID, org: UUID, request: MonitorUpdate) -> Monitor:
    monitor = public_monitor(session, monitor_id, org, lock=True)
    values = request.model_dump(exclude_none=True)
    if "name" in values: monitor.name = values["name"]
    if "target" in values: monitor.target = str(values["target"])
    if "alert_on_failure" in values: monitor.alert_on_failure = values["alert_on_failure"]
    if "cadence_seconds" in values:
        monitor.cadence_seconds = values["cadence_seconds"]
        monitor.next_run_at = database_now(session) + timedelta(seconds=monitor.cadence_seconds)
    session.flush()
    return monitor

def set_monitor_state(session: Session, monitor_id: UUID, org: UUID, desired: str) -> Monitor:
    monitor = public_monitor(session, monitor_id, org, lock=True)
    monitor.state = desired
    if desired == "enabled": monitor.next_run_at = database_now(session)
    session.flush()
    return monitor

def resolve(session: Session, diagnostic_id: UUID, organization_id: UUID, status: str) -> tuple[MonitorRun, Monitor]:
    run = session.scalar(select(MonitorRun).where(MonitorRun.diagnostic_job_id == diagnostic_id).with_for_update())
    if not run or run.organization_id != organization_id: raise LookupError("run not found")
    monitor = session.get(Monitor, run.monitor_id)
    assert monitor is not None
    if run.state in ("completed", "failed"):
        if run.state != status: raise ValueError("terminal status conflicts")
        return run, monitor
    if run.state != "diagnostic_attached": raise ValueError("run is not ready for terminal resolution")
    run.state, run.lease_token_hash, run.lease_expires_at = status, None, None
    session.flush(); return run, monitor
