from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from signaldesk_monitor_api.database import Base
from signaldesk_monitor_api.models import MonitorRun
from signaldesk_monitor_api.schemas import MonitorCreate
from signaldesk_monitor_api.service import attach, claim_due, create_monitor, resolve, utcnow

@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as value:
        yield value

def request(key=None):
    return MonitorCreate(name="primary", target="https://example.test/health", cadence_seconds=30, idempotency_key=key or uuid4())

def create_as_creator(session, org, creator, monitor_request):
    return create_monitor(session, org, creator, monitor_request, actor_user_id=creator)


def test_configuration_changes_require_a_human_actor(session):
    with pytest.raises(TypeError, match="actor_user_id"):
        create_monitor(session, uuid4(), uuid4(), request())


def test_create_idempotency_and_conflict(session):
    org, user, key = uuid4(), uuid4(), uuid4()
    monitor, created = create_as_creator(session, org, user, request(key))
    assert created
    replay, created = create_as_creator(session, org, user, request(key))
    assert replay.id == monitor.id and not created
    with pytest.raises(ValueError, match="conflicts"):
        create_as_creator(session, org, user, MonitorCreate(name="changed", target="https://example.test/health", cadence_seconds=30, idempotency_key=key))

def test_claim_attach_fences_stale_and_terminal_is_idempotent(session):
    monitor, _ = create_as_creator(session, uuid4(), uuid4(), request())
    claimed = claim_due(session, 120)
    assert claimed is not None
    run, _, token = claimed
    with pytest.raises(PermissionError): attach(session, run.id, uuid4(), token, run.lease_generation + 1)
    diagnostic = uuid4()
    attached = attach(session, run.id, diagnostic, token, run.lease_generation)
    assert attach(session, run.id, diagnostic, token, run.lease_generation).id == attached.id
    resolved, _ = resolve(session, diagnostic, monitor.organization_id, "failed")
    assert resolved.state == "failed"
    assert resolve(session, diagnostic, monitor.organization_id, "failed")[0].id == run.id
    with pytest.raises(ValueError, match="conflicts"):
        resolve(session, diagnostic, monitor.organization_id, "completed")

def test_reclaim_uses_new_generation_and_no_second_slot(session):
    monitor, _ = create_as_creator(session, uuid4(), uuid4(), request())
    first = claim_due(session, 1)
    assert first is not None
    run, _, old_token = first
    run.lease_expires_at = utcnow() - timedelta(seconds=1)
    second = claim_due(session, 60)
    assert second is not None and second[0].id == run.id
    assert second[0].lease_generation == 2
    with pytest.raises(PermissionError): attach(session, run.id, uuid4(), old_token, 1)
    assert session.query(MonitorRun).count() == 1


def test_attached_run_blocks_new_slot_and_replay_survives_expiry(session):
    monitor, _ = create_as_creator(session, uuid4(), uuid4(), request())
    run, _, token = claim_due(session, 1)
    diagnostic = uuid4()
    attach(session, run.id, diagnostic, token, run.lease_generation)
    assert attach(session, run.id, diagnostic, token, run.lease_generation).id == run.id
    with pytest.raises(ValueError, match="already attached"):
        attach(session, run.id, uuid4(), token, run.lease_generation)
    assert claim_due(session, 60) is None
    assert session.query(MonitorRun).filter_by(monitor_id=monitor.id).count() == 1
