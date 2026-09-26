"""PostgreSQL-only migration, database-clock, constraint, and locking proof."""
from pathlib import Path
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from signaldesk_monitor_api.models import MonitorActivity, MonitorRun
from signaldesk_monitor_api.schemas import MonitorCreate, MonitorUpdate
from signaldesk_monitor_api.service import claim_due, create_monitor, set_monitor_state, update_monitor

def _create_as_creator(session, org, creator, request):
    return create_monitor(session, org, creator, request, actor_user_id=creator)


POSTGRES_IMAGE = "postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777"
ROOT = Path(__file__).parents[1]
_STARTUP_TIMEOUT_SECONDS = 30


def _docker(*args: str) -> str:
    completed = subprocess.run(
        ["docker", *args], check=True, text=True, capture_output=True, timeout=15
    )
    return completed.stdout.strip()


def _mapped_port(container_id: str) -> int | None:
    try:
        mapping = _docker("port", container_id, "5432/tcp")
    except subprocess.CalledProcessError:
        return None
    return int(mapping.rsplit(":", 1)[1]) if mapping else None


def _remove_container(container_id: str) -> None:
    # Exact IDs make cleanup safe when test processes run concurrently.
    subprocess.run(["docker", "rm", "-f", container_id], check=False, capture_output=True, timeout=15)


def _start_postgres() -> tuple[str, int]:
    # Inspect first, then --pull=never: no registry or credential-helper calls.
    _docker("image", "inspect", POSTGRES_IMAGE)
    name = f"signaldesk-monitor-api-postgres-{uuid4().hex}"
    container_id = _docker(
        "run", "--pull=never", "--rm", "-d", "-P", "--name", name,
        "-e", "POSTGRES_PASSWORD=postgres", POSTGRES_IMAGE,
    )
    try:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            port = _mapped_port(container_id)
            if port is not None:
                return container_id, port
            time.sleep(0.1)
        raise TimeoutError(f"Docker did not map PostgreSQL for {container_id}")
    except BaseException:
        _remove_container(container_id)
        raise


def _wait_for_postgres(port: int) -> str:
    url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:{port}/postgres"
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(url.replace("+psycopg", ""), connect_timeout=1) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
            return url
        except psycopg.OperationalError:
            time.sleep(0.2)
    raise TimeoutError("PostgreSQL did not become ready")


@pytest.fixture(scope="module")
def postgres_url():
    container_id: str | None = None
    try:
        container_id, port = _start_postgres()
        url = _wait_for_postgres(port)
        config = Config(str(ROOT / "alembic.ini")); config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url
    finally:
        if container_id is not None:
            _remove_container(container_id)


def test_migration_constraints_and_serialized_claim(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == "20260926_0002"
        with factory.begin() as session:
            monitor, _ = _create_as_creator(session, uuid4(), uuid4(), MonitorCreate(name="postgres", target="https://example.test/health", cadence_seconds=30, idempotency_key=uuid4()))
            monitor_id = monitor.id
        with factory.begin() as first:
            claimed = claim_due(first, 120)
            assert claimed is not None
            first_run = claimed[0].id
        with factory.begin() as second:
            assert claim_due(second, 120) is None
            assert second.query(MonitorRun).filter_by(monitor_id=monitor_id).count() == 1
        with factory() as session:
            with pytest.raises(IntegrityError):
                session.execute(text("UPDATE monitors SET state = 'invalid' WHERE id = :id"), {"id": monitor_id})
            session.rollback()
        with factory.begin() as session:
            assert session.get(MonitorRun, first_run).state == "claimed"
    finally:
        engine.dispose()


def test_activity_migration_is_atomic_with_monitor_updates(postgres_url: str) -> None:
    engine = create_engine(postgres_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    org, user = uuid4(), uuid4()
    try:
        with factory.begin() as session:
            monitor, _ = create_monitor(session, org, user, MonitorCreate(name="audit", target="https://example.test/path?secret=value", cadence_seconds=30, idempotency_key=uuid4()), actor_user_id=user)
            monitor_id = monitor.id
        with factory() as session:
            activity = session.query(MonitorActivity).filter_by(monitor_id=monitor_id).all()
            assert len(activity) == 1 and activity[0].action == "created"
            assert activity[0].actor_user_id == user
            assert "secret" not in str(activity[0].changed_fields)
        with pytest.raises(RuntimeError):
            with factory.begin() as session:
                update_monitor(session, monitor_id, org, MonitorUpdate(name="rolled back"), actor_user_id=user)
                raise RuntimeError("rollback")
        with factory() as session:
            assert session.query(MonitorActivity).filter_by(monitor_id=monitor_id).count() == 1
            assert session.execute(text("SELECT name FROM monitors WHERE id = :id"), {"id": monitor_id}).scalar() == "audit"
        with factory.begin() as session:
            update_monitor(session, monitor_id, org, MonitorUpdate(target="https://example.test/changed?secret=other"), actor_user_id=user)
        with factory() as session:
            events = session.query(MonitorActivity).filter_by(monitor_id=monitor_id).order_by(MonitorActivity.id).all()
            assert [event.action for event in events] == ["created", "updated"]
            assert events[-1].changed_fields == ["target"]
            assert "secret" not in str(events[-1].changed_fields)
        with factory.begin() as session:
            set_monitor_state(session, monitor_id, org, "deleted", actor_user_id=user)
    finally:
        engine.dispose()


def test_postgres_skip_locked_allows_only_one_concurrent_claim(postgres_url: str) -> None:
    """A held claim lock makes the second scheduler return without blocking."""
    engine = create_engine(postgres_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    claimed = threading.Event()
    second_finished = threading.Event()
    release = threading.Event()
    results: list[object] = []
    try:
        with factory.begin() as session:
            monitor, _ = _create_as_creator(session, uuid4(), uuid4(), MonitorCreate(name="concurrent", target="https://example.test/health", cadence_seconds=30, idempotency_key=uuid4()))
            monitor_id = monitor.id

        def first_worker() -> None:
            with factory.begin() as session:
                results.append(claim_due(session, 120))
                claimed.set()
                assert release.wait(timeout=5)

        def second_worker() -> None:
            assert claimed.wait(timeout=5)
            with factory.begin() as session:
                results.append(claim_due(session, 120))
            second_finished.set()

        first = threading.Thread(target=first_worker)
        second = threading.Thread(target=second_worker)
        first.start(); second.start()
        assert second_finished.wait(timeout=5), "SKIP LOCKED claim blocked behind another scheduler"
        release.set()
        first.join(timeout=5); second.join(timeout=5)
        assert not first.is_alive() and not second.is_alive()
        assert sum(result is not None for result in results) == 1
        with factory() as session:
            assert session.query(MonitorRun).filter_by(monitor_id=monitor_id).count() == 1
    finally:
        release.set()
        engine.dispose()


@pytest.mark.parametrize("skew", (timedelta(days=3650), timedelta(days=-3650)))
def test_scheduling_uses_postgres_clock_despite_api_skew(postgres_url: str, monkeypatch: pytest.MonkeyPatch, skew: timedelta) -> None:
    """Create, cadence change, and re-enable must never trust API-process time."""
    import signaldesk_monitor_api.service as service

    monkeypatch.setattr(service, "utcnow", lambda: datetime.now(timezone.utc) + skew)
    engine = create_engine(postgres_url)
    factory = sessionmaker(engine, expire_on_commit=False)
    try:
        with factory.begin() as session:
            database_before = session.scalar(text("SELECT now()"))
            assert database_before is not None
            monitor, _ = _create_as_creator(session, uuid4(), uuid4(), MonitorCreate(name="clock", target="https://example.test/health", cadence_seconds=30, idempotency_key=uuid4()))
            assert abs(monitor.next_run_at - database_before) < timedelta(seconds=2)
            monitor_id, organization_id = monitor.id, monitor.organization_id
        with factory.begin() as session:
            updated = update_monitor(session, monitor_id, organization_id, MonitorUpdate(cadence_seconds=90), actor_user_id=monitor.creator_id)
            database_now = session.scalar(text("SELECT now()"))
            assert database_now is not None
            assert abs(updated.next_run_at - (database_now + timedelta(seconds=90))) < timedelta(seconds=2)
            set_monitor_state(session, monitor_id, organization_id, "paused", actor_user_id=monitor.creator_id)
            enabled = set_monitor_state(session, monitor_id, organization_id, "enabled", actor_user_id=monitor.creator_id)
            database_now = session.scalar(text("SELECT now()"))
            assert database_now is not None
            assert abs(enabled.next_run_at - database_now) < timedelta(seconds=2)
    finally:
        engine.dispose()
