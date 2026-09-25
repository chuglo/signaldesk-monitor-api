from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from signaldesk_monitor_api.main import create_app
from signaldesk_monitor_api.settings import Settings


def env(**overrides: str) -> dict[str, str]:
    values = {
        "SIGNALDESK_DATABASE_URL": "postgresql+psycopg://monitor:password@db/monitor",
        "SIGNALDESK_CONTROL_API_URL": "https://control.example",
        "SIGNALDESK_WEB_BFF_CREDENTIAL": "a" * 32,
        "SIGNALDESK_SCHEDULER_CREDENTIAL": "b" * 32,
        "SIGNALDESK_ALERT_RULE_CREDENTIAL": "c" * 32,
        "SIGNALDESK_CONTROL_API_CREDENTIAL": "d" * 32,
    }
    values.update(overrides)
    return values


def test_settings_requires_distinct_credentials() -> None:
    with pytest.raises(ValueError, match="distinct"):
        Settings(_env_file=None, **{key.removeprefix("SIGNALDESK_").lower(): value for key, value in env(SIGNALDESK_SCHEDULER_CREDENTIAL="a" * 32).items()})


def test_settings_rejects_short_or_whitespace_credentials() -> None:
    values = {key.removeprefix("SIGNALDESK_").lower(): value for key, value in env(SIGNALDESK_WEB_BFF_CREDENTIAL="a" * 31).items()}
    with pytest.raises(ValueError, match="32"):
        Settings(_env_file=None, **values)
    values = {key.removeprefix("SIGNALDESK_").lower(): value for key, value in env(SIGNALDESK_WEB_BFF_CREDENTIAL="a" * 31 + " ").items()}
    with pytest.raises(ValueError, match="whitespace"):
        Settings(_env_file=None, **values)


def test_health_is_process_only() -> None:
    client = TestClient(create_app())
    assert client.get("/healthz").json() == {"status": "ok"}


def test_public_requires_correct_actor_and_membership_headers() -> None:
    app = create_app(settings=Settings(_env_file=None, **{key.removeprefix("SIGNALDESK_").lower(): value for key, value in env().items()}))
    client = TestClient(app)
    assert client.get("/v1/monitors").status_code == 401
    response = client.get("/v1/monitors", headers={
        "X-SignalDesk-Service-Actor": "monitor-scheduler-worker",
        "X-SignalDesk-Service-Credential": "b" * 32,
        "X-SignalDesk-User-ID": str(uuid4()), "X-SignalDesk-Organization-ID": str(uuid4()),
    })
    assert response.status_code == 403
