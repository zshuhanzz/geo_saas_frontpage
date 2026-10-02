"""
BaseConfig — unified Pydantic v2 Settings base class for every GEO module.

Every module's Settings class should inherit from this and add module-specific fields:

    from geo_common.config import BaseConfig

    class Settings(BaseConfig):
        CLORO_API_KEY: str  # module-specific
        # DB_* / GCP_* / ENVIRONMENT fields are inherited

Environment variables are read from process env + optional `.env` file.
Legacy env var `DB_PASS` is accepted as alias for `DB_PASSWORD` to ease migration.
"""

import os
import urllib.parse
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConfig(BaseSettings):
    """Shared configuration base class for all GEO modules."""

    # ---------- Database (Cloud SQL Postgres) ----------
    DB_USER: str = "answer-x-geo-db-user"
    DB_PASSWORD: str = Field(
        default="",
        validation_alias=AliasChoices("DB_PASSWORD", "DB_PASS"),
        description=(
            "Database password. Reads env `DB_PASSWORD` (preferred) or "
            "`DB_PASS` (legacy, geo_analyzer convention)."
        ),
    )
    DB_NAME: str = "answer-x-geo-db"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432

    # Cloud SQL unix-socket connection (Cloud Run environments only).
    # When set and running under Cloud Run, `build_database_url()` prefers the
    # socket path `/cloudsql/<DB_INSTANCE_CONNECTION_NAME>` over TCP.
    DB_INSTANCE_CONNECTION_NAME: Optional[str] = None

    # Optional explicit override. If set, `build_database_url()` returns this
    # unchanged (used by local dev pointing at a dump DB, or test fixtures).
    DATABASE_URL: Optional[str] = None

    # ---------- GCP ----------
    GCP_PROJECT_ID: Optional[str] = None
    GCP_REGION: str = "us-central1"
    GCP_REGION_GLOBAL: str = "global"

    # ---------- App runtime ----------
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- Helpers ----------

    def build_database_url(self, driver: str = "asyncpg") -> str:
        """
        Construct a SQLAlchemy-style DATABASE_URL.

        - If `self.DATABASE_URL` is set, return it unchanged.
        - Else if running under Cloud Run (`K_SERVICE` or `IS_CLOUD_RUN` env
          is set) and `DB_INSTANCE_CONNECTION_NAME` is configured, return a
          unix-socket URL pointing at `/cloudsql/<conn_name>`.
        - Else fall back to a TCP URL using `DB_HOST:DB_PORT`.

        :param driver: SQLAlchemy driver token — `asyncpg` (default for async
                       callers), `psycopg2`, `psycopg` (v3), etc.
        """
        if self.DATABASE_URL:
            return self.DATABASE_URL

        encoded_password = urllib.parse.quote_plus(self.DB_PASSWORD)
        is_cloud_run = bool(
            os.environ.get("K_SERVICE") or os.environ.get("IS_CLOUD_RUN")
        )

        if is_cloud_run and self.DB_INSTANCE_CONNECTION_NAME:
            socket_dir = f"/cloudsql/{self.DB_INSTANCE_CONNECTION_NAME}"
            return (
                f"postgresql+{driver}://{self.DB_USER}:{encoded_password}"
                f"@/{self.DB_NAME}?host={socket_dir}"
            )

        return (
            f"postgresql+{driver}://{self.DB_USER}:{encoded_password}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )
