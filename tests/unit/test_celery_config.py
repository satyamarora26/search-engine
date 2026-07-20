from app.core.config import (
    DEFAULT_CELERY_RESULT_BACKEND,
    DEFAULT_CELERY_BROKER_URL,
    DEFAULT_REDIS_URL,
    Settings,
    get_settings,
)
from app.workers.celery_app import create_celery_app
from app.workers.tasks import ping


def test_default_worker_settings_use_local_redis(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    settings = get_settings()

    assert settings.redis_url == DEFAULT_REDIS_URL
    assert settings.celery_broker_url == DEFAULT_CELERY_BROKER_URL
    assert settings.celery_result_backend == DEFAULT_CELERY_RESULT_BACKEND


def test_worker_settings_can_use_shared_redis_url(monkeypatch):
    redis_url = "redis://localhost:6379/2"
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)

    settings = get_settings()

    assert settings.redis_url == redis_url
    assert settings.celery_broker_url == redis_url
    assert settings.celery_result_backend == redis_url


def test_worker_settings_allow_explicit_celery_overrides(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://broker:6379/1")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://backend:6379/2")

    settings = get_settings()

    assert settings.celery_broker_url == "redis://broker:6379/1"
    assert settings.celery_result_backend == "redis://backend:6379/2"


def test_create_celery_app_uses_settings_and_json_serialization():
    settings = Settings(
        database_url="postgresql+psycopg://user:pass@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        celery_broker_url="redis://broker:6379/1",
        celery_result_backend="redis://backend:6379/2",
    )

    celery_app = create_celery_app(settings)

    assert celery_app.main == "search_engine"
    assert celery_app.conf.broker_url == "redis://broker:6379/1"
    assert celery_app.conf.result_backend == "redis://backend:6379/2"
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert "app.workers.tasks" in celery_app.conf.imports


def test_ping_task_returns_health_payload():
    assert ping.name == "workers.ping"
    assert ping.run() == {"status": "ok"}
