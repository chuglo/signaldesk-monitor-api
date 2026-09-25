# SignalDesk Monitor API

Tenant-isolated monitor authority. It owns monitor schedules and lease-fenced monitor runs; it never accesses another service database.

Public routes (service actor `web-bff`) are `POST/GET /v1/monitors`, `GET/PATCH/DELETE /v1/monitors/{id}`, and `POST /v1/monitors/{id}/pause|resume`. Each requires asserted user and organization headers which are re-authorized by Control API.

Internal routes are `POST /internal/scheduler/claim`, `POST /internal/scheduler/runs/{run_id}/diagnostic` (actor `monitor-scheduler-worker`), and `POST /internal/alert-rules/resolve` (actor `alert-rule-worker`). Health routes are `/healthz` and `/readyz`.

Required environment: `SIGNALDESK_DATABASE_URL`, `SIGNALDESK_CONTROL_API_URL`, `SIGNALDESK_WEB_BFF_CREDENTIAL`, `SIGNALDESK_SCHEDULER_CREDENTIAL`, `SIGNALDESK_ALERT_RULE_CREDENTIAL`, and `SIGNALDESK_CONTROL_API_CREDENTIAL`. Credentials must be distinct, ASCII, non-whitespace, and at least 32 characters.

Build from this repository with the sibling service kit supplied as a relative additional context:
`docker build --build-context service-kit=../signaldesk-service-kit .`

Run migrations with `alembic upgrade head`; launch with `signaldesk-monitor-api`.
