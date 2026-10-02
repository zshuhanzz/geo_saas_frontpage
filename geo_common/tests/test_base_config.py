"""Smoke tests for BaseConfig env-var resolution and DATABASE_URL building."""

import os
from unittest.mock import patch

from geo_common.config import BaseConfig


def test_db_password_from_env():
    with patch.dict(os.environ, {"DB_PASSWORD": "secret123"}, clear=True):
        cfg = BaseConfig()
        assert cfg.DB_PASSWORD == "secret123"


def test_db_pass_legacy_alias():
    """geo_analyzer historically used DB_PASS instead of DB_PASSWORD."""
    with patch.dict(os.environ, {"DB_PASS": "legacy_pass"}, clear=True):
        cfg = BaseConfig()
        assert cfg.DB_PASSWORD == "legacy_pass"


def test_database_url_local_tcp():
    env = {"DB_PASSWORD": "pw", "DB_HOST": "localhost", "DB_PORT": "5432"}
    with patch.dict(os.environ, env, clear=True):
        cfg = BaseConfig()
        url = cfg.build_database_url()
        assert url.startswith("postgresql+asyncpg://")
        assert "localhost:5432" in url
        assert "answer-x-geo-db" in url


def test_database_url_cloud_run_socket():
    """When K_SERVICE is set and DB_INSTANCE_CONNECTION_NAME is given → unix socket URL."""
    env = {
        "DB_PASSWORD": "pw",
        "DB_INSTANCE_CONNECTION_NAME": "proj:region:inst",
        "K_SERVICE": "my-service",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = BaseConfig()
        url = cfg.build_database_url()
        assert "/cloudsql/proj:region:inst" in url
        assert "postgresql+asyncpg://" in url


def test_explicit_database_url_wins():
    """Explicit DATABASE_URL short-circuits the construction logic."""
    env = {
        "DB_PASSWORD": "pw",
        "DATABASE_URL": "postgresql+asyncpg://custom/override",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = BaseConfig()
        assert cfg.build_database_url() == "postgresql+asyncpg://custom/override"


def test_driver_parameter():
    """build_database_url(driver=...) lets callers pick sync/async drivers."""
    with patch.dict(os.environ, {"DB_PASSWORD": "pw"}, clear=True):
        cfg = BaseConfig()
        assert "postgresql+psycopg2://" in cfg.build_database_url(driver="psycopg2")


def test_password_url_encoding():
    """Passwords with special chars are URL-encoded."""
    with patch.dict(os.environ, {"DB_PASSWORD": "p@ss:w/rd+!"}, clear=True):
        cfg = BaseConfig()
        url = cfg.build_database_url()
        # The encoded form of `p@ss:w/rd+!` must be present.
        assert "p%40ss%3Aw%2Frd%2B%21" in url
        # And the raw form must NOT be (otherwise parsing of the URL would break).
        assert "p@ss:w/rd+!" not in url
