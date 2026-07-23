import pytest

from app.core.config import (
    DEFAULT_DATABASE_URL,
    DEFAULT_MEDIUM_USER_AGENT,
    DEFAULT_RSS_USER_AGENT,
    DEFAULT_WIKIPEDIA_ACTION_API_URL,
    DEFAULT_WIKIPEDIA_REST_API_URL,
    DEFAULT_WIKIPEDIA_USER_AGENT,
    get_settings,
)


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


def test_default_wikipedia_settings_are_bounded_and_identifying(monkeypatch):
    for name in (
        "WIKIPEDIA_ACTION_API_URL",
        "WIKIPEDIA_REST_API_URL",
        "WIKIPEDIA_USER_AGENT",
        "WIKIPEDIA_CONCURRENCY",
        "WIKIPEDIA_REQUESTS_PER_SECOND",
        "WIKIPEDIA_REQUEST_TIMEOUT_SECONDS",
        "WIKIPEDIA_MAX_RESPONSE_BYTES",
        "WIKIPEDIA_MAX_CATEGORIES",
        "WIKIPEDIA_FETCH_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.wikipedia_action_api_url == (
        DEFAULT_WIKIPEDIA_ACTION_API_URL
    )
    assert settings.wikipedia_rest_api_url == DEFAULT_WIKIPEDIA_REST_API_URL
    assert settings.wikipedia_user_agent == DEFAULT_WIKIPEDIA_USER_AGENT
    assert settings.wikipedia_concurrency == 4
    assert settings.wikipedia_requests_per_second == 2.0
    assert settings.wikipedia_request_timeout_seconds == 30.0
    assert settings.wikipedia_max_response_bytes == 10 * 1024 * 1024
    assert settings.wikipedia_max_categories == 100
    assert settings.wikipedia_fetch_attempts == 3


def test_default_medium_settings_are_bounded_and_identifying(monkeypatch):
    for name in (
        "MEDIUM_USER_AGENT",
        "MEDIUM_CONCURRENCY",
        "MEDIUM_REQUESTS_PER_SECOND",
        "MEDIUM_REQUEST_TIMEOUT_SECONDS",
        "MEDIUM_MAX_RESPONSE_BYTES",
        "MEDIUM_FETCH_ATTEMPTS",
        "MEDIUM_DISCOVERY_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.medium_user_agent == DEFAULT_MEDIUM_USER_AGENT
    assert settings.medium_concurrency == 4
    assert settings.medium_requests_per_second == 1.0
    assert settings.medium_request_timeout_seconds == 30.0
    assert settings.medium_max_response_bytes == 10 * 1024 * 1024
    assert settings.medium_fetch_attempts == 3
    assert settings.medium_discovery_attempts == 2


def test_default_rss_settings_are_bounded_and_identifying(monkeypatch):
    for name in (
        "RSS_USER_AGENT",
        "RSS_CONCURRENCY",
        "RSS_REQUESTS_PER_SECOND",
        "RSS_REQUEST_TIMEOUT_SECONDS",
        "RSS_MAX_RESPONSE_BYTES",
        "RSS_FETCH_ATTEMPTS",
        "RSS_DISCOVERY_ATTEMPTS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = get_settings()

    assert settings.rss_user_agent == DEFAULT_RSS_USER_AGENT
    assert settings.rss_concurrency == 4
    assert settings.rss_requests_per_second == 1.0
    assert settings.rss_request_timeout_seconds == 30.0
    assert settings.rss_max_response_bytes == 10 * 1024 * 1024
    assert settings.rss_fetch_attempts == 3
    assert settings.rss_discovery_attempts == 2


def test_medium_settings_accept_stripped_test_server_overrides(monkeypatch):
    monkeypatch.setenv(
        "MEDIUM_USER_AGENT",
        "  CrawlerTest/1.0 (test@example.com)  ",
    )
    monkeypatch.setenv("MEDIUM_CONCURRENCY", "2")
    monkeypatch.setenv("MEDIUM_REQUESTS_PER_SECOND", "5")
    monkeypatch.setenv("MEDIUM_REQUEST_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("MEDIUM_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("MEDIUM_FETCH_ATTEMPTS", "2")
    monkeypatch.setenv("MEDIUM_DISCOVERY_ATTEMPTS", "4")

    settings = get_settings()

    assert settings.medium_user_agent == "CrawlerTest/1.0 (test@example.com)"
    assert settings.medium_concurrency == 2
    assert settings.medium_requests_per_second == 5.0
    assert settings.medium_request_timeout_seconds == 2.5
    assert settings.medium_max_response_bytes == 4096
    assert settings.medium_fetch_attempts == 2
    assert settings.medium_discovery_attempts == 4


def test_rss_settings_accept_stripped_test_server_overrides(monkeypatch):
    monkeypatch.setenv(
        "RSS_USER_AGENT",
        "  CrawlerTest/1.0 (test@example.com)  ",
    )
    monkeypatch.setenv("RSS_CONCURRENCY", "2")
    monkeypatch.setenv("RSS_REQUESTS_PER_SECOND", "5")
    monkeypatch.setenv("RSS_REQUEST_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("RSS_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("RSS_FETCH_ATTEMPTS", "2")
    monkeypatch.setenv("RSS_DISCOVERY_ATTEMPTS", "4")

    settings = get_settings()

    assert settings.rss_user_agent == "CrawlerTest/1.0 (test@example.com)"
    assert settings.rss_concurrency == 2
    assert settings.rss_requests_per_second == 5.0
    assert settings.rss_request_timeout_seconds == 2.5
    assert settings.rss_max_response_bytes == 4096
    assert settings.rss_fetch_attempts == 2
    assert settings.rss_discovery_attempts == 4


def test_wikipedia_settings_accept_stripped_test_server_overrides(monkeypatch):
    monkeypatch.setenv(
        "WIKIPEDIA_ACTION_API_URL",
        "  http://127.0.0.1:8765/action  ",
    )
    monkeypatch.setenv(
        "WIKIPEDIA_REST_API_URL",
        "  http://127.0.0.1:8765/rest  ",
    )
    monkeypatch.setenv(
        "WIKIPEDIA_USER_AGENT",
        "  CrawlerTest/1.0 (test@example.com)  ",
    )
    monkeypatch.setenv("WIKIPEDIA_CONCURRENCY", "2")
    monkeypatch.setenv("WIKIPEDIA_REQUESTS_PER_SECOND", "50")
    monkeypatch.setenv("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("WIKIPEDIA_MAX_RESPONSE_BYTES", "4096")
    monkeypatch.setenv("WIKIPEDIA_MAX_CATEGORIES", "7")
    monkeypatch.setenv("WIKIPEDIA_FETCH_ATTEMPTS", "2")

    settings = get_settings()

    assert settings.wikipedia_action_api_url == "http://127.0.0.1:8765/action"
    assert settings.wikipedia_rest_api_url == "http://127.0.0.1:8765/rest"
    assert settings.wikipedia_user_agent == (
        "CrawlerTest/1.0 (test@example.com)"
    )
    assert settings.wikipedia_concurrency == 2
    assert settings.wikipedia_requests_per_second == 50.0
    assert settings.wikipedia_request_timeout_seconds == 2.5
    assert settings.wikipedia_max_response_bytes == 4096
    assert settings.wikipedia_max_categories == 7
    assert settings.wikipedia_fetch_attempts == 2


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "python-httpx/0.28", "python-requests/2.32", "curl/8.0"],
)
def test_wikipedia_settings_reject_blank_or_generic_user_agents(
    monkeypatch,
    user_agent,
):
    monkeypatch.setenv("WIKIPEDIA_USER_AGENT", user_agent)

    with pytest.raises(ValueError, match="WIKIPEDIA_USER_AGENT"):
        get_settings()


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "python-httpx/0.28", "python-requests/2.32", "curl/8.0"],
)
def test_medium_settings_reject_blank_or_generic_user_agents(
    monkeypatch,
    user_agent,
):
    monkeypatch.setenv("MEDIUM_USER_AGENT", user_agent)

    with pytest.raises(ValueError, match="MEDIUM_USER_AGENT"):
        get_settings()


@pytest.mark.parametrize(
    "user_agent",
    ["", "   ", "python-httpx/0.28", "python-requests/2.32", "curl/8.0"],
)
def test_rss_settings_reject_blank_or_generic_user_agents(monkeypatch, user_agent):
    monkeypatch.setenv("RSS_USER_AGENT", user_agent)

    with pytest.raises(ValueError, match="RSS_USER_AGENT"):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("WIKIPEDIA_CONCURRENCY", "0"),
        ("WIKIPEDIA_REQUESTS_PER_SECOND", "-1"),
        ("WIKIPEDIA_REQUEST_TIMEOUT_SECONDS", "0"),
        ("WIKIPEDIA_MAX_RESPONSE_BYTES", "-10"),
        ("WIKIPEDIA_MAX_CATEGORIES", "0"),
        ("WIKIPEDIA_FETCH_ATTEMPTS", "-1"),
    ],
)
def test_wikipedia_settings_reject_nonpositive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MEDIUM_CONCURRENCY", "0"),
        ("MEDIUM_REQUESTS_PER_SECOND", "-1"),
        ("MEDIUM_REQUEST_TIMEOUT_SECONDS", "0"),
        ("MEDIUM_MAX_RESPONSE_BYTES", "-10"),
        ("MEDIUM_FETCH_ATTEMPTS", "-1"),
        ("MEDIUM_DISCOVERY_ATTEMPTS", "0"),
    ],
)
def test_medium_settings_reject_nonpositive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_settings()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RSS_CONCURRENCY", "0"),
        ("RSS_REQUESTS_PER_SECOND", "-1"),
        ("RSS_REQUEST_TIMEOUT_SECONDS", "0"),
        ("RSS_MAX_RESPONSE_BYTES", "-10"),
        ("RSS_FETCH_ATTEMPTS", "-1"),
        ("RSS_DISCOVERY_ATTEMPTS", "0"),
    ],
)
def test_rss_settings_reject_nonpositive_limits(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        get_settings()
