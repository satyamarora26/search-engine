from app.core.config import DEFAULT_DATABASE_URL, get_settings


def test_default_database_url_uses_postgresql_psycopg(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = get_settings()

    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_database_url_can_be_overridden(monkeypatch):
    database_url = "postgresql+psycopg://user:pass@localhost:5432/test_db"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = get_settings()

    assert settings.database_url == database_url
