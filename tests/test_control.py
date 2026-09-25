from uuid import uuid4
import httpx
import pytest
from signaldesk_monitor_api.control import ControlClient

def test_membership_client_requires_exact_authoritative_identifiers() -> None:
    user, org = uuid4(), uuid4()
    seen = []
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"user_id": str(user), "organization_id": str(org), "role": "analyst"})
    client = ControlClient("https://control.test", "x" * 32, client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://control.test"))
    assert client.verify_membership(user, org)
    assert seen[0].url.path == "/internal/monitor-api/tenant-memberships/verify"
    assert seen[0].headers["x-signaldesk-service-actor"] == "monitor-api"


@pytest.mark.parametrize("response", [httpx.Response(500), httpx.Response(200, content=b"not-json"), httpx.Response(200, json={"user_id": "wrong", "organization_id": "wrong"})])
def test_membership_failures_deny(response: httpx.Response) -> None:
    user, org = uuid4(), uuid4()
    client = ControlClient("https://control.test", "x" * 32, client=httpx.Client(transport=httpx.MockTransport(lambda _: response), base_url="https://control.test"))
    assert not client.verify_membership(user, org)


def test_membership_timeout_denies() -> None:
    def fail(_: httpx.Request) -> httpx.Response: raise httpx.ReadTimeout("timeout")
    client = ControlClient("https://control.test", "x" * 32, client=httpx.Client(transport=httpx.MockTransport(fail), base_url="https://control.test"))
    assert not client.verify_membership(uuid4(), uuid4())


def test_ready_requires_control_ready_endpoint_and_exact_safe_body() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b'{"status":"ready"}')

    client = ControlClient(
        "https://control.test",
        "x" * 32,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://control.test"),
    )

    assert client.ready()
    assert seen[0].url.path == "/readyz"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b'{"status":"ok"}'),
        httpx.Response(200, content=b'{"status": "ready"}'),
        httpx.Response(200, content=b'{"status":"ready","extra":true}'),
        httpx.Response(200, content=b'not-json'),
        httpx.Response(204, content=b'{"status":"ready"}'),
        httpx.Response(302, headers={"location": "/readyz"}),
        httpx.Response(503, content=b'{"status":"ready"}'),
    ],
)
def test_ready_fails_closed_for_any_noncanonical_response(response: httpx.Response) -> None:
    client = ControlClient(
        "https://control.test",
        "x" * 32,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: response), base_url="https://control.test"),
    )

    assert not client.ready()


def test_ready_network_error_fails_closed() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    client = ControlClient(
        "https://control.test",
        "x" * 32,
        client=httpx.Client(transport=httpx.MockTransport(fail), base_url="https://control.test"),
    )

    assert not client.ready()


def test_close_does_not_close_injected_client() -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)), base_url="https://control.test")
    client = ControlClient("https://control.test", "x" * 32, client=http_client)

    client.close()

    assert not http_client.is_closed
    http_client.close()


def test_close_closes_owned_client() -> None:
    client = ControlClient("https://control.test", "x" * 32)

    client.close()

    assert client.client.is_closed
