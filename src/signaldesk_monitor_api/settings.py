"""Validated deployment configuration; secrets are never rendered."""
from __future__ import annotations

import secrets
from pydantic import AnyHttpUrl, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIGNALDESK_", extra="forbid", strict=True)
    database_url: PostgresDsn
    control_api_url: AnyHttpUrl
    web_bff_credential: SecretStr
    scheduler_credential: SecretStr
    alert_rule_credential: SecretStr
    control_api_credential: SecretStr
    service_name: str = "signaldesk-monitor-api"
    lease_seconds: int = 120
    control_connect_timeout_seconds: float = 2
    control_read_timeout_seconds: float = 5

    @field_validator("web_bff_credential", "scheduler_credential", "alert_rule_credential", "control_api_credential")
    @classmethod
    def strong(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 32 or not raw.isascii() or any(char.isspace() for char in raw):
            raise ValueError("service credentials must be at least 32 ASCII characters without whitespace")
        return value

    @model_validator(mode="after")
    def distinct(self) -> "Settings":
        values = [x.get_secret_value() for x in (self.web_bff_credential, self.scheduler_credential, self.alert_rule_credential, self.control_api_credential)]
        if any(secrets.compare_digest(a, b) for i, a in enumerate(values) for b in values[i + 1 :]):
            raise ValueError("service credentials must be distinct")
        if not 1 <= self.lease_seconds <= 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        return self
