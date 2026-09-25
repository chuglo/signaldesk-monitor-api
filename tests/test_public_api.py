from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from signaldesk_monitor_api.database import Base
from signaldesk_monitor_api.main import create_app
from signaldesk_monitor_api.settings import Settings


class Control:
    def __init__(self, allowed: set[tuple[UUID, UUID]]): self.allowed = allowed
    def verify_membership(self, user_id: UUID, organization_id: UUID) -> bool: return (user_id, organization_id) in self.allowed
    def ready(self) -> bool: return True


def configured_app():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    settings = Settings(database_url="postgresql+psycopg://u:p@localhost/db", control_api_url="https://control.test", web_bff_credential="a" * 32, scheduler_credential="b" * 32, alert_rule_credential="c" * 32, control_api_credential="d" * 32)
    user_a, org_a, user_b, org_b = uuid4(), uuid4(), uuid4(), uuid4()
    return TestClient(create_app(settings=settings, session_factory=factory, control_client=Control({(user_a, org_a), (user_b, org_b)}))), user_a, org_a, user_b, org_b


def headers(user: UUID, org: UUID, *, actor: str = "web-bff", credential: str = "a" * 32) -> dict[str, str]:
    return {"X-SignalDesk-Service-Actor": actor, "X-SignalDesk-Service-Credential": credential, "X-SignalDesk-User-ID": str(user), "X-SignalDesk-Organization-ID": str(org)}


def body(key: UUID, **override: object) -> dict[str, object]:
    result: dict[str, object] = {"name": "  uptime  ", "target": "https://example.test/health", "cadence_seconds": 30, "idempotency_key": str(key)}
    result.update(override)
    return result


def test_public_crud_idempotency_isolation_and_validation() -> None:
    client, user_a, org_a, user_b, org_b = configured_app()
    key = uuid4()
    create = client.post("/v1/monitors", headers=headers(user_a, org_a), json=body(key))
    assert create.status_code == 201, create.text
    monitor = create.json(); monitor_id = monitor["id"]
    assert monitor["organization_id"] == str(org_a) and monitor["creator_id"] == str(user_a) and monitor["name"] == "uptime"
    assert client.post("/v1/monitors", headers=headers(user_a, org_a), json=body(key)).status_code == 200
    assert client.post("/v1/monitors", headers=headers(user_a, org_a), json=body(key, name="other")).status_code == 409
    assert client.get("/v1/monitors", headers=headers(user_a, org_a)).json()[0]["id"] == monitor_id
    assert client.get(f"/v1/monitors/{monitor_id}", headers=headers(user_b, org_b)).status_code == 404
    changed = client.patch(f"/v1/monitors/{monitor_id}", headers=headers(user_a, org_a), json={"name": " changed ", "target": "https://new.test/x", "cadence_seconds": 60})
    assert changed.status_code == 200 and changed.json()["name"] == "changed" and changed.json()["cadence_seconds"] == 60
    assert client.post(f"/v1/monitors/{monitor_id}/pause", headers=headers(user_a, org_a)).json()["state"] == "paused"
    assert client.post(f"/v1/monitors/{monitor_id}/resume", headers=headers(user_a, org_a)).json()["state"] == "enabled"
    assert client.delete(f"/v1/monitors/{monitor_id}", headers=headers(user_a, org_a)).status_code == 204
    assert client.get(f"/v1/monitors/{monitor_id}", headers=headers(user_a, org_a)).status_code == 404
    assert client.post("/v1/monitors", headers=headers(user_a, org_a), json=body(uuid4(), organization_id=str(org_b))).status_code == 422
    assert client.patch(f"/v1/monitors/{monitor_id}", headers=headers(user_a, org_a), json={"name": "   "}).status_code == 422


def test_public_auth_membership_and_headers_are_exact_and_sanitized() -> None:
    client, user_a, org_a, _, _ = configured_app()
    assert client.get("/v1/monitors", headers=headers(user_a, org_a, actor="monitor-scheduler-worker", credential="b" * 32)).status_code == 403
    assert client.get("/v1/monitors", headers={"X-SignalDesk-Service-Actor": "web-bff", "X-SignalDesk-Service-Credential": "a" * 32, "X-SignalDesk-User-ID": str(user_a)}).status_code == 422
    denied = client.get("/v1/monitors", headers=headers(uuid4(), org_a))
    assert denied.status_code == 403 and "a" * 32 not in denied.text
