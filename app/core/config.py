import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://search_engine:search_engine@localhost:5432/search_engine"
)
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_CELERY_BROKER_URL = DEFAULT_REDIS_URL
DEFAULT_CELERY_RESULT_BACKEND = DEFAULT_REDIS_URL
DEFAULT_WIKIPEDIA_ACTION_API_URL = "https://en.wikipedia.org/w/api.php"
DEFAULT_WIKIPEDIA_REST_API_URL = "https://en.wikipedia.org/w/rest.php/v1"
DEFAULT_WIKIPEDIA_USER_AGENT = (
    "SatyamSearchEngineBot/1.0 "
    "(https://github.com/satyamarora26/search-engine)"
)


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    celery_broker_url: str = DEFAULT_CELERY_BROKER_URL
    celery_result_backend: str = DEFAULT_CELERY_RESULT_BACKEND
    wikipedia_action_api_url: str = DEFAULT_WIKIPEDIA_ACTION_API_URL
    wikipedia_rest_api_url: str = DEFAULT_WIKIPEDIA_REST_API_URL
    wikipedia_user_agent: str = DEFAULT_WIKIPEDIA_USER_AGENT
    wikipedia_concurrency: int = 4
    wikipedia_requests_per_second: float = 2.0
    wikipedia_request_timeout_seconds: float = 30.0
    wikipedia_max_response_bytes: int = 10 * 1024 * 1024
    wikipedia_max_categories: int = 100
    wikipedia_fetch_attempts: int = 3


def _positive(name: str, value: int | float) -> int | float:
    if value <= 0:
        raise ValueError(f"{name} must be positive.")
    return value


def _wikipedia_user_agent() -> str:
    value = os.getenv(
        "WIKIPEDIA_USER_AGENT",
        DEFAULT_WIKIPEDIA_USER_AGENT,
    ).strip()
    if not value or value.casefold().startswith(
        ("python-httpx", "python-requests", "curl")
    ):
        raise ValueError(
            "WIKIPEDIA_USER_AGENT must identify the crawler project."
        )
    return value


def get_settings() -> Settings:
    redis_url = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
    return Settings(
        database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
        redis_url=redis_url,
        celery_broker_url=os.getenv("CELERY_BROKER_URL", redis_url),
        celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", redis_url),
        wikipedia_action_api_url=os.getenv(
            "WIKIPEDIA_ACTION_API_URL",
            DEFAULT_WIKIPEDIA_ACTION_API_URL,
        ).strip(),
        wikipedia_rest_api_url=os.getenv(
            "WIKIPEDIA_REST_API_URL",
            DEFAULT_WIKIPEDIA_REST_API_URL,
        ).strip(),
        wikipedia_user_agent=_wikipedia_user_agent(),
        wikipedia_concurrency=int(
            _positive(
                "WIKIPEDIA_CONCURRENCY",
                int(os.getenv("WIKIPEDIA_CONCURRENCY", "4")),
            )
        ),
        wikipedia_requests_per_second=float(
            _positive(
                "WIKIPEDIA_REQUESTS_PER_SECOND",
                float(os.getenv("WIKIPEDIA_REQUESTS_PER_SECOND", "2")),
            )
        ),
        wikipedia_request_timeout_seconds=float(
            _positive(
                "WIKIPEDIA_REQUEST_TIMEOUT_SECONDS",
                float(
                    os.getenv("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "30")
                ),
            )
        ),
        wikipedia_max_response_bytes=int(
            _positive(
                "WIKIPEDIA_MAX_RESPONSE_BYTES",
                int(os.getenv("WIKIPEDIA_MAX_RESPONSE_BYTES", "10485760")),
            )
        ),
        wikipedia_max_categories=int(
            _positive(
                "WIKIPEDIA_MAX_CATEGORIES",
                int(os.getenv("WIKIPEDIA_MAX_CATEGORIES", "100")),
            )
        ),
        wikipedia_fetch_attempts=int(
            _positive(
                "WIKIPEDIA_FETCH_ATTEMPTS",
                int(os.getenv("WIKIPEDIA_FETCH_ATTEMPTS", "3")),
            )
        ),
    )
