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
DEFAULT_MEDIUM_USER_AGENT = (
    "SatyamSearchEngineMediumBot/1.0 "
    "(https://github.com/satyamarora26/search-engine)"
)
DEFAULT_RSS_USER_AGENT = (
    "SatyamSearchEngineRssBot/1.0 "
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
    medium_user_agent: str = DEFAULT_MEDIUM_USER_AGENT
    medium_concurrency: int = 4
    medium_requests_per_second: float = 1.0
    medium_request_timeout_seconds: float = 30.0
    medium_max_response_bytes: int = 10 * 1024 * 1024
    medium_fetch_attempts: int = 3
    medium_discovery_attempts: int = 2
    rss_user_agent: str = DEFAULT_RSS_USER_AGENT
    rss_concurrency: int = 4
    rss_requests_per_second: float = 1.0
    rss_request_timeout_seconds: float = 30.0
    rss_max_response_bytes: int = 10 * 1024 * 1024
    rss_fetch_attempts: int = 3
    rss_discovery_attempts: int = 2


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


def _medium_user_agent() -> str:
    value = os.getenv(
        "MEDIUM_USER_AGENT",
        DEFAULT_MEDIUM_USER_AGENT,
    ).strip()
    if not value or value.casefold().startswith(
        ("python-httpx", "python-requests", "curl")
    ):
        raise ValueError(
            "MEDIUM_USER_AGENT must identify the crawler project."
        )
    return value


def _rss_user_agent() -> str:
    value = os.getenv(
        "RSS_USER_AGENT",
        DEFAULT_RSS_USER_AGENT,
    ).strip()
    if not value or value.casefold().startswith(
        ("python-httpx", "python-requests", "curl")
    ):
        raise ValueError("RSS_USER_AGENT must identify the crawler project.")
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
        medium_user_agent=_medium_user_agent(),
        medium_concurrency=int(
            _positive(
                "MEDIUM_CONCURRENCY",
                int(os.getenv("MEDIUM_CONCURRENCY", "4")),
            )
        ),
        medium_requests_per_second=float(
            _positive(
                "MEDIUM_REQUESTS_PER_SECOND",
                float(os.getenv("MEDIUM_REQUESTS_PER_SECOND", "1")),
            )
        ),
        medium_request_timeout_seconds=float(
            _positive(
                "MEDIUM_REQUEST_TIMEOUT_SECONDS",
                float(os.getenv("MEDIUM_REQUEST_TIMEOUT_SECONDS", "30")),
            )
        ),
        medium_max_response_bytes=int(
            _positive(
                "MEDIUM_MAX_RESPONSE_BYTES",
                int(os.getenv("MEDIUM_MAX_RESPONSE_BYTES", "10485760")),
            )
        ),
        medium_fetch_attempts=int(
            _positive(
                "MEDIUM_FETCH_ATTEMPTS",
                int(os.getenv("MEDIUM_FETCH_ATTEMPTS", "3")),
            )
        ),
        medium_discovery_attempts=int(
            _positive(
                "MEDIUM_DISCOVERY_ATTEMPTS",
                int(os.getenv("MEDIUM_DISCOVERY_ATTEMPTS", "2")),
            )
        ),
        rss_user_agent=_rss_user_agent(),
        rss_concurrency=int(
            _positive(
                "RSS_CONCURRENCY",
                int(os.getenv("RSS_CONCURRENCY", "4")),
            )
        ),
        rss_requests_per_second=float(
            _positive(
                "RSS_REQUESTS_PER_SECOND",
                float(os.getenv("RSS_REQUESTS_PER_SECOND", "1")),
            )
        ),
        rss_request_timeout_seconds=float(
            _positive(
                "RSS_REQUEST_TIMEOUT_SECONDS",
                float(os.getenv("RSS_REQUEST_TIMEOUT_SECONDS", "30")),
            )
        ),
        rss_max_response_bytes=int(
            _positive(
                "RSS_MAX_RESPONSE_BYTES",
                int(os.getenv("RSS_MAX_RESPONSE_BYTES", "10485760")),
            )
        ),
        rss_fetch_attempts=int(
            _positive(
                "RSS_FETCH_ATTEMPTS",
                int(os.getenv("RSS_FETCH_ATTEMPTS", "3")),
            )
        ),
        rss_discovery_attempts=int(
            _positive(
                "RSS_DISCOVERY_ATTEMPTS",
                int(os.getenv("RSS_DISCOVERY_ATTEMPTS", "2")),
            )
        ),
    )
