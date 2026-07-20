import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine"
)
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_CELERY_BROKER_URL = DEFAULT_REDIS_URL
DEFAULT_CELERY_RESULT_BACKEND = DEFAULT_REDIS_URL


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    celery_broker_url: str = DEFAULT_CELERY_BROKER_URL
    celery_result_backend: str = DEFAULT_CELERY_RESULT_BACKEND


def get_settings() -> Settings:
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        redis_url=redis_url,
        celery_broker_url=os.getenv("CELERY_BROKER_URL", redis_url),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", redis_url),
    )
