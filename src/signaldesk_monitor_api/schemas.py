from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

class Strict(BaseModel): model_config = ConfigDict(extra="forbid", strict=True)
class MonitorCreate(Strict):
    name: str = Field(min_length=1, max_length=200)
    target: HttpUrl
    cadence_seconds: int = Field(ge=30, le=86400)
    alert_on_failure: bool = True
    idempotency_key: UUID = Field(strict=False)
    @field_validator("name")
    @classmethod
    def nonblank(cls, v: str) -> str:
        if not v.strip(): raise ValueError("name must not be blank")
        return v.strip()
class MonitorUpdate(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    target: HttpUrl | None = None
    cadence_seconds: int | None = Field(default=None, ge=30, le=86400)
    alert_on_failure: bool | None = None
    @field_validator("name")
    @classmethod
    def nonblank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip(): raise ValueError("name must not be blank")
        return v.strip() if v is not None else v
class MonitorOut(Strict):
    id: UUID; organization_id: UUID; creator_id: UUID; name: str; target: str; cadence_seconds: int; state: str; alert_on_failure: bool; next_run_at: datetime
class ClaimOut(Strict):
    run_id: UUID; monitor_id: UUID; organization_id: UUID; creator_id: UUID; target: str; scheduled_for: datetime; lease_token: str; lease_generation: int; lease_expires_at: datetime
class AttachRequest(Strict): diagnostic_job_id: UUID = Field(strict=False); lease_token: str = Field(min_length=16); lease_generation: int = Field(ge=1)
class AttachOut(Strict): run_id: UUID; diagnostic_job_id: UUID
class ResolveRequest(Strict): diagnostic_job_id: UUID = Field(strict=False); organization_id: UUID = Field(strict=False); status: Literal["completed", "failed"]
class ResolveOut(Strict): run_id: UUID; monitor_id: UUID; organization_id: UUID; creator_id: UUID; alert_on_failure: bool
