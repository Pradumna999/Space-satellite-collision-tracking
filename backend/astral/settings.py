"""Validated application settings (environment variables prefixed ASTRAL_)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTRAL_", env_file=".env", extra="ignore")

    profile: str = Field("local", pattern="^(local|production|test)$")
    database_url: str = "sqlite:///./data/astral.db"
    storage_dir: Path = Path("./data/objects")
    model_dir: Path = Path("./data/models")

    # Security
    secret_key: str = Field("dev-only-change-me", min_length=16)
    session_hours: int = 12
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost:5173"]
    allow_registration: bool = False  # admin creates accounts by default

    # Limits
    max_upload_mb: int = 25
    max_objects_per_job: int = 5000
    max_window_days: float = 14.0
    max_concurrent_jobs: int = 2
    max_jobs_per_user_per_hour: int = 30
    rate_limit_per_minute: int = 240
    auth_rate_limit_per_minute: int = 10

    # Workers: "inprocess" runs a worker thread inside the API (local profile);
    # "external" expects `python -m astral.worker` processes (production).
    worker_mode: str = Field("inprocess", pattern="^(inprocess|external)$")

    # Providers
    celestrak_enabled: bool = True
    celestrak_base_url: str = "https://celestrak.org/NORAD/elements/gp.php"
    spacetrack_username: str | None = None
    spacetrack_password: str | None = None
    provider_cache_hours: float = 2.0

    retention_days_uploads: int = 365

    def check_production(self) -> list[str]:
        problems = []
        if self.profile == "production":
            if self.secret_key == "dev-only-change-me":
                problems.append("ASTRAL_SECRET_KEY must be set in production")
            if not self.cookie_secure:
                problems.append("ASTRAL_COOKIE_SECURE must be true in production (TLS required)")
            if self.database_url.startswith("sqlite"):
                problems.append("SQLite is not supported in the production profile; use PostgreSQL")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
