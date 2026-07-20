from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
REDIS_URL = "redis://localhost:6379/0"


def test_docker_compose_defines_local_redis_service():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())

    redis = compose["services"]["redis"]

    assert redis["image"] == "redis:7-alpine"
    assert redis["ports"] == ["6379:6379"]
    assert redis["healthcheck"]["test"] == ["CMD", "redis-cli", "ping"]
    assert redis["healthcheck"]["interval"] == "5s"
    assert redis["healthcheck"]["timeout"] == "5s"
    assert redis["healthcheck"]["retries"] == 10


def test_env_example_includes_worker_redis_settings():
    env_example = (ROOT / ".env.example").read_text()

    assert f"REDIS_URL={REDIS_URL}" in env_example
    assert f"CELERY_BROKER_URL={REDIS_URL}" in env_example
    assert f"CELERY_RESULT_BACKEND={REDIS_URL}" in env_example


def test_celery_worker_documentation_lists_run_commands():
    docs = (ROOT / "docs" / "celery-worker.md").read_text()

    assert "docker compose up -d redis" in docs
    assert "celery -A app.workers.celery_app.celery_app worker --loglevel=info" in docs
    assert "celery -A app.workers.celery_app.celery_app call workers.ping" in docs
    assert "/api/v1/search/rebuild" in docs
    assert "/api/v1/jobs/" in docs
    assert "search:index:active_version" in docs
