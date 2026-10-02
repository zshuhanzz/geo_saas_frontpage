from src.core.config import Settings


def test_cloud_run_preserves_configured_production_db_user(monkeypatch):
    monkeypatch.setenv("IS_CLOUD_RUN", "true")
    monkeypatch.setenv("DB_USER", "answer-x-geo-db-user")
    monkeypatch.setenv("DB_NAME", "answer-x-geo-db")
    monkeypatch.setenv(
        "DB_INSTANCE_CONNECTION_NAME",
        "project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance",
    )

    settings = Settings(_env_file=None)

    assert settings.DB_USER == "answer-x-geo-db-user"
    assert settings.DB_NAME == "answer-x-geo-db"
    assert settings.DB_INSTANCE_CONNECTION_NAME


def test_local_without_explicit_db_env_keeps_legacy_analyzer_defaults(monkeypatch):
    monkeypatch.delenv("IS_CLOUD_RUN", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("DB_USER", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)

    settings = Settings(_env_file=None)

    assert settings.DB_USER == "postgres"
    assert settings.DB_NAME == "geo_platform"
