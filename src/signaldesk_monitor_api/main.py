from __future__ import annotations
from collections.abc import Generator
from contextlib import asynccontextmanager
from uuid import UUID
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker
from signaldesk_service_kit import ServiceCredential, ServiceCredentialSet, ServicePrincipal, build_service_auth_dependency
from .control import ControlClient
from .database import create_session_factory
from .models import Monitor
from .schemas import AttachOut, AttachRequest, ClaimOut, MonitorActivityOut, MonitorCreate, MonitorOut, MonitorUpdate, ResolveOut, ResolveRequest
from .service import attach, claim_due, create_monitor, list_activity, public_monitor, resolve, set_monitor_state, update_monitor
from .settings import Settings

def _credentials(s: Settings) -> ServiceCredentialSet:
    return ServiceCredentialSet(credentials=(
        ServiceCredential(principal=ServicePrincipal(actor="web-bff", audience="signaldesk-monitor-api"), credential=s.web_bff_credential),
        ServiceCredential(principal=ServicePrincipal(actor="monitor-scheduler-worker", audience="signaldesk-monitor-api"), credential=s.scheduler_credential),
        ServiceCredential(principal=ServicePrincipal(actor="alert-rule-worker", audience="signaldesk-monitor-api"), credential=s.alert_rule_credential),))
def _out(m: Monitor) -> MonitorOut: return MonitorOut.model_validate(m, from_attributes=True)

def create_app(*, settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None, control_client: ControlClient | None = None) -> FastAPI:
    factory = session_factory
    if settings and factory is None: factory = create_session_factory(str(settings.database_url))
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            if control_client:
                control_client.close()
    app = FastAPI(lifespan=lifespan)
    app.state.settings, app.state.session_factory, app.state.control_client = settings, factory, control_client
    def db() -> Generator[Session, None, None]:
        if not factory: raise HTTPException(503, "database unavailable")
        with factory() as session:
            try: yield session; session.commit()
            except Exception: session.rollback(); raise
    def membership(user_id: UUID = Header(alias="X-SignalDesk-User-ID"), organization_id: UUID = Header(alias="X-SignalDesk-Organization-ID")) -> tuple[UUID, UUID]:
        if not control_client or not control_client.verify_membership(user_id, organization_id): raise HTTPException(403, "membership not authorized")
        return user_id, organization_id
    if settings:
        creds = _credentials(settings)
        public_auth = build_service_auth_dependency(credentials=creds, audience="signaldesk-monitor-api", allowed_actors={"web-bff"})
        scheduler_auth = build_service_auth_dependency(credentials=creds, audience="signaldesk-monitor-api", allowed_actors={"monitor-scheduler-worker"})
        alert_auth = build_service_auth_dependency(credentials=creds, audience="signaldesk-monitor-api", allowed_actors={"alert-rule-worker"})
    else:
        # Unconfigured app is useful only for process liveness tests.
        async def unavailable() -> None: raise HTTPException(503, "service not configured")
        public_auth = scheduler_auth = alert_auth = Depends(unavailable)
    @app.get("/healthz")
    def healthz() -> dict[str, str]: return {"status": "ok"}
    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        try:
            if not factory or not control_client or not control_client.ready(): raise RuntimeError
            with factory() as s: s.execute(text("SELECT 1"))
            return {"status":"ok"}
        except Exception: raise HTTPException(503, "dependencies unavailable")
    @app.post("/v1/monitors", response_model=MonitorOut, status_code=201)
    def create(request: MonitorCreate, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)):
        try: monitor, created = create_monitor(session, context[1], context[0], request, actor_user_id=context[0])
        except ValueError as e: raise HTTPException(409, str(e))
        if not created: return Response(content=_out(monitor).model_dump_json(), media_type="application/json", status_code=200)
        return _out(monitor)
    @app.get("/v1/monitors", response_model=list[MonitorOut])
    def list_monitors(_: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)):
        return [_out(x) for x in session.scalars(select(Monitor).where(Monitor.organization_id == context[1], Monitor.state != "deleted").order_by(Monitor.created_at)).all()]
    @app.get("/v1/monitors/{monitor_id}", response_model=MonitorOut)
    def get(monitor_id: UUID, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)):
        try: return _out(public_monitor(session, monitor_id, context[1]))
        except LookupError: raise HTTPException(404, "monitor not found")
    @app.get("/v1/monitors/{monitor_id}/activity", response_model=list[MonitorActivityOut])
    def activity(monitor_id: UUID, limit: int = Query(default=50, ge=1, le=100), before_id: int | None = Query(default=None, ge=1), _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)):
        try: return [MonitorActivityOut.model_validate(event, from_attributes=True) for event in list_activity(session, monitor_id, context[1], limit, before_id)]
        except LookupError: raise HTTPException(404, "monitor not found")
    @app.patch("/v1/monitors/{monitor_id}", response_model=MonitorOut)
    def update(monitor_id: UUID, request: MonitorUpdate, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)):
        try: monitor = update_monitor(session, monitor_id, context[1], request, actor_user_id=context[0])
        except LookupError: raise HTTPException(404, "monitor not found")
        return _out(monitor)
    def set_state(monitor_id: UUID, desired: str, context: tuple[UUID, UUID], session: Session) -> MonitorOut:
        try: m = set_monitor_state(session, monitor_id, context[1], desired, actor_user_id=context[0])
        except LookupError: raise HTTPException(404, "monitor not found")
        return _out(m)
    @app.post("/v1/monitors/{monitor_id}/pause", response_model=MonitorOut)
    def pause(monitor_id: UUID, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)): return set_state(monitor_id, "paused", context, session)
    @app.post("/v1/monitors/{monitor_id}/resume", response_model=MonitorOut)
    def resume(monitor_id: UUID, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)): return set_state(monitor_id, "enabled", context, session)
    @app.delete("/v1/monitors/{monitor_id}", status_code=204)
    def delete(monitor_id: UUID, _: ServicePrincipal = public_auth, context: tuple[UUID, UUID] = Depends(membership), session: Session = Depends(db)): set_state(monitor_id, "deleted", context, session); return Response(status_code=204)
    @app.post("/internal/scheduler/claim", response_model=ClaimOut)
    def claim(_: ServicePrincipal = scheduler_auth, session: Session = Depends(db)):
        result = claim_due(session, settings.lease_seconds if settings else 120)
        if not result: return Response(status_code=204)
        run, mon, raw = result
        return ClaimOut(run_id=run.id, monitor_id=mon.id, organization_id=mon.organization_id, creator_id=mon.creator_id, target=mon.target, scheduled_for=run.scheduled_for, lease_token=raw, lease_generation=run.lease_generation, lease_expires_at=run.lease_expires_at)
    @app.post("/internal/scheduler/runs/{run_id}/diagnostic", response_model=AttachOut)
    def diagnostic(run_id: UUID, request: AttachRequest, _: ServicePrincipal = scheduler_auth, session: Session = Depends(db)):
        try: run = attach(session, run_id, request.diagnostic_job_id, request.lease_token, request.lease_generation)
        except PermissionError: raise HTTPException(409, "lease is no longer current")
        except ValueError as e: raise HTTPException(409, str(e))
        return AttachOut(run_id=run.id, diagnostic_job_id=run.diagnostic_job_id)
    @app.post("/internal/alert-rules/resolve", response_model=ResolveOut)
    def terminal(request: ResolveRequest, _: ServicePrincipal = alert_auth, session: Session = Depends(db)):
        try: run, mon = resolve(session, request.diagnostic_job_id, request.organization_id, request.status)
        except LookupError: raise HTTPException(404, "run not found")
        except ValueError as e: raise HTTPException(409, str(e))
        return ResolveOut(run_id=run.id, monitor_id=mon.id, organization_id=mon.organization_id, creator_id=mon.creator_id, alert_on_failure=mon.alert_on_failure)
    return app

app = create_app()

def create_configured_app() -> FastAPI:
    """Factory used by deployment servers after environment validation."""
    settings = Settings()
    return create_app(settings=settings, control_client=ControlClient(str(settings.control_api_url), settings.control_api_credential.get_secret_value()))
