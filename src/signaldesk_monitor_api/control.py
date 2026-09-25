from __future__ import annotations
from uuid import UUID
import httpx
from signaldesk_service_kit import bounded_timeout

class ControlClient:
    def __init__(self, base_url: str, credential: str, *, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(base_url=base_url, timeout=bounded_timeout(connect=2, read=5, write=5, pool=2))
        self.headers = {"X-SignalDesk-Service-Actor": "monitor-api", "X-SignalDesk-Service-Credential": credential}

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def verify_membership(self, user_id: UUID, organization_id: UUID) -> bool:
        try:
            response = self.client.post("/internal/monitor-api/tenant-memberships/verify", headers=self.headers, json={"user_id": str(user_id), "organization_id": str(organization_id)})
            data = response.json() if response.status_code == 200 else {}
            return data.get("user_id") == str(user_id) and data.get("organization_id") == str(organization_id)
        except (httpx.HTTPError, ValueError): return False
    def ready(self) -> bool:
        try:
            response = self.client.get("/readyz", headers=self.headers)
            return response.status_code == 200 and response.content == b'{"status":"ready"}'
        except httpx.HTTPError: return False
