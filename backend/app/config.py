"""config.py — all environment-specific settings, read from environment variables.

Nothing environment-specific is hard-coded elsewhere. See ../.env.example.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"  # local | staging | production | test
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "sqlite:///./digital_twin.db"
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # Local-dev convenience only. Production runs `alembic upgrade head` as a separate step.
    auto_create_schema: bool = False

    redis_url: str | None = None

    jwt_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    admin_username: str | None = None
    admin_password: str | None = None

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Simulation / streaming
    run_simulation: bool = True
    seed_demo_motor: bool = True
    seed_default_faults: bool = True
    realtime_factor: float = 1.0
    stream_hz: float = 10.0
    persist_interval_s: float = 1.0
    use_ml: bool = True
    sim_seed: int | None = 0

    # Retention
    retention_days: int = 30
    retention_interval_s: float = 3600.0

    # Rate limits (requests per minute, per client)
    login_rate_per_min: int = 10
    fault_rate_per_min: int = 30

    # Feature flags (comma-separated), e.g. "experimental_fault_x"
    feature_flags: Annotated[set[str], NoDecode] = set()

    @field_validator("cors_origins", "feature_flags", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env in ("staging", "production")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_production:
        import os

        if "JWT_SECRET" not in os.environ:
            raise RuntimeError("JWT_SECRET must be set explicitly in staging/production")
        if "*" in s.cors_origins:
            raise RuntimeError("CORS wildcard is not allowed in staging/production")
    return s
