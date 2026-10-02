"""
GEO Analyzer - Configuration

Phase 2.5b refactor: ``Settings`` now inherits from ``geo_common.config.BaseConfig``
so analyzer shares the same DB / GCP / env field set as the other GEO modules.
Phase 2.5b second pass also flipped the DB layer from sync SQLAlchemy+psycopg2
to the shared asyncpg pool — see ``src/core/database.py``.

Backward compatibility:
- ``settings.DB_PASS`` still works because ``BaseConfig.DB_PASSWORD`` accepts
  ``DB_PASS`` as an alias.
- ``settings.database_url`` is preserved as a property for any out-of-band
  consumers; analyzer's runtime DB access goes through ``asyncpg`` directly
  via the pool, but the URL helper stays available for tooling that wants a
  DSN string. It now asks ``BaseConfig.build_database_url("asyncpg")`` so the
  driver token matches the live runtime.
- The legacy ``CLOUD_SQL_CONNECTION_NAME`` env var is mapped to BaseConfig's
  ``DB_INSTANCE_CONNECTION_NAME`` via a model validator so existing deployments
  keep working without redeploying with new env vars.
"""
from functools import lru_cache
import os
from typing import Optional

from pydantic import AliasChoices, Field, model_validator

from geo_common.config import BaseConfig


class Settings(BaseConfig):
    """Analyzer settings — extends shared BaseConfig with sync-DB-specific helpers."""

    # Accept the legacy analyzer env var name as an alias so prod deployments
    # that still set ``CLOUD_SQL_CONNECTION_NAME`` keep working.
    DB_INSTANCE_CONNECTION_NAME: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices(
            "DB_INSTANCE_CONNECTION_NAME",
            "CLOUD_SQL_CONNECTION_NAME",
        ),
    )

    @model_validator(mode="after")
    def _normalize_legacy_defaults(self) -> "Settings":
        # Legacy analyzer defaults differ from BaseConfig (which uses Cloud SQL
        # production names). Preserve the analyzer's local-dev-friendly defaults
        # only for local runs where DB env vars were not explicitly set.
        is_cloud_run = bool(
            os.environ.get("K_SERVICE") or os.environ.get("IS_CLOUD_RUN")
        )
        has_explicit_db_user = "DB_USER" in os.environ
        has_explicit_db_name = "DB_NAME" in os.environ

        if (
            not is_cloud_run
            and not has_explicit_db_user
            and self.DB_USER == "answer-x-geo-db-user"
        ):
            self.DB_USER = "postgres"
        if (
            not is_cloud_run
            and not has_explicit_db_name
            and self.DB_NAME == "answer-x-geo-db"
        ):
            self.DB_NAME = "geo_platform"
        if self.DB_HOST == "127.0.0.1":
            self.DB_HOST = "localhost"
        return self

    @property
    def database_url(self) -> str:
        """Async DB URL for asyncpg.

        Analyzer's runtime DB layer goes through the asyncpg pool created by
        ``geo_common.db.create_asyncpg_pool`` (no DSN required). This property
        is kept for out-of-band tooling that wants a DSN string and now asks
        ``BaseConfig.build_database_url("asyncpg")`` so the driver token
        matches the live runtime.
        """
        return self.build_database_url(driver="asyncpg")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
