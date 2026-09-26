# SignalDesk Monitor API

**Not for production use.**

Tenant-isolated monitor authority. It owns monitor schedules and lease-fenced monitor runs; it never accesses another service database.

Public routes (service actor `web-bff`) are `POST/GET /v1/monitors`, `GET/PATCH/DELETE /v1/monitors/{id}`, `POST /v1/monitors/{id}/pause|resume`, and `GET /v1/monitors/{id}/activity`. Each requires asserted user and organization headers which are re-authorized by Control API.

Monitor activity records creation, material configuration updates, pauses, resumes, and soft deletion in the same database transaction as the monitor change. An idempotent create replay or no-op update does not write another event. Each event has the tenant ID, monitor ID, verified human actor ID, action, changed field names (not values), and timestamp. Targets, URL query strings, credentials and lease tokens are never copied into activity rows. Activity remains readable after deletion, but only to authenticated members of that organization; unknown or other-tenant IDs return 404. `GET /v1/monitors/{id}/activity?limit=50&before_id=<last-seen-id>` returns newest first with a limit of 1–100. Pagination uses the last returned integer ID as an exclusive cursor. This is a configuration activity feed, not a database-enforced tamper-proof compliance ledger; retention and export policies are outside this service's scope.

Internal routes are `POST /internal/scheduler/claim`, `POST /internal/scheduler/runs/{run_id}/diagnostic` (actor `monitor-scheduler-worker`), and `POST /internal/alert-rules/resolve` (actor `alert-rule-worker`). Health routes are `/healthz` and `/readyz`.

Required environment: `SIGNALDESK_DATABASE_URL`, `SIGNALDESK_CONTROL_API_URL`, `SIGNALDESK_WEB_BFF_CREDENTIAL`, `SIGNALDESK_SCHEDULER_CREDENTIAL`, `SIGNALDESK_ALERT_RULE_CREDENTIAL`, and `SIGNALDESK_CONTROL_API_CREDENTIAL`. Credentials must be distinct, ASCII, non-whitespace, and at least 32 characters.

Build from this repository with the sibling service kit supplied as a relative additional context:
`docker build --build-context service-kit=../signaldesk-service-kit .`

Run migrations with `alembic upgrade head`; launch with `signaldesk-monitor-api`.

## License

MIT. See [LICENSE](LICENSE).
