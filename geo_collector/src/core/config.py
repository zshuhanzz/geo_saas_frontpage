"""
GEO Collector — Settings.

Inherits from `geo_common.config.BaseConfig` so DB / GCP / runtime fields
match every other GEO module. Only Collector-specific fields are declared
here (Cloro API + Pub/Sub + Webhook + Gemini model).

Phase 2.5a migration: removed the legacy SQLAlchemy `DATABASE_URL`
construction logic — the asyncpg pool now resolves Cloud Run unix-socket
vs TCP itself via `geo_common.db.create_asyncpg_pool`.
"""
from functools import lru_cache
from typing import Optional

from pydantic_settings import SettingsConfigDict

from geo_common.config import BaseConfig


class Settings(BaseConfig):
    """Collector-specific settings layered on top of `BaseConfig`."""

    # --- Cloro API Configuration ---
    CLORO_API_KEY: str
    CLORO_BASE_URL: str = "https://api.cloro.dev"

    # --- Google Cloud Pub/Sub Configuration ---
    PUBSUB_PROJECT_ID: str
    PUBSUB_CALLBACKS_TOPIC: str = "geo-cloro-callbacks"  # Cloro callback results
    PUBSUB_TASKS_TOPIC: str = "geo-tasks-pending"        # Tasks ready for dispatch

    # --- Webhook Configuration ---
    WEBHOOK_PUBLIC_URL: str
    WEBHOOK_SECRET: Optional[str] = None  # Reserved; not currently enforced

    # --- Vertex AI (Gemini) Configuration ---
    GEMINI_MODEL_ID: str = "gemini-3-flash-preview"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
